"""Original contact-editor side cursor and held numeric shortcuts over HTTP.

Holds and character intervals use guest instruction budgets, not calibrated
physical time. Stored punctuation is asserted without dialing or pause audio.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_text_entry_e2e import (
    EMPTY_EDITOR_HEADER, EMPTY_PHONEBOOK, ENTRY_ADDED, TEXT_LANGUAGE_MENU, TEXT_MULTI_TAP,
)


class SharedCursorShortcutChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.handset.boot()
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))),
                  "soft_left", "down", "soft_left")
        self.expect(TEXT_MULTI_TAP)
        self.keys("down", "down", "down", "soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.keys("red", "soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left")
        self.handset.wait_screen(EMPTY_EDITOR_HEADER, first=0, last=14,
                                 max_steps=20000000)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, screen):
        return self.handset.wait_screen(screen, max_steps=20000000)

    def expect_field(self, text, row, *, active_number=False):
        expected, cursor = self.font.render(text, 113)
        choices = [expected]
        if active_number:
            # The active numeric field adds a right border and a blinking
            # five-pixel caret on row14. Compare both complete states; no mask.
            border = bytearray(expected)
            for y in range(15):
                border[y * 113 + 112] = 3
            choices = [bytes(border)]
            self.assertLessEqual(cursor + 5, 112)
            border[14 * 113 + cursor:14 * 113 + cursor + 5] = bytes([3]) * 5
            choices.append(bytes(border))
        for elapsed in range(0, 20000001, 200000):
            state = self.handset.assert_healthy()
            pixels = state["lcd"]["pixels"]
            actual = bytes(pixels[(row + y) * 128 + 15 + x]
                           for y in range(15) for x in range(113))
            if actual in choices:
                return state
            if elapsed < 20000000:
                self.handset.step(200000)
        self.handset.save_artifacts("complete-field-timeout", state)
        self.fail(f"Original LCD field at row{row} must contain exactly {text!r}")

    def save_leave_and_reopen(self, name, number):
        self.keys("soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right", "red")
        self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                 max_steps=2000000)
        self.keys("soft_left", "soft_left", "soft_left", "down", "down", "soft_left")
        self.expect_field(number, 32)  # Name has focus; every number pixel is checked.
        self.keys("down")
        state = self.expect_field(name, 16)  # Number has focus; name caret is absent.
        self.assertEqual(state["keys"], [])
        self.handset.save_artifacts("complete-saved-name-and-number-reopened", state)
        self.keys("red", "red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                         max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def held_number_shortcut(self, key, text):
        self.assertTrue(self.handset.key(key, True)["delivered"])
        try:
            self.handset.step(10000000)
            state = self.expect_field(text, 32, active_number=True)
            self.assertEqual(state["keys"], [key])
            self.handset.step(8000000)
            state = self.expect_field(text, 32, active_number=True)
            self.assertEqual(state["keys"], [key])
            self.handset.save_artifacts("held-zero-plus" if key == "0" else "held-star-comma", state)
        finally:
            self.assertTrue(self.handset.key(key, False)["delivered"])
        self.handset.step(2000000)
        state = self.expect_field(text, 32, active_number=True)
        self.assertEqual(state["keys"], [])
        self.handset.save_artifacts("zero-release-no-extra-zero" if key == "0"
                                    else "star-release-no-extra-star", state)

    def test_volume_keys_move_contact_cursor_for_insertion_deletion_and_complete_saved_readback(self):
        self.keys("2", "3", "4", "volume_up", "5", "down")
        self.expect_field("Adjg", 16)
        self.handset.save_artifacts("backward-cursor-name-insertion")
        self.keys("up", *(["volume_up"] * 4), *(["volume_down"] * 4),
                  "soft_right", "6", "down")
        self.expect_field("Adjm", 16)
        self.handset.save_artifacts("forward-cursor-name-deletion-and-insertion")
        self.keys("1", "2", "3", "4", "volume_up", "volume_up", "9", "up")
        self.expect_field("+12934", 32)
        self.handset.save_artifacts("backward-cursor-number-insertion")
        self.keys("down", *(["volume_up"] * 6), *(["volume_down"] * 5),
                  "soft_right", "6", "up")
        self.expect_field("+12964", 32)
        self.handset.save_artifacts("forward-cursor-number-deletion-and-insertion")
        self.save_leave_and_reopen("Adjm", "+12964")

    def test_brief_numeric_controls_and_held_zero_plus_star_comma_suppress_release_then_save(self):
        self.keys("2", "3", "4", "down", "soft_right")
        self.expect_field("", 32, active_number=True)
        self.keys("0")
        self.expect_field("0", 32, active_number=True)
        self.keys("*")
        self.expect_field("0*", 32, active_number=True)
        self.keys("up")
        self.expect_field("0*", 32)
        self.handset.save_artifacts("brief-zero-and-star-remain-literal")
        self.keys("down", "soft_right", "soft_right")
        self.expect_field("", 32, active_number=True)
        self.held_number_shortcut("0", "+")
        # Original number normalization clears a lone + on field change.
        self.keys("1", "2")
        self.expect_field("+12", 32, active_number=True)
        self.keys("up")
        self.expect_field("+12", 32)
        self.keys("down")
        self.held_number_shortcut("*", "+12,")
        self.keys("up")
        self.expect_field("+12,", 32)
        self.keys("down", "9", "up")
        self.expect_field("+12,9", 32)
        self.save_leave_and_reopen("Adg", "+12,9")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 cursor/shortcut E2E")
class Factory9555CursorShortcutE2ETests(SharedCursorShortcutChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 cursor/shortcut E2E")
class Factory9575CursorShortcutE2ETests(SharedCursorShortcutChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
