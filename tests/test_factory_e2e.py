"""Shared handset journeys through HTTP and original factory instructions."""

import os
from hashlib import sha256
import time
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


# LCD rows 16:97, visually checked on the factory 9555. Both releases share
# these menu resources; the tests independently verify their actual output.
MAIN_MENU = [
    ("My Phonebook", "dd3d228fb0b974e47af552285e8fcd9175ba89a18e3cb9000ee6bd7795c59272"),
    ("SIM Phonebook", "ebed4ef1aded6a4e64bfa87f533696bd6f578245ab8df647e222d29acd905c73"),
    ("Messages", "84ff53ebce4c2486634a63bb68864ff8f3b5ba02898538834744e08226ac70d2"),
    ("Voicemail", "82201b0901558a0a2862fc0f4b18ac4537d1d76376ec9152058c5b686b34073c"),
    ("Data Modem", "86dc69bf39ec42ff1b71980e4c630268a7693e349efb44f810eae77d756130dd"),
    ("Call History", "239b49359ccbd59030d112bae0815a90694393931a21e6912c95f4a311367bdf"),
    ("Setup", "8faa17b3de118cb848a7c644dbe2344d706210b7a65fd1293803be9dfcd54d14"),
    ("Security", "4a7948708175ba12a41758e1ef55641697952c2929348f74059311b9ce675523"),
    ("Help", "5e229f0f01b010b49ddf6ec90d480f68d0f63916bf56619606c53a7004e09e6c"),
]
HELP = "953a8e69dc39c0f36ab2c279065772d3ff13c1c7205b075cf62efeb43b2d337d"
EXTREME_SETUP = "890e354045721f1f847576665d56bcf9290fbb524519885da4c18680a8023055"
MISSING_SIM = "f703d9eb19336f3cde3349497347b12671928045165e37e8fd3243222450685f"
MENU_CONTENT = [
    "5c8ac71e85b20e86e1c8a970e3826381c9028b4e86fda20c7a8978260ecbba68",  # Empty phonebook.
    "afbdc304429f6fa77bf0ec9bdce17bc27df50cec9f82d227e3e858e85ba42c22",  # Missing SIM.
    "7102bb45f54781eb0c9932a1c01787ed8002d149d9a7773c071d79e50290a7bc",  # SMS configuration error.
    "a66304e31e6588bb688adaea3c69d1a699c9a41dc313c67a643fb69bb08b5e5b",  # Voicemail menu.
    "6940f847616532cfc9d116f5be9f96b4bd8b26b12ecfe7ed045bba1fbf637ad2",  # Connect USB cable.
    "86fa1a5b80657d9bdf52d006a2aa8851992ff5a544cfb29227ba31fbef9316ce",  # Call History menu.
    "d47dc08f6320579a7b6dfe5850b294653ad4e6d37d55c484b6a29dbd763197b0",  # Setup menu.
    "aff33e5301f81c65719736fff7d485cb6c9b023e3af3dcdd76ac0a042ebe4038",  # Security menu.
    HELP,
]


