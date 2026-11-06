"""Original TRX reset/card-detect/T=0 contracts; no SIM filesystem or RF service."""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from factory_handset import EXECUTABLE, factory_firmware
from iridium.engine import Engine


class SharedSIMChecks:
    def setUp(self):
        firmware = next(image for image in factory_firmware(
            self.model, self.firmware_directory, modem=True) if image.image == "trx")
        temporary = tempfile.TemporaryDirectory(prefix="iridium-sim-contract-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "trx.bin"
        path.write_bytes(firmware.data)
        self.engine = Engine(EXECUTABLE, "trx", path, model=self.model)
        self.addCleanup(self.engine.close)
        self.events = []
        self.identity = {"firmware": firmware.describe(),
                         "executable_sha256": sha256(EXECUTABLE.read_bytes()).hexdigest()}
        self.addCleanup(self.save_evidence)
        for _ in range(60):
            self.advance(1000000)
        self.assertEqual(self.pins()["pins"], 0x40)
        self.assertEqual(self.read(0x400B4D24, 2), [0, 0])
        self.assertEqual(self.read(0x70003234, 4), [0, 0, 0, 0])
        self.assertEqual(self.wire(), [])

    def save_evidence(self):
        directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (self.id() + ".json")).write_text(json.dumps({
            **self.identity, "events": self.events, "final_state": self.engine.request("state"),
            "scope": "Natural original TRX boot and external UART3 card peer; no guest writes, calls, SIM files or network service",
        }, indent=2) + "\n")

    def read(self, address, count):
        return self.engine.request("read", address=address, count=count)["values"]

    def pins(self, **arguments):
        return self.engine.request("uart_pins", port=3, **arguments)

    def advance(self, steps=100000):
        state = self.engine.request("run", steps=steps)
        self.assertIsNone(state["halt"])
        self.assertIsNone(state["last_call"], "The modem must execute naturally from reset")
        return state

    def wire(self, received=()):
        response = self.engine.request("uart_io", port=3, rx=list(received))
        self.assertEqual(response["accepted"], len(received))
        self.assertEqual(response["dropped"], 0, "SIM output capture lost bytes")
        if received or response["values"]:
            self.events.append({"steps": self.engine.state["steps"], "rx": list(received),
                                "tx": response["values"]})
        return response["values"]

    def wait_reset_release(self, max_steps=10000000):
        previous = self.pins()["outputs"]
        observed = []
        for _ in range(max_steps // 100000):
            state = self.advance()
            pins = self.pins()
            sample = self.read(0x400B4D24, 2)
            stable = self.read(0x70003234, 4)
            self.events.append({"steps": state["steps"], "pins": pins,
                                "sample": sample, "stabilizing": stable})
            observed.append((pins["outputs"], sample, stable))
            self.assertEqual(self.wire(), [])
            if pins["outputs"] & 0x34 == 0x34 and previous & 0x20 == 0:
                self.assertEqual(sample, [1, 0])
                self.assertEqual(stable, [0, 0, 0, 0])
                return observed
            previous = pins["outputs"]
        self.fail(f"Original SIM reset did not release within {max_steps} instructions")

    def insert(self):
        before = self.engine.request("state")["steps"]
        self.assertEqual(self.pins(value=1, mask=1)["inputs"], 1)
        self.assertEqual(self.engine.request("state")["steps"], before)
        observed = self.wait_reset_release()
        # CKM's original stable-sample counter reaches eight before the queue event.
        self.assertTrue(any(sample == [1, 8] and stable == [0, 0, 0, 1]
                            for _, sample, stable in observed))
        self.assertTrue(any(outputs & 0x34 == 0x14 for outputs, _, _ in observed))

    def remove(self):
        self.pins(value=0, mask=1)
        for _ in range(50):
            self.advance()
            self.assertEqual(self.wire(), [])
        self.assertEqual(self.read(0x400B4D24, 2), [0, 0])
        self.assertEqual(self.read(0x70003234, 4), [0, 0, 0, 0])
        self.assertEqual(self.pins()["pins"], 0x40)

    def test_original_insertion_accepts_atr_selects_iridium_df_and_removal_aborts_exchange(self):
        self.insert()
        self.assertEqual(self.wire([0x3B, 0]), [])  # direct convention, default T=0
        command = []
        for _ in range(30):
            self.advance()
            command.extend(self.wire())
            if command:
                break
        self.assertEqual(command, [0xA0, 0xA4, 0, 0, 2])
        self.assertEqual(self.read(0x400B4D90, 2), [0x3B, 0])
        self.assertEqual(self.wire([0xA4]), [])  # actual T=0 procedure acknowledgement
        selected_file = []
        for _ in range(30):
            self.advance()
            selected_file.extend(self.wire())
            if selected_file:
                break
        self.assertEqual(selected_file, [0x7F, 0x20])
        self.remove()  # no fabricated SELECT success or file metadata

    def test_original_rejects_invalid_atr_then_retries_without_transmitting_a_command(self):
        self.insert()
        self.assertEqual(self.wire([0, 0]), [])  # neither supported initial convention byte
        cleared = False
        for _ in range(100):
            self.advance()
            self.assertEqual(self.wire(), [])
            outputs = self.pins()["outputs"]
            if outputs & 0x20 == 0:
                cleared = True
            elif cleared:
                break
        else:
            self.fail("Original modem did not reject the malformed ATR and retry reset")
        self.assertEqual(self.read(0x400B4D90, 2), [0, 0])
        self.remove()

    def test_original_warm_reset_detects_retained_card_without_another_input_edge(self):
        self.pins(value=1, mask=1)
        state = self.engine.request("warm_reset")
        self.assertEqual(state["steps"], 0)
        self.assertEqual(self.pins()["inputs"], 1)
        self.assertEqual(self.pins()["outputs"], 0)
        self.wait_reset_release(max_steps=70000000)
        self.assertEqual(self.wire([0x3B, 0]), [])
        command = []
        for _ in range(30):
            self.advance()
            command.extend(self.wire())
            if command:
                break
        self.assertEqual(command, [0xA0, 0xA4, 0, 0, 2])
        self.remove()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 SIM contracts")
class Factory9555SIMContractTests(SharedSIMChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 SIM contracts")
class Factory9575SIMContractTests(SharedSIMChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
