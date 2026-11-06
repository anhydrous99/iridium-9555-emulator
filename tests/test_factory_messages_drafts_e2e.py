"""Original local-flash draft editing and deletion through HTTP keypad input.

The external SIM remains read-only. GUI drafts use BC5 flash, independently of
the modem CMGW/card contracts. No recipient, transmission or delivery is used.
"""

from hashlib import sha256
import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_editor_e2e import MessagesEditorChecks, OPTIONS
from test_factory_messages_local_e2e import MESSAGES, MessagesLocalChecks


class MessagesDraftChecks:
    setUp = MessagesLocalChecks.setUp
    finish = MessagesLocalChecks.finish
    read = MessagesLocalChecks.read
    record = MessagesLocalChecks.record
    press = MessagesLocalChecks.press
    original_home_and_scan = MessagesLocalChecks.original_home_and_scan
    text = MessagesLocalChecks.text
    title = MessagesLocalChecks.title
    menu = MessagesLocalChecks.menu
    open_messages = MessagesLocalChecks.open_messages
    empty_mailbox = MessagesLocalChecks.empty_mailbox
    keys = MessagesEditorChecks.keys
    blank = staticmethod(MessagesEditorChecks.blank)
    field = MessagesEditorChecks.field
    options = MessagesEditorChecks.options
    reopen_messages = MessagesEditorChecks.reopen_messages

    def expect(self, label, predicate, oracle, *, max_steps=4000000):
        for elapsed in range(0, max_steps + 1, 200000):
            state = self.handset.assert_healthy()
            self.peer.check()
            self.assertLess(next(cpu["steps"] for cpu in state["processors"]
                                 if cpu["image"] == "trx"), 300000000)
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < max_steps:
                self.handset.step(200000)
        self.handset.save_artifacts(label + "-timeout", state)
        self.fail(f"Original LCD did not match {label}: {oracle}")

    def editor(self, value, label, *, title="Edit", numeric=False):
        counter = str(1000 - len(value))
        _, width = self.font.render(counter, 128)
        mode, _ = self.font.render("123" if numeric else "abc", 21)

        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, title) and
                    all(pixels[y * 128 + x] == mode[y * 21 + x]
                        for y in range(15) for x in range(1, 20)) and
                    self.text(state, counter, 0, 128 - width, width) and
                    self.field(state, value, 16, vertical=True) and
                    self.blank(state, 32, 110, 4, 126) and
                    all(pixels[y * 128 + x] == 3 for y in range(15, 112) for x in (3, 126)) and
                    all(pixels[y * 128 + x] == 3 for y in (15, 111) for x in range(3, 127)) and
                    self.text(state, "Options", 112, 2, 45) and
                    self.text(state, "Clear", 112, 97, 30))

        return self.expect(label, matches, {"title": title, "complete_text": value,
            "input_mode": "123" if numeric else "abc", "remaining_characters": int(counter),
            "allowed_caret": "exact vertical line after text, on/off", "unused_text_rows_blank": True})

    def numeric_mode(self, value, *, title):
        self.keys("soft_left")
        self.options(0, "numeric-mode-options")
        index = 2 + (self.model == "9575")
        self.keys(*(["down"] * index))
        self.options(index, "visible-enter-digits")
        self.keys("soft_left")
        self.editor(value, "numeric-mode-editor", title=title, numeric=True)

    def save(self, *, title):
        self.keys("soft_left")
        self.options(0, "save-options", numeric=True)
        index = 3 + (self.model == "9575")
        self.keys(*(["down"] * index))
        self.options(index, "visible-save-as-draft", numeric=True)
        self.keys("soft_left")
        # New-message save uses the original bespoke toast at y48. Edit-save
        # uses the standard single-line message layout at y55 instead.
        if title == "New":
            glyphs, width = self.font.render("Saved to drafts", 94)
            self.assertEqual(width, 94)
            body = bytearray(128 * 97)
            for row in range(15):
                start = (48 - 16 + row) * 128 + 17
                body[start:start + width] = glyphs[row * width:(row + 1) * width]
            expected = sha256(body).hexdigest()
        else:
            expected = self.font.message(("Saved to drafts",), divider=False)
        self.expect("saved-local-draft-toast", lambda state: (
            self.handset.screen_hash(state=state) == expected),
            {"literal_message": "Saved to drafts", "glyph_top": 48 if title == "New" else 55})
        self.expect("saved-draft-natural-close-home", lambda state: (
            self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS and state["keys"] == []),
            {"footer": ["Menu", "Help"], "original_delayed_close": True}, max_steps=24000000)

    def create_saved(self):
        self.open_messages()
        self.keys("soft_left")
        self.editor("", "new-empty-editor", title="New")
        self.numeric_mode("", title="New")
        self.keys("1", "2", "3")
        self.editor("123", "complete-new-text", title="New", numeric=True)
        self.save(title="New")

    def drafts(self, value, label):
        return self.expect(label, lambda state: (
            self.title(state, "Drafts") and self.text(state, value, 16, 13, 107, selected=True) and
            self.blank(state, 33, 111) and self.text(state, "Options", 112, 2, 45) and
            self.text(state, "Back", 112, 99, 28)),
            {"title": "Drafts", "complete_preview": value, "only_row_selected": True,
             "unused_rows_blank": True})

    def reopen_draft(self, value):
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "drafts-folder-selected")
        self.keys("soft_left")
        self.drafts(value, "saved-draft-listed")

    def actions(self, selected, label):
        labels = ("Edit", "Delete", "Delete All")
        return self.expect(label, lambda state: (
            self.title(state, "Message") and
            all(self.text(state, item, 16 + 17 * row, selected=row == selected)
                for row, item in enumerate(labels)) and self.blank(state, 67, 111) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Message", "ordered_labels": labels, "focused_index": selected})

    def edit(self, value):
        self.keys("soft_left")
        self.actions(0, "draft-edit-selected")
        self.keys("soft_left")
        self.editor(value, "full-saved-text-reopened")

    def delete_confirmation(self, label):
        expected = self.font.message(("Delete Message?",))
        _, no_width = self.font.render("No", 128)
        return self.expect(label, lambda state: (
            self.title(state, "Message") and self.handset.screen_hash(state=state) == expected and
            self.text(state, "Yes", 112, 2, 22) and
            self.text(state, "No", 112, 127 - no_width, no_width)),
            {"title": "Message", "literal_message": "Delete Message?", "actions": ["Yes", "No"]})

    def test_local_draft_edit_options_back_resave_and_full_text_readback(self):
        self.create_saved()
        self.reopen_draft("123")
        self.edit("123")
        self.numeric_mode("123", title="Edit")
        self.keys("4")
        self.editor("1234", "changed-draft-text", numeric=True)
        self.keys("soft_left")
        self.options(0, "modified-editor-options", numeric=True)
        self.keys("soft_right")
        self.editor("1234", "options-back-keeps-modified-text", numeric=True)
        self.save(title="Edit")
        self.reopen_draft("1234")
        self.edit("1234")

    def test_local_draft_delete_no_preserves_then_yes_removes_last_message(self):
        self.create_saved()
        self.reopen_draft("123")
        self.keys("soft_left", "down")
        self.actions(1, "delete-selected")
        self.keys("soft_left")
        self.delete_confirmation("delete-confirmation-before-no")
        self.keys("soft_right")
        self.actions(1, "delete-no-returns-to-actions")
        self.keys("soft_right")
        self.drafts("123", "delete-no-keeps-draft")
        self.keys("soft_left", "down", "soft_left")
        self.delete_confirmation("delete-confirmation-before-yes")
        self.keys("soft_left")
        deleted = self.font.message(("Message Deleted",), divider=False)
        self.expect("message-deleted-toast", lambda state: (
            self.handset.screen_hash(state=state) == deleted), {"literal_message": "Message Deleted"})
        exhausted = self.font.message(("No more messages",), divider=False)
        self.expect("last-draft-exhausted-toast", lambda state: (
            self.title(state, "Drafts") and self.handset.screen_hash(state=state) == exhausted),
            {"title": "Drafts", "literal_message": "No more messages"}, max_steps=24000000)
        # Original85602/88590 closes the exhausted folder before the toast.
        # Its expiry exposes Messages; re-enter Drafts for actual empty readback.
        self.menu(MESSAGES, 2, "deleted-drafts-folder-selected", max_steps=24000000)
        self.empty_mailbox(2, "Drafts")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 draft E2E")
class Factory9555MessagesDraftsE2ETests(MessagesDraftChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 draft E2E")
class Factory9575MessagesDraftsE2ETests(MessagesDraftChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
