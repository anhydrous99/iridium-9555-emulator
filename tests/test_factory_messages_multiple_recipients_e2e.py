"""Simultaneous local SMS recipients, with complete original list observations.

The synthetic SIM stays read-only. Phone and contact Email selection establish
local editor behavior only; neither Send nor service delivery is exercised.
"""

import os
from pathlib import Path
import unittest

from test_factory_messages_local_e2e import MESSAGES, MessagesLocalChecks as _Local
from test_factory_messages_phonebook_recipient_e2e import (
    CONTEXT, MessagesPhonebookRecipientChecks as _Recipient,
)
from test_factory_messages_contact_numbers_e2e import MessagesContactNumberChecks as _Boot
from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_phonebook_fields_persistence_e2e import SharedExtendedPersistenceChecks as _Fields
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED, ADG_SELECTED


# Literal saved-contact values and distinct manual telephone inputs.
PHONE_RECIPIENTS = ((0, "Adg", "+123"), (0, None, "+456"),
                    (0, None, "+789"), (0, None, "+246"))
CONTACT_CHOICES = ("+123", "", "", "", "a@b.c")


class MessagesMultipleRecipientChecks:
    # Alias helpers only; older test methods are not inherited/discovered.
    setUp = _Recipient.setUp
    finish = _Recipient.finish
    read = _Recipient.read
    press = _Recipient.press
    submit = _Recipient.submit
    text = _Recipient.text
    title = _Recipient.title
    menu = _Recipient.menu
    empty_mailbox = _Recipient.empty_mailbox
    keys = _Recipient.keys
    blank = staticmethod(_Recipient.blank)
    field = _Recipient.field
    editor = _Recipient.editor
    options = _Recipient.options
    number = _Editor.number
    discard = _Recipient.discard
    home = _Recipient.home
    reopen_messages = _Recipient.reopen_messages
    field_pixels = _Recipient.field_pixels
    expect = _Recipient.expect
    chooser = _Recipient.chooser
    expected_counter = _Fields.expected_counter
    assert_field = _Fields.assert_field
    boot_to_home = _Boot.boot_to_home
    wait_for_original_scan_at_home = _Boot.wait_for_original_scan_at_home

    def record(self, label):
        return _Local.record(self, f"{len(self.evidence):03d}-{label}")

    def snapshot(self, label, state=None):
        self.record(label)
        return Path(self.evidence[-1]["artifact"])

    def create_and_read_contact(self):
        # Actual saved fields, created while the original scan timer runs.
        self.keys("soft_left", "soft_left")
        self.handset.wait_screen(EMPTY_PHONEBOOK, max_steps=2000000)
        self.keys("soft_left", "soft_left", "2", "3", "4", "down", "1", "2", "3",
                  "down", "down", "down", "down", "2", "1", "1", "2", "2", "1", "2", "2", "2",
                  "soft_left")
        self.handset.wait_screen(ENTRY_ADDED, max_steps=4000000)
        self.record("contact-name-home-email-saved")
        self.keys("soft_right")
        self.handset.wait_screen(ADG_SELECTED, max_steps=2000000)
        self.keys("soft_left", "down", "down", "soft_left")
        self.assert_field(0, "Adg", "saved-complete-name")
        self.keys("down")
        self.assert_field(1, "+123", "saved-complete-home")
        self.keys("down", "down", "down", "down")
        self.assert_field(5, "a@b.c", "saved-complete-email")
        self.keys("red", "red", "red")
        self.home("saved-contact-readback-home")

    def contact_choices(self, selected, label):
        return self.expect(label, lambda state: (
            self.title(state, "Adg") and
            all(self.text(state, value, 16 + 17 * row, 13, 107, selected=row == selected)
                for row, value in enumerate(CONTACT_CHOICES)) and
            self.blank(state, 101, 111, 13, 120) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Adg", "complete_choices": CONTACT_CHOICES,
             "field_order": ["Home", "Work", "Mobile1", "Mobile2", "Email"],
             "focused_index": selected, "text_rows_only_excludes_field_icons": True})

    def rendered_recipients(self, recipients, selected, label):
        labels = ("New Recipient",) + tuple(name or number for _, name, number in recipients)
        self.assertLessEqual(len(labels), 5, "This case asserts the complete unscrolled list")
        right = "Remove" if selected else "Add"
        _, right_width = self.font.render(right, 128)
        return self.expect(label, lambda state: (
            self.title(state, "Send To") and
            all(self.text(state, value, 16 + 17 * row, selected=row == selected)
                for row, value in enumerate(labels)) and
            self.blank(state, 16 + 17 * len(labels), 111) and
            (self.text(state, "Send", 112, 2, 29) if recipients else
             self.blank(state, 112, 127, 2, 31)) and
            self.text(state, right, 112, 127 - right_width, right_width)),
            {"title": "Send To", "complete_ordered_rows": labels,
             "focused_index": selected, "right_action": right,
             "send_caption_present": bool(recipients), "unused_text_rows_blank": True})

    def original_recipients(self, expected, label):
        # Read-only observation of the actual five-word C20CC/DC7B2 nodes.
        context = self.read("bc5", CONTEXT[self.model])[0]
        self.assertNotEqual(context, 0)
        head = self.read("bc5", context + 0x13)[0]
        pointer, previous, nodes, seen = head, 0, [], set()
        for index, (kind, name, number) in enumerate(expected):
            self.assertNotEqual(pointer, 0)
            self.assertNotIn(pointer, seen)
            seen.add(pointer)
            node = self.read("bc5", pointer, 5)
            self.assertEqual(node[0], kind)
            self.assertEqual(node[3], previous)
            if name is None:
                self.assertEqual(node[1], 0)
                name_words = None
            else:
                self.assertNotEqual(node[1], 0)
                name_words = self.read("bc5", node[1], len(name) + 1)
                self.assertEqual(name_words, [ord(c) for c in name] + [0])
            self.assertNotEqual(node[2], 0)
            number_words = self.read("bc5", node[2], len(number) + 1)
            self.assertEqual(number_words, [ord(c) for c in number] + [0])
            if index + 1 < len(expected):
                self.assertNotEqual(node[4], 0)
            else:
                self.assertEqual(node[4], 0)
            nodes.append({"pointer": pointer, "words": node, "name": name_words,
                          "number": number_words})
            previous, pointer = pointer, node[4]
        self.assertEqual(pointer, 0)
        self.record(label)
        self.evidence[-1]["original_recipient_list"] = {
            "read_only": True, "context_pointer_address": CONTEXT[self.model],
            "context": context, "head": head, "nodes": nodes, "expected": expected,
            "complete_forward_and_back_links": True}

    def check_recipients(self, expected, selected, label):
        self.rendered_recipients(expected, selected, label + "-visible")
        self.original_recipients(expected, label + "-whole-original-list")

    def open_contact_choices(self, label):
        self.keys("soft_right")
        self.chooser(0, label + "-chooser-first")
        index = 2 if self.model == "9575" else 1
        self.keys(*(["down"] * index))
        self.chooser(index, label + "-saved-contact")
        self.keys("soft_left")
        self.contact_choices(0, label + "-home-and-email-choices")

    def test_simultaneous_manual_contact_recipients_email_selection_cancel_and_positional_removal(self):
        self.boot_to_home()
        self.create_and_read_contact()
        self.wait_for_original_scan_at_home()
        self.reopen_messages()
        self.keys("soft_left", "2", "3", "4")
        self.editor("adg", "complete-body-before-recipients")
        self.keys("soft_left")
        self.options(0, "send-options-without-transmission")
        self.keys("soft_left")
        self.check_recipients((), 0, "initial-empty-list")

        # Original mode1 contact selector includes tag0330 at row4. Observe
        # actual local Email eligibility, with no gateway or delivery claim.
        self.open_contact_choices("email")
        self.keys("down", "down", "down", "down")
        self.contact_choices(4, "email-focused")
        self.keys("soft_left")
        self.check_recipients(((1, "Adg", "a@b.c"),), 0, "email-selected-locally")
        self.keys("down", "soft_right")
        self.check_recipients((), 0, "email-removed")

        self.open_contact_choices("home-phone")
        self.keys("soft_left")
        self.check_recipients(PHONE_RECIPIENTS[:1], 0, "local-home-added")
        for index, (_, _, number) in enumerate(PHONE_RECIPIENTS[1:], 2):
            self.keys("soft_right")
            self.chooser(0, f"manual-{index}-chooser")
            self.keys("soft_left")
            self.number("+", f"manual-{index}-initial-plus")
            self.keys(*number[1:])
            self.number(number, f"manual-{index}-complete-number")
            self.submit()
            self.check_recipients(PHONE_RECIPIENTS[:index], 0, f"simultaneous-{index}")

        self.keys("soft_right")
        self.chooser(0, "cancel-chooser-with-four-existing")
        self.keys(*(["down"] * (2 if self.model == "9575" else 1)))
        self.chooser(2 if self.model == "9575" else 1, "cancel-existing-saved-contact-focused")
        self.keys("soft_right")
        self.check_recipients(PHONE_RECIPIENTS, 0, "cancel-keeps-all-four")

        remaining = PHONE_RECIPIENTS
        for name, row, remove_index in (("first", 1, 0), ("middle", 2, 1),
                                        ("last", 2, 1), ("final", 1, 0)):
            # After each original Remove, focus becomes removed row minus one.
            # The next explicit Up returns to row0 without altering the list.
            if name in ("last", "final"):
                self.keys("up")
            self.keys(*(["down"] * row))
            self.check_recipients(remaining, row, name + "-remove-focused")
            self.keys("soft_right")
            remaining = remaining[:remove_index] + remaining[remove_index + 1:]
            self.check_recipients(remaining, row - 1, name + "-removed-preserving-others")

        self.keys("red")
        self.options(0, "recipients-back-to-options", numeric=True)
        self.keys("soft_right")
        self.editor("adg", "complete-body-retained-after-all-list-actions")
        self.discard("unsent-composition-exit", numeric=True)
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "drafts-selected-after-discard")
        self.empty_mailbox(2, "Drafts")
        self.keys("red")
        self.home("restored-home-no-message-sent")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesMultipleRecipientsE2ETests(MessagesMultipleRecipientChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesMultipleRecipientsE2ETests(MessagesMultipleRecipientChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
