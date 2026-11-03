"""Opt-in original-firmware regressions; no proprietary fixtures are stored here.

Run IRIDIUM_TEST_FIRMWARE=/path/to/firmware ./test. Build the worker first.
"""

from hashlib import sha256
import os
from pathlib import Path
import tempfile
import unittest

from iridium.engine import Engine, EngineError
from iridium.firmware import load_firmware, parse_firmware
from iridium.session import Session


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_FIRMWARE")
EXECUTABLE = Path(__file__).resolve().parent.parent / "zig-out/bin/iridium-core"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_FIRMWARE for original-binary execution tests")
class OriginalFirmwareTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def worker(self, image, patch=None):
        firmware = load_firmware(Path(FIRMWARE_DIRECTORY), image)[0]
        data = bytearray(firmware.data)
        if patch:
            offset, replacement = patch
            data[offset:offset + len(replacement)] = replacement
        path = Path(self.directory.name) / f"{image}.bin"
        path.write_bytes(data)
        engine = Engine(EXECUTABLE, image, path)
        self.addCleanup(engine.close)
        return engine

    def test_original_bc5_boot_and_real_function_memory_effects(self):
        engine = self.worker("bc5")
        state = engine.request("run", steps=7000000)
        self.assertIsNone(state["halt"])
        self.assertTrue(state["milestones"]["scheduler"])
        self.assertTrue(state["milestones"]["idle"])
        self.assertIsNone(state["milestones"]["panic"])
        self.assertEqual(engine.request("read", address=0xF960, count=1)["values"], [0xAAAA])
        # Execute original memset, then observe its RAM writes through the debugger.
        state = engine.request("call", entry=0x1DC, al=0xA100, ah=0xBEEF, stack=[3], steps=10000)
        self.assertTrue(state["last_call"]["returned"])
        self.assertEqual(engine.request("read", address=0xA100, count=3)["values"], [0xBEEF] * 3)
        # Original event dispatcher is not connected to a handset UI at kernel idle.
        self.assertEqual(engine.request("read", address=0xF6FB, count=2)["values"], [0, 0])

    def test_patched_reset_instruction_changes_executed_behavior(self):
        engine = self.worker("bc5", (0, b"\x04\x00"))  # XAP BRK replaces reset branch.
        state = engine.request("run", steps=10)
        self.assertIsNotNone(state["halt"])
        self.assertIn("brk", state["halt"])
        self.assertFalse(state["milestones"]["main"])
        self.assertLess(state["steps"], 10)
        self.assertEqual(engine.request("reset")["steps"], 0)
        self.assertIn("brk", engine.request("run", steps=10)["halt"])

    def test_avr_startup_and_two_modem_scheduler_entries(self):
        for image, budget in (("avr", 100000), ("trx", 7000000), ("ptt", 7000000)):
            with self.subTest(image=image):
                engine = self.worker(image)
                state = engine.request("run", steps=budget)
                self.assertIsNone(state["halt"])
                self.assertTrue(state["milestones"]["main"])
                self.assertTrue(state["milestones"]["idle" if image == "avr" else "scheduler"])

    def test_bad_protocol_requests_do_not_mutate_memory_or_kill_worker(self):
        engine = self.worker("avr")
        before = engine.request("read", address=0x100, count=2)["values"]
        with self.assertRaises(EngineError):
            engine.request("write", address=0x100, values=[42, 256])
        self.assertEqual(engine.request("read", address=0x100, count=2)["values"], before)
        with self.assertRaises(EngineError):
            engine.request("run", steps=10000001)
        self.assertEqual(engine.request("state")["steps"], 0)

    def test_experimental_original_ui_initialization_and_software_key_delivery(self):
        firmware = load_firmware(Path(FIRMWARE_DIRECTORY), "bc5")
        with Session(EXECUTABLE, firmware) as session:
            session.control("initialize_ui")
            self.assertTrue(session.ui_initialized)
            epoch = session.state()["key_epoch"]
            response = session.key("soft_left", True, client_id="browser-a", sequence=1, epoch=epoch)
            self.assertTrue(response["delivered"])
            self.assertEqual(session.engines["bc5"].request("read", address=0xF743, count=1)["values"], [0x96])
            self.assertFalse(session.key("soft_left", True, client_id="browser-b", sequence=1, epoch=epoch)["delivered"])
            bc5 = session.engines["bc5"]
            session.load(load_firmware(Path(FIRMWARE_DIRECTORY), "avr")[0])
            self.assertIs(session.engines["bc5"], bc5)
            self.assertEqual(session.state()["key_epoch"], epoch)
            self.assertFalse(session.key("soft_left", False, client_id="browser-a", sequence=2, epoch=epoch)["delivered"])
            self.assertEqual(session.keys, {"soft_left"})
            self.assertTrue(session.key("soft_left", False, client_id="browser-b", sequence=2, epoch=epoch)["delivered"])
            self.assertEqual(session.keys, set())
            for _ in range(40):
                session.control("step", 50000)
            state = session.state()
            self.assertIsNone(state["processors"][0]["halt"])
            self.assertIsNotNone(state["lcd"])
            self.assertIsNone(state["lcd"]["error"])
            self.assertEqual(state["lcd"]["known_pixels"], 128 * 128)
            self.assertFalse(state["satellite"]["firmware_connected"])
            # A firmware patch/debugger write can remove the callback. Do not
            # keep claiming delivery merely because initialization once passed.
            session.probe("bc5", "write", {"address": 0xF6FB, "values": [0, 0]})
            with self.assertRaisesRegex(EngineError, "handler is absent"):
                session.key("1", True)
            self.assertFalse(session.ui_initialized)
            session.control("reset")
            self.assertFalse(session.ui_initialized)
            self.assertIsNone(session.state()["lcd"])

    def test_original_animation_reaches_readable_home_and_navigable_menu(self):
        firmware = load_firmware(Path(FIRMWARE_DIRECTORY), "bc5")
        with Session(EXECUTABLE, firmware) as session:
            session.control("initialize_ui")
            for _ in range(600):
                session.control("step", 200000)

            def assert_rows(first, last, expected):
                state = session.state()
                self.assertIsNone(state["processors"][0]["halt"])
                lcd = state["lcd"]
                self.assertIsNone(lcd["error"])
                self.assertEqual(lcd["known_pixels"], 16384)
                self.assertTrue(lcd["segment_zero_on_right"])
                pixels = bytes(lcd["pixels"][first * 128:last * 128])
                self.assertEqual(sha256(pixels).hexdigest(), expected)

            def press(key):
                self.assertTrue(session.key(key, True)["delivered"])
                self.assertTrue(session.key(key, False)["delivered"])
                for _ in range(10):
                    session.control("step", 200000)

            # Known-answer pixel crops of visually verified original HT25003 text.
            # Exclude changing status icons; a mirrored logo or blank redraw cannot pass.
            # Home screen: readable Menu / Help captions after the animation, without keys.
            assert_rows(113, 128, "b27866e4b66c4276d7f13b5b830b672ddf8f348dab67e38c8df5326a58de66d9")
            press("soft_left")
            # My Phonebook, SIM Phonebook, Messages, Voicemail, Data Modem; first selected.
            assert_rows(16, 97, "dd3d228fb0b974e47af552285e8fcd9175ba89a18e3cb9000ee6bd7795c59272")
            press("down")
            # Selection moves to SIM Phonebook.
            selected = "ebed4ef1aded6a4e64bfa87f533696bd6f578245ab8df647e222d29acd905c73"
            assert_rows(16, 97, selected)
            press("soft_left")
            # The original application reports the absent SIM instead of inventing contacts.
            assert_rows(16, 97, "f703d9eb19336f3cde3349497347b12671928045165e37e8fd3243222450685f")
            press("soft_right")
            assert_rows(16, 97, selected)
            press("soft_right")
            assert_rows(113, 128, "b27866e4b66c4276d7f13b5b830b672ddf8f348dab67e38c8df5326a58de66d9")

    def test_patched_application_initializer_fault_is_not_hidden(self):
        data = bytearray(load_firmware(Path(FIRMWARE_DIRECTORY), "bc5")[0].data)
        data[0x8CC8C:0x8CC8E] = b"\x04\x00"  # BRK in application setup.
        firmware = parse_firmware(bytes(data), "patched-bc5.bin", "bc5")
        with Session(EXECUTABLE, [firmware]) as session:
            with self.assertRaisesRegex(EngineError, "brk"):
                session.control("initialize_ui")
            self.assertFalse(session.ui_initialized)
            self.assertFalse(session.running)
            with self.assertRaisesRegex(EngineError, "reset before retrying"):
                session.control("initialize_ui")


if __name__ == "__main__":
    unittest.main()
