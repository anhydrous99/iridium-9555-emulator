"""Original Reset to Defaults menu, including cancellation and saved effects."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_settings_e2e import RINGER_DEFAULT, RINGER_LOUDER, VOLUME_MENU


RESET_CONFIRMATION = "65a5af87ecf8918b360feff3376214e63a22478b0f3968b87d006bd021608c60"
SETTINGS_RESET = "92e56c0c3ed4ed0ccaa59cdd9295aa604c02e947db7a7ef463373a90fe23f09f"


class SharedResetChecks:
    def test_reset_to_defaults_cancel_preserves_setting_and_confirm_restores_it(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        def expect(screen):
            return handset.wait_screen(screen, max_steps=20000000)

        def home():
            handset.press("red")
            handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

        def open_setup(item):
            handset.press("soft_left")
            for _ in range(6):
                handset.press("down")
            handset.press("soft_left")
            for _ in range(item + (1 if self.model == "9575" else 0)):
                handset.press("down")
            handset.press("soft_left")

        def open_ringer():
            open_setup(1)
            expect(VOLUME_MENU)
            handset.press("soft_left")

        open_ringer()
        expect(RINGER_DEFAULT)
        handset.press("up")
        handset.press("soft_left")
        expect(VOLUME_MENU)
        handset.press("soft_left")
        expect(RINGER_LOUDER)
        handset.press("soft_right")
        home()

        open_setup(9)
        expect(RESET_CONFIRMATION)
        handset.press("soft_right")  # No.
        home()
        open_ringer()
        expect(RINGER_LOUDER)
        handset.press("soft_right")
        home()

        open_setup(9)
        expect(RESET_CONFIRMATION)
        handset.press("soft_left")  # Yes.
        expect(SETTINGS_RESET)
        handset.save_artifacts("settings-reset")
        handset.press("soft_right")
        home()
        open_ringer()
        expect(RINGER_DEFAULT)
        handset.press("soft_right")
        home()
        state = handset.assert_healthy()
        self.assertEqual(state["keys"], [])


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 reset E2E")
class Factory9555ResetE2ETests(SharedResetChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 reset E2E")
class Factory9575ResetE2ETests(SharedResetChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
