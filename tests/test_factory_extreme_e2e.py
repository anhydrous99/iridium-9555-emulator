"""9575 factory location and cancellable emergency UI through the HTTP API."""

import os
import unittest

from factory_handset import FactoryHandset


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
GPS_PROMPT = "ccab0537fb15d496f17cc97f8104369a8d402327827e54765d9819e856dd1357"
LOCATION_UPDATING = "7f211763990f11dadfc3ec8b186a8f4c2c98308e64877bceb412b2010cf30a7e"
SOS_TWENTY_SECONDS = "bb6ba11a55781edb3b9b98732e303f6c226f6664e2711b611f3e7739b8dcdb83"
SOS_NINETEEN_SECONDS = "86a5e1479aaa98cdc6bce18300abb9df0b69e74b43a11ed75fc78ab202be1939"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 E2E tests")
class ExtremeFactoryE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def test_location_decline_enable_and_reopen_without_a_receiver_fix(self):
        handset = self.handset
        home = handset.screen_hash()
        handset.press("convenience")
        handset.wait_screen(GPS_PROMPT, max_steps=2000000)
        handset.press("soft_right")
        handset.wait_screen(home, max_steps=2000000)

        handset.press("convenience")
        handset.wait_screen(GPS_PROMPT, max_steps=2000000)
        handset.press("soft_left")
        # Known-answer LCD: empty coordinates and 'Age of fix: Updating'.
        handset.wait_screen(LOCATION_UPDATING, max_steps=2000000)
        handset.press("soft_right")
        handset.wait_screen(home, max_steps=2000000)
        handset.press("convenience")
        handset.wait_screen(LOCATION_UPDATING, max_steps=2000000)
        handset.press("soft_right")
        state = handset.wait_screen(home, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.assertFalse(state["satellite"]["firmware_connected"])

    def test_sos_countdown_advances_and_can_be_cancelled_repeatedly(self):
        handset = self.handset
        home = handset.screen_hash()
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                before = handset.state()["processors"][0]["last_call"]
                state = handset.press("sos")
                self.assertEqual(state["processors"][0]["last_call"], before,
                                 "SOS must reach original code through AVR input, without a software-key probe")
                self.assertEqual(state["processors"][0]["gpio"]["key_contacts"], 0)
                handset.wait_screen(SOS_TWENTY_SECONDS, max_steps=2000000)
                # The inferred BC5 clock advances one microsecond per eight instructions.
                handset.step(8000000)
                handset.wait_screen(SOS_NINETEEN_SECONDS, max_steps=2000000)
                handset.press("soft_right")
                state = handset.wait_screen(home, max_steps=2000000)
                self.assertEqual(state["keys"], [])
                self.assertFalse(state["satellite"]["firmware_connected"])


if __name__ == "__main__":
    unittest.main()
