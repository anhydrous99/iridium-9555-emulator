"""Saved local settings through the original handset widgets and HTTP controls."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


SETUP = {
    "9555": "d47dc08f6320579a7b6dfe5850b294653ad4e6d37d55c484b6a29dbd763197b0",
    "9575": "890e354045721f1f847576665d56bcf9290fbb524519885da4c18680a8023055",
}
VOLUME_MENU = "8ea50f9b4baf0e095a619c70b4c4215acb454deab23b72cbf900ea6db4f23289"
SPEAKER_MENU = "75e705973034d503b9f07ef14ec63acf1111168e9b964b2951c06576089e9986"
RINGER_DEFAULT = "345151c5ac740650d2ef99fea278d418863a4fe2eda5c6dc2ae6a39e222b738f"
RINGER_LOUDER = "fa7e6382c35a41e7e63c08405b222a60fa876408c32d0cee401a680be1fdc8f4"
SPEAKER_DEFAULT = "e4192b6833ff42d6811353af37983e0613a570b08226718115b581ec26ce07e6"
SPEAKER_LOUDER = "c650871fe0692eda3eac521c8e517dd36c8695af13c150c54ad068b14221b213"
BACKLIGHT_MENU = {
    "9555": "7ff0fefb913ab9790ed412db4130961c7e59cf2bb1b4cc756fdc7dc10998c33f",
    "9575": "752b2f7a9ef1dbb13f731c0f5fcbd0b981e977643cf20048c1126da867796731",
}
BACKLIGHT_FIVE_SECONDS = "128da131e551ffb64de3ef8df1aa188a7e6d1a16705a84cd5adf182ef1b2ffb6"
BACKLIGHT_TEN_SECONDS = "016d44914797d9ea79092223d917b5bc5e4f8636c09230c2c8917e74a0762d9d"
CONTRAST_MENU = {
    "9555": "6252c2553a46e3e9a377097dd2d1a2e28f91e6a48ff9c0979687642711d0c805",
    "9575": "9ced97d5aeda5376df0ffd62f35e72f05c4786b74deef72b31b59efb42c6bf51",
}
CONTRAST_DEFAULT = "e1ed47a3ea6badfa98581cf9782b3491c242b5c17ffc3d25d4f9a4a0f43c0443"
CONTRAST_HIGHER = "bb449ae4ec8a5a42aca05c4df56cc44b2a97f597d67cbb82bdb68186467a60aa"
TIME_ZONE_MENU = "906b1eff0501973d9f7a8e786ab31bcd0e3a9927ebacecc955bc9f93a4bb0750"
TIME_ZONE_UTC = "fa631e3832f89032b487c374ba551eb93ce181b49fada28ed478c8f844fd3fbe"
TIME_ZONE_PLUS_HALF = "d4cb385b19512112b946e23d8e4634f9816510f1b863270638640f471c9fb1e5"
TIME_FORMAT_MENU = "e1832fab1800e70d13cd7a280f560f5225ec6d88491aabce08585b2de147f9b0"
TIME_TWENTY_FOUR_HOURS = "4ba0076cf8004119c2e2f581b506e1fabd04ccc3ae686c0c82b3f7f0e20dfbc6"
TIME_AM_PM = "2b21492b9ffe58a07030b61b18d55e1817ba1d8938b6bc3c5579380dbcf5d105"
DATE_FORMAT_MENU = "0d03b3f437e58f7254b7f2476fcdfae476bbde4bf929ebe955364e518571caa8"
DATE_DEFAULT = "f4f5b60eda7b8e3904900098ab9caf28d57ef74862d0ebe24126cae165d88b54"
DATE_SLASHES = "e264f480de531b8f1eeaf2170a77b80544176102a38e42e60ab636cf01935b4f"
RING_TONE_MENU = "305fc2093d56faed93c2ef7be70ecb8ccc47bf16c2e8eab3d5066166b51cf137"
ALERT_TONE_MENU = "34ac209a4c2f291b6494fbe709ee34f65b6c4798c220e2df8fa93419ec2a0bd5"
TONE_ONE = "3a078c05a750abccc612296f0b775c38d18b754f9dcf0229e610b84a0ee549ed"
TONE_TWO = "cf8237885ccbb347c1395c99ffc35f109d31a80e17590a8afeca46d7886c47d0"
KEYPAD_TONE_MENU = "7ed3ca4989afeb7976c9b91fa0bddb104273b9cbbdfcf7a829d7cead614b8185"
KEYPAD_SINGLE_TONE = "3354efd8ce460a4c9c0cc10f357053cd22789b298a5b5ae39a917665b8d92a95"
KEYPAD_NO_TONE = "7cb00fb39d1111bb1d075b9507ef803f4e199f1c451130bf503f77c49ea001cc"
NETWORK_TONE_MENU = "92c3602dd28debd907b74c2e2576dd2267ef6d7203b799f7ec7f6429925b1e07"
NETWORK_NO_TONE = "871950be9ed2480076c24b66f7ad2ee7a07e4a1450ffe9f68f2a292407357b17"
NETWORK_TONE = "2609a29d41df5a0e65ab0dbdb382f481e782b2d3c45c177183f4e1d4aa1350cc"
VIBRATE_MENU = "12170f4779341d1d2f770e83d0c6ffec6a8b1d06da20257c4c32861332033b22"
RING_ONLY = "ee4270fc9f3eca53b8a36f5f35ae8936e43830c92ff710bf6b7eea513310d2d7"
VIBRATE_ONLY = "15d2c67532b90e217fec029ef8e521e9e85b12c8b6f8fca654473fb8c2b8e3d3"


class SavedSettingsChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def expect(self, expected):
        return self.handset.wait_screen(expected, max_steps=20000000)

    def open_setup(self, item):
        handset = self.handset
        handset.press("soft_left")
        for _ in range(6):
            handset.press("down")
        handset.press("soft_left")
        self.expect(SETUP[self.model])
        for _ in range(item + (1 if self.model == "9575" else 0)):
            handset.press("down")

    def setting_round_trip(self, parent, original, changed, change="up", restore="down"):
        handset = self.handset
        self.expect(parent)
        handset.press("soft_left")
        self.expect(original)
        handset.press(change)
        handset.press("soft_left")
        # Persistent writes may finish after the first changed-value redraw.
        self.expect(parent)
        handset.press("soft_left")
        self.expect(changed)
        handset.press(restore)
        handset.press("soft_right")
        self.expect(parent)
        handset.press("soft_left")
        self.expect(changed)
        handset.press(restore)
        handset.press("soft_left")
        self.expect(parent)
        handset.press("soft_left")
        self.expect(original)
        handset.press("soft_right")
        self.expect(parent)

    def test_ringer_and_speaker_volume_save_cancel_and_restore(self):
        handset = self.handset
        self.open_setup(1)
        handset.press("soft_left")
        self.setting_round_trip(VOLUME_MENU, RINGER_DEFAULT, RINGER_LOUDER)
        handset.press("down")
        self.setting_round_trip(SPEAKER_MENU, SPEAKER_DEFAULT, SPEAKER_LOUDER)
        handset.press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

    def test_backlight_and_contrast_save_cancel_and_restore(self):
        handset = self.handset
        self.open_setup(4)
        self.setting_round_trip(BACKLIGHT_MENU[self.model], BACKLIGHT_FIVE_SECONDS, BACKLIGHT_TEN_SECONDS,
                                change="down", restore="up")
        handset.press("down")
        self.setting_round_trip(CONTRAST_MENU[self.model], CONTRAST_DEFAULT, CONTRAST_HIGHER)
        handset.press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

    def test_time_zone_clock_and_date_formats_save_cancel_and_restore(self):
        handset = self.handset
        self.open_setup(2)
        handset.press("soft_left")
        self.setting_round_trip(TIME_ZONE_MENU, TIME_ZONE_UTC, TIME_ZONE_PLUS_HALF,
                                change="down", restore="up")
        handset.press("down")
        self.setting_round_trip(TIME_FORMAT_MENU, TIME_TWENTY_FOUR_HOURS, TIME_AM_PM,
                                change="down", restore="up")
        handset.press("down")
        self.setting_round_trip(DATE_FORMAT_MENU, DATE_DEFAULT, DATE_SLASHES,
                                change="down", restore="up")
        handset.press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

    def test_ring_alert_keypad_network_and_vibrate_choices_save_cancel_and_restore(self):
        handset = self.handset
        self.open_setup(1)
        handset.press("soft_left")
        handset.press("down")
        handset.press("down")
        for index, (parent, original, changed) in enumerate((
                (RING_TONE_MENU, TONE_ONE, TONE_TWO),
                (ALERT_TONE_MENU, TONE_ONE, TONE_TWO),
                (KEYPAD_TONE_MENU, KEYPAD_SINGLE_TONE, KEYPAD_NO_TONE),
                (NETWORK_TONE_MENU, NETWORK_NO_TONE, NETWORK_TONE),
                (VIBRATE_MENU, RING_ONLY, VIBRATE_ONLY))):
            if index:
                handset.press("down")
            self.setting_round_trip(parent, original, changed, change="down", restore="up")
        handset.press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 settings E2E tests")
class Settings9555E2ETests(SavedSettingsChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 settings E2E tests")
class Settings9575E2ETests(SavedSettingsChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
