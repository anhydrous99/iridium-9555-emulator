"""Real HTTP → native factory BC5/AVR → LCD test fixture.

Local UI journeys load BC5/AVR. Modem-dependent journeys additionally request
the pinned telephony image; that does not supply RF service or GPS fixes.
"""

from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import re
import threading

from iridium.assets import Bitmap
from iridium.firmware import load_firmware
from iridium.server import Server
from iridium.session import Session


ROOT = Path(__file__).resolve().parent.parent
EXECUTABLE = ROOT / "zig-out/bin/iridium-core"
FIRMWARE_ENV = {"9555": "IRIDIUM_TEST_FIRMWARE", "9575": "IRIDIUM_TEST_9575_FIRMWARE"}
FACTORY_HASHES = {
    "9555": {
        "bc5": "38a12b9994456ebb9b2dc1b8afc8aad2dd903370bb282f01af925164bf44a98e",
        "avr": "84801ab15a81fb208fac95001004ed8bff4c3d625224b764fa58f1bce3b9df5b",
        "trx": "4f7939844993b28cae3031fa3da1b5bdb5c9546045cae1e0f6e42dd2d591e54b",
    },
    "9575": {
        "bc5": "21b9f28484bc1be0a5dc5cce78444e50b265b0b025ee40ed1d332830f7e90da1",
        "avr": "8b2e5df7b59d04f526facfeb422939ef09d5df11603da0f7ad207262fd30ddc2",
        "trx": "4f7939844993b28cae3031fa3da1b5bdb5c9546045cae1e0f6e42dd2d591e54b",
    },
}
HOME_CAPTIONS = "b27866e4b66c4276d7f13b5b830b672ddf8f348dab67e38c8df5326a58de66d9"


def factory_firmware(model, directory, *, modem=False):
    """Reject missing, mixed-model or modified images before calling them factory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Factory firmware directory does not exist: {directory}")
    processors = ("bc5", "avr", "trx") if modem else ("bc5", "avr")
    images = [load_firmware(directory, image=image, model=model)[0] for image in processors]
    for image in images:
        expected = FACTORY_HASHES[model][image.image]
        if image.payload_sha256 != expected:
            raise ValueError(f"{model} {image.image} is not the pinned factory image: "
                             f"expected {expected}, got {image.payload_sha256}")
    return images


class FactoryHandset:
    def __init__(self, testcase, model, firmware_directory, *, modem=False):
        self.test = testcase
        self.model = model
        self.epoch = 0
        self.sequence = 0
        self.last_state = None
        self.server = self.thread = self.session = None
        images = factory_firmware(model, firmware_directory, modem=modem)
        if not EXECUTABLE.is_file():
            raise ValueError("Build the native worker first: zig build -j2")
        try:
            self.session = Session(EXECUTABLE, images)
            self.session.start()
            self.server = Server(("127.0.0.1", 0), self.session, ROOT / "ui")
            self.thread = threading.Thread(target=self.server.serve_forever,
                                           kwargs={"poll_interval": 0.05}, daemon=True)
            self.thread.start()
            testcase.addCleanup(self.close)
            self.state()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.server:
            if self.thread and self.thread.is_alive():
                self.server.shutdown()
                self.thread.join(timeout=2)
            self.server.server_close()
            self.server = None
        if self.session:
            self.session.close()
            self.session = None

    def request(self, method, path, data=None, expected_status=200, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=60)
        try:
            binary = isinstance(data, bytes)
            body = data if binary else None if data is None else json.dumps(data)
            content_type = "application/octet-stream" if binary else "application/json"
            connection.request(method, path, body, {"Content-Type": content_type} | (headers or {}))
            response = connection.getresponse()
            body = response.read()
            self.test.assertEqual(response.status, expected_status,
                                  f"{method} {path}: {body.decode(errors='replace')}")
            result = json.loads(body)
            if "key_epoch" in result:
                self.epoch = result["key_epoch"]
            return result
        finally:
            connection.close()

    def state(self):
        self.last_state = self.request("GET", "/api/state")
        return self.last_state

    def control(self, action, steps=10000):
        return self.request("POST", "/api/control", {"action": action, "steps": steps})

    def step(self, steps=200000):
        self.control("step", steps)
        state = self.state()
        self.assert_healthy(state, require_lcd=False)
        return state

    def key(self, key, pressed, client_id="e2e", epoch=None, sequence=None):
        if sequence is None:
            self.sequence += 1
            sequence = self.sequence
        return self.request("POST", "/api/key", {
            "key": key, "pressed": pressed, "client_id": client_id,
            "sequence": sequence, "epoch": self.epoch if epoch is None else epoch,
        })

    def press(self, key, settle_steps=2000000):
        self.test.assertTrue(self.key(key, True)["delivered"], f"{key} press was not delivered")
        self.test.assertTrue(self.key(key, False)["delivered"], f"{key} release was not delivered")
        if settle_steps:
            return self.step(settle_steps)
        return self.state()

    def boot(self):
        self.control("initialize_ui")
        self.control("pause")
        return self.wait_screen(HOME_CAPTIONS, first=113, last=128)

    def assert_healthy(self, state=None, require_lcd=True):
        state = self.state() if state is None else state
        for processor in state["processors"]:
            self.test.assertIsNone(processor["halt"],
                                   f"{processor['image']} halted: {processor['halt']}")
            self.test.assertIsNone(processor.get("milestones", {}).get("panic"))
        lcd = state["lcd"]
        if require_lcd:
            self.test.assertIsNotNone(lcd, "Firmware has not produced LCD traffic")
            self.test.assertEqual(lcd["known_pixels"], 128 * 128)
            self.test.assertTrue(lcd["display_on"])
        if lcd:
            self.test.assertIsNone(lcd["error"])
        return state

    def screen_hash(self, first=16, last=113, state=None):
        state = self.state() if state is None else state
        lcd = state["lcd"]
        return sha256(bytes(lcd["pixels"][first * 128:last * 128])).hexdigest() if lcd else None

    def wait_screen(self, expected, first=16, last=113, max_steps=120000000, chunk_steps=200000):
        if not 0 <= max_steps or not 1 <= chunk_steps <= 10000000:
            raise ValueError("Screen waits need a nonnegative budget and chunks of 1 to 10000000 instructions")
        state = self.state()
        elapsed = 0
        while True:
            self.assert_healthy(state, require_lcd=False)
            lcd = state["lcd"]
            actual = self.screen_hash(first, last, state)
            if (lcd and lcd["known_pixels"] == 128 * 128 and lcd["display_on"] and actual == expected):
                return state
            if elapsed >= max_steps:
                artifacts = self.save_artifacts(f"screen-{first}-{last}-{expected[:8]}-timeout", state)
                self.test.fail(f"LCD rows {first}:{last} did not reach {expected} in {max_steps} "
                               f"instructions; got {actual}. Artifacts: {artifacts}")
            budget = min(chunk_steps, max_steps - elapsed)
            state = self.step(budget)
            elapsed += budget

    def save_artifacts(self, label, state=None):
        directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", ROOT / "test-artifacts/factory-e2e"))
        directory.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{self.test.id()}-{label}")
        target = directory / name
        state = self.state() if state is None else state
        Path(str(target) + ".json").write_text(json.dumps(state, indent=2) + "\n")
        if state["lcd"]:
            Path(str(target) + ".png").write_bytes(Bitmap(128, 128, bytes(state["lcd"]["pixels"]), 1).to_png())
        return target
