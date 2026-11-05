"""Local Extreme emergency configuration through original HTTP/LCD widgets."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_extreme_settings_e2e import (
    EMERGENCY_ACTION_MENU, EMERGENCY_MENU, LOCATION_OPTIONS,
    MESSAGE_AND_CALL, SETUP, DELETE_RECIPIENT, EMPTY_RECIPIENTS,
    MESSAGE_RECIPIENT_MENU, RECIPIENT_OPTIONS, SELECT_RECIPIENT, NUMBER_EMPTY,
)
from test_factory_location_config_e2e import DELETE_ALL_RECIPIENTS, SELECT_RECIPIENT_WITH_ADG
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED
from test_factory_phonebook_details_e2e import DELETE_ADG
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_text_entry_e2e import SYMBOL_PICKER, SYMBOL_SECOND_ROW


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
CALL_ONLY = "18d77ee4dac8fd88f704ba4493dcee7d2d8dd03b4d53e272165a635aa646a505"
RESTORE_MESSAGE_AND_CALL_DRAFT = "957a0eb72efbc3ef5e2c4b3e7759206c0419d2ac1bd56e7ec5efc7921b08ae0c"
CALL_RECIPIENT_MENU = "0ff61d67f3fafd1809e654499adf2fa2eab2ce9a35a5edcbd375c3a86eb0bc6b"
CALL_RECIPIENT_EMPTY = "1f0a226ee4e30d325287991992abb489f72e772b5ac5d53c95f2d52d6797fdac"
CALL_RECIPIENT_12345 = "4b9a3ac84daee176d49d7b28ecd7b6482e064b8aaf47e7e099332bf7359f54f9"
CALL_RECIPIENT_1234_DRAFT = "ca32df617a29d1c9afeed9ce999fce32c8b02180f8c5f90c17d5d0246a8307fe"
EMAIL_EMPTY = "53dd4523ff87d036f5c7e31f9423621697a946e5725f6b4063cda576db3a1763"
EMAIL_A_SAVED = "b43451c6b137afe85e645ec9bfd3a627e5c036b767ca5cf93aae01e04ef12e94"
EMAIL_A_EDIT = "44917a404a2bb61ca0a44514a28d15db98499f9f5a896ca7b52a2c972a96d539"
EMAIL_A_DRAFT_WITHOUT_C = "d631be23e377efb0224dd17a82bf947fde5cf2d5fee4b64d16e433475adb99c4"
SELECT_EMAIL = "119312a7a07e026d257dacf876b454afaf172a92eba0324c344015465d21ec2b"
EMAIL_B_SAVED = "5eabf68fe23276af3ba7a48c378463f181c99d5b735c82f99a5c7feac57ddeec"
COPIED_EMERGENCY_RECIPIENT_123 = "c52061dbe850bef1e0e6140b4564c29ab7a7fe69d9e2c5a8c9af23b779b8c31c"
TWO_RECIPIENTS_SECOND_SELECTED = "3de223b773ad3bf638e40776cf0cf98e719d40239ef2e1967fb69df47c0ce80b"
THREE_RECIPIENTS_LAST_SELECTED = "5c23dd2ff1839c9fc778d15af6d7f54cc8eecbef26ce2135225aed033db3dfe7"
THREE_RECIPIENTS_REOPENED = "52dda445fdff9176a344c3c810d5c116a980b9dbbf6ce536197c37f77de438d4"
RECIPIENT_789 = "1d1d3cff7d48f4950835c3b6e7d2e312dec3f929777c06e80b815d4c505444db"
RECIPIENT_7899_DRAFT = "4cf05ab5d8c6a33e1a39c7edef39f7ac952bea0dd9b05a240f6f014351db244d"
THIRD_RECIPIENT_REPLACED = "6cb5f28920977169c47a9d0c122f120fab4f85db184ae94de28c6377c3cc6746"
MIDDLE_DELETED_COMPACTED_TWO = "0dc04030d9ad86ca5823fff6e5714888b677c8f03ffb38300a5654d9072a4029"
FREED_SLOT_REUSED_THREE = "257ba4769cc9c2ad71ff0476a58dc0efbddad669e6c4119b9ec3a24d8f4332bb"
EMAIL_ZERO_AVAILABLE = "f750d9df1c099ecb438d7ae729f609813369db12b466a787b4bc650048af60d5"
EMAIL_ONE_AVAILABLE = "f74c3b4a662182b0164aade878c59bc4af7e028df98491f59cc681d20a2c7586"
EMAIL_FULL_INPUT = "8d900e1a2b17d4248c5b619949e1e2815f0d103f1af4daa2df097d7287adab10"
EMAIL_ONE_SPACE_FREED = "46937148e831f55a7554b9b64defab3fc2f3c5d3b78eb705b47277f3061baccc"
LONG_EMAIL_RECIPIENT_SAVED = "bdbfbc8ffd46e3c86b5b3306366c7a71f55742a152a520341270d44f6d2994d3"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory emergency configuration E2E")
class Factory9575EmergencyConfigurationE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def press(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, screen):
        return self.handset.wait_screen(screen, max_steps=30000000)

    def open_emergency(self, item):
        self.press("soft_left", *(["down"] * 6), "soft_left")
        self.expect(SETUP)
        self.press("soft_left")
        self.expect(LOCATION_OPTIONS)
        self.press("down", "down", "soft_left")
        self.expect(EMERGENCY_MENU)
        self.press(*(["down"] * item))

    def finish_home(self):
        self.press("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                         max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def open_email(self):
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        self.press("down", "soft_left")

    def type_email(self, first):
        # Repeated-key intervals use guest instructions, not calibrated time.
        for key in ("2" if first == "a" else "22") + "11221222":
            self.handset.press(key, settle_steps=500000)

    def open_message_number(self):
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        self.press("soft_left")

    def save_message_number(self, number):
        self.open_message_number()
        self.expect(NUMBER_EMPTY)
        self.press(*number, "soft_left")

    def reopen_message_recipients(self):
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.press("soft_left")

    def expect_email_counter(self, screen):
        return self.handset.wait_screen(screen, first=0, last=14, max_steps=30000000)

    def type_length_boundary_email(self, local_digits):
        # 0x92780 supplies 75 units to the original editor. Its counter reserves
        # the NUL: 60 ones + @ + eleven twos + .a fills all 74 character places.
        self.press("#", "#")
        for _ in range(local_digits):
            self.handset.press("1", settle_steps=500000)
        self.press("*")
        self.expect(SYMBOL_PICKER)
        self.press("down")
        self.expect(SYMBOL_SECOND_ROW)
        self.press("soft_left")  # @; numeric mode is retained after insertion.
        for _ in range(11):
            self.handset.press("2", settle_steps=500000)
        self.press("*")
        self.expect(SYMBOL_PICKER)
        self.press("soft_left", "#", "#", "2")  # . then lower-case a.

    def expect_email_suffix(self, text):
        font = OriginalASCII1(self.handset.session.firmware["bc5"])
        _, width = font.render(text, 128)
        expected, _ = font.render(text, width)
        # The original single-line editor scrolls horizontally. Its glyph row
        # starts at y32; search its visible suffix without the caret or border.
        for elapsed in range(0, 30000001, 200000):
            state = self.handset.assert_healthy()
            pixels = state["lcd"]["pixels"]
            for left in range(4, 125 - width):
                actual = bytes(pixels[(32 + y) * 128 + left + x]
                               for y in range(15) for x in range(width))
                if actual == expected:
                    return state
            if elapsed < 30000000:
                self.handset.step(200000)
        self.handset.save_artifacts("long-email-suffix-timeout", state)
        self.fail(f"Original email editor must show saved suffix {text!r}")

    def test_call_only_action_save_reopen_visible_cancel_and_restore_message_and_call(self):
        self.open_emergency(1)
        self.expect(EMERGENCY_ACTION_MENU)
        self.press("soft_left")
        self.expect(MESSAGE_AND_CALL)
        self.press("down", "down", "soft_left")
        self.expect(EMERGENCY_ACTION_MENU)
        self.press("soft_left")
        self.expect(CALL_ONLY)
        self.handset.save_artifacts("call-only-action-saved")
        self.press("up", "up")
        self.expect(RESTORE_MESSAGE_AND_CALL_DRAFT)
        self.press("soft_right")
        self.expect(EMERGENCY_ACTION_MENU)
        self.press("soft_left")
        self.expect(CALL_ONLY)
        self.press("up", "up", "soft_left")
        self.expect(EMERGENCY_ACTION_MENU)
        self.press("soft_left")
        self.expect(MESSAGE_AND_CALL)
        self.handset.save_artifacts("message-and-call-action-restored")
        self.finish_home()

    def test_call_recipient_save_reopen_cancel_edit_clear_and_restore_empty(self):
        self.open_emergency(4)
        self.expect(CALL_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(CALL_RECIPIENT_EMPTY)
        self.press(*"12345")
        self.expect(CALL_RECIPIENT_12345)
        self.press("soft_left")
        self.expect(CALL_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(CALL_RECIPIENT_12345)
        self.handset.save_artifacts("call-recipient-saved-and-reopened")
        self.press("soft_right")
        self.expect(CALL_RECIPIENT_1234_DRAFT)
        self.press("red")
        self.expect(CALL_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(CALL_RECIPIENT_12345)
        self.press(*(["soft_right"] * 5))
        self.expect(CALL_RECIPIENT_EMPTY)
        self.press("soft_left")
        self.expect(CALL_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(CALL_RECIPIENT_EMPTY)
        self.handset.save_artifacts("call-recipient-empty-restored")
        self.press("red")
        self.expect(CALL_RECIPIENT_MENU)
        self.finish_home()

    def test_message_email_recipient_empty_save_edit_cancel_replace_and_delete_restore(self):
        self.open_emergency(3)
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        self.open_email()
        self.expect(EMAIL_EMPTY)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)  # Empty input adds no recipient.
        self.open_email()
        self.expect(EMAIL_EMPTY)
        self.type_email("a")
        self.press("soft_left")
        self.expect(EMAIL_A_SAVED)  # Inspected original LCD: a@b.c.
        self.handset.save_artifacts("email-recipient-a-saved")
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(EMAIL_A_SAVED)

        self.open_email()
        self.expect(EMAIL_A_EDIT)
        self.press("soft_right")
        self.expect(EMAIL_A_DRAFT_WITHOUT_C)
        self.press("red")
        self.expect(SELECT_EMAIL)
        self.press("soft_right")
        self.expect(EMAIL_A_SAVED)
        self.open_email()
        self.expect(EMAIL_A_EDIT)
        self.press(*(["soft_right"] * 5))
        self.expect(EMAIL_EMPTY)
        self.type_email("b")
        self.press("soft_left")
        self.expect(EMAIL_B_SAVED)  # Replacement: b@b.c.
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(EMAIL_B_SAVED)
        self.handset.save_artifacts("email-recipient-b-replaced-and-reopened")

        for confirm in ("soft_right", "soft_left"):
            with self.subTest(confirm=confirm):
                self.press("soft_left", "down", "soft_left")
                self.expect(DELETE_RECIPIENT)
                self.press(confirm)
                self.expect(EMAIL_B_SAVED if confirm == "soft_right" else EMPTY_RECIPIENTS)
        self.handset.save_artifacts("email-recipient-empty-restored")
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.finish_home()

    def test_message_recipient_copies_phonebook_number_and_retains_it_after_contact_deletion(self):
        self.press("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.press("soft_left", "soft_left", "2", "3", "4", "down",
                   "1", "2", "3", "soft_left")
        self.expect(ENTRY_ADDED)
        self.press("soft_right")
        self.expect(ADG_SELECTED)
        self.finish_home()

        self.open_emergency(3)
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT_WITH_ADG)
        self.press("down", "down", "soft_left")
        self.expect(COPIED_EMERGENCY_RECIPIENT_123)
        self.handset.save_artifacts("emergency-recipient-copied-from-real-contact")
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.press("soft_left")
        self.expect(COPIED_EMERGENCY_RECIPIENT_123)
        self.finish_home()

        self.press("soft_left", "soft_left")
        self.expect(ADG_SELECTED)
        self.press("soft_left", "down", "down", "down", "soft_left")
        self.expect(DELETE_ADG)
        self.press("soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.handset.save_artifacts("emergency-source-contact-deleted")
        self.finish_home()

        self.open_emergency(3)
        self.press("soft_left")
        self.expect(COPIED_EMERGENCY_RECIPIENT_123)
        self.handset.save_artifacts("emergency-copied-recipient-retained-after-source-deletion")
        for confirm in ("soft_right", "soft_left"):
            with self.subTest(confirm=confirm):
                self.press("soft_left", "down", "soft_left")
                self.expect(DELETE_RECIPIENT)
                self.press(confirm)
                self.expect(COPIED_EMERGENCY_RECIPIENT_123 if confirm == "soft_right"
                            else EMPTY_RECIPIENTS)
        self.handset.save_artifacts("emergency-recipient-empty-restored")
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.finish_home()

    def test_three_message_recipients_replace_last_delete_middle_and_reuse_freed_slot(self):
        self.open_emergency(3)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        self.save_message_number("123")
        self.expect(COPIED_EMERGENCY_RECIPIENT_123)
        self.press("down")
        self.save_message_number("456")
        self.expect(TWO_RECIPIENTS_SECOND_SELECTED)
        self.press("down", "down")
        self.save_message_number("789")
        self.expect(THREE_RECIPIENTS_LAST_SELECTED)
        self.reopen_message_recipients()
        self.expect(THREE_RECIPIENTS_REOPENED)
        self.handset.save_artifacts("three-emergency-recipients-saved-and-reopened")
        self.press("down", "down")
        self.expect(THREE_RECIPIENTS_LAST_SELECTED)
        self.press("down")
        self.expect(THREE_RECIPIENTS_LAST_SELECTED)  # No fourth row is exposed.

        self.open_message_number()
        self.expect(RECIPIENT_789)
        self.press("9")
        self.expect(RECIPIENT_7899_DRAFT)
        self.press("red")
        self.expect(SELECT_RECIPIENT)
        self.press("soft_right")
        self.expect(THREE_RECIPIENTS_LAST_SELECTED)
        self.open_message_number()
        self.expect(RECIPIENT_789)
        self.press(*(["soft_right"] * 3))
        self.expect(NUMBER_EMPTY)
        self.press(*"999", "soft_left")
        self.reopen_message_recipients()
        self.expect(THIRD_RECIPIENT_REPLACED)

        self.press("down", "soft_left", "down", "soft_left")
        self.expect(DELETE_RECIPIENT)
        self.press("soft_right")
        self.reopen_message_recipients()
        self.expect(THIRD_RECIPIENT_REPLACED)
        self.press("down", "soft_left", "down", "soft_left")
        self.expect(DELETE_RECIPIENT)
        self.press("soft_left")
        self.reopen_message_recipients()
        self.expect(MIDDLE_DELETED_COMPACTED_TWO)
        self.handset.save_artifacts("middle-recipient-deleted-and-list-compacted")
        self.press("down", "down")
        self.save_message_number("456")
        self.reopen_message_recipients()
        self.expect(FREED_SLOT_REUSED_THREE)
        self.handset.save_artifacts("freed-emergency-recipient-slot-reused")

        for confirm in ("soft_right", "soft_left"):
            with self.subTest(confirm=confirm):
                self.press("soft_left", "down", "down", "soft_left")
                self.expect(DELETE_ALL_RECIPIENTS)
                self.press(confirm)
                self.expect(FREED_SLOT_REUSED_THREE if confirm == "soft_right"
                            else EMPTY_RECIPIENTS)
        self.handset.save_artifacts("all-three-emergency-recipient-slots-empty-restored")
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.finish_home()

    def test_email_input_limit_accepts_seventy_four_rejects_extra_and_reuses_freed_character(self):
        self.open_emergency(3)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        self.open_email()
        self.expect(EMAIL_EMPTY)
        self.type_length_boundary_email(60)
        self.expect_email_counter(EMAIL_ZERO_AVAILABLE)
        self.expect(EMAIL_FULL_INPUT)
        self.handset.save_artifacts("email-input-seventy-four-characters")
        self.press("3")
        self.expect_email_counter(EMAIL_ZERO_AVAILABLE)
        self.expect(EMAIL_FULL_INPUT)
        self.handset.save_artifacts("email-seventy-fifth-character-not-added")
        self.press("soft_right")
        self.expect_email_counter(EMAIL_ONE_AVAILABLE)
        self.expect(EMAIL_ONE_SPACE_FREED)
        self.press("2")
        self.expect_email_counter(EMAIL_ZERO_AVAILABLE)
        self.expect(EMAIL_FULL_INPUT)
        self.press("red")
        self.expect(SELECT_EMAIL)
        self.press("soft_right")
        self.expect(EMPTY_RECIPIENTS)
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.finish_home()

    def test_maximum_length_email_save_and_reopen_preserves_all_seventy_four_characters(self):
        self.open_emergency(3)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        self.open_email()
        self.expect(EMAIL_EMPTY)
        self.type_length_boundary_email(59)
        self.expect_email_counter(EMAIL_ONE_AVAILABLE)
        self.press("soft_left")
        self.expect(LONG_EMAIL_RECIPIENT_SAVED)
        self.reopen_message_recipients()
        self.expect(LONG_EMAIL_RECIPIENT_SAVED)
        self.open_email()
        self.expect_email_counter(EMAIL_ONE_AVAILABLE)
        self.expect_email_suffix("@" + "2" * 11 + ".a")
        self.handset.save_artifacts("seventy-three-character-email-saved-and-reopened")

        self.press("3")  # Append d: the valid address now fills all 74 places.
        self.expect_email_counter(EMAIL_ZERO_AVAILABLE)
        self.press("soft_left")
        self.expect(LONG_EMAIL_RECIPIENT_SAVED)
        self.reopen_message_recipients()
        self.expect(LONG_EMAIL_RECIPIENT_SAVED)
        self.open_email()
        # Original 0xE6A76 rejects an exact-fit prefill. Keep this functional
        # assertion enabled: a saved address must reopen intact and editable.
        state = self.handset.state()
        self.handset.save_artifacts("seventy-four-character-email-reopen", state)
        self.expect_email_counter(EMAIL_ZERO_AVAILABLE)
        self.expect_email_suffix("@" + "2" * 11 + ".ad")
        self.press("red")
        self.expect(SELECT_EMAIL)
        self.press("soft_right")
        self.expect(LONG_EMAIL_RECIPIENT_SAVED)
        self.press("soft_left", "down", "soft_left")
        self.expect(DELETE_RECIPIENT)
        self.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        self.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.finish_home()


if __name__ == "__main__":
    unittest.main()
