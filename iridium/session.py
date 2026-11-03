"""Coordinate the debugger, independent processors, and explicit test stimuli."""

from collections import deque
from pathlib import Path
import tempfile
import threading
import time

from .assets import AssetError, BC5Assets
from .engine import Engine, EngineError
from .firmware import Firmware
from .lcd import ST7541
from .satellite import Satellite


KEY_CODES = {str(n): 0x64 + n for n in range(10)} | {
    "*": 0x79, "#": 0x78, "up": 0x82, "down": 0x83,
    "soft_left": 0x96, "soft_right": 0x97, "green": 0x8D,
    "red": 0x8C, "volume_up": 0xA0, "volume_down": 0xA1, "power": 0xAA,
}
ALL_KEYS = set(KEY_CODES) | {"convenience"}
LIMITATIONS = [
    "Partial hardware model: this is not yet a complete Iridium 9555 emulator.",
    "Processors execute independently; BC5–AVR–modem board links are not coupled.",
    "Natural handset startup is unresolved; experimental initialization calls original firmware routines.",
    "Keys use the original software input entry after explicit initialization; electrical wiring is unresolved.",
    "LCD output uses an inferred controller model; resource previews remain separate from live output.",
    "Satellite service scenarios are offline and are not connected to the modem firmware.",
    "Modem boot ROM, DSP/RF behavior, SIM/provisioning and hardware timing are incomplete.",
]


