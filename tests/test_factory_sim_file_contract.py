"""Original TRX consumes an external synthetic card file through real T=0 bytes."""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from factory_handset import EXECUTABLE, factory_firmware
from iridium.engine import Engine
from sim_language_card import LanguageSIM


class SharedSIMFileChecks:
    def run_card(self, languages, *, memory_failure=False):
        firmware = next(image for image in factory_firmware(
            self.model, self.firmware_directory, modem=True) if image.image == "trx")
        card = LanguageSIM(languages, memory_failure=memory_failure)
        evidence = {"firmware": firmware.describe(), "card_version": card.version,
                    "synthetic_languages": list(languages), "memory_failure": memory_failure,
                    "executable_sha256": sha256(EXECUTABLE.read_bytes()).hexdigest(),
                    "scope": "Original reset/UART3/SEEM cache; no guest writes, forced calls, subscriber identity or storage/service claim",
                    "wire": [], "cache": []}
        with tempfile.TemporaryDirectory(prefix="iridium-sim-file-") as temporary:
            path = Path(temporary) / "trx.bin"
            path.write_bytes(firmware.data)
            with Engine(EXECUTABLE, "trx", path, model=self.model) as engine:
                def read(address, count):
                    return engine.request("read", address=address, count=count)["values"]

                def step(steps=100000):
                    state = engine.request("run", steps=steps)
                    self.assertIsNone(state["halt"])
                    self.assertIsNone(state["last_call"], "Execute naturally from original reset")
                    pins = engine.request("uart_pins", port=3)
                    card.controls(pins["inputs"], pins["outputs"])
                    for port in range(3):
                        engine.request("uart_io", port=port)
                    offered = bytes(card.pending) if card.ready else b""
                    wire = engine.request("uart_io", port=3, rx=list(offered))
                    self.assertEqual(wire["dropped"], 0)
                    card.accepted(wire["accepted"])
                    if offered or wire["values"]:
                        evidence["wire"].append({"steps": state["steps"], "offered": list(offered),
                                                 "accepted": wire["accepted"], "tx": wire["values"]})
                    card.feed(wire["values"])
                    return state

                try:
                    while engine.state["steps"] < 60000000:
                        step(min(1024 if engine.state["steps"] < 8000000 else 100000,
                                 60000000 - engine.state["steps"]))
                    self.assertFalse(card.events)
                    pointer = int.from_bytes(bytes(read(0x70002270, 4)), "big")
                    self.assertTrue(0x40000000 <= pointer < 0x400C3E10)
                    initial = read(pointer, 6)
                    self.assertEqual(initial, [0, 5, 0, 0, 255, 255])
                    before = engine.state["steps"]
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    self.assertEqual(engine.request("state")["steps"], before)
                    expected = ([0, 4, 1, 0, 255, 255] if memory_failure
                                else [0, 0, 1, 2, *languages])
                    for _ in range(300):
                        state = step()
                        actual = read(pointer, 6)
                        if actual != initial:
                            evidence["cache"].append({"steps": state["steps"], "pointer": pointer,
                                                      "bytes": actual})
                        if actual == expected:
                            break
                    else:
                        self.fail(f"Original F100 cache never published {expected}; got {actual}")
                    # These independently located original buffers precede the cache copy.
                    self.assertEqual(read(0x400B400E, 2), [0, 0 if memory_failure else 2])
                    if not memory_failure:
                        self.assertEqual(read(0x400B4010, 2), list(languages))
                    self.assertIn({"kind": "header", "bytes": [0xA0, 0xB0, 0, 0, 2],
                                   "selected": 0x6F05}, card.events)
                    response = ([0x92, 0x40] if memory_failure else [0xB0, *languages, 0x90, 0])
                    self.assertEqual(read(0x400B4D90, len(response)), response)
                    self.assertIn({"kind": "read-memory-failure" if memory_failure else "read-language-data",
                                   "bytes": response}, card.events)
                finally:
                    evidence.update({"events": card.events, "final_state": engine.request("state"),
                                     "rx_buffer": read(0x400B4D90, 24),
                                     "read_state": read(0x400B4F20, 16)})
                    directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
                    directory.mkdir(parents=True, exist_ok=True)
                    suffix = "memory-failure" if memory_failure else languages.hex()
                    (directory / (self.id() + "-" + suffix + ".json")).write_text(
                        json.dumps(evidence, indent=2) + "\n")

    def test_original_metadata_and_read_publish_two_distinct_synthetic_file_values(self):
        for languages in (b"\x01\x04", b"\x04\x01"):
            with self.subTest(languages=languages.hex()):
                self.run_card(languages)

    def test_original_card_memory_error_publishes_failure_without_file_data(self):
        self.run_card(b"\x01\x04", memory_failure=True)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 SIM file contracts")
class Factory9555SIMFileContractTests(SharedSIMFileChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 SIM file contracts")
class Factory9575SIMFileContractTests(SharedSIMFileChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
