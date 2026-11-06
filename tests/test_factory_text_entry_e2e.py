"""Observed multi-tap characters saved through the original local phonebook UI.

Golden rows were captured from unmodified BC5/AVR LCD output, independently
repeated on both models. These cases cover explicit multi-tap mode; they do
not assess predictive dictionaries, RF service, or persistence across power loss.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


TEXT_MULTI_TAP = "d175e43bcd84f5e21c17ddf794fe172b6eb56ebf2463ac0f476b1bb01007b0d7"
TEXT_LANGUAGE_MENU = "769af01769ed6173ada4bc18ac342116e909c7b6102f9ffdc0aaafb38cdcebac"
EMPTY_EDITOR_HEADER = "ef42a5565810d5731b61cba252c09030873f210913be91ab119cda461e3e6ac5"
EMPTY_PHONEBOOK = "5c8ac71e85b20e86e1c8a970e3826381c9028b4e86fda20c7a8978260ecbba68"
ENTRY_ADDED = "6221daf9023ac16781d91f5c7f64807b3eca2b8e575281a89bd51d4214a20b3b"
SYMBOL_PICKER = "955e452a85aff699f620fc681ac0068ef80a3009ed47ddedb6419083d1b40902"
SYMBOL_SECOND_ROW = "747053f620c5f29c43a7ffd912029f17c9b08abcc8c3f9037935687588444720"
# Full name rows include the editor's field icon and underline. The active
# caret is excluded from interim 16:27 checks; full 16:32 checks focus elsewhere.
C = "41efaeed01b484eea72a56785c6e3d5b29eab34613b85a11125a2e2747a6846f"
CA = "17a248ca488b5ceb677369b399ec2b0af4449ae26a90dc2aad166ba60c646e07"
CAA = "7febcb150f0bafd5b1bc0059947cd3e76a183371748d4b6e5dfa1bae00a4eab9"
CAA_FULL = "5b3ba8627d7b37af6491c9bb4da8716bf405554eeff9527705344ac2af5b5ff9"
CASE_CYCLE = "05300eab5fed0574a8100c662c401401b06445afe1dd09a8a3edd5560ae61fac"  # AaD4j
PUNCTUATION = "eb68e7f79fcf8ed45701be1c91cbfa420d62d294692391d6ee59436443ea6b09"  # AaD4j@
CASE_SYMBOL_FULL = "c1094bcab5954cab45dbcd3ca750d3119e03c353b72afb798709d4bfc3aa94f0"  # AaD4j@@
NUMBER_123 = "4de915bd746339b62d06fa4d2421c33fdf8efb3e228659e016f08bf000f2f76c"


class TextEntryChecks:
    def expect(self, handset, digest, first=16, last=113, max_steps=2000000):
        return handset.wait_screen(digest, first=first, last=last, max_steps=max_steps)

    def new_multitap_contact(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()
        # Explicitly save Multi-Tap via Setup -> Language -> Text Entry.
        keys = (["soft_left"] + ["down"] * 6 + ["soft_left"]
                + ["down"] * (3 + (self.model == "9575"))
                + ["soft_left", "down", "soft_left"])
        for key in keys:
            handset.press(key)
        self.expect(handset, TEXT_MULTI_TAP)
        for key in ["down"] * 3 + ["soft_left"]:
            handset.press(key)
        self.expect(handset, TEXT_LANGUAGE_MENU, max_steps=20000000)
        handset.press("red")
        self.expect(handset, HOME_CAPTIONS, 113, 128)
        handset.press("soft_left")
        handset.press("soft_left")
        self.expect(handset, EMPTY_PHONEBOOK)
        handset.press("soft_left")
        handset.press("soft_left")
        self.expect(handset, EMPTY_EDITOR_HEADER, 0, 14)
        return handset

    def save_and_reopen(self, handset, name_digest):
        handset.press("down")
        self.expect(handset, name_digest, 16, 32)
        for key in ("1", "2", "3"):
            handset.press(key)
        handset.press("up")
        self.expect(handset, NUMBER_123, 32, 43)
        handset.press("soft_left")
        self.expect(handset, ENTRY_ADDED, max_steps=20000000)
        handset.save_artifacts("entry-added")
        handset.press("soft_right")
        # Leave the phonebook before reopening its saved entry.
        handset.press("red")
        self.expect(handset, HOME_CAPTIONS, 113, 128)
        for key in ("soft_left", "soft_left", "soft_left", "down", "down", "soft_left"):
            handset.press(key)
        self.expect(handset, NUMBER_123, 32, 43)
        handset.press("down")
        state = self.expect(handset, name_digest, 16, 32)
        handset.save_artifacts("saved-name-reopened", state)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)

    def test_multitap_repeated_key_cycles_then_timeout_appends_saved_letters(self):
        handset = self.new_multitap_contact()
        # A measured accepted keypad interval: three rapid presses select C.
        # These are guest-instruction budgets, not a claim about wall-clock time.
        for _ in range(3):
            handset.press("2", settle_steps=500000)
        self.expect(handset, C, 16, 27)
        handset.save_artifacts("rapid-222-is-C")
        # Let the original timer commit the character, then use the same key.
        handset.step(10000000)
        handset.press("2")
        self.expect(handset, CA, 16, 27)
        handset.step(10000000)
        handset.press("2")
        self.expect(handset, CAA, 16, 27)
        handset.save_artifacts("timed-same-key-is-Caa")
        self.save_and_reopen(handset, CAA_FULL)

    def test_case_cycle_punctuation_and_symbol_select_cancel_save_and_reopen(self):
        handset = self.new_multitap_contact()
        # Actual text: initial-capital A, lower-case a, upper-case D, digit 4,
        # then initial-capitals mode mid-word produces lower-case j.
        for key in ("2", "#", "2", "#", "3", "#", "4", "#", "5"):
            handset.press(key)
        self.expect(handset, CASE_CYCLE, 16, 27)
        handset.save_artifacts("case-cycle-is-AaD4j")
        for _ in range(2):
            handset.press("1", settle_steps=500000)
        self.expect(handset, PUNCTUATION, 16, 27)
        handset.save_artifacts("punctuation-is-at-sign")
        handset.press("*")
        self.expect(handset, SYMBOL_PICKER)
        handset.press("down")
        self.expect(handset, SYMBOL_SECOND_ROW)
        handset.press("soft_left")  # Select the original @ glyph from the grid.
        handset.press("down")
        self.expect(handset, CASE_SYMBOL_FULL, 16, 32)
        handset.press("up")
        handset.press("*")
        self.expect(handset, SYMBOL_PICKER)
        handset.press("down")
        handset.press("down")
        handset.press("soft_right")  # Cancel a tentative symbol selection.
        handset.press("down")
        self.expect(handset, CASE_SYMBOL_FULL, 16, 32)
        handset.save_artifacts("symbol-cancel-preserves-AaD4j-at-at")
        handset.press("up")
        self.save_and_reopen(handset, CASE_SYMBOL_FULL)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 text-entry E2E tests")
class Factory9555TextEntryE2ETests(TextEntryChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 text-entry E2E tests")
class Factory9575TextEntryE2ETests(TextEntryChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
