"""Local voicemail number configuration through factory handset HTTP controls."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


VOICEMAIL_MENU = "a66304e31e6588bb688adaea3c69d1a699c9a41dc313c67a643fb69bb08b5e5b"
NUMBER_MENU = "e49f3d29ff331ce47358d7f7c3abc9e6c2d1ff09ce12b08f500d317c112dd5ae"
DEFAULT_NUMBER = "0593341ac364365d0c7f589f064ebe1f1fce96a209127a0d67ca2147787bb945"
EXTENDED_NUMBER = "a5ff19abc1ea1cc4f819954ba9a1a544fba4e9e7551829890cdae08b8f0fefbf"


class SharedVoicemailChecks:
    def test_voicemail_number_save_reopen_cancel_and_restore(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        def expect(screen):
            return handset.wait_screen(screen, max_steps=20000000)

        handset.press("soft_left")
        for _ in range(3):
            handset.press("down")
        handset.press("soft_left")
        expect(VOICEMAIL_MENU)
        handset.press("down")
        handset.press("soft_left")
        expect(NUMBER_MENU)
        handset.press("soft_left")
        expect(DEFAULT_NUMBER)  # Inspected original default: +881662990000.
        for key in "123":
            handset.press(key)
        handset.press("soft_left")
        expect(NUMBER_MENU)
        handset.press("soft_left")
        expect(EXTENDED_NUMBER)  # Saved +881662990000123.

        handset.press("soft_right")
        handset.press("red")
        expect(NUMBER_MENU)
        handset.press("soft_left")
        expect(EXTENDED_NUMBER)  # Cancelling the tentative deletion retained it.
        for _ in range(3):
            handset.press("soft_right")
        handset.press("soft_left")
        expect(NUMBER_MENU)
        handset.press("soft_left")
        expect(DEFAULT_NUMBER)
        handset.press("red")
        for _ in range(3):
            handset.press("soft_right")
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 voicemail E2E")
class Factory9555VoicemailE2ETests(SharedVoicemailChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 voicemail E2E")
class Factory9575VoicemailE2ETests(SharedVoicemailChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
