"""Observed factory English, French and Spanish prediction in local Notes.

Words, accents, entry-mode labels and remaining counts are compared with the
original pinned bitmap font. These examples do not establish entire dictionaries
or messaging service. The blank caret column is the only omitted text column.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_customization_e2e import (
    EDITOR_MULTI_TAP, LANGUAGE_MENU, TEXT_LANGUAGE_MENU,
)
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_phonebook_details_e2e import DELETE_ADG, NOTES_SELECTED
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED


NOTE_CAPTIONS = "fded4005622149a17c3991b96e63f98a9e78ebdc8a8d0972843177c63b056006"
PREDICTIVE_NOTE_OPTIONS = "6b0b6ada8b0037a8600a4fdabba6d7a7801bfe90b701444bf6e78e73970d5c9b"
SAVED_MULTI_TAP = "c2b68a669d308dca31b7ab416c50c2a3211ee20954f214f93244325254313606"


class PredictiveNoteChecks:
    def setUp(self):
        self.evidence = []
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.handset.boot()
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left")
        self.expect(EDITOR_MULTI_TAP, 0, 14)
        self.keys("2", "3", "4", "down", "1", "2", "3", "soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.expect(ADG_SELECTED)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=20000000)

    def text_language(self, index):
        self.keys("red", "red", "red")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))), "soft_left")
        self.expect(LANGUAGE_MENU)
        self.keys("down", "soft_left", *(["up"] * 3),
                  *(["down"] * index), "soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.keys("red")
        self.expect(HOME_CAPTIONS, 113, 128)

    def start_notes(self, language):
        self.text_language(language)
        self.keys("soft_left", "soft_left")
        self.expect(ADG_SELECTED)
        self.open_notes()
        self.note("", "Ww")

    def open_notes(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left")

    def note(self, text, mode):
        expected, advance = self.font.render(text, 122)
        self.assertFalse(any(expected[y * 122 + advance] for y in range(15)),
                         "The caret exclusion must contain no expected glyph ink")
        header = bytearray(128 * 14)
        for value, left in ((mode, 0), (str(64 - len(text)), None)):
            glyphs, width = self.font.render(value, 128)
            if left is None:
                left = 127 - width
            for y in range(14):
                for x in range(width):
                    if glyphs[y * 128 + x]:
                        header[y * 128 + left + x] = glyphs[y * 128 + x]
        # Full first-line glyphs and trailing blanks; only the observed blank
        # column at the insertion caret is omitted. The independent remaining
        # count also detects an extra space or a narrow glyph at that column.
        wanted = bytes(expected[y * 122 + x] for y in range(15) for x in range(122)
                       if x != advance)
        state = self.handset.assert_healthy()
        for elapsed in range(0, 20000001, 200000):
            pixels = state["lcd"]["pixels"]
            actual = bytes(pixels[(16 + y) * 128 + 4 + x]
                           for y in range(15) for x in range(122) if x != advance)
            lower_blank = not any(pixels[y * 128 + x]
                                  for y in range(32, 110) for x in range(4, 126))
            if (actual == wanted and bytes(pixels[:128 * 14]) == header and lower_blank
                    and self.handset.screen_hash(113, 128, state) == NOTE_CAPTIONS):
                self.handset.assert_healthy(state)
                self.assertEqual(state["keys"], [])
                path = self.handset.save_artifacts(f"prediction-{len(self.evidence):02d}", state)
                self.evidence.append({"text": text, "mode": mode, "remaining": 64 - len(text),
                                      "caret_column": advance + 4, "artifact": str(path)})
                return state
            if elapsed < 20000000:
                state = self.handset.step(200000)
        path = self.handset.save_artifacts("prediction-timeout", state)
        self.fail(f"Original Notes must show {text!r} in {mode}, remaining {64 - len(text)}; {path}")

    def save_reopen(self, text):
        self.keys("soft_left")
        self.expect(PREDICTIVE_NOTE_OPTIONS)
        self.keys("soft_left")
        self.expect(ADG_SELECTED)
        self.open_notes()
        self.note(text, "ww")

    def cancel_reopen(self, saved):
        self.keys("red")
        self.expect(NOTES_SELECTED)
        self.keys("soft_left")
        self.note(saved, "ww")

    def finish(self):
        self.keys("red")
        self.expect(NOTES_SELECTED)
        self.keys("soft_right")
        self.expect(ADG_SELECTED)
        self.keys("soft_left", "down", "down", "down", "soft_left")
        self.expect(DELETE_ADG)
        self.keys("soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.text_language(3)  # Restore the original Multi-Tap setting.
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))), "soft_left",
                  "down", "soft_left", "down", "down", "down")
        self.expect(SAVED_MULTI_TAP)
        self.keys("red")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def test_english_letterwise_and_wordwise_predictions_save_reopen_and_cancel(self):
        self.start_notes(0)
        self.keys("#")
        self.note("", "ww")
        self.keys("convenience")
        self.note("", "lw")
        self.keys("3")
        self.note("f", "lw")
        self.keys("*")
        self.note("d", "lw")
        self.keys("6", "6", "5", "8")
        self.note("don't", "lw")
        self.save_reopen("don't")
        self.keys("soft_right")
        self.note("fool", "ww")  # Observed re-prediction of the shorter draft.
        self.cancel_reopen("don't")
        self.keys(*(["soft_right"] * 5))
        self.note("", "ww")
        self.keys("7", "3", "3")
        self.note("see", "ww")
        self.keys("*")
        self.note("red", "ww")
        self.save_reopen("red")
        self.keys("soft_right")
        self.note("rd", "ww")
        self.cancel_reopen("red")
        self.finish()

    def test_french_wordwise_accents_alternatives_save_reopen_and_cancel(self):
        self.start_notes(1)
        self.keys("2", "6", "6", "5", "6", "8", "7")
        self.note("Bonjour", "ww")
        self.save_reopen("Bonjour")
        self.keys("soft_right")
        self.note("Bonjou", "ww")
        self.cancel_reopen("Bonjour")
        self.keys(*(["soft_right"] * 7), "3", "8", "3")
        self.note("été", "ww")
        self.keys("*")
        self.note("due", "ww")
        self.cancel_reopen("Bonjour")
        self.keys(*(["soft_right"] * 7), "3", "8", "3")
        self.note("été", "ww")
        self.save_reopen("été")
        self.finish()

    def test_spanish_wordwise_inverted_punctuation_save_reopen_and_cancel(self):
        self.start_notes(2)
        self.keys("4", "6", "5", "2")
        self.note("Hoja", "ww")
        self.keys("*")
        self.note("Hola", "ww")
        self.save_reopen("Hola")
        self.keys("convenience")
        self.note("Hola", "lw")
        self.keys("convenience")
        self.note("Hola", "#?@")
        self.keys("1")
        self.note("Hola!", "#?@")
        self.keys("*")
        self.note("Hola¡", "#?@")
        self.keys("2")
        self.note("Hola¡?", "#?@")
        self.keys("*")
        self.note("Hola¡¿", "#?@")
        self.save_reopen("Hola¡¿")
        self.keys("convenience", "convenience", "soft_right")
        self.note("Hola¡", "#?@")
        self.cancel_reopen("Hola¡¿")
        self.finish()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 prediction E2E")
class Factory9555PredictionE2ETests(PredictiveNoteChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 prediction E2E")
class Factory9575PredictionE2ETests(PredictiveNoteChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
