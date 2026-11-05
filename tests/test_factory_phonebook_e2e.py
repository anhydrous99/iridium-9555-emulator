"""Local contact lifecycle using factory firmware and the handset HTTP controls."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


EMPTY_PHONEBOOK = "5c8ac71e85b20e86e1c8a970e3826381c9028b4e86fda20c7a8978260ecbba68"
ENTRY_ADDED = "6221daf9023ac16781d91f5c7f64807b3eca2b8e575281a89bd51d4214a20b3b"
ADG_SELECTED = "3782b2c97ed854dcfccec43b2c5c50570d040d5244ba529256a474edcdb852d5"
ENTRY_UPDATED = "55ad160dc5a965307321799eda5eaa61dae3dbefd654da3f74f281ea62c6c0ca"
ADJ_SELECTED = "6c3d46d3fba42b66d0e1964e305f6dc3a1cc29899528963b2ea7d9ccd60e8386"
DELETE_ADJ = "4b75afc2a437944d2c09bf8abab254f865d67678d2c1804c2978fa9967083392"
ENTRY_DELETED = "46f27ab8ebd0295577b35aec537c4038a60e0dc56f56daf3aff30042ea8a5273"


class LocalPhonebookChecks:
    def test_create_read_edit_cancel_deletion_and_delete_local_contact(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        def expect(screen, first=16, last=113):
            return handset.wait_screen(screen, first=first, last=last, max_steps=2000000)

        handset.press("soft_left")
        handset.press("soft_left")
        expect(EMPTY_PHONEBOOK)
        handset.press("soft_left")
        handset.press("soft_left")
        for key in ("2", "3", "4", "down", "1", "2", "3"):
            handset.press(key)
        handset.press("soft_left")
        expect(ENTRY_ADDED)
        handset.press("soft_right")
        expect(ADG_SELECTED)

        for key in ("soft_left", "down", "down", "soft_left"):
            handset.press(key)
        # Read saved text without the blinking caret or changing input-mode header.
        expect("43c71edf6ac92194c1abec64dc583fd5baab48ab44d7286c4d8f335b18fed362", 16, 27)  # Adg
        expect("4de915bd746339b62d06fa4d2421c33fdf8efb3e228659e016f08bf000f2f76c", 32, 43)  # +123
        for key in ("soft_right", "5", "down", "4", "soft_left"):
            handset.press(key)
        expect(ENTRY_UPDATED)
        handset.press("soft_right")
        expect(ADJ_SELECTED)

        for key in ("soft_left", "down", "down", "soft_left"):
            handset.press(key)
        expect("2da1370017ee2faa5df69747ff6afede36b904ea0f7818298333caa6177f2b06", 16, 27)  # Adj
        expect("c8992f664c2dd3b042d4e77d2c185a6b16cdf2294e707132037cddccac6272ef", 32, 43)  # +1234
        handset.press("soft_left")
        handset.press("soft_right")
        expect(ADJ_SELECTED)

        for key in ("soft_left", "down", "down", "down", "soft_left"):
            handset.press(key)
        expect(DELETE_ADJ)
        handset.press("soft_right")
        handset.press("soft_right")
        expect(ADJ_SELECTED)
        for key in ("soft_left", "down", "down", "down", "soft_left"):
            handset.press(key)
        expect(DELETE_ADJ)
        handset.press("soft_left")
        expect(ENTRY_DELETED)
        handset.press("soft_right")
        expect(EMPTY_PHONEBOOK)
        handset.press("soft_right")
        handset.press("soft_right")
        state = expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 phonebook E2E tests")
class Factory9555PhonebookE2ETests(LocalPhonebookChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 phonebook E2E tests")
class Factory9575PhonebookE2ETests(LocalPhonebookChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
