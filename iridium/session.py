"""Coordinate guest processors, inferred board links and explicit test stimuli."""

from collections import deque
from pathlib import Path
import re
import tempfile
import threading
import time

from .assets import AssetError, BC5Assets
from .board import ModemLink, SpiLink
from .engine import Engine, EngineError
from .firmware import Firmware
from .lcd import ST7541
from .profiles import KEY_CODES, PROFILES
from .satellite import Satellite


ALL_KEYS = set(KEY_CODES) | {"power", "convenience", "sos"}
LIMITATIONS = [
    "Digital hardware behavior and processor clock ratios are inferred from firmware; physical timing is not calibrated.",
    "Empty upgrade images need factory settings; original factory routines provision these before hardware startup.",
    "Keys use the GPIO matrix and power uses AVR inputs; the 9575 SOS electrical path is unresolved and uses its known software entry.",
    "LCD output uses inferred serial/controller models; resource previews remain separate from live output.",
    "Satellite service scenarios are offline and are not connected to the modem firmware.",
    "Unshipped modem boot ROM/DSP code, unestablished RF behavior and SIM/provisioning are outside the modeled scope.",
]


class Session:
    def __init__(self, executable: Path, firmware: list[Firmware], engine_factory=Engine,
                 *, strict_hardware: bool = False, modem_image: str = "trx"):
        if not firmware or len({item.model for item in firmware}) != 1:
            raise ValueError("Load at least one image, all for the same handset model")
        self.model = firmware[0].model
        if modem_image not in ("trx", "ptt", "none"):
            raise ValueError("modem_image must be trx, ptt or none")
        self.modem_image = modem_image
        self.modem_link = None
        self.spi_link = None
        self.strict_hardware = strict_hardware
        self._executable = executable
        self._engine_factory = engine_factory
        self._temporary = tempfile.TemporaryDirectory(prefix="iridium-")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._closed = False
        self.engines = {}
        self.firmware = {}
        self.events = deque(maxlen=200)
        self.keys = set()
        self.key_generations = {key: 0 for key in ALL_KEYS}
        self.key_epoch = 0
        self._key_clients = {}
        self._key_sources = {key: set() for key in ALL_KEYS}
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

    @property
    def profile(self):
        return PROFILES[self.model]

    def load(self, firmware: Firmware) -> None:
        with self._lock:
            self._ensure_open()
            if firmware.model != self.model and firmware.image != "bc5":
                raise ValueError("Load the new handset's BC5 image before its auxiliary processors")
            # A replacement worker is ready before the previous experiment is discarded.
            with tempfile.NamedTemporaryFile(dir=self._temporary.name, suffix=".bin", delete=False) as out:
                out.write(firmware.data)
                path = Path(out.name)
            try:
                worker = self._engine_factory(self._executable, firmware.image, path, model=firmware.model)
                if self.strict_hardware:
                    try:
                        worker.request("hardware", strict=True)
                    except BaseException:
                        worker.close()
                        raise
            finally:
                path.unlink(missing_ok=True)
            restart_board = firmware.image == "avr" and "bc5" in self.engines
            clear_inputs = firmware.image == "bc5" or restart_board
            if firmware.model == self.model and clear_inputs:
                try:
                    primary = self.engines.get("bc5")
                    for key in self.keys:
                        code = self.profile.key_codes.get(key)
                        if primary and primary.state.get("bc5_hardware") and code is not None and key != "sos":
                            if firmware.image != "bc5":
                                self._request(primary, "key", code=code, pressed=False)
                        elif key == "power" and self.spi_link and firmware.image != "avr":
                            self._power_input(False)
                    # A new AVR starts a new board boot. Reset the retained primary
                    # so no native DMA byte remains owned by the retired SPI link.
                    if restart_board:
                        self._request(primary, "warm_reset")
                        self._reset_display()
                except BaseException:
                    worker.close()
                    raise
            if firmware.model != self.model:
                # The new primary image starts a separate board experiment.
                for old in self.engines.values():
                    old.close()
                self.engines.clear()
                self.firmware.clear()
                self.model = firmware.model
                self.satellite = Satellite()
            old = self.engines.get(firmware.image)
            self.engines[firmware.image] = worker
            self.firmware[firmware.image] = firmware
            if old:
                old.close()
            self._connect_modem()
            self.running = False
            if clear_inputs:
                self._clear_keys()
            if firmware.image == "bc5":
                self._reset_display()
                self.asset = None
                try:
                    file_id = firmware.profile.animation_file
                    bitmap = BC5Assets(firmware.data, firmware.profile).bitmap(file_id, 49)
                    self.asset = {"width": bitmap.width, "height": bitmap.height,
                                  "pixels": list(bitmap.pixels), "frame": 49,
                                  "frames": bitmap.frame_count, "source": f"firmware resource {file_id}",
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
        remaining = steps
        while remaining:
            quantum = self._board_quantum(remaining)
            amount = min(remaining, quantum)
            self._step_processors(amount)
            self._exchange_links()
            if (self.spi_link or self.modem_link) and any(
                    worker.state.get("halt") not in (None, "steps", "running", "ready")
                    for worker in self._active_processors()):
                self.running = False
                break
            remaining -= amount
        # Explicit virtual scenario time; this does not assert a physical CPU clock ratio.
        self.satellite.advance(20)
        if all(worker.state.get("halt") not in (None, "steps", "running", "ready")
               for worker in self._active_processors()):
            self.running = False

    def _active_processors(self):
        return [worker for image, worker in self.engines.items()
                if (not self.modem_link or image not in ("trx", "ptt") or image == self.modem_image)
                and not (image == "avr" and self.spi_link and self.spi_link.hold_reset)]

    def _board_quantum(self, limit):
        return min(limit, self.spi_link.quantum if self.spi_link else limit,
                   self.modem_link.quantum if self.modem_link else limit)

    def _connect_modem(self):
        if "avr" in self.engines and self.modem_image in self.engines:
            endpoints = ((self.engines["avr"], 0), (self.engines[self.modem_image], 1))
            if not self.modem_link or self.modem_link.endpoints != endpoints:
                self.modem_link = ModemLink(self.engines["avr"], self.engines[self.modem_image], self.modem_image)
        else:
            self.modem_link = None
        if "bc5" in self.engines and "avr" in self.engines:
            bc5, avr = self.engines["bc5"], self.engines["avr"]
            if not self.spi_link or self.spi_link.bc5 is not bc5 or self.spi_link.avr is not avr:
                state = bc5.request("hardware", serial_peer=True)
                self.spi_link = SpiLink(bc5, avr, self.model, reset_count=state["gpio"]["reset_count"])
        else:
            self.spi_link = None

    def _service_board(self, steps):
        self._clock_reset(steps)
        for worker in self._active_processors():
            if worker is self.engines.get("bc5"):
                continue
            result = self._request(worker, "run", steps=steps)
            if result.get("halt") not in (None, "steps", "running", "ready"):
                raise EngineError(f"Peripheral processor halted during board service: {result.get('halt')}")
        self._exchange_links()

    def _clock_reset(self, cycles):
        if self.spi_link and self.spi_link.hold_reset:
            self._request(self.engines["avr"], "reset_clock", cycles=cycles)

    def _exchange_links(self):
        avr_reset = False
        if self.spi_link:
            before = self.spi_link.resets
            self.spi_link.exchange()
            avr_reset = self.spi_link.hold_reset or self.spi_link.resets != before
        if self.modem_link:
            self.modem_link.exchange(avr_reset=avr_reset)

    def _step_processors(self, steps: int) -> None:
        self._clock_reset(steps)
        for worker in self._active_processors():
            previous = worker.state.get("halt")
            if previous not in (None, "steps", "running", "ready"):
                continue
            result = self._request(worker, "run", steps=steps)
            halt = result.get("halt")
            if halt not in (None, "steps", "running", "ready") and halt != previous:
                self.log("cpu", f"{result.get('image')}: {halt} at {result.get('pc')}")

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
                self.modem_link = None
                self.spi_link = None
                reset_error = None
                for worker in self.engines.values():
                    try:
                        worker.request("reset")
                    except EngineError as error:
                        if reset_error is None:
                            reset_error = error
                if reset_error is not None:
                    raise reset_error
                self._connect_modem()
            elif action == "initialize_ui":
                self.running = False
                self._initialize_ui()
                self.running = self.lcd_capture_error is None
            else:
                raise ValueError("Unknown execution action")
            self.log("control", action)
            return {"ok": True, "message": action, "key_epoch": self.key_epoch}

    def _clear_keys(self) -> None:
        self.keys.clear()
        self.key_epoch += 1
        self._key_clients.clear()
        for sources in self._key_sources.values():
            sources.clear()
        for key in self.key_generations:
            self.key_generations[key] += 1

    def key(self, key: str, pressed: bool, generation: int | None = None, *,
            client_id: str | None = None, sequence: int | None = None,
            epoch: int | None = None) -> dict:
        if not isinstance(key, str) or type(pressed) is not bool:
            raise ValueError("Unknown key or invalid pressed state")
        if generation is not None and (type(generation) is not int or generation < 0):
            raise ValueError("generation must be a nonnegative integer")
        browser = any(value is not None for value in (client_id, sequence, epoch))
        if browser:
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", client_id):
                raise ValueError("client_id must contain 1 to 64 ASCII letters, digits, underscores or hyphens")
            if type(sequence) is not int or not 1 <= sequence <= 2**53 - 1:
                raise ValueError("sequence must be an integer from 1 to 9007199254740991")
            if type(epoch) is not int or not 0 <= epoch <= 2**53 - 1:
                raise ValueError("epoch must be a nonnegative safe integer")
            if generation is not None:
                raise ValueError("Use either browser sequencing or legacy generation")
        with self._lock:
            self._ensure_open()
            if key not in self.profile.keys:
                raise ValueError("Unknown key for this handset")
            response = {"ok": True, "delivered": False, "key_epoch": self.key_epoch,
                        "generation": self.key_generations[key]}
            if browser:
                if epoch != self.key_epoch:
                    return {**response, "message": "Stale key epoch ignored"}
                if client_id not in self._key_clients:
                    # shortcut: 128 clients until reset, add client leases if sessions need more pages.
                    if len(self._key_clients) >= 128:
                        raise ValueError("Key client limit (128) reached; reset the session before opening more clients")
                    self._key_clients[client_id] = {}
                sequences = self._key_clients[client_id]
                if sequence <= sequences.get(key, 0):
                    return {**response, "message": "Stale key sequence ignored"}
            if generation is not None and generation != self.key_generations[key]:
                return {**response, "message": "Stale key event ignored"}
            sources = self._key_sources[key]
            source = client_id if browser else None
            down = pressed or bool(sources - {source})
            changed = (key in self.keys) != down
            delivered = False
            electrical = False
            try:
                key_code = self.profile.key_codes.get(key)
                worker = self.engines.get("bc5")
                if changed and worker and worker.state.get("bc5_hardware") and key_code is not None and key != "sos":
                    if self.ui_initialized and worker.request("read", address=self.profile.key_callback, count=2)["values"] == [0, 0]:
                        self.ui_initialized = False
                    self._request(worker, "key", code=key_code, pressed=down)
                    delivered = electrical = True
                elif changed and key == "power" and self.spi_link:
                    self._power_input(down)
                    delivered = electrical = True
                elif changed and self.ui_initialized and key_code is not None:
                    worker = self.engines["bc5"]
                    self._idle(worker)
                    callback = worker.request("read", address=self.profile.key_callback, count=2)["values"]
                    if callback == [0, 0]:
                        self.ui_initialized = False
                        raise EngineError("Firmware key handler is absent; reset before reinitializing")
                    self._call(worker, self.profile.key_entry, al=key_code, ah=1 if down else 4, steps=100000)
                    delivered = True
                if pressed:
                    sources.add(source)
                else:
                    sources.discard(source)
                if down:
                    self.keys.add(key)
                else:
                    self.keys.discard(key)
                if browser:
                    # Record releases even when already up, cancelling older in-flight presses.
                    sequences[key] = sequence
                elif not pressed:
                    self.key_generations[key] += 1
                if delivered:
                    if electrical:
                        self._step(5200000 if key == "power" and down else 150000)
                    else:
                        self._idle(worker)
            except EngineError:
                self.running = False
                raise
            message = f"{key} {'down' if pressed else 'up'} " + (
                "applied to the emulated electrical input" if electrical else
                "delivered through original software key routine" if delivered else
                "recorded; shared key state unchanged" if not changed else
                "recorded; this control's hardware input is not connected" if key_code is None else
                "recorded; initialize the application first")
            self.log("key", message)
            return {"ok": True, "delivered": delivered, "message": message,
                    "generation": self.key_generations[key], "key_epoch": self.key_epoch}

    def _power_input(self, pressed):
        worker = self.engines["avr"]
        port, bit = self.profile.power_pin
        value = worker.request("pin_state")["inputs"][port]
        value = value & ~(1 << bit) if pressed else value | (1 << bit)
        self._request(worker, "pins", port=port, value=value)

    def probe(self, image: str, operation: str, arguments: dict) -> dict:
        if operation not in ("read", "write", "call", "state", "pins", "uart_rx", "uart_tx", "spi",
                             "adc", "irq", "trace", "uart_io", "comparator", "async_clock", "twi",
                             "program_read", "fuses", "pin_state", "serial", "call_resume", "key"):
            raise ValueError("Unsupported debugger operation")
        with self._lock:
            self._ensure_open()
            if self.running:
                raise ValueError("Pause execution before a debugger probe")
            if image not in self.engines:
                raise ValueError("Processor image is not loaded")
            worker = self.engines[image]
            if image == "bc5" and operation in ("call", "call_resume"):
                response = self._probe_operation(worker, operation, arguments)
            else:
                response = self._request(worker, operation, **arguments)
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
            limitations = list(LIMITATIONS)
            if self.model == "9575":
                limitations.append("9575 GPS receiver, location reports and SOS service transport are not connected.")
            return {"handset": self.profile.describe(),
                    "firmware": primary.describe(), "images": [item.describe() for item in self.firmware.values()],
                    "processors": [dict(worker.state) for worker in self.engines.values()],
                    "running": self.running, "keys": sorted(self.keys),
                    "key_generations": dict(self.key_generations),
                    "key_epoch": self.key_epoch,
                    "satellite": self.satellite.state(), "events": list(self.events),
                    "asset": self.asset, "lcd": lcd, "ui_initialized": self.ui_initialized,
                    "processor_link": self.modem_link.state() if self.modem_link else {"connected": False},
                    "spi_link": self.spi_link.state() if self.spi_link else {"connected": False},
                    "fidelity": {"complete": False, "scope": "firmware-derived",
                                 "board_coupled": bool(self.spi_link and self.modem_link), "limitations": limitations}}

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
            if self.ui_initialized and response.get("power_state") in (2, 8):
                self.ui_initialized = False
                self.ui_attempted = False
                self.log("firmware", "Original firmware powered off")
        return response

    def _idle(self, worker) -> None:
        if self.spi_link:
            remaining = 30000000
            while remaining > 0:
                quantum = self._board_quantum(remaining)
                response = self._request(worker, "idle", steps=quantum)
                remaining -= quantum
                if response.get("halt"):
                    break
                if response.get("at_idle"):
                    return
                self._service_board(quantum)
            raise EngineError(f"Cannot reach a safe scheduler boundary: {response.get('halt') or 'instruction budget exhausted'}")
        # A configured warm boot also runs the application's device initialization.
        for _ in range(3):
            response = self._request(worker, "idle", steps=10000000)
            if response.get("halt"):
                break
            if response.get("at_idle"):
                return
        raise EngineError(f"Cannot reach a safe scheduler boundary: {response.get('halt') or 'instruction budget exhausted'}")

    def _call(self, worker, entry: int, **arguments) -> dict:
        response = self._probe_call(worker, entry, **arguments)
        if response.get("halt") or not (response.get("last_call") or {}).get("returned"):
            raise EngineError(f"Original function 0x{entry:X} did not return: {response.get('halt')}")
        return response

    def _probe_call(self, worker, entry, **arguments):
        return self._probe_operation(worker, "call", {"entry": entry, **arguments})

    def _probe_operation(self, worker, operation, arguments):
        arguments = dict(arguments)
        budget = arguments.get("steps", 100000 if operation == "call" else 100000000)
        if self.spi_link and type(budget) is int and budget > 0:
            arguments.setdefault("quantum", self._board_quantum(budget))
        before = (worker.state.get("last_call") or {}).get("steps", 0) if operation == "call_resume" else 0
        # Native validation must run before any peripheral processor advances.
        response = self._request(worker, operation, **arguments)
        peripheral_budget = budget
        while (response.get("last_call") or {}).get("pending"):
            remaining = budget - (response["last_call"]["steps"] - before)
            if remaining <= 0:
                return response
            if not self.spi_link:
                if not response.get("serial_waiting"):
                    return response
                raise EngineError("Function probe is waiting for a connected serial peer")
            if not self.spi_link.pending:
                self._exchange_links()
            quantum = self._board_quantum(min(remaining, peripheral_budget))
            if quantum <= 0:
                raise EngineError("Peripheral wait exceeded the function-probe budget; reset before retrying")
            self._service_board(quantum)
            peripheral_budget -= quantum
            response = self._request(worker, "call_resume", steps=quantum)
        return response

    def _initialize_ui(self) -> None:
        if self.ui_initialized:
            return
        if self.ui_attempted:
            raise EngineError("Application initialization was incomplete; reset before retrying")
        if "bc5" not in self.engines:
            raise ValueError("Load BC5 firmware before initializing the handset application")
        if not self.spi_link:
            raise ValueError("Load AVR firmware with BC5 firmware before powering on the handset")
        if "power" in self.keys:
            raise ValueError("Release the power button before powering on the handset")
        self.ui_attempted = True
        worker = self.engines["bc5"]
        self._request(worker, "warm_reset")
        self._idle(worker)
        if worker.request("read", address=self.profile.graphics_pointer, count=1)["values"] == [0]:
            self._call(worker, self.profile.graphics_init, steps=10000000)
        setup = self._probe_call(worker, self.profile.application_setup, steps=10000000)
        if setup.get("halt") != "firmware-reset-requested" and (
                setup.get("halt") or not (setup.get("last_call") or {}).get("returned")):
            raise EngineError(f"Original application setup did not return: {setup.get('halt')}")
        # Startup samples the released, active-low power button before polling changes.
        self._power_input(False)
        try:
            self._request(worker, "warm_reset")
            self._idle(worker)
            self.log("firmware", "Original factory defaults retained across the warm reset")
            for _ in range(200):
                self._step(200000)
                if worker.state.get("halt"):
                    raise EngineError(f"Handset startup halted: {worker.state['halt']}")
                callback = worker.request("read", address=self.profile.key_callback, count=2)["values"]
                if callback != [0, 0]:
                    break
            else:
                raise EngineError("Original firmware did not power on within the startup budget")
        finally:
            self._power_input(False)
        self._idle(worker)
        callback = worker.request("read", address=self.profile.key_callback, count=2)["values"]
        if callback == [0, 0]:
            raise EngineError("Original initialization did not install a key handler")
        if self.lcd_capture_error:
            raise EngineError(f"Application display initialization failed: {self.lcd_capture_error}")
        self.ui_initialized = True
        self.log("firmware", "Factory settings initialized by original code; firmware powered on through AVR inputs")

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
            self.modem_link = None
            self.spi_link = None
        if self._thread:
            self._thread.join(timeout=2)

    def _ensure_open(self) -> None:
        if self._closed:
            raise EngineError("Emulator session is closed")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
