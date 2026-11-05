"""Original TRX reset loads and starts DSP images; DSP execution is unimplemented.

These peripheral contracts do not claim a working DSP or handset service.
"""

import os
from pathlib import Path
import tempfile
import unittest

from factory_handset import EXECUTABLE, factory_firmware
from iridium.engine import Engine


# Original TRX RAM-shadow sources, host destinations, 32-bit word counts.
DSP_IMAGES = (
    (0x70064F6C, 0xD0000000, 0x569),
    (0x70066514, 0xC0000000, 0x1000),
    (0x7006AEAC, 0xB0000000, 0x1D39),
    (0x70072394, 0xA0000000, 0x4000),
)
HPI_WRITES = (
    (0xC2C, 1), (0xD2C, 1),
    (0xD24, 0), (0xC24, 0), (0xD04, 1), (0xC04, 1),
    (0xD2C, 1), (0xC2C, 1), (0xD00, 0), (0xC00, 0),
    (0xD2C, 0), (0xC2C, 0), (0xD20, 0), (0xD14, 1),
    (0xD14, 0), (0xC20, 0), (0xC14, 1), (0xC14, 0),
    (0xD04, 0), (0xC04, 0), (0xD24, 1), (0xC24, 1),
    (0xD00, 1), (0xC00, 1),
)


class SharedDSPStartupChecks:
    def test_original_reset_copies_all_four_dsp_blobs_and_issues_entry_start_strobes(self):
        firmware = next(f for f in factory_firmware(self.model, self.firmware_directory, modem=True)
                        if f.image == "trx")
        temporary = tempfile.TemporaryDirectory(prefix="iridium-dsp-contract-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "trx.bin"
        path.write_bytes(firmware.data)
        engine = Engine(EXECUTABLE, "trx", path, model=self.model)
        self.addCleanup(engine.close)
        engine.request("trace", enabled=True)
        windows, controls = {}, []
        for _ in range(1250):
            state = engine.request("run", steps=4096)
            self.assertIsNone(state["halt"])
            trace = engine.request("trace")
            self.assertEqual(trace["dropped"], 0)
            for event in trace["accesses"]:
                address = event["addr"]
                if event["write"]:
                    if 0x80000C00 <= address < 0x80000E00:
                        controls.append((address - 0x80000000, event["value"]))
                    if event["bits"] == 32 and 0xA0000000 <= address < 0xE0000000:
                        windows[address] = event["value"]
            if (0xD00, 1) in controls and (0xC00, 1) in controls:
                break
        else:
            self.fail("Original reset did not start both DSPs within 5.12 million instructions")

        self.assertEqual(controls, list(HPI_WRITES))
        for source, destination, words in DSP_IMAGES:
            with self.subTest(destination=hex(destination)):
                offset = 0x1D921C + source - 0x70000078
                self.assertEqual(int.from_bytes(firmware.data[offset - 4:offset], "big"), source)
                expected = firmware.data[offset:offset + words * 4]
                addresses = range(destination, destination + words * 4, 4)
                self.assertTrue(all(address in windows for address in addresses), "Missing original DSP writes")
                actual = b"".join(windows[address].to_bytes(4, "big") for address in addresses)
                self.assertEqual(actual, expected)
        self.assertIsNone(engine.state["last_call"], "Boot must execute naturally from reset")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 DSP startup contracts")
class Factory9555DSPStartupContractTests(SharedDSPStartupChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 DSP startup contracts")
class Factory9575DSPStartupContractTests(SharedDSPStartupChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
