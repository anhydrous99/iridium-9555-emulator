"""Original SIM Phonebook -> SMS recipient selection without transmission.

The finite read-only card supplies Adg/+12345. Original code copies the number
into a new composition; the default optional name callback is unset. Exact
recipient/body readback and discard are local assertions, not card writes,
subscriber authentication, sending or delivery. Holds are guest instructions.
"""

import os
import unittest

from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_messages_local_e2e import MESSAGES
from test_factory_messages_phonebook_recipient_e2e import CONTEXT
from test_factory_sim_phonebook_e2e import SIMPhonebookChecks as _SIM


# Independently decoded HT C20F8/C20FC and HL DC7DE/DC7E2.
NAME_CALLBACK = {"9555": 0xF85F, "9575": 0xF88F}


class MessagesSIMRecipientChecks:
    # Alias helpers only, so none of the older cases are rediscovered here.
    start = _SIM.start
    finish = _SIM.finish
    verify_card_unchanged = _SIM.verify_card_unchanged
    read = _SIM.read
    press = _SIM.press
    submit = _SIM.submit
    original_home_and_scan = _SIM.original_home_and_scan
    original_card_consumed = _SIM.original_card_consumed
    open_sim = _SIM.open_sim
    record = _SIM.record
    expect = _SIM.expect
    text = _SIM.text
    title = _SIM.title
    blank = staticmethod(_SIM.blank)
    keys = _Editor.keys
    field = _Editor.field
    editor = _Editor.editor
    options = _Editor.options
    recipients = _Editor.recipients
    discard = _Editor.discard
    home = _Editor.home
    reopen_messages = _Editor.reopen_messages
    menu = _Editor.menu
    empty_mailbox = _Editor.empty_mailbox

    def sim_entry(self, label):
        return self.expect(label, lambda state: (
            self.title(state, "Phonebook") and
            self.text(state, "Adg", 16, width=117, selected=True) and
            self.blank(state, 34, 111) and self.text(state, "Options", 112, 2, 45) and
            self.text(state, "Back", 112, 99, 28)),
            {"title": "Phonebook", "selected_name": "Adg", "logical_index": 101,
             "row_text_width": 117, "selected_row_rect": [0, 15, 118, 33],
             "unused_rows_start": 34, "right_caption": "Back"})

    def sim_actions(self, selected, label):
        labels = ("Call", "SMS", "Copy")
        return self.expect(label, lambda state: (
            self.title(state, "Adg") and
            all(self.text(state, item, 16 + 17 * row, selected=row == selected)
                for row, item in enumerate(labels)) and self.blank(state, 67, 111) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Adg", "ordered_actions": labels, "focused_index": selected})

    def original_recipient(self, *, present, label):
        context = self.read("bc5", CONTEXT[self.model])[0]
        self.assertNotEqual(context, 0)
        head = self.read("bc5", context + 0x13)[0]
        callback = self.read("bc5", NAME_CALLBACK[self.model], 2)
        # Original C20CC/DC7B2 calls a separate name resolver only when this
        # function pointer is nonzero. The factory fixture leaves it unset.
        self.assertEqual(callback, [0, 0])
        observed = {"read_only": True, "context_pointer_address": CONTEXT[self.model],
                    "context": context, "head": head,
                    "name_callback_address": NAME_CALLBACK[self.model], "name_callback": callback}
        if present:
            self.assertNotEqual(head, 0)
            node = self.read("bc5", head, 5)
            self.assertEqual(node[0:2], [0, 0])
            self.assertNotEqual(node[2], 0)
            self.assertEqual(node[3:], [0, 0], "Exactly one original recipient is required")
            number = self.read("bc5", node[2], 7)
            self.assertEqual(number, [ord(char) for char in "+12345"] + [0])
            observed.update({"node": node, "number": number, "name_pointer_is_null": True})
        else:
            self.assertEqual(head, 0)
        self.record(label)
        self.evidence[-1]["recipient_copy"] = observed
        return observed

    def test_direct_sim_sms_copies_exact_number_retains_body_removes_and_discards(self):
        self.start(populated=True)
        self.original_home_and_scan()
        self.original_card_consumed(populated=True)
        self.open_sim()
        self.sim_entry("original-sim-adg-selected")
        self.submit()
        self.sim_actions(0, "original-sim-actions-call-focused")
        self.keys("down")
        self.sim_actions(1, "original-sim-sms-action-focused")
        self.submit()
        self.editor("", "new-empty-composition-from-sim-sms")
        self.original_recipient(present=True, label="direct-sim-number-in-original-list")

        self.keys("2", "3", "4")
        self.editor("adg", "complete-body-count-after-direct-sim-sms")
        self.original_recipient(present=True, label="typing-keeps-direct-sim-recipient")
        self.keys("soft_left")
        self.options(0, "body-options-send-focused-without-transmission")
        self.keys("soft_left")  # Opens Send To; the actual Send key is not used.
        self.recipients("+12345", 0, "direct-sim-number-rendered-without-an-invented-name")
        self.original_recipient(present=True, label="rendered-number-matches-original-node")
        self.keys("down")
        self.recipients("+12345", 1, "direct-sim-number-remove-focused")
        self.keys("soft_right")
        self.recipients(None, 0, "direct-sim-recipient-removed-without-send")
        self.original_recipient(present=False, label="remove-empties-original-recipient-list")

        self.keys("red")
        self.options(0, "recipient-list-back-to-original-options")
        self.keys("soft_right")
        self.editor("adg", "complete-body-retained-after-recipient-removal")
        self.discard("direct-sim-unsent-composition-exit")
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "drafts-focused-after-direct-sim-composition-exit")
        self.empty_mailbox(2, "Drafts")
        self.keys("red")
        self.home("direct-sim-sms-restored-home")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesSIMRecipientE2ETests(MessagesSIMRecipientChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesSIMRecipientE2ETests(MessagesSIMRecipientChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
