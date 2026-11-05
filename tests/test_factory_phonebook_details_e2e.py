"""Factory contact notes, their size limit, and displayed memory accounting."""

from hashlib import sha256
import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED


MEMORY_ZERO = "8d387c96b3e87a00a1d3ef5e249ac375b7b4d404a00d5e79d2aec7dee2a91f99"
MEMORY_ONE = "7131a632369d49c1c7d5a17c82d7f03b1e8a15e17378ae780624fd944d550d89"
EMPTY_NOTE = "44f4666e9da307bc42096fc23afd6265ee9cc974ab4e91cb99c4073564cf08ed"
NOTE_OPTIONS = "bd9bcaf774d0b6f3164bc2a1dd816211c7777c702de3c644c86c3955b005a7a1"
NOTES_SELECTED = "50e8b18aea3f2973503b4cdbd6c353c60bb841c064c4a20c6e108312264cb7d7"
DELETE_ADG = "e9571c5710094081785507d95f69cdfc86aa0e9d3f6530a0b595cf759642ee4a"
NOTE_SIXTY_ONE_REMAINING = "14515246aa8a9cef1efbaee1f3472b0601d154052537077efb5544421f977daa"
NOTE_SIXTY_TWO_REMAINING = "c16c49922cc1d25dbb78d26ecd4cb5ab6e7933b6aa5cb4a5141baca4807bc6df"
NOTE_ZERO_REMAINING = "c57f2603a63d165dca9515225fcec177d1385fb5b736a3e560bf572e7ddd594a"
NOTE_ADG = "349e0b33e98c7de8fd5c8b1c634f3762edbbb9b560018d1c0388f768e54091a3"
NOTE_AD = "3e532063d568cad7ca58e4195984dcd3e622684849a97c60adfd43a0adb55bf7"
NOTE_SIXTY_FOUR = "fd759d14e03cfc83aca43062f58bdc01b9aaa1274d02c9eb6f0aaa7463b9fa6e"


class SharedPhonebookDetailChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, screen):
        return self.handset.wait_screen(screen, max_steps=20000000)

    def create_contact(self):
        self.keys("soft_left", "soft_left", "2", "3", "4", "down", "1", "2", "3", "soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.expect(ADG_SELECTED)

    def open_notes(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left")

    def save_notes(self):
        self.keys("soft_left")
        self.expect(NOTE_OPTIONS)
        self.keys("soft_left")
        self.expect(ADG_SELECTED)

    def finish_from_phonebook(self):
        self.keys("soft_right", "soft_right")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def test_contact_notes_save_reopen_cancel_and_memory_usage(self):
        handset = self.handset
        self.keys("soft_left", "down", "soft_left")
        self.expect(MEMORY_ZERO)  # Space on Phone: Used 0 of 100.
        self.keys("soft_right", "soft_right")
        self.create_contact()
        self.keys("soft_left", *(["down"] * 5), "soft_left")
        self.expect(MEMORY_ONE)
        self.keys("soft_right", "down", "soft_left")
        self.expect(EMPTY_NOTE)
        self.keys("2", "3", "4")

        def assert_note():
            state = handset.assert_healthy()
            self.assertEqual(handset.screen_hash(0, 14, state), NOTE_SIXTY_ONE_REMAINING)
            pixels = state["lcd"]["pixels"]
            # All three glyphs, excluding the caret at x=27 on reopen.
            glyphs = bytes(pixels[y * 128 + x] for y in range(19, 30) for x in range(4, 26))
            self.assertEqual(sha256(glyphs).hexdigest(), NOTE_ADG)

        assert_note()
        self.save_notes()
        self.open_notes()
        assert_note()
        self.keys("soft_right")
        draft = handset.assert_healthy()
        self.assertEqual(handset.screen_hash(0, 14, draft), NOTE_SIXTY_TWO_REMAINING)
        glyphs = bytes(draft["lcd"]["pixels"][y * 128 + x]
                       for y in range(19, 30) for x in range(4, 19))
        self.assertEqual(sha256(glyphs).hexdigest(), NOTE_AD)
        self.keys("red")  # Cancel the observed Ad draft.
        self.expect(NOTES_SELECTED)
        self.keys("soft_left")
        assert_note()
        self.keys("red", "soft_right")
        self.expect(ADG_SELECTED)
        # Removing the contact and its note restores the displayed usage.
        self.keys("soft_left", *(["down"] * 3), "soft_left")
        self.expect(DELETE_ADG)
        handset.save_artifacts("delete-contact-with-note")
        self.keys("soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "down", "soft_left")
        self.expect(MEMORY_ZERO)
        self.keys("soft_right", "soft_right")
        self.finish_from_phonebook()

    def test_note_accepts_sixty_four_characters_rejects_extra_and_reopens_saved_text(self):
        handset = self.handset
        self.create_contact()
        self.open_notes()
        self.expect(EMPTY_NOTE)
        self.keys("2", "3", "4", *("23" * 30 + "2"))

        def assert_full_note():
            state = handset.assert_healthy()
            self.assertEqual(handset.screen_hash(0, 14, state), NOTE_ZERO_REMAINING)
            pixels = state["lcd"]["pixels"]
            # Adg + 'ad'*30 + 'a', in four lines. Omit only the final blinking
            # caret column; any additional glyph still changes this crop.
            glyphs = bytes(pixels[y * 128 + x] for y in range(16, 111) for x in range(4, 126)
                           if not (x == 95 and 61 <= y < 77))
            self.assertEqual(sha256(glyphs).hexdigest(), NOTE_SIXTY_FOUR)

        assert_full_note()
        self.keys("4")
        assert_full_note()
        self.save_notes()
        self.open_notes()
        assert_full_note()
        handset.save_artifacts("saved-sixty-four-character-note")
        self.keys("red", "soft_right")
        self.finish_from_phonebook()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 contact details E2E")
class Factory9555PhonebookDetailsE2ETests(SharedPhonebookDetailChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 contact details E2E")
class Factory9575PhonebookDetailsE2ETests(SharedPhonebookDetailChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
