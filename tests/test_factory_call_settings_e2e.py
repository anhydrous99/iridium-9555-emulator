"""Local call history, meters, preferences, and voicemail request through factory HTTP UI."""

from hashlib import sha256
import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


# Observed factory 9555 LCDs; both model cases independently verify these pixels.
# Body hashes cover rows 16:113; title hashes cover rows 0:14.
HOME = "c5b13a7f8cb40d8e802fa101ddedc73657fc70b7ddf24b3becd757bf12fabee2"
HISTORY_MENU = "86fa1a5b80657d9bdf52d006a2aa8851992ff5a544cfb29227ba31fbef9316ce"
CALL_LOG = "4eb43a5adb0cf103312e0eb7e4cc1034707bcc6f5e8a6e41cf42e6085af34793"
EMPTY_HISTORY = "4b58cc8dc472cccd4dcf6e5aea8cef1b365b0d2d40a78bb2059dbd61914e1362"
HISTORY_TITLES = (
    ("received", "37b89a21946300b1bd91563b40e258878973106e27dbcefa4e2e741be08dd5a6"),
    ("missed", "ee63f2bdaab2e96aad35b4628ed199f5a6b1b07938bf645258acddf2cd37de30"),
    ("dialed", "00ef3814c62ba0b8de8fa8be3752fac39c4c5e90b3f4e2582ecefc6735b6cdbb"),
)
METERS_TITLE = "16d711308f8c0ff77fe9ce412388fd4baff990bc5f149da42096873cd46b9e8a"
# Highlighted 120×16 label pixels, independent of the original menu's scroll position.
LAST_SELECTED = "2e03bfa778310feaff3b9d7914195541c799c60df111a7539c7700b8ef1fa369"
TOTAL_SELECTED = "9293a027f1e8cab906f03531e79106c825d00b6efa411304e6199c72962b3a07"
LIFETIME_SELECTED = "1562a3363bc64d4b5e6de3540bc17b7071feb904142537892ef0cf379718a3c5"
RESET_SELECTED = "6722f9bff09293630b3a8c761321a954a32c3ecad02b92530178f0a25343f64d"
ZERO_TIME = "f5b6a7abbadf7680609fbf88a81056dd834557670ef8f465f3afec429e3b0d7a"
RESET_QUESTION = "f808550e27d595bef92b1f4a44a418de6ddf43eb5082ce2b17199130f9fed95b"
METERS_RESET = "dda8c7eace69cb8082634fceafc529a3bdd76cb5b8bc75e2aec9baf212146801"
DISPLAY_MENU = "85e4d8bdc2a4d129fce5fc59f9d59fb0078e2f6be18e51badf6d59f08a18979c"
DISPLAY_ENABLED = "548b69d0f1388aa8f8bd6022b478234b2439dbd0e6b2809f5e8d1ca1f19435c6"
DISPLAY_DISABLED = "e58122419cdcecb34cfe2cb3bc4eb6fc19f7b58813babd0d043a853290776188"
AUDIBLE_SINGLE_MENU = "fcca9a5ee1ba3e32b7853f60f90baab0c37150e79a4e76a6bc12277ea0ebe140"
AUDIBLE_REPETITIVE_MENU = "b0b8ba0f4499480bb160c4f8089b069bb621366a5e92d273bc26b0202e5c18ac"
SINGLE_TITLE = "ce55f2d1bd9cba83a27ded0d1dff02757916891273214c51e1cb6c6afe8173d5"
REPETITIVE_TITLE = "af24e9839dd7df143d716bf81c0fc5b3864b263fab3b9b79a64908c5ea19eec7"
ALERT_OFF = "3739c993b11da5e142c8aa09765e707fb4ca45c1521d0a35dfa331c66b5b195f"
SINGLE_ONE_MINUTE = "b056fd6f3604a649b8205c1ed20abed6c67dd6cab1aa20a58d1f389304c1ba4b"
REPETITIVE_FIVE_MINUTES = "c95bd1e7f2bb15d28a0b74e368292cfdea771e0e7c073929b252eedc05b41c0d"
CALL_REQUEST_PENDING = "5bd3f2bce41ba06debc2508340553bc4bb19e6abfa084b49d3bcc84a4c562c19"


class SharedCallSettingsChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def expect(self, expected, first=16, last=113):
        return self.handset.wait_screen(expected, first=first, last=last, max_steps=20000000)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def open_history(self):
        self.keys("soft_left", *(["down"] * 5), "soft_left")
        self.expect(HISTORY_MENU)

    def open_meters(self):
        self.open_history()
        self.keys("down", "soft_left")
        self.expect_meter(LAST_SELECTED)

    def expect_meter(self, selected):
        state = self.expect(METERS_TITLE, 0, 14)
        pixels = state["lcd"]["pixels"]
        # The menu retains its scroll offset when a counter dialog closes.
        visible_rows = [sha256(bytes(value for row in range(top, top + 16)
                                     for value in pixels[row * 128:row * 128 + 120])).hexdigest()
                        for top in range(16, 101, 17)]
        self.assertIn(selected, visible_rows, "The intended call-meter label must be highlighted")

    def zero_meter(self, selected):
        self.expect_meter(selected)
        self.keys("soft_left")
        self.expect(ZERO_TIME)  # Visually inspected 00:00:00.
        self.keys("soft_right")
        self.expect_meter(selected)

    def finish_home(self):
        self.keys("red")
        self.expect(HOME)
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])

    def test_empty_histories_and_zero_meters_reset_cancellation_and_confirmation(self):
        self.open_history()
        self.keys("soft_left")
        self.expect(CALL_LOG)
        for index, (label, title) in enumerate(HISTORY_TITLES):
            with self.subTest(history=label):
                if index:
                    self.keys("down")
                self.keys("soft_left")
                self.expect(title, 0, 14)
                self.expect(EMPTY_HISTORY)
                self.keys("soft_right")
        self.keys("soft_right", "down", "soft_left")
        self.zero_meter(LAST_SELECTED)
        self.keys("down")
        self.zero_meter(TOTAL_SELECTED)

        self.keys("down")
        self.expect_meter(RESET_SELECTED)
        self.keys("soft_left")
        self.expect(RESET_QUESTION)
        self.keys("soft_right")  # No.
        self.expect_meter(RESET_SELECTED)
        self.keys("down")
        self.zero_meter(LIFETIME_SELECTED)

        self.keys("up", "soft_left")
        self.expect(RESET_QUESTION)
        # Fresh counters are zero; this checks the reset flow without inventing an elapsed call.
        self.keys("soft_left")  # Yes.
        self.expect(METERS_RESET)
        self.keys("soft_right")
        self.expect_meter(RESET_SELECTED)
        self.keys("up")
        self.zero_meter(TOTAL_SELECTED)
        self.keys("up")
        self.zero_meter(LAST_SELECTED)
        self.keys("down", "down", "down")
        self.zero_meter(LIFETIME_SELECTED)
        self.finish_home()

    def preference_round_trip(self, parent, original, changed, choose, restore, title=None):
        self.expect(parent)
        self.keys("soft_left")
        self.expect(original)
        if title:
            self.expect(title, 0, 14)
        self.keys(*choose, "soft_left")
        # Wait for the original persistence operation to finish before sending another key.
        self.expect(parent)
        self.keys("soft_left")
        self.expect(changed)
        self.keys(*restore, "soft_right")
        self.expect(parent)
        self.keys("soft_left")
        self.expect(changed)
        self.keys(*restore, "soft_left")
        self.expect(parent)
        self.keys("soft_left")
        self.expect(original)
        self.keys("soft_right")
        self.expect(parent)

    def test_in_call_display_and_audible_preferences_save_cancel_and_restore(self):
        self.open_meters()
        self.keys(*(["down"] * 4))
        # This widget initially focuses Disabled while its saved value is Enabled.
        self.preference_round_trip(DISPLAY_MENU, DISPLAY_ENABLED, DISPLAY_DISABLED, (), ("down",))
        self.keys("down", "soft_left")
        self.preference_round_trip(AUDIBLE_SINGLE_MENU, ALERT_OFF, SINGLE_ONE_MINUTE,
                                   ("down",), ("up",), SINGLE_TITLE)
        self.keys("down")
        self.preference_round_trip(AUDIBLE_REPETITIVE_MENU, ALERT_OFF, REPETITIVE_FIVE_MINUTES,
                                   ("down", "down"), ("up", "up"), REPETITIVE_TITLE)
        # These assertions cover saved preferences; no elapsed-call alert or sound is asserted.
        self.finish_home()

    def test_one_touch_voicemail_hold_issues_original_pending_call_request(self):
        handset = self.handset
        self.expect(HOME)
        self.assertTrue(handset.key("1", True)["delivered"])
        try:
            state = handset.wait_screen(CALL_REQUEST_PENDING, max_steps=30000000,
                                        chunk_steps=2000000)
            self.assertEqual(state["keys"], ["1"])
        finally:
            self.assertTrue(handset.key("1", False)["delivered"])
        state = handset.step(2000000)
        self.expect(CALL_REQUEST_PENDING)
        self.assertEqual(state["keys"], [])
        self.assertFalse(state["satellite"]["firmware_connected"])
        self.assertFalse(state["processor_link"]["connected"])


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 call-settings E2E tests")
class Factory9555CallSettingsE2ETests(SharedCallSettingsChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 call-settings E2E tests")
class Factory9575CallSettingsE2ETests(SharedCallSettingsChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
