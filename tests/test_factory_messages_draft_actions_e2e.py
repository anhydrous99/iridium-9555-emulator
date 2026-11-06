"""Original Red autosave and Delete All for local BC5-flash SMS drafts.

The external synthetic SIM is read-only. These short-text journeys establish
local UI behavior, not card writes, power-cycle retention or message delivery.
"""

import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_drafts_e2e import MessagesDraftChecks
from test_factory_messages_editor_e2e import MessagesEditorChecks
from test_factory_messages_local_e2e import MESSAGES, MessagesLocalChecks


class MessagesDraftActionChecks:
    # Copy helpers only; inheriting either old mixin would rediscover its tests.
    setUp = MessagesDraftChecks.setUp
    finish = MessagesDraftChecks.finish
    read = MessagesDraftChecks.read
    press = MessagesDraftChecks.press
    original_home_and_scan = MessagesDraftChecks.original_home_and_scan
    text = MessagesDraftChecks.text
    title = MessagesDraftChecks.title
    menu = MessagesDraftChecks.menu
    open_messages = MessagesDraftChecks.open_messages
    empty_mailbox = MessagesDraftChecks.empty_mailbox
    keys = MessagesDraftChecks.keys
    blank = staticmethod(MessagesDraftChecks.blank)
    field = MessagesDraftChecks.field
    options = MessagesDraftChecks.options
    reopen_messages = MessagesDraftChecks.reopen_messages
    expect = MessagesDraftChecks.expect
    editor = MessagesDraftChecks.editor
    numeric_mode = MessagesDraftChecks.numeric_mode
    save = MessagesDraftChecks.save
    create_saved = MessagesDraftChecks.create_saved
    drafts = MessagesDraftChecks.drafts
    reopen_draft = MessagesDraftChecks.reopen_draft
    actions = MessagesDraftChecks.actions
    edit = MessagesDraftChecks.edit
    discard = MessagesEditorChecks.discard

    def record(self, label):
        # Several helpers reuse labels. Each actual frame must remain available.
        return MessagesLocalChecks.record(self, f"{len(self.evidence):03d}-{label}")

    def home(self, label):
        return self.expect(label, lambda state: (
            self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS and state["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def selected_drafts(self, label):
        self.keys("down", "down")
        self.menu(MESSAGES, 2, label)

    def two_drafts(self, selected, label):
        # C39F0 prepends each new local message; C377A/C37D4 enumerate that
        # chain. These three-character bodies fit the twelve-character preview.
        labels = ("789", "123")
        return self.expect(label, lambda state: (
            self.title(state, "Drafts") and
            all(self.text(state, value, 16 + 17 * row, 13, 107, selected=row == selected)
                for row, value in enumerate(labels)) and self.blank(state, 50, 111) and
            self.text(state, "Options", 112, 2, 45) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Drafts", "ordered_short_previews": labels, "focused_index": selected,
             "unused_rows_blank": True})

    def delete_all_confirmation(self, label):
        expected = self.font.message(("Delete all messages?",))
        _, no_width = self.font.render("No", 128)
        return self.expect(label, lambda state: (
            self.title(state, "Drafts") and self.handset.screen_hash(state=state) == expected and
            self.text(state, "Yes", 112, 2, 22) and
            self.text(state, "No", 112, 127 - no_width, no_width)),
            {"title": "Drafts", "literal_message": "Delete all messages?", "actions": ["Yes", "No"]})

    def test_red_autosaves_nonempty_text_but_empty_red_adds_no_draft(self):
        self.open_messages()
        self.keys("soft_left")
        self.editor("", "empty-new-before-red", title="New")
        self.keys("red")
        self.home("empty-red-returns-home")
        self.reopen_messages()
        self.selected_drafts("empty-red-drafts-selected")
        self.empty_mailbox(2, "Drafts")
        self.keys("up", "up")
        self.menu(MESSAGES, 0, "create-after-empty-red")
        self.keys("soft_left")
        self.editor("", "new-empty-before-text", title="New")
        self.keys("2", "3", "4")
        self.editor("adg", "complete-unsaved-adg-count-997", title="New")
        # Original841AA/870F4 calls the local writer only for nonempty text,
        # then closes Home. This branch does not use the Saved-to-drafts toast.
        self.keys("red")
        self.home("nonempty-red-autosave-returns-home")
        self.reopen_draft("adg")
        self.edit("adg")
        # Original Edit removes the stored entry before opening the full text.
        # Exit here discards that editable copy; it is not an undo operation.
        self.discard("discard-auto-saved-edit-copy")
        self.reopen_messages()
        self.selected_drafts("edit-copy-cleanup-drafts-selected")
        self.empty_mailbox(2, "Drafts")
        self.keys("red")
        self.home("autosave-case-restored-home")

    def test_delete_all_no_preserves_two_drafts_then_yes_removes_both(self):
        self.create_saved()  # Explicit Save-as-draft, exact123 and success toast.
        self.reopen_messages()
        self.keys("soft_left")
        self.editor("", "second-new-empty", title="New")
        self.numeric_mode("", title="New")
        self.keys("7", "8", "9")
        self.editor("789", "second-complete-text-count-997", title="New", numeric=True)
        self.keys("red")
        self.home("second-draft-red-autosave-home")
        self.reopen_messages()
        self.selected_drafts("two-drafts-folder-selected")
        self.keys("soft_left")
        self.two_drafts(0, "two-drafts-newest-first")
        self.keys("down")
        self.two_drafts(1, "older-draft-focused")
        self.keys("up")
        self.two_drafts(0, "newer-draft-focused")
        self.keys("soft_left", "down", "down")
        self.actions(2, "delete-all-selected-before-no")
        self.keys("soft_left")
        self.delete_all_confirmation("delete-all-confirmation-before-no")
        self.keys("soft_right")
        self.actions(2, "delete-all-no-returns-to-actions")
        self.keys("soft_right")
        self.two_drafts(0, "delete-all-no-preserves-both-rows")
        self.keys("soft_right")
        self.menu(MESSAGES, 2, "delete-all-no-folder-closed")
        self.keys("soft_left")
        self.two_drafts(0, "delete-all-no-both-rows-reopened")
        self.keys("down")
        self.two_drafts(1, "delete-all-no-older-content-reopened")
        self.keys("soft_left", "down", "down")
        self.actions(2, "delete-all-selected-before-yes")
        self.keys("soft_left")
        self.delete_all_confirmation("delete-all-confirmation-before-yes")
        self.keys("soft_left")
        expected = self.font.message(("All Messages Deleted",), divider=False)
        self.expect("all-messages-deleted-toast", lambda state: (
            self.title(state, "Drafts") and self.handset.screen_hash(state=state) == expected),
            {"title": "Drafts", "literal_message": "All Messages Deleted"})
        # Original83B2E/83BB2 (and HL equivalents) closes the exhausted folder
        # after its standard toast. Re-enter from Messages for the empty oracle.
        self.menu(MESSAGES, 2, "delete-all-parent-after-natural-close", max_steps=24000000)
        self.empty_mailbox(2, "Drafts")
        self.keys("red")
        self.home("delete-all-case-restored-home")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesDraftActionsE2ETests(MessagesDraftActionChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesDraftActionsE2ETests(MessagesDraftActionChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")
