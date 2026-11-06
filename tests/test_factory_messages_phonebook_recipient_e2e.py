"""Select a saved local contact as an SMS recipient without sending a message.

LCD name/content assertions are complemented by read-only original recipient
list observations: the visible contact name must carry its saved +123 number.
No card write, subscriber authentication or service delivery is supplied.
"""

import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_messages_local_e2e import MESSAGES, MessagesLocalChecks as _Local
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED
from test_factory_phonebook_fields_e2e import PhonebookFieldChecks as _Fields


# Independently decoded from each pinned profile's Send To row getter:
# HT84978 / HL87906 load the context, then its +13 recipient-list head.
CONTEXT = {"9555": 0xF78C, "9575": 0xF7A2}


class MessagesPhonebookRecipientChecks:
    setUp = _Local.setUp
    finish = _Local.finish
    read = _Local.read
    press = _Local.press
    submit = _Local.submit
    original_home_and_scan = _Local.original_home_and_scan
    text = _Local.text
    title = _Local.title
    menu = _Local.menu
    empty_mailbox = _Local.empty_mailbox
    keys = _Editor.keys
    blank = staticmethod(_Editor.blank)
    field = _Editor.field
    editor = _Editor.editor
    options = _Editor.options
    recipients = _Editor.recipients
    discard = _Editor.discard
    home = _Editor.home
    reopen_messages = _Editor.reopen_messages
    field_pixels = _Fields.field_pixels

    def record(self, label):
        return _Local.record(self, f"{len(self.evidence):03d}-{label}")

    def expect(self, label, predicate, oracle):
        for elapsed in range(0, 4000001, 200000):
            state = self.handset.assert_healthy()
            self.peer.check()
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < 4000000:
                self.handset.step(200000)
        self.handset.save_artifacts(label + "-timeout", state)
        self.fail(f"Original LCD did not match {label}: {oracle}")

    def create_and_read_contact(self):
        self.keys("soft_left", "soft_left")
        self.handset.wait_screen(EMPTY_PHONEBOOK, max_steps=2000000)
        self.keys("soft_left", "soft_left", "2", "3", "4", "down", "1", "2", "3", "soft_left")
        self.handset.wait_screen(ENTRY_ADDED, max_steps=4000000)
        self.record("local-contact-save-succeeded")
        self.keys("soft_right")
        self.handset.wait_screen(ADG_SELECTED, max_steps=2000000)
        self.keys("soft_left", "down", "down", "soft_left")
        expected = [self.font.render(value, 112)[0][:14 * 112] for value in ("Adg", "+123")]
        self.expect("saved-contact-name-and-home-number", lambda state: all(
            b"".join(row[:112] for row in self.field_pixels(state, index)[:14]) == expected[index]
            for index in range(2)),
            {"saved_name": "Adg", "saved_home_number": "+123", "complete_field_glyphs": True})
        for _ in range(3):
            self.keys("red")
            if self.handset.screen_hash(113, 128) == HOME_CAPTIONS:
                break
        self.home("contact-readback-returned-home")

    def chooser(self, selected, label):
        labels = (("Enter Number...", "Quick GPS List", "Adg") if self.model == "9575" else
                  ("Enter Number...", "Adg"))
        return self.expect(label, lambda state: (
            self.title(state, "Select Recipient") and
            all(self.text(state, item, 16 + 18 * row, width=117, selected=row == selected)
                for row, item in enumerate(labels)) and
            self.blank(state, 16 + 18 * len(labels), 111) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Select Recipient", "ordered_labels": labels, "focused_index": selected,
             "source": "saved local phonebook"})

    def recipient_copy(self, *, present, label):
        context = self.read("bc5", CONTEXT[self.model])[0]
        self.assertNotEqual(context, 0)
        head = self.read("bc5", context + 0x13)[0]
        evidence = {"context_pointer_address": CONTEXT[self.model], "context": context,
                    "head": head, "read_only": True}
        if present:
            self.assertNotEqual(head, 0)
            node = self.read("bc5", head, 5)
            self.assertNotEqual(node[1], 0)
            self.assertNotEqual(node[2], 0)
            self.assertEqual(node[3:], [0, 0], "Expected exactly one original recipient node")
            name = self.read("bc5", node[1], 4)
            number = self.read("bc5", node[2], 5)
            self.assertEqual(name, [ord(char) for char in "Adg"] + [0])
            self.assertEqual(number, [ord(char) for char in "+123"] + [0])
            evidence.update({"node": node, "name": name, "number": number})
        else:
            self.assertEqual(head, 0)
        self.record(label)
        self.evidence[-1]["recipient_copy"] = evidence

    def test_saved_contact_selection_cancel_copy_remove_and_composition_retention(self):
        self.original_home_and_scan()
        self.create_and_read_contact()
        self.reopen_messages()
        self.keys("soft_left", "2", "3", "4")
        self.editor("adg", "composition-before-phonebook-selection")
        self.keys("soft_left")
        self.options(0, "send-selected-without-recipient")
        self.keys("soft_left")
        self.recipients(None, 0, "empty-send-to-before-contact")
        self.recipient_copy(present=False, label="empty-original-recipient-list")
        self.keys("soft_right")
        self.chooser(0, "chooser-includes-saved-contact")
        contact_index = 2 if self.model == "9575" else 1
        self.keys(*(["down"] * contact_index))
        self.chooser(contact_index, "saved-contact-visible-before-cancel")
        self.keys("soft_right")
        self.recipients(None, 0, "contact-chooser-back-adds-no-recipient")
        self.recipient_copy(present=False, label="cancel-keeps-original-list-empty")
        self.keys("soft_right")
        self.chooser(0, "contact-chooser-reopened")
        self.keys(*(["down"] * contact_index))
        self.chooser(contact_index, "saved-contact-selected")
        self.submit()
        self.recipients("Adg", 0, "contact-name-added-without-send")
        self.recipient_copy(present=True, label="contact-name-carries-saved-number")
        self.keys("down")
        self.recipients("Adg", 1, "copied-contact-remove-selected")
        self.keys("soft_right")
        self.recipients(None, 0, "copied-contact-removed-without-send")
        self.recipient_copy(present=False, label="removed-contact-leaves-no-recipient")
        self.keys("red")
        self.options(0, "recipient-list-cancelled-to-options")
        self.keys("soft_right")
        self.editor("adg", "composition-preserved-after-phonebook-recipient")
        self.discard("exit-composition-after-contact-selection")
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "drafts-after-unsent-composition-exit")
        self.empty_mailbox(2, "Drafts")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesPhonebookRecipientE2ETests(MessagesPhonebookRecipientChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesPhonebookRecipientE2ETests(MessagesPhonebookRecipientChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
