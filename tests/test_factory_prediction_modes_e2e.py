"""Supported original Notes punctuation and text-preserving mode transitions.

These local editor cases do not establish the broader help map, SMS or complete
dictionary coverage. Guest instruction intervals are not physical timing.
"""

import os
import unittest

from test_factory_prediction_e2e import NOTE_CAPTIONS, PredictiveNoteChecks


PUNCTUATION_GROUPS = (
    ("3", "%$£"), ("4", "_"), ("5", '-+="'), ("6", "(<"),
    ("7", "/"), ("8", ":;&"), ("9", ")>"), ("0", ".,@"),
)
MULTITAP_WITH_51_REMAINING = "12bbadd10740e0ac5968be1643a591a618dc642e6ece3abccc0d3353b3429036"


class PredictionModeChecks:
    # Reuse the established genuine-key Notes setup, original-font/count oracle,
    # saved-text readback and setting restoration without inheriting old cases.
    setUp = PredictiveNoteChecks.setUp
    keys = PredictiveNoteChecks.keys
    expect = PredictiveNoteChecks.expect
    text_language = PredictiveNoteChecks.text_language
    start_notes = PredictiveNoteChecks.start_notes
    open_notes = PredictiveNoteChecks.open_notes
    note = PredictiveNoteChecks.note
    save_reopen = PredictiveNoteChecks.save_reopen
    cancel_reopen = PredictiveNoteChecks.cancel_reopen
    finish = PredictiveNoteChecks.finish

    def multitap_preserves_note(self, text):
        # The original Multi-Tap header uses its own Abc glyph and count layout.
        # Its inspected complete header includes the exact 51 remaining count.
        self.assertEqual(64 - len(text), 51)
        state = self.expect(MULTITAP_WITH_51_REMAINING, 0, 14)
        pixels = state["lcd"]["pixels"]
        expected, advance = self.font.render(text, 122)
        self.assertFalse(any(expected[y * 122 + advance] for y in range(15)))
        self.assertEqual(
            bytes(pixels[(16 + y) * 128 + 4 + x]
                  for y in range(15) for x in range(122) if x != advance),
            bytes(expected[y * 122 + x]
                  for y in range(15) for x in range(122) if x != advance))
        self.assertFalse(any(pixels[y * 128 + x]
                             for y in range(32, 110) for x in range(4, 126)))
        self.assertEqual(self.handset.screen_hash(113, 128, state), NOTE_CAPTIONS)
        self.assertEqual(state["keys"], [])
        path = self.handset.save_artifacts("multitap-preserves-preceding-text", state)
        self.evidence.append({"text": text, "mode": "Abc", "remaining": 51,
                              "caret_column": advance + 4, "artifact": str(path),
                              "header_sha256": MULTITAP_WITH_51_REMAINING})

    def test_all_remaining_punctuation_groups_next_wrap_save_reopen_and_visible_draft_cancel(self):
        self.start_notes(0)
        self.keys("#")
        self.note("", "ww")
        saved = ""
        for key, symbols in PUNCTUATION_GROUPS:
            self.keys("convenience", "convenience", *(["soft_right"] * len(saved)))
            self.note("", "#?@")
            text = ""
            for index, symbol in enumerate(symbols):
                self.keys(key)
                self.note(text + symbols[0], "#?@")
                for alternative in symbols[1:index + 1]:
                    self.keys("*")
                    self.note(text + alternative, "#?@")
                text += symbol
            self.keys("*")
            self.note(text[:-1] + symbols[0], "#?@")
            for alternative in symbols[1:]:
                self.keys("*")
                self.note(text[:-1] + alternative, "#?@")
            self.save_reopen(text)
            self.keys("convenience", "convenience", "soft_right")
            self.note(text[:-1], "#?@")
            self.cancel_reopen(text)
            saved = text
        self.finish()

    def test_wordwise_spaces_inline_punctuation_and_digit_mode_preserve_preceding_text(self):
        self.start_notes(0)
        self.keys("#", "7", "3", "3", "*")
        self.note("red", "ww")
        self.keys("0", "7", "3", "3")
        self.note("red see", "ww")
        self.keys("*")
        self.note("red red", "ww")
        self.keys("1")
        self.note("red red.", "ww")
        self.keys("*")
        self.note("red red,", "ww")
        self.keys("7", "3", "3")
        self.note("red red,see", "ww")
        self.keys("*")
        self.note("red red,red", "ww")
        self.keys("convenience")
        self.note("red red,red", "lw")
        self.keys("convenience")
        self.note("red red,red", "#?@")
        self.keys("convenience")
        self.note("red red,red", "123")
        self.keys("4", "2")
        self.note("red red,red42", "123")
        self.keys("convenience")
        self.multitap_preserves_note("red red,red42")
        self.keys("convenience")
        self.note("red red,red42", "ww")
        self.keys("0", "7", "3", "3", "*")
        self.note("red red,red42 red", "ww")
        self.save_reopen("red red,red42 red")
        self.keys("1", "*")
        self.note("red red,red42 red,", "ww")
        self.cancel_reopen("red red,red42 red")
        self.finish()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 prediction modes E2E")
class Factory9555PredictionModeE2ETests(PredictionModeChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 prediction modes E2E")
class Factory9575PredictionModeE2ETests(PredictionModeChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
