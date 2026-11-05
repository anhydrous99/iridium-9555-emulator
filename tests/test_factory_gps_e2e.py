"""Real HTTP receiver UART0 → factory 9575 AVR/SPI/BC5 → location LCD."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from gps_receiver_frames import GPSReceiverFixture


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
GPS_PROMPT = "ccab0537fb15d496f17cc97f8104369a8d402327827e54765d9819e856dd1357"
LOCATION_UPDATING = "7f211763990f11dadfc3ec8b186a8f4c2c98308e64877bceb412b2010cf30a7e"
RECEIVER_FIX = "43f676bd42dca06be72c8e54c1ede7bfc11e3b6d26ac6e33ba4ccffe73ab0bc2"
RECEIVER_COORDINATES = "d3699df0a4f80f857d2002856f02e34672fbc051d56ba783185ee01bce6edd74"
EIGHT_SATELLITES = "beadb9b81e54dc44b99f8a17535133ce15da52f4b2560c1a3cf63e51feda4258"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory GPS E2E")
class Factory9575GPSReceiverE2ETests(unittest.TestCase):
    def test_receiver_fix_reaches_location_screen_and_survives_reopening(self):
        handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        handset.press("convenience")
        handset.wait_screen(GPS_PROMPT, max_steps=2000000)
        handset.press("soft_left")
        handset.wait_screen(LOCATION_UPDATING, max_steps=2000000)
        pins = handset.request("POST", "/api/probe", {"image": "avr", "operation": "pin_state"})
        self.assertTrue(pins["pins"][8] & 0x80, "Original GPS enable must raise PJ7")
        before = handset.state()["spi_link"]["transferred"]

        GPSReceiverFixture(handset).publish_fix()

        # Inspected LCD: 37deg46'29", -122deg25'09", +98 ft and eight
        # satellites. Fix age stays unknown without the handset clock/service.
        state = handset.wait_screen(RECEIVER_FIX, max_steps=10000000)
        handset.save_artifacts("receiver-fix", state)
        self.assertGreater(state["spi_link"]["transferred"], before)
        self.assertFalse(state["satellite"]["firmware_connected"])
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        handset.press("convenience")
        # Reopening requests an updated fix while retaining the last coordinates
        # and satellite count. Its age text therefore changes to Updating.
        handset.wait_screen(RECEIVER_COORDINATES, first=16, last=60, max_steps=2000000)
        state = handset.wait_screen(EIGHT_SATELLITES, first=96, last=109, max_steps=2000000)
        handset.save_artifacts("reopened-receiver-fix", state)
        handset.press("soft_right")
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)


if __name__ == "__main__":
    unittest.main()
