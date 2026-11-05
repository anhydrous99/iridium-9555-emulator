"""Factory convenience assignments and local outcomes, without service completion."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_call_settings_e2e import CALL_REQUEST_PENDING, EMPTY_HISTORY, HISTORY_TITLES
from test_factory_customization_e2e import (CONVENIENCE_DEFAULT, DIAL_PLUS_TWELVE,
                                          HOME, KEY_SETUP_CONVENIENCE, SIM_NOT_READY)
from test_factory_voicemail_e2e import DEFAULT_NUMBER


# Rows 16:113 of original HTTP/native LCD captures retained under
# /tmp/iridium-convenience-expansion/explore; each model is checked independently.
START_CALL = "468953a1313b9b63e3942212560ed017ef6cbcdf9adc6486c9af2b019bba4878"
START_CANCEL_DRAFT = "713e27900239985c4c72957888e5741802d5e79b4cd5982044f91f4571a248b7"
END_CALL = "da80b8e1ab85c33433896cddc1a236bebfd55c882ad45ce0834a30459ad7249c"
END_CANCEL_DRAFT = "5ed9914f2dd69c0e23a95c95a401f57b276185a68fedb0b32dffc82e844967af"
REDIAL = "e873c540fed70cb4c77c029e869fd44d904409a09fa67cd106db1864962e3d6a"
REDIAL_CANCEL_DRAFT = "3cf646c187e39293120146b3fe9562bfbbeda8e693ead40221b89827b6d0486b"
SIM_PHONEBOOK = "7b120311a171a341dc69c1fc2fb67bdd878c2b8f65ffd8d016aacb35eb49edb0"
SIM_CANCEL_DRAFT = "1b42346d32004c41ad325ed6c34aa5cb8a6dd868682365aec5e8117ac2634caa"
MESSAGES = {
    "9555": "d2b57b7746d45aa863fbd1a0e4ec380ce15f7e680a69815b1ebd636e69730f3b",
    "9575": "765fb222c7622332681c7e43ad8b1265dc37d69b87e4a4ece1a84ece60bfeebe",
}
MESSAGES_CANCEL_DRAFT = {
    "9555": "893cb7e969b7886ed4ad163b919535fc4dcb8fbef777990ead66dcaf8edd0d5b",
    "9575": "2c5ef1105bef3f8696b2b0d91edc275f9c8f033dd5a0477b3dd86c2034bb27df",
}
MAILBOX_NOT_READY = "7102bb45f54781eb0c9932a1c01787ed8002d149d9a7773c071d79e50290a7bc"
CALL_VOICEMAIL = {
    "9555": "8c9e032a89b98d3197d81f6d5635ddb7f86f133b1ca3b11d2210446d9d0dbf96",
    "9575": "c80d18ddc31dfe4966d763ed45d6a4e19d858fac96f01eec0f237892026634ee",
}
VOICEMAIL_CANCEL_DRAFT = {
    "9555": "6e506a3c2060a7dec68ccaf7127b8636d26d474b42eb82c4f0d8530f12a72eba",
    "9575": "d033ae2607909c4c7f39001199fe6d3e41f8f2f25758cb937153f5a74300b372",
}


class SharedConvenienceChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, screen, first=16, last=113):
        return self.handset.wait_screen(screen, first=first, last=last, max_steps=20000000)

    def home(self):
        self.keys("red")
        self.expect(HOME)
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])

    def assignment(self, index, saved, draft):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (7 if self.model == "9575" else 6)), "soft_left")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(CONVENIENCE_DEFAULT[self.model])
        choose = ["up"] * (8 - index) if self.model == "9575" else ["down"] * index
        self.keys(*choose, "soft_left")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(saved)
        self.keys("up")
        self.expect(draft)  # The prior action is visibly highlighted before cancelling.
        self.keys("soft_right")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(saved)
        self.keys("soft_right")
        self.home()

    def pending_request(self):
        state = self.expect(CALL_REQUEST_PENDING)
        self.assertEqual(state["keys"], [])
        self.assertFalse(state["satellite"]["firmware_connected"])
        self.assertFalse(state["processor_link"]["connected"])

    def test_start_call_assignment_save_cancel_and_request_from_number_entry(self):
        self.assignment(1, START_CALL, START_CANCEL_DRAFT)
        self.keys("convenience")
        self.expect(HOME)  # No number/call exists on the idle screen.
        self.keys("1", "2")
        self.expect(DIAL_PLUS_TWELVE)
        self.keys("convenience")
        self.pending_request()

    def test_end_call_assignment_save_cancel_and_idle_guard(self):
        self.assignment(2, END_CALL, END_CANCEL_DRAFT)
        # No active call is supplied; this checks the idle dispatch guard only.
        self.keys("convenience")
        self.expect(HOME)
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("1", "2")
        self.expect(DIAL_PLUS_TWELVE)
        self.keys("convenience")
        self.expect(DIAL_PLUS_TWELVE)
        self.home()

    def test_call_voicemail_assignment_save_cancel_and_request_with_factory_number(self):
        self.keys("soft_left", "down", "down", "down", "soft_left",
                  "down", "soft_left", "soft_left")
        self.expect(DEFAULT_NUMBER)  # Original configured +881662990000.
        self.keys("red", "soft_right", "soft_right", "soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.assignment(7, CALL_VOICEMAIL[self.model], VOICEMAIL_CANCEL_DRAFT[self.model])
        self.keys("convenience")
        self.pending_request()

    def test_redial_assignment_save_cancel_and_request_with_empty_history(self):
        self.keys("green")
        self.expect(HISTORY_TITLES[2][1], 0, 14)
        self.expect(EMPTY_HISTORY)
        self.home()
        self.assignment(3, REDIAL, REDIAL_CANCEL_DRAFT)
        self.keys("convenience")
        # Factory behavior with no records reaches a request; no prior call is invented.
        self.pending_request()

    def test_sim_phonebook_assignment_save_cancel_and_unavailable_storage_error(self):
        self.assignment(4, SIM_PHONEBOOK, SIM_CANCEL_DRAFT)
        self.keys("convenience")
        self.expect(SIM_NOT_READY)
        self.home()

    def test_messages_assignment_save_cancel_and_unavailable_mailbox_error(self):
        self.assignment(6, MESSAGES[self.model], MESSAGES_CANCEL_DRAFT[self.model])
        self.keys("convenience")
        self.expect(MAILBOX_NOT_READY)
        self.home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 convenience E2E")
class Factory9555ConvenienceE2ETests(SharedConvenienceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 convenience E2E")
class Factory9575ConvenienceE2ETests(SharedConvenienceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
