"""Select saved Work/Mobile1/Mobile2 SMS recipients without sending.

All four phone fields are independently reread before their original number
chooser is used. The copied name/number and complete one-node recipient list
are read-only observations. No card update, RF or delivery is established.
"""

from pathlib import Path
import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_local_e2e import (
    ALERTS, CAPACITY, MESSAGES, SCAN_READY, MessagesLocalChecks as _Local,
)
from test_factory_messages_phonebook_recipient_e2e import (
    CONTEXT, MessagesPhonebookRecipientChecks as _Recipient,
)
from test_factory_phonebook_fields_persistence_e2e import SharedExtendedPersistenceChecks as _Fields
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED


PHONES = ("+123", "+456", "+789", "+246")


class MessagesContactNumberChecks:
    # Alias helpers only: no older test methods are inherited/discovered.
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
    recipients = _Recipient.recipients
    discard = _Recipient.discard
    home = _Recipient.home
    reopen_messages = _Recipient.reopen_messages
    field_pixels = _Recipient.field_pixels
    expect = _Recipient.expect
    chooser = _Recipient.chooser
    expected_counter = _Fields.expected_counter
    assert_field = _Fields.assert_field

    def record(self, label):
        return _Local.record(self, f"{len(self.evidence):03d}-{label}")

    def snapshot(self, label, state=None):
        # The short-field oracle does no CPU stepping between its match and
        # this observation. Keep the same evidence/provenance schema throughout.
        self.record(label)
        return Path(self.evidence[-1]["artifact"])

    def boot_to_home(self):
        # Same recognized original startup as the established Messages helper.
        # Contact work uses the otherwise-idle initial scan-retry interval;
        # every processor continues to execute normally throughout.
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        self.startup_seen = set()
        for _ in range(125):
            state = self.handset.state()
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, self.startup_seen, "Repeated startup modal")
                self.startup_seen.add(body)
                self.record("startup-" + ALERTS[body])
                self.press("soft_right")
            elif self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.record("home-before-saved-contact")
                return
            else:
                self.handset.step(1000000)
                self.peer.check()
        self.handset.save_artifacts("startup-timeout")
        self.fail("Original modem startup did not reach recognized Home")

    def wait_for_original_scan_at_home(self):
        while self.read("bc5", SCAN_READY[self.model]) != [1]:
            state = self.handset.assert_healthy()
            trx = next(cpu for cpu in state["processors"] if cpu["image"] == "trx")
            self.assertLess(trx["steps"], 240000000, "Original initial scan did not complete")
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, self.startup_seen, "Repeated startup modal during scan")
                self.startup_seen.add(body)
                self.record("startup-" + ALERTS[body])
                self.press("soft_right")
            else:
                self.assertEqual(self.handset.screen_hash(113, 128, state), HOME_CAPTIONS)
                self.handset.step(2000000)
                self.peer.check()
        self.assertEqual(self.read("bc5", CAPACITY[self.model]), [2])
        self.assertEqual(self.read("trx", 0x400AA2D6), [2])
        self.assertEqual(self.read("trx", 0x400AA2D3), [3])
        self.assertEqual(self.read("trx", 0x400AA30C, 4), [0, 0, 0, 1])
        self.record("original-scan-ready-after-contact-readback")

    def create_and_read_four_numbers(self):
        self.keys("soft_left", "soft_left")
        self.handset.wait_screen(EMPTY_PHONEBOOK, max_steps=2000000)
        self.keys("soft_left", "soft_left", "2", "3", "4")
        for number in PHONES:
            self.keys("down", *number[1:])
        self.keys("soft_left")
        self.handset.wait_screen(ENTRY_ADDED, max_steps=4000000)
        self.record("four-distinct-phone-fields-save-succeeded")
        self.keys("soft_right")
        self.handset.wait_screen(ADG_SELECTED, max_steps=2000000)
        self.keys("soft_left", "down", "down", "soft_left")
        for field, value in enumerate(("Adg", *PHONES)):
            if field:
                self.keys("down")
            self.assert_field(field, value, f"saved-field-{field}-complete-value-count-focus")
        self.keys("red", "red", "red")
        self.home("saved-fields-readback-returned-home")

    def number_choices(self, selected, label):
        return self.expect(label, lambda state: (
            self.title(state, "Adg") and
            all(self.text(state, value, 16 + 17 * row, 13, 107, selected=row == selected)
                for row, value in enumerate(PHONES)) and
            self.blank(state, 84, 111, 13, 120) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Adg", "complete_phone_choices": PHONES,
             "phone_field_order": ["Home", "Work", "Mobile1", "Mobile2"],
             "focused_index": selected, "unused_text_rows_blank": True})

    def original_recipient(self, number, label):
        context = self.read("bc5", CONTEXT[self.model])[0]
        self.assertNotEqual(context, 0)
        head = self.read("bc5", context + 0x13)[0]
        observed = {"context_pointer_address": CONTEXT[self.model], "context": context,
                    "head": head, "read_only": True}
        if number is None:
            self.assertEqual(head, 0)
        else:
            self.assertNotEqual(head, 0)
            node = self.read("bc5", head, 5)
            self.assertIn(node[0], (0, 1))  # C20CC normalizes its input kind2.
            self.assertNotEqual(node[1], 0)
            self.assertNotEqual(node[2], 0)
            self.assertEqual(node[3:], [0, 0], "Exactly one original recipient is required")
            name = self.read("bc5", node[1], 4)
            value = self.read("bc5", node[2], len(number) + 1)
            self.assertEqual(name, [ord(c) for c in "Adg"] + [0])
            self.assertEqual(value, [ord(c) for c in number] + [0])
            observed.update({"node": node, "name": name, "number": value})
        self.record(label)
        self.evidence[-1]["recipient_copy"] = observed

    def open_contact_numbers(self, label):
        self.keys("soft_right")
        self.chooser(0, label + "-outer-first-row")
        index = 2 if self.model == "9575" else 1
        self.keys(*(["down"] * index))
        self.chooser(index, label + "-saved-contact-focused")
        self.keys("soft_left")
        self.number_choices(0, label + "-four-saved-phone-choices")

    def test_multi_number_chooser_back_then_work_mobile1_mobile2_copy_remove_and_discard(self):
        self.boot_to_home()
        self.create_and_read_four_numbers()
        self.wait_for_original_scan_at_home()
        self.reopen_messages()
        self.keys("soft_left", "2", "3", "4")
        self.editor("adg", "complete-composition-before-multiple-phone-choices")
        self.keys("soft_left")
        self.options(0, "send-options-without-transmission")
        self.keys("soft_left")
        self.recipients(None, 0, "empty-send-to-before-number-selection")
        self.original_recipient(None, "original-list-empty-before-number-selection")

        self.open_contact_numbers("cancel-number-choice")
        self.keys("down", "down", "down")
        self.number_choices(3, "mobile2-tentative-before-back")
        self.keys("soft_right")
        self.chooser(2 if self.model == "9575" else 1, "number-back-returns-to-contact-chooser")
        self.keys("soft_right")
        self.recipients(None, 0, "number-and-contact-back-add-no-recipient")
        self.original_recipient(None, "cancel-keeps-original-list-empty")

        for index, field in enumerate(("Work", "Mobile1", "Mobile2"), 1):
            self.open_contact_numbers(field)
            self.keys(*(["down"] * index))
            self.number_choices(index, field + "-saved-number-focused")
            self.keys("soft_left")
            self.recipients("Adg", 0, field + "-recipient-name-visible")
            self.original_recipient(PHONES[index], field + "-exact-selected-number-copied")
            self.keys("down")
            self.recipients("Adg", 1, field + "-remove-focused")
            self.keys("soft_right")
            self.recipients(None, 0, field + "-removed-without-send")
            self.original_recipient(None, field + "-original-list-empty-after-remove")

        self.keys("red")
        self.options(0, "number-list-cancelled-to-options")
        self.keys("soft_right")
        self.editor("adg", "complete-composition-retained-after-all-number-choices")
        self.discard("unsent-number-selection-composition-exit")
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "drafts-focused-after-unsaved-exit")
        self.empty_mailbox(2, "Drafts")
        self.keys("red")
        self.home("restored-home-without-sending")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesContactNumbersE2ETests(MessagesContactNumberChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesContactNumbersE2ETests(MessagesContactNumberChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
