"""Copy a read-only SIM contact into the original editable local phonebook.

The factory Copy callback clears absent secondary fields. A focused empty
phone editor may show its configured '+' prefix; that is not a saved number.
No SIM update, authentication, network or cold-power behavior is supplied.
"""

from hashlib import sha256
import os
from pathlib import Path
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_phonebook_details_e2e import EMPTY_NOTE, NOTES_SELECTED
from test_factory_phonebook_e2e import ADG_SELECTED
from test_factory_phonebook_fields_persistence_e2e import SharedExtendedPersistenceChecks as _Fields
from test_factory_sim_phonebook_e2e import SIMPhonebookChecks as _SIM


COPY_LINES = ("Entry successfully", "copied to My", "Phonebook")


class SIMPhonebookCopyChecks:
    # Alias helpers without inheriting the already published test methods.
    start = _SIM.start
    finish = _SIM.finish
    verify_card_unchanged = _SIM.verify_card_unchanged
    read = _SIM.read
    press = _SIM.press
    submit = _SIM.submit
    original_home_and_scan = _SIM.original_home_and_scan
    original_card_consumed = _SIM.original_card_consumed
    open_sim = _SIM.open_sim
    back_home = _SIM.back_home
    record = _SIM.record
    expect = _SIM.expect
    text = _SIM.text
    title = _SIM.title
    blank = staticmethod(_SIM.blank)
    keys = _Fields.keys
    field_pixels = _Fields.field_pixels
    expected_counter = _Fields.expected_counter
    assert_field = _Fields.assert_field

    def snapshot(self, label, state=None):
        self.record(label)
        return Path(self.evidence[-1]["artifact"])

    def sim_entry(self, label):
        return self.expect(label, lambda s: (
            self.title(s, "Phonebook") and self.text(s, "Adg", 16, width=117, selected=True) and
            self.blank(s, 34, 111) and self.text(s, "Options", 112, 2, 45) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Phonebook", "complete_selected_name": "Adg", "row_text_width": 117,
             "unused_rows_start": 34, "source": "unchanged external SIM record"})

    def sim_actions(self, selected, label):
        labels = ("Call", "SMS", "Copy")
        return self.expect(label, lambda s: (
            self.title(s, "Adg") and
            all(self.text(s, value, 16 + 17 * i, selected=i == selected)
                for i, value in enumerate(labels)) and
            self.blank(s, 67, 111) and self.text(s, "Select", 112, 2, 36) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Adg", "ordered_actions": labels, "focused_index": selected})

    def copy_success(self):
        body = bytearray(128 * 97)
        for index, line in enumerate(COPY_LINES):
            glyphs, width = self.font.render(line, 128)
            left, top = (128 - width) // 2, (126 - 15 * len(COPY_LINES)) // 2 + 15 * index - 16
            for y in range(15):
                body[(top + y) * 128 + left:(top + y) * 128 + left + width] = glyphs[y * 128:y * 128 + width]
        expected = sha256(body).hexdigest()
        return self.expect("original-copy-success-complete-message", lambda s: (
            self.title(s, "Success") and self.handset.screen_hash(state=s) == expected and
            self.blank(s, 112, 128, 0, 128)),
            {"title": "Success", "literal_message": " ".join(COPY_LINES),
             "original_font_lines": COPY_LINES, "body_divider": False, "footer": "blank"})

    def home(self, label):
        for _ in range(3):
            self.keys("red")
            state = self.handset.assert_healthy()
            if self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                break
        return self.expect(label, lambda s: (
            self.handset.screen_hash(113, 128, s) == HOME_CAPTIONS and s["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def local_list(self, label):
        return self.expect(label, lambda s: self.handset.screen_hash(state=s) == ADG_SELECTED,
                           {"local_phonebook_selected_contact": "Adg", "original_list_body": ADG_SELECTED})

    def edit_local(self):
        self.keys("soft_left", "down", "down", "soft_left")
        self.assert_field(0, "Adg", "copied-local-name-before-edit")

    def empty_note(self):
        _, width = self.font.render("64", 128)
        return self.expect("copied-local-note-is-empty", lambda s: (
            self.handset.screen_hash(state=s) == EMPTY_NOTE and
            self.text(s, "64", 0, 128 - width, width)),
            {"local_note": "", "remaining_characters": 64, "original_empty_note_body": EMPTY_NOTE})

    def test_original_sim_copy_preserves_complete_local_fields_notes_cancel_and_sim_independence(self):
        self.start(populated=True)
        self.original_home_and_scan()
        self.original_card_consumed(populated=True)
        self.open_sim()
        self.sim_entry("source-SIM-Adg-visible")
        self.submit()
        # The selected entry is fetched asynchronously before this menu opens.
        self.sim_actions(0, "source-SIM-actions-ready")
        self.keys("down", "down")
        self.sim_actions(2, "source-SIM-Copy-focused")
        self.submit()
        self.copy_success()
        self.home("copy-success-returned-home")

        self.keys("soft_left")
        self.expect("main-menu-before-local-copy", lambda s: self.title(s, "Menu"), {"title": "Menu"})
        self.keys("soft_left")
        self.local_list("copied-contact-listed-in-My-Phonebook")
        self.edit_local()
        # 7AA14 supplies '+' to an empty numeric editor; 7AA98 normalizes a
        # bare prefix back to empty before any save. Copy clears these tags.
        for field, value in enumerate(("+12345", "+", "+", "+", ""), 1):
            self.keys("down")
            self.assert_field(field, value, f"copied-local-field-{field}-complete")
            if field in (2, 3, 4):
                self.evidence[-1]["empty_phone_prefix"] = True
        self.expect("empty-secondary-phone-prefixes-cleared-on-blur", lambda s: all(
            not any(b"".join(self.field_pixels(s, field))) for field in (2, 3, 4)),
            {"inactive_secondary_phones": ["", "", ""],
             "focused_plus_was_only_an_editor_prefix": True})
        self.keys("red")
        self.local_list("copied-fields-readback-cancelled-without-save")
        self.keys("soft_left", *(["down"] * 6))
        self.expect("copied-local-Notes-action-focused", lambda s: self.handset.screen_hash(state=s) == NOTES_SELECTED,
                    {"local_action": "Notes", "original_focused_body": NOTES_SELECTED})
        self.keys("soft_left")
        self.empty_note()
        self.keys("red", "soft_right")
        self.local_list("copied-note-cancelled-without-save")

        self.edit_local()
        self.keys("soft_right")
        self.assert_field(0, "Ad", "visible-local-name-draft-before-cancel")
        self.keys("red")
        self.local_list("visible-local-name-draft-cancelled")
        self.edit_local()
        self.evidence[-1]["cancelled_local_name_restored"] = True
        fields = {field: self.font.render(value, 112)[0]
                  for field, value in enumerate(("+12345", "", "", "", ""), 1)}
        self.expect("all-inactive-copied-fields-retained-after-cancel", lambda s: all(
            b"".join(row[:112] for row in self.field_pixels(s, field)) == expected
            for field, expected in fields.items()),
            {"complete_inactive_fields": ["+12345", "", "", "", ""],
             "no_local_save_performed": True})
        self.keys("red")
        self.home("local-copy-cancel-returned-home")
        self.verify_card_unchanged()
        self.open_sim()
        self.sim_entry("original-SIM-Adg-reopened-after-local-copy-and-cancel")
        self.verify_card_unchanged()
        self.back_home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555SIMPhonebookCopyE2ETests(SIMPhonebookCopyChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575SIMPhonebookCopyE2ETests(SIMPhonebookCopyChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")
