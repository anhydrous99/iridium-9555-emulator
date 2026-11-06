"""Local HL25003 location-message limits; no message delivery is asserted.

All screen goldens come from original factory LCD output. The supplied
Extreme manual (printed pages 175-176) and shipped English strings list the
fourteen frequency choices and five Quick GPS recipient slots.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_extreme_settings_e2e import (
    DELETE_RECIPIENT, LOCATION_OPTIONS, NUMBER_EMPTY,
    RECIPIENT_OPTIONS, SELECT_RECIPIENT, SETUP,
)
from test_factory_location_config_e2e import (
    DELETE_ALL_RECIPIENTS, EMPTY_QUICK_GPS_RECIPIENTS, EMPTY_UPDATE_RECIPIENT,
    MESSAGE_OPTIONS, NO_UPDATE, QUICK_GPS_MENU, UPDATE_FREQUENCY, UPDATE_RECIPIENT,
)


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
# Shipped English UI IDs 0x12C1..0x12CE, matching manual pages 175-176.
FREQUENCIES = (
    ("No Update", NO_UPDATE),
    ('Startup Only', 'b03e1d9eab15ab46c4dd088b897cd1bf2061e396db20b852674cf6e2a8612339'),
    ('2 minutes', '4cf08209331da7550a45a6a2fecbca1923f71727b534deb9eed63255c4eee6fd'),
    ('5 minutes', 'c0f503942202e6910a39ce782e0e7f15a10e3e8a69486f56b96b2e9005d54627'),
    ('10 minutes', '8b59b3a5ebc9f78560b65615cb74d8134a614bf42d5fcd2d7cc3ebedeb958352'),
    ('30 minutes', '4eda632b3bcc4adbab8780ba11750b4467e602c71e8f82a7a368696524c3b916'),
    ('1 hour', 'bbaa3d31bb56af97d9b26b7498d625e50dbf42ae77fcf4c1f74c52fa9c5765b3'),
    ('4 hours', 'a4b9886f5f3dc95439d419414f911e6ccdda7572757633497a466fbcd1306816'),
    ('8 hours', 'fa8519098d6f3b56e9de20496e9a6cb9cc474089ababd7d7bb3e430f3dd376ba'),
    ('12 hours', '924f890245a8367522ef258da3c7d2a23ff28c38b628aae6453c0bd10a26a707'),
    ('18 hours', '83d69ec41b68dd0b455ffbbec8de1fbf71db9711e8f8ed4c09ee356e4a975893'),
    ('1 day', '93485ff450c250acdcb0846cde10a94c28bc3d4c51b709ba71a3f80104a23533'),
    ('3 days', 'd0e8db0a720541091b98124709e92c5babd13ae64afa5a2ff7c9192e8f6499a5'),
    ('1 week', '107d3a1f4017e28f01e720ad294d73846a304470cf799e7ce9fc2405f88acea8'),
)

# Visible tentative choice before cancel: Down, except Up at the final choice.
FREQUENCY_DRAFTS = (
    '9aff07d4d3ac04a914d190afb09cb6d70d6ae5c5c87c026ef16873e0aba971a1',
    '62cbf31ec42cf323a1b753395635c251f9e7f619279f59b69a8af9d2cc7b5ecb',
    '63054e40a0fd7b161294fadc127dd79ffd44419ce239f1b07f0d33b31f53b8d1',
    '843ce7a5ae307b49c1f9dea43560336369507d0fb66c9d537cfb91e757b2d3a2',
    '4e4a7154ed11eea9cd33568070dee87178417cb135fff9cf0d8af63f4209a3d1',
    '4daf57dbe6176acf8580f18de854b46ebe3af93e234f56ac0c56198dd02bca9b',
    '755c417c5d7fea27cec7fca4deafc43c2ae5c71c489e5a46e697826bef94b5fa',
    'a6fe0b353d84eba7ce0c94e3bc8aecb3bb2b6b23c4b912b3ce7bf62e5d62eb07',
    '70b88967eee753c6c24bbce44d17e27c1b520a426c003dc71a903c57f8bd2cb6',
    'c95dacce17c747487f5f59960e01438e79bca53efc6a1e17eee6ce2fb6a058c4',
    'a385b76bbff6f88a40754d6d8be1c3c7760dbebd09d6f513ed402e5a74836101',
    'babf4bc3ec63d2db3dd95118426ade023acc748a57620a68d561c6108dfd076e',
    '3fa1da08bb370992fd963f30a8c933c4845b96ceea68e37722d62191904a4915',
    '8752b1246eb4867b5154114eae54b13d0a504e0d9be77b8dce8cab86aa4415b2',
)

QUICK_FILLED = (
    'e4957cd8020933d9900447867fc27c719b5fee268289ca71c3da3a1568fbce0f',
    'f108932353cf645ffd885eb45a92979cf0ff9d8278bf4fc536f516fdd594be12',
    '00726f6e78f4fcc4e1cea4fae1041063d3957fefb2c1efcbaaca6d0bea42836b',
    '79e8ab6ad8188860ad2f26c28b56798f7a299398fa1c2f4942c6593e82323a3e',
    'e984dbed28445626406e8417d81e685e75ecb2c0fe1a027937f219c9fc092779',
)
QUICK_REPLACED = "6e10059cb87be75b63227030f352a46aec5bb8655e57bbc4c9e74537d4b20c4d"
QUICK_SECOND_SELECTED = "94912a902c4f295267d5f00e2467eb7615cc47a80c278d3b8234794f62cf1dca"
QUICK_COMPACTED = "2806d0984304dffd964c65c94f085287fd25888ab6c535ad2bf2dd1e1703ec92"
QUICK_FOUR_LAST = "a89f1b68d55628b7e559b3c66e904b5afb3dd2e5e97e4b25df7569ffb924c90a"
QUICK_RECOVERED_LAST = "7b981be45b92f58c148ca32e165a38b9cb69eedc47af68d9cf752171a93a5b90"
QUICK_RECOVERED_FIRST = "ce0d54ba09c51851bffa1c1f416bc30701961a5930bd0aece942a8305605090c"
QUICK_FIFTH_NUMBER = '2c8c6c6c72a072f8f60003ca073b7bd62b801cfaf44d03499a695c60775ee0bb'

EMAIL_EMPTY = "53dd4523ff87d036f5c7e31f9423621697a946e5725f6b4063cda576db3a1763"
SELECT_EMAIL = "119312a7a07e026d257dacf876b454afaf172a92eba0324c344015465d21ec2b"
# Editor rows omit the active caret; saved-list goldens include every glyph.
EMAIL_PREFIX_AT = "6fe47dc907d0fd4001e5ef9cab3abfb99eecf995753501901c826244c6e8ec1c"
EMAIL_FIELD = "06e48bce6ed8cc22f42da1702ef20bf713a261ad951b0c6758501bddb651b38c"
EMAIL_EDITED_FIELD = "da56d263e41f47f1224ac8011b9af02a59e99e57d08f5e8b71bb5e6ab1925f6b"
EMAIL_SAVED = "7d03940a2a711b0954adda81ab4325507223362fbb5604e7b36557abeced38db"  # adg@adg.adg
EMAIL_EDITED = "971c8badc1f62d6b17df7c17161feeb4074c176651d6fb5c47e1b22d5bb14be6"  # adg@adg.adj


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory location limits E2E")
class Factory9575LocationLimitsE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=30000000)

    def press(self, *keys):
        for key in keys:
            self.handset.press(key)

    def open_messages(self):
        self.press("soft_left", *(["down"] * 6), "soft_left")
        self.expect(SETUP)
        self.press("soft_left")
        self.expect(LOCATION_OPTIONS)
        self.press("down", "down", "down", "soft_left")
        self.expect(MESSAGE_OPTIONS)

    def finish_home(self):
        self.press("red")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def open_email_editor(self):
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left", "down")
        self.expect(SELECT_EMAIL)
        self.press("soft_left")

    def test_email_recipient_blank_save_edit_cancel_readback_and_delete(self):
        self.open_messages()
        self.press("soft_left", "down")
        self.expect(UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(EMPTY_UPDATE_RECIPIENT)
        self.open_email_editor()
        self.expect(EMAIL_EMPTY)
        self.press("soft_left")
        self.expect(EMPTY_UPDATE_RECIPIENT)  # Blank OK adds no recipient.
        self.open_email_editor()
        self.expect(EMAIL_EMPTY)
        self.press("2", "3", "4")
        for _ in range(2):
            self.handset.press("1", settle_steps=500000)
        self.expect(EMAIL_PREFIX_AT, 32, 43)  # adg@
        self.press("2", "3", "4", "1", "2", "3", "4")
        self.expect(EMAIL_FIELD, 32, 43)
        self.press("soft_left")
        self.expect(EMAIL_SAVED)
        self.press("soft_right")
        self.expect(UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(EMAIL_SAVED)
        self.handset.save_artifacts("proper-email-saved-and-reopened")

        self.open_email_editor()
        self.expect(EMAIL_FIELD, 32, 43)
        self.press("soft_right", "5")
        self.expect(EMAIL_EDITED_FIELD, 32, 43)
        self.handset.save_artifacts("tentative-email-adj-before-cancel")
        self.press("red")
        self.expect(SELECT_EMAIL)
        self.press("soft_right")
        self.expect(EMAIL_SAVED)
        self.handset.save_artifacts("cancel-retains-saved-email-adg")

        self.open_email_editor()
        self.expect(EMAIL_FIELD, 32, 43)
        self.press("soft_right", "5")
        self.expect(EMAIL_EDITED_FIELD, 32, 43)
        self.press("soft_left")
        self.expect(EMAIL_EDITED)
        self.press("soft_right")
        self.expect(UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(EMAIL_EDITED)
        self.open_email_editor()
        self.expect(EMAIL_EDITED_FIELD, 32, 43)
        self.press("red")
        self.expect(SELECT_EMAIL)
        self.press("soft_right")
        self.expect(EMAIL_EDITED)
        self.handset.save_artifacts("edited-email-adj-reopened")
        for confirm in ("soft_right", "soft_left"):
            with self.subTest(delete=confirm):
                self.press("soft_left", "down", "soft_left")
                self.expect(DELETE_RECIPIENT)
                self.press(confirm)
                self.expect(EMAIL_EDITED if confirm == "soft_right" else EMPTY_UPDATE_RECIPIENT)
        self.handset.save_artifacts("email-recipient-empty-restored")
        self.finish_home()

    def add_quick_number(self, number):
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        self.press("soft_left")
        self.expect(NUMBER_EMPTY)
        self.press(*number, "soft_left")

    def test_five_quick_gps_slots_bound_navigation_replace_delete_and_recover_capacity(self):
        self.open_messages()
        self.press("down")
        self.expect(QUICK_GPS_MENU)
        self.press("soft_left")
        self.expect(EMPTY_QUICK_GPS_RECIPIENTS)
        numbers = ("12345", "23456", "34567", "45678", "56789")
        for index, number in enumerate(numbers):
            with self.subTest(slot=index + 1):
                if index:
                    self.press("down")
                self.add_quick_number(number)
                self.expect(QUICK_FILLED[index])
        self.handset.save_artifacts("quick-gps-all-five-slots-filled")
        # The manual's five-slot UI has no sixth row or Add action. A delivered
        # Down at the last occupied row must leave all five visible rows intact.
        self.press("down")
        self.expect(QUICK_FILLED[-1])
        self.handset.save_artifacts("quick-gps-no-sixth-row")
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)  # Edit / Delete / Delete All, without Add.
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        self.press("soft_left")
        self.expect(QUICK_FIFTH_NUMBER, 32, 43)
        self.press(*(["soft_right"] * 5), *"67890", "soft_left")
        # Entering a sixth distinct address replaces the selected fifth slot.
        self.expect(QUICK_REPLACED)
        self.handset.save_artifacts("sixth-number-replaces-fifth-slot")
        self.press("up", "up", "up")
        self.expect(QUICK_SECOND_SELECTED)
        for confirm in ("soft_right", "soft_left"):
            with self.subTest(delete=confirm):
                self.press("soft_left", "down", "soft_left")
                self.expect(DELETE_RECIPIENT)
                self.press(confirm)
                self.expect(QUICK_SECOND_SELECTED if confirm == "soft_right" else QUICK_COMPACTED)
        self.handset.save_artifacts("middle-deletion-compacts-and-frees-fifth-slot")
        self.press("down", "down", "down")
        self.expect(QUICK_FOUR_LAST)
        self.add_quick_number("78901")
        self.expect(QUICK_RECOVERED_LAST)
        self.press("soft_right")
        self.expect(QUICK_GPS_MENU)
        self.press("soft_left")
        self.expect(QUICK_RECOVERED_FIRST)
        self.handset.save_artifacts("all-five-recovered-recipients-reopened")
        for confirm in ("soft_right", "soft_left"):
            with self.subTest(delete_all=confirm):
                self.press("soft_left", "down", "down", "soft_left")
                self.expect(DELETE_ALL_RECIPIENTS)
                self.press(confirm)
                self.expect(QUICK_RECOVERED_FIRST if confirm == "soft_right"
                            else EMPTY_QUICK_GPS_RECIPIENTS)
        self.handset.save_artifacts("quick-gps-five-empty-slots-restored")
        self.finish_home()

    def test_all_fourteen_report_frequencies_save_readback_cancel_and_restore(self):
        self.open_messages()
        self.press("soft_left")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(NO_UPDATE)
        for index, (label, digest) in enumerate(FREQUENCIES[1:], start=1):
            with self.subTest(frequency=label):
                self.press("down", "soft_left")
                self.expect(UPDATE_FREQUENCY)
                self.press("soft_left")
                self.expect(digest)
                self.handset.save_artifacts(f"frequency-{index:02d}-saved")
                self.press("up" if index == len(FREQUENCIES) - 1 else "down")
                self.expect(FREQUENCY_DRAFTS[index])
                self.press("soft_right")
                self.expect(UPDATE_FREQUENCY)
                self.press("soft_left")
                self.expect(digest)
        self.press(*(["up"] * (len(FREQUENCIES) - 1)), "soft_left")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(NO_UPDATE)
        self.handset.save_artifacts("no-update-restored")
        self.press("down")
        self.expect(FREQUENCY_DRAFTS[0])
        self.press("soft_right")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(NO_UPDATE)
        self.press("soft_right")
        self.expect(UPDATE_FREQUENCY)
        self.finish_home()


if __name__ == "__main__":
    unittest.main()
