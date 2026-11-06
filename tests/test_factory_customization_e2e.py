"""Saved handset customization and its visible effects through factory HTTP UI."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


LANGUAGE_MENU = "d4887b8650475e61ea7df493d58293184819e49de8fc20d71787ad08b8975065"
MENU_ENGLISH = "145342085ea5f26eab7428f63ffb25329b22713ae679313fa926031f8b975522"
LANGUAGE_FRENCH = "314fcccbe72cbd9b06169d63942667966917dd13ce2f10e619d4d48a371265d0"
MENU_FRENCH = "7ee8fe70e2089fb0e6bfef80537c2270511e4da4537158e9b385050b71282e5f"
MENU_FRENCH_ENGLISH_FOCUS = "45afee0d46ed9398f09c1da83ca025bb95b8b320e976972e337364a653aaa5af"
TEXT_LANGUAGE_MENU = "769af01769ed6173ada4bc18ac342116e909c7b6102f9ffdc0aaafb38cdcebac"
TEXT_MULTI_TAP = "d175e43bcd84f5e21c17ddf794fe172b6eb56ebf2463ac0f476b1bb01007b0d7"
TEXT_ENGLISH = "4974982ab81f65735864c46245d4e55e7258e2a19d62439641d54aaafeba97fb"
EDITOR_LETTERWISE = "762be38e0f614e2f21fc292e9d5a5ebbf313c212696c70fdcb1794ec9119b231"
EDITOR_MULTI_TAP = "ef42a5565810d5731b61cba252c09030873f210913be91ab119cda461e3e6ac5"
KEY_SETUP_CONVENIENCE = "85b0934981452d98a39ad8dbfc48f424eb8ee8789246065864d17ce1788eba0c"
KEY_SETUP_RIGHT = "8f2d411602ea606a48187fca96c503ee3ef8ee72d1889591c5abaa079f127c47"
CONVENIENCE_DEFAULT = {
    "9555": "2c5ce7da517bfc2492a88b9116369b0d6dcb98a74d4f4c53412a54a32ade764a",
    "9575": "b96e5f28681f73944b2712493d7cc463a57bb8b51dd0e4d86c07a22a953b2f61",
}
CONVENIENCE_PHONEBOOK = {
    "9555": "45039bab506aae7d313956ee9391249eff85348d40e958417dc687ab574ba2f5",
    "9575": "e196062c456c481bee77ec7ce15bd941a41b3fc2497561fe738542257a99cd3c",
}
RIGHT_HELP = "ccc59343042cb469e29ad5e5ed741ded2181e2f13c6bf373b5b9fe3c139d3801"
RIGHT_PHONEBOOK = "5bc4fc55441bf2b574377fd84951eff66eb1607038ef6d2753063b58eb57e5f8"
RIGHT_SIM = "7b22b956d9b6856714c4e152f56ed2013b6aa08544fbf77fec746f9448bf3d7f"
SIM_NOT_READY = "afbdc304429f6fa77bf0ec9bdce17bc27df50cec9f82d227e3e858e85ba42c22"
PHONEBOOK_CAPTIONS = "2a7cd67a83ab126b6ca36115b44023efaf6308d1bee1cb5b227a00779b868300"
EMPTY_PHONEBOOK = "5c8ac71e85b20e86e1c8a970e3826381c9028b4e86fda20c7a8978260ecbba68"
HELP = "953a8e69dc39c0f36ab2c279065772d3ff13c1c7205b075cf62efeb43b2d337d"
GPS_PROMPT = "ccab0537fb15d496f17cc97f8104369a8d402327827e54765d9819e856dd1357"
HOME = "c5b13a7f8cb40d8e802fa101ddedc73657fc70b7ddf24b3becd757bf12fabee2"
NUMBER_ENTRY_MENU = {
    "9555": "23de4c61a8d924197170e8aa79a7fd08309007e1f371b5b07a93710d933754e3",
    "9575": "dacc5ddf3e9abc6fb102775de168dabe270a2bca42d5edf955637ed294e2e662",
}
PREFIX_PLUS = "b75173fee7a16e5bee7b4f0b05623d7ac6667ebb13f9828cdba04bbe89423a3c"
PREFIX_ZERO = "6d25cbcb95edc73777b99fe2f5596ed6b25487dc61c618469889cf4b4adfaa8f"
PREFIX_NONE = "32c691f899706cf3908efa40a3a43c9bfeca327e561cb5615bbe0cda6c957586"
DIAL_PLUS_TWELVE = "0202fd2bdaff65347166c5507d64b6947fe26117599393a717de476a01e50093"
DIAL_ZERO_TWELVE = "d727ad738110b5c85d9c96b0c1d471d761a732565e11b401d50dbd5e6bff275c"
DIAL_TWELVE = "090299bf6ac71755a6c41dc0ef908ae4df031954990fecaef52bedeafa9d834f"


class SharedCustomizationChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def expect(self, screen, first=16, last=113):
        return self.handset.wait_screen(screen, first=first, last=last, max_steps=20000000)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def open_setup(self, item):
        self.keys("soft_left", *(["down"] * 6), "soft_left")
        self.keys(*(["down"] * (item + (self.model == "9575"))))

    def home(self, captions=HOME_CAPTIONS):
        self.keys("red")
        self.expect(HOME)
        state = self.expect(captions, 113, 128)
        self.assertEqual(state["keys"], [])
        return state

    def test_menu_language_french_save_readback_cancel_and_restore_english(self):
        self.open_setup(3)
        self.keys("soft_left")
        self.expect(LANGUAGE_MENU)
        self.keys("soft_left")
        self.expect(MENU_ENGLISH)
        self.keys(*(["down"] * 5), "soft_left")
        # Saving French translates Text Entry to Saisie texte in the parent menu.
        self.expect(LANGUAGE_FRENCH)
        self.keys("soft_left")
        self.expect(MENU_FRENCH_ENGLISH_FOCUS)
        self.keys(*(["down"] * 5))
        self.expect(MENU_FRENCH)

        self.keys(*(["up"] * 5), "soft_right")
        self.expect(LANGUAGE_FRENCH)
        self.keys("soft_left")
        self.expect(MENU_FRENCH_ENGLISH_FOCUS)
        self.keys(*(["down"] * 5))
        self.expect(MENU_FRENCH)
        self.keys(*(["up"] * 5), "soft_left")
        self.expect(LANGUAGE_MENU)
        self.keys("soft_left")
        self.expect(MENU_ENGLISH)
        self.keys("soft_right")
        self.home()

    def test_text_language_save_cancel_and_restore_changes_contact_editor_mode(self):
        self.open_setup(3)
        self.keys("soft_left", "down", "soft_left")
        self.expect(TEXT_MULTI_TAP)
        self.keys("soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.keys("soft_left")
        self.expect(TEXT_ENGLISH)
        self.keys("down", "down", "down", "soft_right")
        self.expect(TEXT_LANGUAGE_MENU)
        self.keys("soft_left")
        self.expect(TEXT_ENGLISH)
        self.keys("soft_right")
        self.home()

        self.keys("soft_left", "soft_left", "soft_left", "soft_left")
        # The editor header is stable while its empty name field blinks.
        self.expect(EDITOR_LETTERWISE, 0, 14)
        self.keys("red")
        self.home()

        self.open_setup(3)
        self.keys("soft_left", "down", "soft_left")
        self.expect(TEXT_ENGLISH)
        self.keys("down", "down", "down", "soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.keys("soft_left")
        self.expect(TEXT_MULTI_TAP)
        self.keys("soft_right")
        self.home()
        self.keys("soft_left", "soft_left", "soft_left", "soft_left")
        self.expect(EDITOR_MULTI_TAP, 0, 14)
        self.keys("red")
        self.home()

    def test_convenience_phonebook_assignment_cancel_and_restore_original_action(self):
        original = CONVENIENCE_DEFAULT[self.model]
        phonebook = CONVENIENCE_PHONEBOOK[self.model]
        choose = ["up"] * 3 if self.model == "9575" else ["down"] * 5
        restore = ["down"] * 3 if self.model == "9575" else ["up"] * 5
        self.open_setup(6)
        self.keys("soft_left")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(original)
        self.keys(*choose, "soft_left")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(phonebook)
        self.keys(*restore, "soft_right")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(phonebook)
        self.keys("soft_right")
        self.home()
        self.keys("convenience")
        self.expect(EMPTY_PHONEBOOK)
        self.home()

        self.open_setup(6)
        self.keys("soft_left", "soft_left")
        self.expect(phonebook)
        self.keys(*restore, "soft_left")
        self.expect(KEY_SETUP_CONVENIENCE)
        self.keys("soft_left")
        self.expect(original)
        self.keys("soft_right")
        self.home()
        self.keys("convenience")
        if self.model == "9575":
            self.expect(GPS_PROMPT)
            self.keys("soft_right")
        self.expect(HOME)
        self.expect(HOME_CAPTIONS, 113, 128)

    def test_right_soft_key_assignments_open_phonebook_sim_error_and_help(self):
        self.open_setup(6)
        self.keys("soft_left", "down")
        self.expect(KEY_SETUP_RIGHT)
        self.keys("soft_left")
        self.expect(RIGHT_HELP)
        self.keys("down", "down", "soft_left")
        self.expect(KEY_SETUP_RIGHT)
        self.keys("soft_left")
        self.expect(RIGHT_PHONEBOOK)
        self.keys("up", "up", "soft_right")
        self.expect(KEY_SETUP_RIGHT)
        self.keys("soft_left")
        self.expect(RIGHT_PHONEBOOK)
        self.keys("soft_right")
        self.home(PHONEBOOK_CAPTIONS)
        self.keys("soft_right")
        self.expect(EMPTY_PHONEBOOK)
        self.home(PHONEBOOK_CAPTIONS)

        self.open_setup(6)
        self.keys("soft_left", "down", "soft_left")
        self.expect(RIGHT_PHONEBOOK)
        self.keys("up", "soft_left")
        self.expect(KEY_SETUP_RIGHT)
        self.keys("soft_left")
        self.expect(RIGHT_SIM)
        self.keys("soft_right")
        self.home(PHONEBOOK_CAPTIONS)
        self.keys("soft_right")
        self.expect(SIM_NOT_READY)
        self.home(PHONEBOOK_CAPTIONS)

        self.open_setup(6)
        self.keys("soft_left", "down", "soft_left")
        self.expect(RIGHT_SIM)
        self.keys("up", "soft_left")
        self.expect(KEY_SETUP_RIGHT)
        self.keys("soft_left")
        self.expect(RIGHT_HELP)
        self.keys("soft_right")
        self.home()
        self.keys("soft_right")
        self.expect(HELP)
        self.home()

    def test_all_number_prefixes_save_readback_cancel_and_change_dialer(self):
        parent = NUMBER_ENTRY_MENU[self.model]
        self.open_setup(7)
        self.expect(parent)
        self.keys("soft_left")
        self.expect(PREFIX_PLUS)
        self.keys("down", "soft_left")
        self.expect(parent)
        self.keys("soft_left")
        self.expect(PREFIX_ZERO)
        self.keys("up", "soft_right")
        self.expect(parent)
        self.keys("soft_left")
        self.expect(PREFIX_ZERO)
        self.keys("soft_right")
        self.home()
        self.keys("1", "2")
        self.expect(DIAL_ZERO_TWELVE)
        self.home()

        self.open_setup(7)
        self.keys("soft_left")
        self.expect(PREFIX_ZERO)
        self.keys("down", "soft_left")
        self.expect(parent)
        self.keys("soft_left")
        self.expect(PREFIX_NONE)
        self.keys("soft_right")
        self.home()
        self.keys("1", "2")
        self.expect(DIAL_TWELVE)
        self.home()

        self.open_setup(7)
        self.keys("soft_left")
        self.expect(PREFIX_NONE)
        self.keys("up", "up", "soft_left")
        self.expect(parent)
        self.keys("soft_left")
        self.expect(PREFIX_PLUS)
        self.keys("soft_right")
        self.home()
        self.keys("1", "2")
        self.expect(DIAL_PLUS_TWELVE)
        self.home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 customization E2E")
class Factory9555CustomizationE2ETests(SharedCustomizationChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 customization E2E")
class Factory9575CustomizationE2ETests(SharedCustomizationChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