class Session:
    def __init__(self, executable: Path, firmware: list[Firmware], engine_factory=Engine):
        self._executable = executable
        self._engine_factory = engine_factory
        self._temporary = tempfile.TemporaryDirectory(prefix="iridium-9555-")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._closed = False
        self.engines = {}
        self.firmware = {}
        self.events = deque(maxlen=200)
        self.keys = set()
        self.key_generations = {key: 0 for key in ALL_KEYS}
        self.satellite = Satellite()
        self.running = False
        self.asset = None
        self.ui_initialized = False
        self.ui_attempted = False
        self.lcd = ST7541(segment_zero_on_right=True)
        self.lcd_seen = False
        self.lcd_capture_error = None
        try:
            for item in firmware:
                self.load(item)
        except BaseException:
            self.close()
            raise

    def log(self, kind: str, message: str) -> None:
        self.events.append({"time": time.strftime("%H:%M:%S"), "kind": kind, "message": message})

    def load(self, firmware: Firmware) -> None:
        with self._lock:
            self._ensure_open()
            # A replacement worker is ready before the previous experiment is discarded.
            with tempfile.NamedTemporaryFile(dir=self._temporary.name, suffix=".bin", delete=False) as out:
                out.write(firmware.data)
                path = Path(out.name)
            try:
                worker = self._engine_factory(self._executable, firmware.image, path)
            finally:
                path.unlink(missing_ok=True)
            old = self.engines.get(firmware.image)
            self.engines[firmware.image] = worker
            self.firmware[firmware.image] = firmware
            if old:
                old.close()
            self.running = False
            self._clear_keys()
            if firmware.image == "bc5":
                self._reset_display()
                self.asset = None
                try:
                    bitmap = BC5Assets(firmware.data).bitmap(19, 49)
                    self.asset = {"width": bitmap.width, "height": bitmap.height,
                                  "pixels": list(bitmap.pixels), "frame": 49,
                                  "frames": bitmap.frame_count, "source": "firmware resource 19",
                                  "live": False}
                except AssetError as error:
                    self.log("asset", str(error))
            self.log("firmware", f"Loaded {firmware.name} ({firmware.image}), SHA-256 {firmware.sha256}")

    def start(self) -> None:
        with self._lock:
            self._ensure_open()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="firmware-runner", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(0.02):
            with self._lock:
                if not self.running:
                    continue
                try:
                    self._step(200000)
                except (EngineError, ValueError) as error:
                    self.running = False
                    self.log("error", str(error))

    def _step(self, steps: int) -> None:
        for worker in self.engines.values():
            previous = worker.state.get("halt")
            if previous not in (None, "steps", "running", "ready"):
                continue
            result = self._request(worker, "run", steps=steps)
            halt = result.get("halt")
            if halt not in (None, "steps", "running", "ready") and halt != previous:
                self.log("cpu", f"{result.get('image')}: {halt} at {result.get('pc')}")
        # Explicit virtual scenario time; this does not assert a physical CPU clock ratio.
        self.satellite.advance(20)
        if all(worker.state.get("halt") not in (None, "steps", "running", "ready")
               for worker in self.engines.values()):
            self.running = False

    def control(self, action: str, steps: int = 10000) -> dict:
        if type(steps) is not int or not 1 <= steps <= 10000000:
            raise ValueError("steps must be an integer from 1 to 10000000")
        with self._lock:
            self._ensure_open()
            if action == "run":
                self.running = True
            elif action == "pause":
                self.running = False
            elif action == "step":
                self.running = False
                self._step(steps)
            elif action == "reset":
                self.running = False
                self._clear_keys()
                self.satellite = Satellite()
                self._reset_display()
                for worker in self.engines.values():
                    worker.request("reset")
            elif action == "initialize_ui":
                self.running = False
                self._initialize_ui()
                self.running = self.lcd_capture_error is None
            else:
                raise ValueError("Unknown execution action")
            self.log("control", action)
            return {"ok": True, "message": action}

    def _clear_keys(self) -> None:
        self.keys.clear()
        for key in self.key_generations:
            self.key_generations[key] += 1

    def key(self, key: str, pressed: bool, generation: int | None = None) -> dict:
        if key not in ALL_KEYS or type(pressed) is not bool:
            raise ValueError("Unknown key or invalid pressed state")
        if generation is not None and (type(generation) is not int or generation < 0):
            raise ValueError("generation must be a nonnegative integer")
        with self._lock:
            self._ensure_open()
            if generation is not None and generation != self.key_generations[key]:
                return {"ok": True, "delivered": False, "message": "Stale key event ignored",
                        "generation": self.key_generations[key]}
            if (key in self.keys) == pressed:
                if not pressed:
                    # A release arriving first cancels a press still in flight.
                    self.key_generations[key] += 1
                return {"ok": True, "delivered": False, "message": "Unchanged key state",
                        "generation": self.key_generations[key]}
            delivered = False
            try:
                if self.ui_initialized and key in KEY_CODES:
                    worker = self.engines["bc5"]
                    self._idle(worker)
                    callback = worker.request("read", address=0xF6FB, count=2)["values"]
                    if callback == [0, 0]:
                        self.ui_initialized = False
                        raise EngineError("Firmware key handler is absent; reset before reinitializing")
                    self._call(worker, 0x67F04, al=KEY_CODES[key], ah=1 if pressed else 4, steps=100000)
                    delivered = True
                if pressed:
                    self.keys.add(key)
                else:
                    self.keys.discard(key)
                    self.key_generations[key] += 1
                if delivered:
                    self._idle(worker)
            except EngineError:
                self.running = False
                raise
            message = f"{key} {'down' if pressed else 'up'} " + (
                "delivered through original software key routine" if delivered else
                "recorded; initialize the application first or use a mapped key")
            self.log("key", message)
            return {"ok": True, "delivered": delivered, "message": message,
                    "generation": self.key_generations[key]}

    def probe(self, image: str, operation: str, arguments: dict) -> dict:
        if operation not in ("read", "write", "call", "state", "pins", "uart_rx", "uart_tx", "spi"):
            raise ValueError("Unsupported debugger operation")
        with self._lock:
            self._ensure_open()
            if self.running:
                raise ValueError("Pause execution before a debugger probe")
            if image not in self.engines:
                raise ValueError("Processor image is not loaded")
            response = self._request(self.engines[image], operation, **arguments)
            self.log("probe", f"{image}: {operation}")
            return response

    def satellite_action(self, action: str, arguments: dict) -> dict:
        with self._lock:
            self._ensure_open()
            if action == "configure":
                self.satellite.configure(**arguments)
            elif action == "register":
                self.satellite.register()
            elif action == "advance":
                self.satellite.advance(arguments.get("milliseconds", 1000))
            elif action == "incoming_call":
                self.satellite.incoming_call(arguments.get("number", "+881612345678"))
            elif action == "incoming_sms":
                self.satellite.incoming_sms(arguments.get("number", "+881612345678"),
                                            arguments.get("text", "Test message"))
            elif action == "answer":
                self.satellite.answer()
            elif action == "hangup":
                self.satellite.hangup()
            else:
                raise ValueError("Unknown satellite action")
            self.log("satellite", f"Scenario {action}; firmware transport not connected")
            return {"ok": True, "delivered": False, "message": "Scenario updated; firmware transport not connected"}

    def state(self) -> dict:
        with self._lock:
            self._ensure_open()
            primary = self.firmware.get("bc5") or next(iter(self.firmware.values()))
            lcd = self.lcd.state() if self.lcd_seen else None
            if lcd and self.lcd_capture_error:
                lcd["error"] = self.lcd_capture_error
            return {"firmware": primary.describe(), "images": [item.describe() for item in self.firmware.values()],
                    "processors": [dict(worker.state) for worker in self.engines.values()],
                    "running": self.running, "keys": sorted(self.keys),
                    "key_generations": dict(self.key_generations),
                    "satellite": self.satellite.state(), "events": list(self.events),
                    "asset": self.asset, "lcd": lcd, "ui_initialized": self.ui_initialized,
                    "fidelity": {"complete": False, "limitations": LIMITATIONS}}

    def _reset_display(self) -> None:
        self.ui_initialized = False
        self.ui_attempted = False
        self.lcd = ST7541(segment_zero_on_right=True)
        self.lcd_seen = False
        self.lcd_capture_error = None

    def _request(self, worker, operation: str, **arguments) -> dict:
        response = worker.request(operation, **arguments)
        if response.get("image") == "bc5":
            stream = response.get("lcd_bytes", [])
            if response.get("lcd_dropped", 0):
                self.lcd_capture_error = "LCD capture overflow; reset the experiment before interpreting pixels"
                self.lcd_seen = True
                self.running = False
            if stream and not self.lcd_capture_error:
                self.lcd_seen = True
                try:
                    self.lcd.feed(bytes(stream))
                except ValueError as error:
                    self.lcd_capture_error = str(error)
                    self.running = False
                    self.log("lcd", f"Display interpretation stopped: {error}")
            # Captured bytes have been consumed; retain the decoded display instead.
            response["lcd_bytes"] = []
        return response

    def _idle(self, worker) -> None:
        # A configured warm boot also runs the application's device initialization.
        for _ in range(3):
            response = self._request(worker, "idle", steps=10000000)
            if response.get("halt"):
                break
            if response.get("at_idle"):
                return
        raise EngineError(f"Cannot reach a safe scheduler boundary: {response.get('halt') or 'instruction budget exhausted'}")

    def _call(self, worker, entry: int, **arguments) -> dict:
        response = self._request(worker, "call", entry=entry, **arguments)
        if response.get("halt") or not (response.get("last_call") or {}).get("returned"):
            raise EngineError(f"Original function 0x{entry:X} did not return: {response.get('halt')}")
        return response

    def _initialize_ui(self) -> None:
        if self.ui_initialized:
            return
        if self.ui_attempted:
            raise EngineError("Application initialization was incomplete; reset before retrying")
        if "bc5" not in self.engines:
            raise ValueError("Load BC5 firmware before initializing the handset application")
        self.ui_attempted = True
        worker = self.engines["bc5"]
        self._idle(worker)
        if worker.request("read", address=0xF719, count=1)["values"] == [0]:
            self._call(worker, 0x6365E, steps=10000000)
        setup = self._request(worker, "call", entry=0x8CC8C, steps=10000000)
        if setup.get("halt") == "firmware-reset-requested":
            # Blank settings make the original factory routine program defaults and reboot.
            self._request(worker, "warm_reset")
            self._idle(worker)
            self.log("firmware", "Original factory defaults retained across the requested warm reset")
            self._call(worker, 0x8CC8C, steps=10000000)
        elif setup.get("halt") or not (setup.get("last_call") or {}).get("returned"):
            raise EngineError(f"Original application setup did not return: {setup.get('halt')}")
        self._call(worker, 0x8CC5E, steps=10000000)
        self._idle(worker)
        callback = worker.request("read", address=0xF6FB, count=2)["values"]
        if callback == [0, 0]:
            raise EngineError("Original initialization did not install a key handler")
        if self.lcd_capture_error:
            raise EngineError(f"Application display initialization failed: {self.lcd_capture_error}")
        self.ui_initialized = True
        self.log("firmware", "Experimental application initialization completed via original routines; natural hardware boot remains incomplete")

    def close(self) -> None:
        self._stop.set()
        # An in-flight HTTP probe owns the same lock as the runner. Finish it
        # before closing its pipes or changing the worker collection.
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.running = False
            for worker in self.engines.values():
                worker.close()
            self.engines.clear()
            self._temporary.cleanup()
        if self._thread:
            self._thread.join(timeout=2)

    def _ensure_open(self) -> None:
        if self._closed:
            raise EngineError("Emulator session is closed")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
