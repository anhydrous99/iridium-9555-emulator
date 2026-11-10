"""Coordinate guest processors, inferred board links and explicit test stimuli."""

from collections import deque
from pathlib import Path
import re
import tempfile
import threading
import time
from uuid import uuid4

from .assets import AssetError, BC5Assets
from .board import ModemLink, SpiLink
from .engine import Engine, EngineError
from .display_text import DisplayText
from .firmware import Firmware
from .fixtures import GPSPeer, SIMPeer, SyntheticSIM
from .lcd import ST7541
from .offline_modem import OfflineModem
from .profiles import KEY_CODES, PROFILES
from .satellite import Satellite


ALL_KEYS = set(KEY_CODES) | {"power", "convenience", "sos"}
LIMITATIONS = [
    "Digital hardware behavior and processor clock ratios are inferred from firmware; physical timing is not calibrated.",
    "Empty upgrade images need factory settings; original factory routines provision these before hardware startup.",
    "Modem boot-ROM code is absent; a virtual version-4000 handoff selects the supported handset family.",
    "The CSR bank-header fixture supplies the FFFE revision expected by both original upgrade tools.",
    "Keys use the GPIO matrix; power and 9575 SOS use firmware-derived AVR inputs.",
    "LCD output uses inferred serial/controller models; resource previews remain separate from live output.",
    "Satellite service scenarios are offline and are not connected to the modem firmware.",
    "The modem boot ROM is unshipped; DSP execution, RF behavior and real subscriber authentication are outside the modeled scope.",
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
        self.mode = "research"
        self.sim_present = False
        self.sim_card = SyntheticSIM()
        self.sim_peer = None
        self.gps_peer = None
        self.gps_configuration = None
        self.training_storage = {}
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
        self.session_id = uuid4().hex
        self._key_clients = {}
        self._key_sources = {key: set() for key in ALL_KEYS}
        self.satellite = Satellite()
        self.running = False
        self.asset = None
        self.display_text = None
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

    def _start_worker(self, firmware: Firmware):
        worker = None
        try:
            with tempfile.NamedTemporaryFile(dir=self._temporary.name, suffix=".bin") as out:
                out.write(firmware.data)
                out.flush()
                worker = self._engine_factory(self._executable, firmware.image, Path(out.name), model=firmware.model)
                if self.strict_hardware:
                    worker.request("hardware", strict=True)
            return worker
        except BaseException as error:
            if worker is not None:
                worker.close()
            if isinstance(error, OSError):
                raise EngineError(f"Cannot start {firmware.image} worker: {error}") from error
            raise

    def load(self, firmware: Firmware) -> None:
        self.load_bundle([firmware])

    def load_bundle(self, images: list[Firmware]) -> None:
        """Validate and start every replacement before retiring any current worker."""
        with self._lock:
            self._ensure_open()
            if not images or len(images) > 4 or len({item.image for item in images}) != len(images):
                raise ValueError("Choose one to four different processor images")
            if len({item.model for item in images}) != 1:
                raise ValueError("All images must belong to the same handset model")
            model = images[0].model
            replacements = {item.image: item for item in images}
            if model != self.model and "bc5" not in replacements:
                raise ValueError("Load the new handset's BC5 image before its auxiliary processors")
            workers = {}
            restart_board = "avr" in replacements and "bc5" in self.engines
            clear_inputs = "bc5" in replacements or restart_board
            try:
                for item in images:
                    workers[item.image] = self._start_worker(item)
                if model == self.model and clear_inputs:
                    primary = self.engines.get("bc5")
                    for key in self.keys:
                        code = self.profile.key_codes.get(key)
                        if primary and primary.state.get("bc5_hardware") and code is not None and key != "sos":
                            if "bc5" not in replacements:
                                self._request(primary, "key", code=code, pressed=False)
                        elif key in self.profile.button_pins and self.spi_link and "avr" not in replacements:
                            self._button_input(key, False)
                    # A new AVR starts a new board boot. Reset the retained primary
                    # so no native DMA byte remains owned by the retired SPI link.
                    if restart_board and "bc5" not in replacements:
                        self._request(primary, "warm_reset")
                        self._reset_display()
            except BaseException:
                for worker in workers.values():
                    worker.close()
                raise
            if model != self.model:
                # The new primary image starts a separate board experiment.
                for old in self.engines.values():
                    old.close()
                self.engines.clear()
                self.firmware.clear()
                self.model = model
                self.satellite = Satellite()
                self.sim_card = SyntheticSIM()
                self.training_storage = {}
                self.gps_configuration = None
            for name, worker in workers.items():
                old = self.engines.get(name)
                self.engines[name] = worker
                self.firmware[name] = replacements[name]
                if old:
                    old.close()
            self._connect_modem()
            self.running = False
            if clear_inputs:
                self._clear_keys()
            if "bc5" in replacements:
                firmware = replacements["bc5"]
                self.display_text = DisplayText(firmware)
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
            for firmware in images:
                self.log("firmware", f"Loaded {firmware.name} ({firmware.image}), SHA-256 {firmware.sha256}")

    def start(self) -> None:
        with self._lock:
            self._ensure_open()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="firmware-runner", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        delay = 0.02
        while not self._stop.wait(delay):
            started = time.monotonic()
            with self._lock:
                if self.running:
                    try:
                        self._step(200000)
                    except (EngineError, ValueError) as error:
                        self.running = False
                        self.log("error", str(error))
            # Execution time counts toward pacing; yield briefly when already behind.
            delay = max(0.001, 0.02 - (time.monotonic() - started))

    def _step(self, steps: int) -> None:
        remaining = steps
        while remaining:
            quantum = self._board_quantum(remaining)
            amount = min(remaining, quantum)
            halted = self._step_processors(amount)
            if (self.spi_link or self.modem_link) and halted:
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
                if not (self.mode == "training" and image in ("trx", "ptt"))
                and (not self.modem_link or image not in ("trx", "ptt")
                    or image == self.modem_image and self.modem_link.powered)
                and not (image == "avr" and self.spi_link and self.spi_link.hold_reset)]

    def _board_quantum(self, limit):
        return min(limit, self.spi_link.quantum if self.spi_link else limit,
                   self.modem_link.quantum if self.modem_link else limit)

    def _connect_modem(self):
        if self.mode == "training" and "avr" in self.engines:
            avr = self.engines["avr"]
            power_pin = self.profile.modem_power_pin if "bc5" in self.engines else None
            if (not isinstance(self.modem_link, OfflineModem) or self.modem_link.avr is not avr
                    or self.modem_link.power_pin != power_pin):
                self.modem_link = OfflineModem(avr, self.satellite, avr_port=self.profile.modem_uart,
                                              power_pin=power_pin,
                                              sim_present=self.sim_present, storage=self.training_storage)
        elif "avr" in self.engines and self.modem_image in self.engines:
            endpoints = ((self.engines["avr"], self.profile.modem_uart), (self.engines[self.modem_image], 1))
            power_pin = self.profile.modem_power_pin if "bc5" in self.engines else None
            if (not self.modem_link or self.modem_link.endpoints != endpoints
                    or self.modem_link.power_pin != power_pin):
                self.modem_link = ModemLink(self.engines["avr"], self.engines[self.modem_image], self.modem_image,
                                           avr_port=self.profile.modem_uart, power_pin=power_pin)
        else:
            self.modem_link = None
        if "bc5" in self.engines and "avr" in self.engines:
            bc5, avr = self.engines["bc5"], self.engines["avr"]
            if not self.spi_link or self.spi_link.bc5 is not bc5 or self.spi_link.avr is not avr:
                state = bc5.request("hardware", serial_peer=True)
                self.spi_link = SpiLink(bc5, avr, self.model, reset_count=state["gpio"]["reset_count"])
        else:
            self.spi_link = None
        self._connect_fixtures()

    def _connect_fixtures(self):
        modem = self.engines.get(self.modem_image)
        if self.mode == "research" and self.modem_image == "trx" and modem:
            if self.sim_present:
                if not self.sim_peer or self.sim_peer.modem is not modem or self.sim_peer.card is not self.sim_card:
                    self.sim_peer = SIMPeer(modem, self.sim_card)
            else:
                modem.request("uart_pins", port=3, value=0, mask=1)
                self.sim_peer = None
        else:
            self.sim_peer = None
        avr = self.engines.get("avr")
        if self.model == "9575" and avr and self.gps_configuration:
            if not self.gps_peer or self.gps_peer.avr is not avr:
                self.gps_peer = GPSPeer(avr, **self.gps_configuration)
        else:
            self.gps_peer = None

    def _service_board(self, steps):
        self._clock_reset(steps)
        for worker in self._active_processors():
            if worker is self.engines.get("bc5"):
                continue
            result = self._request(worker, "run", steps=steps)
            if result.get("halt") not in (None, "steps", "running", "ready"):
                raise EngineError(f"Peripheral processor halted during board service: {result.get('halt')}")
        self._exchange_links()

    def _service_board_elapsed(self, steps):
        # Apply reset before executing peripherals, including after a terminal chunk.
        self._exchange_links(acknowledge_spi=False)
        while steps:
            quantum = self._board_quantum(steps)
            self._service_board(quantum)
            steps -= quantum

    def _clock_reset(self, cycles):
        if self.spi_link and self.spi_link.hold_reset:
            self._request(self.engines["avr"], "reset_clock", cycles=cycles)

    def _exchange_links(self, *, acknowledge_spi=True):
        avr_reset = False
        if self.spi_link:
            before = self.spi_link.resets
            self.spi_link.exchange(acknowledge=acknowledge_spi)
            avr_reset = self.spi_link.hold_reset or self.spi_link.resets != before
        if self.modem_link:
            self.modem_link.exchange(avr_reset=avr_reset)
        if self.sim_peer and (not self.modem_link or self.modem_link.powered):
            self.sim_peer.exchange()
        if self.gps_peer:
            self.gps_peer.exchange(avr_reset=avr_reset)

    def _step_processors(self, steps: int) -> bool:
        primary = self.engines.get("bc5") if self.spi_link else None
        newly_halted = False
        if primary:
            before = primary.state["steps"]
            halted = primary.state.get("halt") not in (None, "steps", "running", "ready")
            newly_halted = self._step_processor(primary, steps)
            if not halted:
                steps = primary.state["steps"] - before
            self._exchange_links(acknowledge_spi=False)
        while steps:
            quantum = self._board_quantum(steps)
            self._clock_reset(quantum)
            workers = [worker for worker in self._active_processors() if worker is not primary]
            newly_halted = self._step_processor_group(workers, quantum) or newly_halted
            self._exchange_links()
            steps -= quantum
        return newly_halted

    def _step_processor_group(self, workers, steps):
        if (len(workers) < 2 or self.engines.get("bc5") in workers
                or not all(type(worker) is Engine and "request" not in worker.__dict__ for worker in workers)):
            halted = False
            for worker in workers:
                halted = self._step_processor(worker, steps) or halted
            return halted
        active = [(worker, worker.state.get("halt")) for worker in workers]
        active = [(worker, halt) for worker, halt in active if halt in (None, "steps", "running", "ready")]
        results = Engine.run_group([worker for worker, _ in active], steps)
        halted = False
        for (_, previous), result in zip(active, results):
            halted = self._record_processor_halt(result, previous) or halted
        return halted

    def _step_processor(self, worker, steps):
        previous = worker.state.get("halt")
        if previous not in (None, "steps", "running", "ready"):
            return False
        result = self._request(worker, "run", steps=steps)
        return self._record_processor_halt(result, previous)

    def _record_processor_halt(self, result, previous):
        halt = result.get("halt")
        if halt not in (None, "steps", "running", "ready") and halt != previous:
            self.log("cpu", f"{result.get('image')}: {halt} at {result.get('pc')}")
            return True
        return False

    def control(self, action: str, steps: int = 10000, *, mode: str | None = None) -> dict:
        if type(steps) is not int or not 1 <= steps <= 10000000:
            raise ValueError("steps must be an integer from 1 to 10000000")
        with self._lock:
            self._ensure_open()
            if action == "run":
                halted = [worker.state.get("halt") for worker in self._active_processors()
                          if worker.state.get("halt") not in (None, "steps", "running", "ready")]
                if halted:
                    self.running = False
                    self._check_restartable(self.mode)
                    raise ValueError("A processor has halted; restart the handset to continue: " + ", ".join(halted))
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
                self.sim_card = SyntheticSIM()
                self.training_storage = {}
                self.sim_peer = self.gps_peer = None
                self._reset_display()
                self.modem_link = None
                self.spi_link = None
                reset_error = None
                for image, worker in self.engines.items():
                    try:
                        try:
                            worker.request("reset")
                        except EngineError:
                            if worker.state.get("halt") != "worker-failed":
                                raise
                            self.engines[image] = self._start_worker(self.firmware[image])
                            worker.close()
                    except EngineError as error:
                        if reset_error is None:
                            reset_error = error
                if reset_error is not None:
                    raise reset_error
                self._connect_modem()
            elif action == "restart":
                self._restart()
            elif action == "mode":
                if mode not in ("research", "training"):
                    raise ValueError("mode must be research or training")
                if mode != self.mode:
                    self._check_restartable(mode)
                    initialize = self.ui_initialized or self.ui_attempted
                    self.mode = mode
                    if mode == "training":
                        self.sim_present = True
                    self._restart(initialize=initialize)
            elif action == "initialize_ui":
                self.running = False
                self._initialize_ui()
                self.running = self.lcd_capture_error is None
            else:
                raise ValueError("Unknown execution action")
            self.log("control", action)
            return {"ok": True, "message": action, "key_epoch": self.key_epoch,
                    "session_id": self.session_id}

    def _restart(self, *, initialize=True):
        """Restart the board without replacing its programmed flash or EEPROM."""
        self.running = False
        self._check_restartable(self.mode)
        for key in self.keys:
            if key in self.profile.button_pins and self.spi_link:
                self._button_input(key, False)
            elif "bc5" in self.engines and self.engines["bc5"].state.get("bc5_hardware"):
                code = self.profile.key_codes.get(key)
                if code is not None and key != "sos":
                    self._request(self.engines["bc5"], "key", code=code, pressed=False)
        self._clear_keys()
        self._reset_display()
        self.satellite = Satellite()
        self.modem_link = self.spi_link = None
        self.sim_card.controls(0, 0)
        if self.gps_peer:
            self.gps_peer.reset()
        for image, worker in self.engines.items():
            if not (self.mode == "training" and image in ("trx", "ptt")):
                self._request(worker, "warm_reset")
        self._connect_modem()
        if self.spi_link and initialize:
            self._initialize_ui()
            self.running = self.lcd_capture_error is None

    def _check_restartable(self, mode):
        if any(worker.state.get("halt") == "worker-failed" for image, worker in self.engines.items()
               if not (mode == "training" and image in ("trx", "ptt"))):
            raise EngineError("A worker exited; its in-memory changes cannot be recovered. Clear the experiment to reload the input images.")

    def fixture_action(self, action, arguments):
        with self._lock:
            self._ensure_open()
            if action == "sim":
                present = arguments.get("present")
                if type(present) is not bool:
                    raise ValueError("present must be a boolean")
                if present and self.mode == "research" and self.modem_image != "trx":
                    raise ValueError("The synthetic SIM requires the telephony modem or offline training mode")
                if present != self.sim_present:
                    self._check_restartable(self.mode)
                    initialized = self.ui_initialized or self.ui_attempted
                    self.sim_present = present
                    self._restart(initialize=initialized)
            elif action == "gps":
                if self.model != "9575" or "avr" not in self.engines:
                    raise ValueError("The synthetic GPS receiver requires the 9575 AVR image")
                enabled = arguments.get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("enabled must be a boolean")
                configuration = {key: arguments.get(key, default) for key, default in
                                 (("latitude", 37.7749), ("longitude", -122.4194), ("altitude", 30))}
                peer = GPSPeer(self.engines["avr"], **configuration) if enabled else None
                self.gps_configuration = configuration if enabled else None
                self.gps_peer = peer
            else:
                raise ValueError("Unknown synthetic peripheral")
            self.log("fixture", f"Synthetic {action} updated")
            return self.state()

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
            epoch: int | None = None, session_id: str | None = None, settle: bool = False) -> dict:
        if type(settle) is not bool:
            raise ValueError("settle must be a boolean")
        if not isinstance(key, str) or type(pressed) is not bool:
            raise ValueError("Unknown key or invalid pressed state")
        if generation is not None and (type(generation) is not int or generation < 0):
            raise ValueError("generation must be a nonnegative integer")
        browser = any(value is not None for value in (client_id, sequence, epoch, session_id))
        if browser:
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", client_id):
                raise ValueError("client_id must contain 1 to 64 ASCII letters, digits, underscores or hyphens")
            if type(sequence) is not int or not 1 <= sequence <= 2**53 - 1:
                raise ValueError("sequence must be an integer from 1 to 9007199254740991")
            if type(epoch) is not int or not 0 <= epoch <= 2**53 - 1:
                raise ValueError("epoch must be a nonnegative safe integer")
            if session_id is not None and (not isinstance(session_id, str)
                                          or not re.fullmatch(r"[0-9a-f]{32}", session_id)):
                raise ValueError("session_id must contain 32 lowercase hexadecimal digits")
            if generation is not None:
                raise ValueError("Use either browser sequencing or legacy generation")
        with self._lock:
            self._ensure_open()
            if key not in self.profile.keys:
                raise ValueError("Unknown key for this handset")
            response = {"ok": True, "delivered": False, "key_epoch": self.key_epoch,
                        "session_id": self.session_id, "generation": self.key_generations[key]}
            if browser:
                if session_id is not None and session_id != self.session_id:
                    return {**response, "message": "Stale key session ignored"}
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
                if changed and key in self.profile.button_pins and self.spi_link:
                    self._button_input(key, down)
                    delivered = electrical = True
                elif changed and worker and worker.state.get("bc5_hardware") and key_code is not None and key != "sos":
                    if self.ui_initialized and worker.request("read", address=self.profile.key_callback, count=2)["values"] == [0, 0]:
                        self.ui_initialized = False
                    self._request(worker, "key", code=key_code, pressed=down)
                    delivered = electrical = True
                elif changed and self.ui_initialized and key_code is not None and key != "sos":
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
                    if settle and not pressed and self.ui_initialized:
                        # Browser taps include bounded guest time even while paused.
                        # Debugger/key-matrix clients retain exact stepping by default.
                        self._step(2000000)
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
                    "generation": self.key_generations[key], "key_epoch": self.key_epoch,
                    "session_id": self.session_id}

    def _button_input(self, key, pressed):
        worker = self.engines["avr"]
        port, bit = self.profile.button_pins[key]
        value = worker.request("pin_state")["inputs"][port]
        value = value & ~(1 << bit) if pressed else value | (1 << bit)
        self._request(worker, "pins", port=port, value=value)

    def probe(self, image: str, operation: str, arguments: dict) -> dict:
        if operation not in ("read", "write", "call", "state", "pins", "uart_rx", "uart_tx", "spi",
                             "adc", "irq", "trace", "uart_io", "comparator", "async_clock", "twi",
                             "program_read", "fuses", "pin_state", "serial", "call_resume", "key", "uart_pins"):
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
                if self.mode == "training" and not (self.ui_initialized and
                        isinstance(self.modem_link, OfflineModem) and self.modem_link.powered):
                    raise ValueError("Power on the handset before starting an incoming training call")
                self.satellite.incoming_call(arguments.get("number", "+881612345678"))
            elif action == "incoming_sms":
                if isinstance(self.modem_link, OfflineModem):
                    self.modem_link.validate_incoming_sms(arguments.get("number", "+881612345678"),
                                                          arguments.get("text", "Test message"))
                self.satellite.incoming_sms(arguments.get("number", "+881612345678"),
                                            arguments.get("text", "Test message"))
                if isinstance(self.modem_link, OfflineModem):
                    self.modem_link.incoming_sms(arguments.get("number", "+881612345678"),
                                                 arguments.get("text", "Test message"))
            elif action == "answer":
                self.satellite.answer()
            elif action == "hangup":
                self.satellite.hangup()
            else:
                raise ValueError("Unknown satellite action")
            connected = isinstance(self.modem_link, OfflineModem)
            if connected:
                self.modem_link.notify_scenario()
                if self.ui_initialized:
                    self._step(2000000)
            message = ("Offline training scenario queued for the handset" if connected else
                       "Scenario updated; select offline training mode to connect it to the handset")
            self.log("satellite", f"Scenario {action}; {message}")
            return {"ok": True, "delivered": connected, "message": message}

    def state(self) -> dict:
        with self._lock:
            self._ensure_open()
            primary = self.firmware.get("bc5") or next(iter(self.firmware.values()))
            lcd = self.lcd.state() if self.lcd_seen else None
            if lcd and self.lcd_capture_error:
                lcd["error"] = self.lcd_capture_error
            if lcd and self.display_text:
                lcd["accessibility"] = self.display_text.read(lcd)
            if lcd:
                avr = self.engines.get("avr")
                if avr and avr.state.get("halt") != "worker-failed":
                    try:
                        pins = avr.request("pin_state").get("pins", [])
                        if len(pins) >= 4:
                            lcd["backlight_on"] = bool((pins[0] & 0x18) if self.model == "9575"
                                                       else (pins[1] & 8 or pins[3] & 0x20))
                            lcd["backlight_approximate"] = True
                    except EngineError:
                        # State must still explain a disconnected worker's recovery.
                        pass
            limitations = list(LIMITATIONS)
            training = self.mode == "training"
            if training:
                limitations = [line for line in limitations if not line.startswith("Satellite service")]
                limitations.append("Offline training replaces TRX/DSP execution with a finite simulated modem; calls have no voice audio or RF service.")
            elif self.spi_link and not self.modem_link:
                limitations.append("Without a modem startup peer, saved phonebook entries may not appear after restart. Offline training lets the original firmware rebuild its index.")
            if self.model == "9575":
                if not self.gps_peer:
                    limitations.append("9575 GPS needs the optional synthetic receiver or external UART input.")
                limitations.append("9575 location-report and SOS network service transport are not implemented.")
            active = self._active_processors()
            processors = [dict(worker.state, active=worker in active) for worker in self.engines.values()]
            if any(processor.get("active") and processor.get("halt") == "worker-failed" for processor in processors):
                self.running = False
            satellite = self.satellite.state()
            satellite["firmware_connected"] = training and bool(self.spi_link and self.modem_link)
            satellite["mode"] = "offline training" if training else "offline service scenario"
            return {"handset": self.profile.describe(), "mode": self.mode,
                    "capabilities": {"calls": training, "sms": training, "voice_audio": False,
                                     "backlight": bool(lcd and "backlight_on" in lcd), "contrast": "approximate", "gps": bool(self.gps_peer),
                                     "sim": self.sim_present and (training or self.modem_image == "trx")},
                    "fixtures": {"sim": {"present": self.sim_present, "synthetic": True},
                                 "gps": self.gps_peer.state() if self.gps_peer else {"enabled": False}},
                    "firmware": primary.describe(), "images": [item.describe() for item in self.firmware.values()],
                    "processors": processors,
                    "running": self.running, "keys": sorted(self.keys),
                    "key_generations": dict(self.key_generations),
                    "key_epoch": self.key_epoch,
                    "session_id": self.session_id,
                    "satellite": satellite, "events": list(self.events),
                    "asset": self.asset, "lcd": lcd, "ui_initialized": self.ui_initialized,
                    "processor_link": self.modem_link.state() if self.modem_link else {"connected": False},
                    "spi_link": self.spi_link.state() if self.spi_link else {"connected": False},
                    "fidelity": {"complete": False, "scope": "offline-training" if training else "firmware-derived",
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
                before = worker.state["steps"]
                response = self._request(worker, "idle", steps=quantum)
                remaining -= quantum
                elapsed = response["steps"] - before
                self._service_board_elapsed(elapsed)
                if response.get("halt"):
                    break
                if response.get("at_idle"):
                    return
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
        default_budget = 100000 if operation == "call" else (worker.state.get("last_call") or {}).get("remaining_steps", 0)
        budget = arguments.get("steps", default_budget)
        request_limit = arguments.get("quantum", budget)
        if self.spi_link and type(budget) is int and budget > 0:
            quantum = arguments.get("quantum", self._board_quantum(budget))
            if type(quantum) is int and 1 <= quantum <= 100000000:
                arguments["quantum"] = min(quantum, self._board_quantum(budget))
        before = (worker.state.get("last_call") or {}).get("steps", 0) if operation == "call_resume" else 0
        # Native validation must run before any peripheral processor advances.
        response = self._request(worker, operation, **arguments)
        budget = min(budget, request_limit)
        peripheral_budget = budget
        previous = before
        while True:
            call = response.get("last_call") or {}
            elapsed = call.get("steps", previous) - previous
            previous += elapsed
            if self.spi_link:
                self._service_board_elapsed(elapsed)
                peripheral_budget -= elapsed
            if not call.get("pending"):
                return response
            remaining = budget - (previous - before)
            if remaining <= 0:
                return response
            if not self.spi_link:
                if not response.get("serial_waiting"):
                    return response
                raise EngineError("Function probe is waiting for a connected serial peer")
            if not elapsed and self.spi_link.pending and peripheral_budget > 0:
                quantum = self._board_quantum(min(remaining, peripheral_budget))
                self._service_board(quantum)
                peripheral_budget -= quantum
            if peripheral_budget <= 0:
                raise EngineError("Peripheral wait exceeded the function-probe budget; reset before retrying")
            quantum = self._board_quantum(min(remaining, peripheral_budget))
            response = self._request(worker, "call_resume", steps=quantum)

    def _provision_release_version(self, worker) -> None:
        if self.modem_image == "ptt" or any(
                self.firmware[image].payload_sha256 != digest
                for image, digest in zip(("bc5", "avr", "trx"), self.profile.release_hashes)
                if image in self.firmware):
            self.log("firmware", "Factory release metadata not provisioned for modified images or PTT")
            return
        # Replay the updater's PSK_VERSION input; original firmware owns the flash writes.
        words = [ord(char) for char in self.profile.release_manifest] + [0]
        buffer = self._call(worker, 0xFD3A, al=len(words), steps=100000)["last_call"]["al"]
        if not buffer:
            raise EngineError("Cannot allocate the firmware release metadata input")
        try:
            self._request(worker, "write", address=buffer, values=words)
            result = self._call(worker, self.profile.version_store, al=0x2B3, ah=buffer,
                                stack=[len(words) - 1], steps=1000000)
            if result["last_call"]["al"] != 1:
                raise EngineError("Original firmware did not store the release metadata")
        finally:
            if not worker.state.get("halt"):
                self._call(worker, 0x6DFE, al=buffer, steps=100000)
        self.log("firmware", f"Original firmware stored {self.profile.version} upgrade release metadata")

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
        self._button_input("power", False)
        try:
            self._request(worker, "warm_reset")
            self._idle(worker)
            if setup.get("halt") == "firmware-reset-requested":
                self._provision_release_version(worker)
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
            self._button_input("power", False)
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
