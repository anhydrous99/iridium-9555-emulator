"""Alphabetical contact lookup using the factory phonebook's arrow navigation."""

from hashlib import sha256
import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED


D_ONLY = "4ea0c81cf7bd92a229de432ca103ec71fadabd5a9c4ce54b3be81832cdb7e3c8"
A_THEN_D_SELECTED_A = "a79cb2a177e911deb8720243284d0cd9e0d85fe83575c6d823a0e11c956f5744"
A_THEN_D_SELECTED_D = "c46fce8894dbd0de2c796988969eaad93413bb22de14f3ef1ae736ea87be8550"
NAME_A = "1a430b00256202f098c571dacaf5e61a4790e0b6d3ca7520fbd55d40c094a47a"
NAME_D = "f48b4665f3644c36a8f846b8af0778aa1e9fc837a359ae08050c199bb91f8b59"
NUMBER_PLUS_123 = "4de915bd746339b62d06fa4d2421c33fdf8efb3e228659e016f08bf000f2f76c"
NUMBER_PLUS_456 = "73e22c658100f4455fdd0f884c62e7386ec8a27663f25eaf51f04338a8004362"


class SharedPhonebookLookupChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, screen, first=16, last=113):
        return self.handset.wait_screen(screen, first=first, last=last, max_steps=20000000)

    def assert_contact(self, name, number):
        state = self.handset.assert_healthy()
        pixels = state["lcd"]["pixels"]
        # Complete single-letter name glyph; omit the caret/field edge at x=13.
        glyph = bytes(pixels[y * 128 + x] for y in range(19, 30) for x in range(15, 24))
        self.assertEqual(sha256(glyph).hexdigest(), name)
        self.expect(number, 32, 43)

    def return_home(self):
        self.keys("soft_right", "soft_right")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])

    def test_reverse_created_contacts_sort_and_navigation_finds_saved_details(self):
        self.keys("soft_left", "soft_left", "3", "down", "1", "2", "3", "soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.expect(D_ONLY)

        self.keys("soft_left", *(["down"] * 4), "soft_left")
        self.keys("2", "down", "4", "5", "6", "soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.expect(A_THEN_D_SELECTED_A)
        self.handset.save_artifacts("sorted-a-before-d")

        self.keys("soft_left", "down", "down", "soft_left")
        self.assert_contact(NAME_A, NUMBER_PLUS_456)
        self.keys("red")
        self.expect(A_THEN_D_SELECTED_A)
        self.keys("down")
        self.expect(A_THEN_D_SELECTED_D)
        self.keys("soft_left", "down", "down", "soft_left")
        self.assert_contact(NAME_D, NUMBER_PLUS_123)
        self.handset.save_artifacts("saved-d-details")
        self.keys("red")
        self.expect(A_THEN_D_SELECTED_D)
        self.keys("up")
        self.expect(A_THEN_D_SELECTED_A)
        self.return_home()

        self.keys("soft_left", "soft_left")
        self.expect(A_THEN_D_SELECTED_A)
        self.keys("down")
        self.expect(A_THEN_D_SELECTED_D)
        self.keys("soft_left", "down", "down", "soft_left")
        self.assert_contact(NAME_D, NUMBER_PLUS_123)
        self.keys("red")
        self.expect(A_THEN_D_SELECTED_D)
        self.return_home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 contact lookup E2E")
class Factory9555PhonebookLookupE2ETests(SharedPhonebookLookupChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 contact lookup E2E")
class Factory9575PhonebookLookupE2ETests(SharedPhonebookLookupChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
