"""Selected Latin-1 contact-name symbols through the original handset UI.

The full factory BC5/AVR/TRX and read-only external card remain active. The
selected original symbols do not establish full Unicode, sorting, dictionaries,
card writes, RF service or persistence across a power cycle.
"""

from pathlib import Path
import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_contact_numbers_e2e import MessagesContactNumberChecks as _Startup
from test_factory_messages_editor_tools_e2e import MessagesEditorToolChecks as _Symbols
from test_factory_messages_local_e2e import MessagesLocalChecks as _Local
from test_factory_phonebook_fields_persistence_e2e import SharedExtendedPersistenceChecks as _Fields
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED


NAME = "A£øé"


class PhonebookLatin1Checks:
    # Alias helpers, not existing test methods.
    read = _Local.read
    press = _Local.press
    text = _Local.text
    title = _Local.title
    blank = staticmethod(_Symbols.blank)
    keys = _Fields.keys
    field_pixels = _Fields.field_pixels
    expected_counter = _Fields.expected_counter
    assert_field = _Fields.assert_field
    symbol_picker = _Symbols.symbol_picker
    boot_to_home = _Startup.boot_to_home

    def setUp(self):
        _Local.setUp(self)
        self.initial_records = dict(self.peer.card.records)
        self.initial_contents = dict(self.peer.card.contents)
        self.addCleanup(self.verify_card_unchanged)

    def verify_card_unchanged(self):
        self.assertEqual(self.peer.card.records, self.initial_records)
        self.assertEqual(self.peer.card.contents, self.initial_contents)

    def finish(self):
        thread = self.handset.thread
        try:
            _Local.finish(self)
        finally:
            self.http_server_thread_closed = not thread.is_alive()
            self.assertTrue(self.http_server_thread_closed)

    def record(self, label):
        return _Local.record(self, f"{len(self.evidence):03d}-{label}")

    def snapshot(self, label, state=None):
        self.record(label)
        return Path(self.evidence[-1]["artifact"])

    def expect(self, label, predicate, oracle, *, max_steps=4000000):
        for elapsed in range(0, max_steps + 1, 200000):
            state = self.handset.assert_healthy()
            self.peer.check()
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < max_steps:
                self.handset.step(200000)
        self.record(label + "-timeout")
        self.evidence[-1]["oracle"] = oracle
        self.fail(f"Original Latin-1 contact UI did not match {label}: {oracle}")

    def body(self, digest, label, first=16, last=113):
        return self.expect(label, lambda s: self.handset.screen_hash(first, last, s) == digest,
                           {"original_body_sha256": digest, "first": first, "last": last})

    def home(self, label):
        return self.expect(label, lambda s: (
            self.handset.screen_hash(113, 128, s) == HOME_CAPTIONS and s["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def local_list(self, label):
        return self.expect(label, lambda s: (
            self.title(s, "Phonebook") and self.text(s, NAME, 16, width=117, selected=True) and
            self.blank(s, 34, 111) and self.text(s, "Options", 112, 2, 45) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Phonebook", "complete_selected_name": NAME,
             "row_text_width": 117, "unused_rows_start": 34})

    def complete_inactive_home(self, label):
        expected, _ = self.font.render("+123", 112)
        return self.expect(label, lambda s: (
            b"".join(row[:112] for row in self.field_pixels(s, 1)) == expected),
            {"complete_inactive_Home": "+123", "all_trailing_columns_blank": True})

    def reopen_editor(self, label):
        self.keys("soft_left", "down", "down", "soft_left")
        self.assert_field(0, NAME, label)
        self.complete_inactive_home(label + "-Home-retained")

    def choose_symbol(self, keys, index, label):
        self.keys("*")
        self.symbol_picker(0, label + "-original-full-grid")
        self.keys(*keys)
        self.symbol_picker(index, label + "-focused")
        self.keys("soft_left")

    def test_original_latin1_name_symbols_save_reopen_and_cancel_preserve_complete_contact(self):
        self.boot_to_home()
        # Use the original factory Name editor directly. Its actual first A
        # and every selected symbol are checked, without changing a global
        # prediction/language preference or claiming dictionary behavior.
        self.keys("soft_left", "soft_left")
        self.body(EMPTY_PHONEBOOK, "fresh-local-phonebook-empty")
        self.keys("soft_left", "soft_left", "2")
        self.assert_field(0, "A", "initial-capital-A")

        self.choose_symbol(("down", "down", "down", "6"), 25, "pound")
        self.assert_field(0, "A£", "pound-accepted-in-complete-Name")
        self.choose_symbol(("down", "4", "down"), 15, "oslash")
        self.assert_field(0, "A£ø", "oslash-accepted-in-complete-Name")
        self.choose_symbol(("down", "down", "down", "4", "4"), 22, "eacute")
        self.assert_field(0, NAME, "eacute-accepted-in-complete-Name")
        self.keys("*")
        self.symbol_picker(0, "cancel-picker-original-grid")
        self.keys("down")
        self.symbol_picker(8, "tentative-at-sign-before-cancel")
        self.keys("soft_right")
        self.assert_field(0, NAME, "cancelled-symbol-keeps-every-Name-glyph-and-count")

        self.keys("down", "1", "2", "3")
        self.assert_field(1, "+123", "complete-Home-before-save")
        self.keys("up")
        self.assert_field(0, NAME, "complete-Name-before-save")
        self.complete_inactive_home("complete-Home-preserved-before-save")
        self.keys("soft_left")
        self.body(ENTRY_ADDED, "original-Entry-added-success")
        self.keys("soft_right")
        self.local_list("all-Latin1-glyphs-in-saved-contact-list")
        self.keys("red")
        self.home("saved-contact-left-to-home")

        self.keys("soft_left", "soft_left")
        self.local_list("saved-Latin1-contact-reopened-from-home")
        self.reopen_editor("full-saved-Latin1-Name-reopened")
        self.keys("soft_right")
        self.assert_field(0, "A£ø", "visible-Name-draft-removes-exact-eacute")
        self.keys("red")
        self.local_list("cancelled-Name-draft-keeps-original-list")
        self.reopen_editor("cancelled-draft-restores-all-Latin1-characters")
        self.keys("down")
        self.assert_field(1, "+123", "complete-saved-Home-after-Name-cancel")
        self.keys("red", "red")
        self.home("Latin1-contact-journey-finished-home")
        self.verify_card_unchanged()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555PhonebookLatin1E2ETests(PhonebookLatin1Checks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575PhonebookLatin1E2ETests(PhonebookLatin1Checks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")
