"""Factory call/end button semantics; call completion needs a service transport."""

import os
import unittest

from factory_handset import FactoryHandset


# Rows 16:113, visually checked on HT25003 and byte-identical on HL25003.
HOME = "c5b13a7f8cb40d8e802fa101ddedc73657fc70b7ddf24b3becd757bf12fabee2"
DIALED_CALLS_EMPTY = "4b58cc8dc472cccd4dcf6e5aea8cef1b365b0d2d40a78bb2059dbd61914e1362"
NUMBER_PLUS_TWELVE = "0202fd2bdaff65347166c5507d64b6947fe26117599393a717de476a01e50093"
CALL_REQUEST_IN_PROGRESS = "5bd3f2bce41ba06debc2508340553bc4bb19e6abfa084b49d3bcc84a4c562c19"


class SharedCallControlJourney:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def test_call_opens_history_and_requests_dialling_while_end_cancels_number_entry(self):
        handset = self.handset
        handset.wait_screen(HOME, max_steps=2000000)
        handset.press("green")
        handset.wait_screen(DIALED_CALLS_EMPTY, max_steps=2000000)
        handset.press("red")
        handset.wait_screen(HOME, max_steps=2000000)

        for key in "12":
            handset.press(key)
        handset.wait_screen(NUMBER_PLUS_TWELVE, max_steps=2000000)
        handset.press("red")
        handset.wait_screen(HOME, max_steps=2000000)

        for key in "12":
            handset.press(key)
        handset.wait_screen(NUMBER_PLUS_TWELVE, max_steps=2000000)
        handset.press("green")
        # This is the original pending request UI; no modem or call completion is asserted.
        state = handset.wait_screen(CALL_REQUEST_IN_PROGRESS, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.assertFalse(state["satellite"]["firmware_connected"])
        self.assertFalse(state["processor_link"]["connected"])


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 call-control E2E tests")
class CallControls9555E2ETests(SharedCallControlJourney, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 call-control E2E tests")
class CallControls9575E2ETests(SharedCallControlJourney, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
