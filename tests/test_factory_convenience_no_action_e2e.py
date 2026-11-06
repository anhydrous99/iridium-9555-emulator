"""Extreme No Action assignment and restoration through original HTTP widgets."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_customization_e2e import (
    CONVENIENCE_DEFAULT, DIAL_PLUS_TWELVE, GPS_PROMPT, HOME, KEY_SETUP_CONVENIENCE,
)


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
# Independently inspected 9575 pixels match the existing 9555 No Action oracle.
NO_ACTION = CONVENIENCE_DEFAULT["9555"]
LOCATION_CANCEL_DRAFT = "9b6a829e813b4eb2239ccf4e7a82868d671208ec5b48bcaaee38f392e2cf1581"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory No Action E2E")
class Factory9575ConvenienceNoActionE2ETests(unittest.TestCase):
    def test_no_action_preserves_idle_and_number_entry_then_restores_location_prompt(self):
        handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        def keys(*sequence):
            for key in sequence:
                handset.press(key)

        def expect(screen):
            return handset.wait_screen(screen, max_steps=20000000)

        def open_assignment():
            keys("soft_left", *(["down"] * 6), "soft_left",
                 *(["down"] * 7), "soft_left")
            expect(KEY_SETUP_CONVENIENCE)
            keys("soft_left")

        def home():
            keys("red")
            expect(HOME)
            state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                         max_steps=2000000)
            self.assertEqual(state["keys"], [])

        open_assignment()
        expect(CONVENIENCE_DEFAULT["9575"])
        keys(*(["up"] * 8), "soft_left")
        expect(KEY_SETUP_CONVENIENCE)
        keys("soft_left")
        expect(NO_ACTION)
        handset.save_artifacts("no-action-saved")
        keys(*(["down"] * 8))
        expect(LOCATION_CANCEL_DRAFT)
        handset.save_artifacts("location-draft-before-cancel")
        keys("soft_right")
        expect(KEY_SETUP_CONVENIENCE)
        keys("soft_left")
        expect(NO_ACTION)
        keys("soft_right")
        home()

        # FactoryHandset.press asserts delivery of both physical key edges.
        handset.press("convenience")
        expect(HOME)
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                     max_steps=2000000)
        self.assertEqual(state["keys"], [])
        handset.save_artifacts("no-action-preserves-idle-home", state)
        keys("1", "2")
        expect(DIAL_PLUS_TWELVE)
        handset.press("convenience")
        state = expect(DIAL_PLUS_TWELVE)
        self.assertEqual(state["keys"], [])
        handset.save_artifacts("no-action-preserves-entered-number", state)
        home()

        open_assignment()
        expect(NO_ACTION)
        keys(*(["down"] * 8), "soft_left")
        expect(KEY_SETUP_CONVENIENCE)
        keys("soft_left")
        expect(CONVENIENCE_DEFAULT["9575"])
        handset.save_artifacts("location-assignment-restored")
        keys("soft_right")
        home()
        handset.press("convenience")
        expect(GPS_PROMPT)
        handset.save_artifacts("restored-location-opens-gps-enable-prompt")
        keys("soft_right")
        expect(HOME)
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                     max_steps=2000000)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)


if __name__ == "__main__":
    unittest.main()
