"""Browser-request semantics against original firmware; no extra time per key."""

import os
import unittest

from factory_handset import FactoryHandset
from test_factory_gps_e2e import GPS_PROMPT, LOCATION_UPDATING, RECEIVER_COORDINATES, EIGHT_SATELLITES
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK


class BrowserKeysChecks:
    def test_paused_browser_taps_render_the_original_menu_and_phonebook(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        handset.boot()
        for _ in range(2):
            handset.key("soft_left", True)
            handset.sequence += 1
            handset.request("POST", "/api/key", {"key": "soft_left", "pressed": False,
                "client_id": "e2e", "sequence": handset.sequence, "epoch": handset.epoch, "settle": True})
        state = handset.state()
        self.assertFalse(state["running"])
        self.assertEqual(handset.screen_hash(state=state), EMPTY_PHONEBOOK)
        self.assertTrue(any("Phonebook" in line["text"] for line in state["lcd"]["accessibility"]["lines"]))


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "Set IRIDIUM_TEST_FIRMWARE")
class Browser9555E2ETests(BrowserKeysChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "Set IRIDIUM_TEST_9575_FIRMWARE")
class Browser9575E2ETests(BrowserKeysChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")

    def test_browser_gps_control_supplies_original_location_screen(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "gps-controls")
        handset.boot()
        handset.press("convenience")
        handset.wait_screen(GPS_PROMPT, max_steps=2000000)
        handset.press("soft_left")
        handset.wait_screen(LOCATION_UPDATING, max_steps=2000000)
        state = handset.request("POST", "/api/fixtures", {"action": "gps", "enabled": True,
                                  "latitude": 37.7749, "longitude": -122.4194, "altitude": 30})
        self.assertTrue(state["fixtures"]["gps"]["enabled"])
        handset.wait_screen(RECEIVER_COORDINATES, first=16, last=60, max_steps=15000000)
        handset.wait_screen(EIGHT_SATELLITES, first=96, last=109, max_steps=15000000)
        handset.request("POST", "/api/fixtures", {"action": "gps", "enabled": False})
        self.assertFalse(handset.state()["fixtures"]["gps"]["enabled"])


if __name__ == "__main__":
    unittest.main()