class SharedFactoryJourneys:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        # Retain the final framebuffer and full state even when an assertion fails.
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def test_every_main_menu_selection_help_and_missing_sim(self):
        handset = self.handset
        self.assertEqual(handset.state()["handset"]["model"], self.model)
        handset.press("soft_left")
        for index, (label, expected) in enumerate(MAIN_MENU):
            if index:
                handset.press("down")
            handset.wait_screen(expected, last=97, max_steps=2000000)
            handset.press("soft_left")
            content = EXTREME_SETUP if self.model == "9575" and label == "Setup" else MENU_CONTENT[index]
            handset.wait_screen(content, max_steps=2000000)
            handset.press("soft_right")
            handset.wait_screen(expected, last=97, max_steps=2000000)
        # The real list stops at Help rather than wrapping to its first row.
        handset.press("down")
        handset.wait_screen(MAIN_MENU[-1][1], last=97, max_steps=2000000)
        handset.press("soft_left")
        handset.wait_screen(HELP, max_steps=2000000)
        handset.press("soft_right")
        for _ in range(7):
            handset.press("up")
        handset.press("soft_left")
        handset.wait_screen(MISSING_SIM, last=97, max_steps=2000000)
        handset.press("soft_right")
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        # Home's Help shortcut opens the same original menu as Menu → Help.
        handset.press("soft_right")
        handset.wait_screen(HELP, max_steps=2000000)
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

    def test_all_dialing_characters_clear_and_cancel(self):
        handset = self.handset

        def assert_number():
            state = handset.assert_healthy()
            pixels = bytes(state["lcd"]["pixels"])
            # Two lines show 01234567 / 89*#. Omit the blinking caret at x=66.
            glyphs = pixels[56 * 128:80 * 128] + b"".join(
                pixels[row * 128:row * 128 + 64] for row in range(80, 111))
            self.assertEqual(sha256(glyphs).hexdigest(),
                             "86497cccc327d842d6e3607c325e3a61365a0366319b1bd380d64611be74388e",
                             "Dialer must visibly contain 0123456789*#")

        for key in "0123456789*#":
            handset.press(key)
        assert_number()
        handset.press("soft_right")
        handset.press("#")
        assert_number()
        handset.press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

    def test_power_shutdown_and_reboot(self):
        handset = self.handset
        state = handset.press("power", settle_steps=0)
        self.assertFalse(state["ui_initialized"])
        primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
        self.assertIn(primary["power_state"], (2, 8), "Original firmware must enter shutdown")
        for _ in range(50):
            primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
            if primary["power_state"] == 8:
                break
            state = handset.step(200000)
        else:
            self.fail("Original firmware did not complete shutdown within 10 million instructions")
        self.assertEqual(state["keys"], [])
        handset.boot()
        handset.press("soft_left")
        handset.wait_screen(MAIN_MENU[0][1], last=97, max_steps=2000000)

    def test_http_pause_step_shared_keys_reset_and_fresh_boot(self):
        handset = self.handset
        state = handset.state()
        before = {cpu["image"]: cpu["steps"] for cpu in state["processors"]}
        home = handset.screen_hash(state=state)
        for action in ({"action": "register"}, {"action": "advance", "milliseconds": 1000},
                       {"action": "incoming_call", "number": "+123"}, {"action": "answer"},
                       {"action": "hangup"}, {"action": "incoming_sms", "number": "+123", "text": "Test"}):
            self.assertFalse(handset.request("POST", "/api/satellite", action)["delivered"])
        state = handset.state()
        self.assertTrue(state["satellite"]["registered"])
        self.assertEqual(len(state["satellite"]["messages"]), 1)
        self.assertFalse(state["satellite"]["firmware_connected"])
        self.assertEqual(handset.screen_hash(state=state), home)
        self.assertEqual({cpu["image"]: cpu["steps"] for cpu in state["processors"]}, before)
        handset.control("run")
        deadline = time.monotonic() + 10
        while not all(cpu["steps"] > before[cpu["image"]] for cpu in state["processors"]):
            self.assertLess(time.monotonic(), deadline, "Running firmware did not advance")
            state = handset.state()
        handset.control("pause")
        state = handset.state()
        self.assertFalse(state["running"])
        before = {cpu["image"]: cpu["steps"] for cpu in state["processors"]}
        for _ in range(3):
            self.assertEqual({cpu["image"]: cpu["steps"] for cpu in handset.state()["processors"]}, before)
        state = handset.step(200000)
        self.assertFalse(state["running"])
        self.assertTrue(all(cpu["steps"] > before[cpu["image"]] for cpu in state["processors"]))
        self.assertTrue(handset.key("soft_left", True, client_id="tab-a")["delivered"])
        self.assertFalse(handset.key("soft_left", True, client_id="tab-b")["delivered"])
        self.assertFalse(handset.key("soft_left", False, client_id="tab-a")["delivered"])
        self.assertEqual(handset.state()["keys"], ["soft_left"])
        self.assertTrue(handset.key("soft_left", False, client_id="tab-b")["delivered"])
        handset.step(2000000)
        handset.wait_screen(MAIN_MENU[0][1], last=97, max_steps=2000000)
        self.assertEqual(handset.state()["keys"], [])

        self.assertTrue(handset.key("1", True)["delivered"])
        epoch = handset.epoch
        handset.control("reset")
        state = handset.state()
        self.assertGreater(state["key_epoch"], epoch)
        self.assertEqual(state["keys"], [])
        self.assertIsNone(state["lcd"])
        self.assertFalse(state["ui_initialized"])
        self.assertFalse(handset.key("1", True, epoch=epoch)["delivered"])
        self.assertEqual(handset.state()["keys"], [])
        handset.boot()
        handset.press("soft_left")
        handset.wait_screen(MAIN_MENU[0][1], last=97, max_steps=2000000)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 E2E tests")
class Factory9555E2ETests(SharedFactoryJourneys, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 E2E tests")
class Factory9575E2ETests(SharedFactoryJourneys, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
