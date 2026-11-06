"""Factory contact fields, exact input limits, and complete saved text readback.

Original constructors 9555:8B4D2 / 9575:9169C define Name, Home, Work,
Mobile1, Mobile2 (25-word buffers), and Email (65 words). Expected glyphs
come independently from the pinned ASCII1 font. Real side-key cursor moves
expose every overlapping six-character window of horizontally hidden text.
These journeys cover local editing/storage, without claiming RF service.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_phonebook_capacity_e2e import OriginalASCII1, LIST_HEADER, LIST_CAPTIONS
from test_factory_text_entry_e2e import TEXT_MULTI_TAP, TEXT_LANGUAGE_MENU
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED


ENTRY_UPDATED = "55ad160dc5a965307321799eda5eaa61dae3dbefd654da3f74f281ea62c6c0ca"
# Original native header crop x114:128,y0:14, first observed in a full 9575
# name and a one-short 9555 name. These include both digit positions.
COUNTER = {
    0: "4b4452fcab3c7b088e5c1721bdb693964ba42d255c9c6528ca26f4047973e27a",
    1: "e23715608a55bf722247439eccd536e061366e5239db723a3648adb743e4a578",
}
SHORT_VALUES = ("Adg", "+123", "+456", "+789", "+246", "a@b.c")
NAME = "Adgjmptwbehknquxcfilorvy"
NAME_KEYS = list("23456789") + [k for k in "23456789" for _ in range(2)] + [k for k in "23456789" for _ in range(3)]
PHONE_BASE = "12345678902468135790864"
PHONES = tuple("+" + "".join(str((int(d) + i) % 10) for d in PHONE_BASE) for i in range(4))
EMAIL_LOCAL = "2357111317192329313741434753596167717379838997101103"[:48]
EMAIL_DOMAIN = "246813579024"
EMAIL_63 = EMAIL_LOCAL + "@" + EMAIL_DOMAIN + ".a"
EMAIL_64 = EMAIL_63 + "d"


class PhonebookFieldChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.assertEqual(self.font.message(("Entry added", "successfully"), divider=False), ENTRY_ADDED)
        self.handset.boot()
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))), "soft_left", "down", "soft_left")
        self.expect(TEXT_MULTI_TAP)
        self.keys("down", "down", "down", "soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.keys("red")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left")

    def keys(self, *keys, settle=2000000):
        for key in keys:
            self.handset.press(key, settle_steps=settle)

    def type_keys(self, keys, *, settle=2000000):
        self.keys(*keys, settle=settle)
        self.handset.step(2000000)  # Commit the original multi-tap timer.

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=20000000)

    def snapshot(self, label, state=None):
        return self.handset.save_artifacts(label, state)

    def field_pixels(self, state, field):
        pixels = state["lcd"]["pixels"]
        return [bytes(pixels[(16 + 16 * field + y) * 128 + 15:(16 + 16 * field + y) * 128 + 128])
                for y in range(15)]

    def short_text(self, field, text):
        expected, _ = self.font.render(text, 112)
        for elapsed in range(0, 20000001, 200000):
            state = self.handset.assert_healthy()
            actual = b"".join(row[:112] for row in self.field_pixels(state, field))
            if actual == expected:
                return state
            if elapsed < 20000000:
                self.handset.step(200000)
        self.snapshot(f"field-{field}-text-timeout", state)
        self.assertEqual(actual, expected, f"Field {field} must visibly contain {text!r}")

    def counter(self, remaining):
        state = self.handset.assert_healthy()
        pixels = state["lcd"]["pixels"]
        actual = sha256(bytes(pixels[y * 128 + x] for y in range(14) for x in range(114, 128))).hexdigest()
        self.assertEqual(actual, COUNTER[remaining], f"Original remaining-character counter must show {remaining}")

    def reject_extra(self, field, key):
        before = self.field_pixels(self.handset.assert_healthy(), field)[:14]
        self.type_keys(key)
        after = self.handset.assert_healthy()
        self.counter(0)
        # At capacity, an extra input must leave the visible suffix intact,
        # rather than overwriting its final character while keeping count0.
        self.assertEqual(self.field_pixels(after, field)[:14], before)
        self.snapshot(f"field-{field}-extra-rejected", after)

    def full_text(self, field, text, label):
        """Require all unique overlapping windows, not merely prefix/suffix.

        Adjacent six-character windows overlap by five unique characters,
        establishing order as well as every hidden glyph. The caret starts
        at the end in a newly entered or freshly reopened field. We stop as
        soon as coverage is complete, before a move beyond the left boundary.
        """
        size = min(6, len(text))
        self.assertEqual(len({text[i:i + size - 1] for i in range(len(text) - size + 2)}),
                         len(text) - size + 2, "Use unambiguous overlapping expected windows")
        windows = {}
        for i in range(len(text) - size + 1):
            rendered, width = self.font.render(text[i:i + size], 128)
            # Row14 is blank in every expected glyph here, but contains the
            # moving original caret. Keep all glyph ink, including descenders.
            self.assertFalse(any(rendered[14 * 128:14 * 128 + width]))
            rows = [rendered[y * 128:y * 128 + width] for y in range(14)]
            anchor = max(range(14), key=lambda y: rows[y].count(3))
            windows[i] = (rows, anchor)
        seen = {}
        for moves in range(len(text) + 1):
            state = self.handset.assert_healthy()
            actual = self.field_pixels(state, field)
            newly_seen = []
            for offset, (rows, anchor) in windows.items():
                if offset in seen:
                    continue
                left = actual[anchor].find(rows[anchor])
                while left >= 0:
                    if all(actual[y][left:left + len(rows[y])] == rows[y] for y in range(14)):
                        seen[offset] = {"left_moves": moves, "lcd_x": 15 + left}
                        newly_seen.append(offset)
                        break
                    left = actual[anchor].find(rows[anchor], left + 1)
            if newly_seen:
                self.snapshot(f"{label}-left-{moves}", state)
            if len(seen) == len(windows):
                target = self.snapshot(f"{label}-complete", state)
                Path(str(target) + "-coverage.json").write_text(json.dumps({
                    "text": text, "field": field, "window_size": size,
                    "expected_offsets": list(windows), "observed_offsets": seen,
                    "font_sha256": sha256(self.font.data).hexdigest(),
                }, indent=2) + "\n")
                self.counter((64 if field == 5 else 24) - len(text))
                return moves
            if moves < len(text):
                self.keys("volume_up")
        self.snapshot(f"{label}-incomplete", state)
        self.assertEqual(sorted(seen), sorted(windows),
                         f"Saved/input field {field} must expose every original glyph window of {text!r}")

    def save(self, *, update=False):
        self.keys("soft_left")
        self.expect(ENTRY_UPDATED if update else ENTRY_ADDED)
        self.snapshot("entry-updated" if update else "entry-added")
        self.keys("soft_right")
        self.expect(LIST_HEADER, 0, 14)
        self.expect(LIST_CAPTIONS, 113, 128)

    def reopen(self):
        self.keys("soft_left", "down", "down", "soft_left")

    def home(self):
        self.keys("red", "red")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])

    def fill_max_name_phones(self):
        self.type_keys(NAME_KEYS, settle=500000)
        for phone in PHONES:
            self.keys("down")
            # Long scrolling numeric fields need the ordinary UI interval;
            # rapid multi-tap spacing can overrun the original input handler.
            self.type_keys(phone[1:], settle=2000000)  # '+' consumes one of24 slots.

    def fill_email(self, text):
        self.assertIn(text, (EMAIL_63, EMAIL_64))
        self.type_keys("234")
        self.keys(*(["down"] * 5), "#", "#")  # Email abc -> ABC ->123.
        self.type_keys(EMAIL_LOCAL, settle=2000000)
        self.keys("*", "down", "soft_left")  # Original symbol grid: @.
        self.type_keys(EMAIL_DOMAIN, settle=2000000)
        self.keys("*", "soft_left", "#", "#")  # '.', then123 -> Abc ->abc.
        self.type_keys("2" if text == EMAIL_63 else "23")

    def test_six_distinct_fields_save_reopen_and_cancel_visible_work_edit(self):
        self.type_keys("234")
        for digits in ("123", "456", "789", "246"):
            self.keys("down")
            self.type_keys(digits, settle=2000000)
        self.keys("down")
        self.type_keys(("2", "1", "1", "2", "2", "1", "2", "2", "2"), settle=500000)
        self.save()
        self.reopen()
        for field, text in enumerate(SHORT_VALUES[1:], 1):
            self.short_text(field, text)
        self.keys("down")
        self.short_text(0, SHORT_VALUES[0])
        self.keys("down", "soft_right", "0", "down")
        self.short_text(2, "+450")
        self.snapshot("visible-work-draft")
        self.keys("red")  # Original form's Cancel: discard the whole unsaved edit.
        self.expect(LIST_HEADER, 0, 14)
        self.reopen()
        for field, text in enumerate(SHORT_VALUES[1:], 1):
            self.short_text(field, text)
        self.keys("down")
        self.short_text(0, SHORT_VALUES[0])
        self.snapshot("all-six-saved-fields-after-cancel")
        self.home()

    def test_name_and_four_phone_input_limits_reject_extra_and_recover_last_slot(self):
        self.type_keys(NAME_KEYS, settle=500000)
        self.counter(0)
        self.reject_extra(0, "2")
        self.keys("soft_right")
        self.counter(1)
        self.type_keys("999", settle=500000)  # Restore the original final y.
        self.counter(0)
        self.full_text(0, NAME, "name-limit-recovery")
        for field, phone in enumerate(PHONES, 1):
            self.keys("down")
            self.type_keys(phone[1:], settle=2000000)
            self.counter(0)
            self.reject_extra(field, "9")
            self.keys("soft_right")
            self.counter(1)
            self.type_keys(phone[-1])
            self.counter(0)
            self.full_text(field, phone, f"phone-{field}-limit-recovery")
        self.home()

    def test_exact_fit_name_and_four_phones_save_and_full_readback(self):
        self.fill_max_name_phones()
        self.save()
        self.reopen()
        self.counter(0)
        self.full_text(0, NAME, "saved-name-24")
        for field, phone in enumerate(PHONES, 1):
            self.keys("down")
            self.counter(0)
            self.full_text(field, phone, f"saved-phone-{field}-24")
        self.home()

    def test_email_input_limit_rejects_sixty_fifth_and_recovers_last_slot(self):
        self.fill_email(EMAIL_64)
        self.counter(0)
        self.reject_extra(5, "4")
        self.keys("soft_right")
        self.counter(1)
        self.type_keys("3")
        self.counter(0)
        self.full_text(5, EMAIL_64, "email-64-limit-recovery")
        self.home()

    def saved_email(self, text):
        self.fill_email(text)
        self.counter(65 - 1 - len(text))
        self.full_text(5, text, f"email-{len(text)}-input")
        self.save()
        self.reopen()
        self.keys(*(["down"] * 5))
        self.counter(65 - 1 - len(text))
        self.full_text(5, text, f"email-{len(text)}-saved")
        self.home()

    def test_email_sixty_three_character_save_and_full_readback(self):
        self.saved_email(EMAIL_63)

    def test_email_sixty_four_character_exact_fit_save_and_full_readback(self):
        self.saved_email(EMAIL_64)

    def test_reopened_exact_fit_name_cursor_right_at_end_stays_healthy(self):
        self.type_keys(NAME_KEYS, settle=500000)
        self.counter(0)
        self.keys("down")
        self.type_keys("123")
        self.save()
        self.reopen()
        self.counter(0)
        self.snapshot("full-name-reopened-before-right")
        # A cursor command at the end must clamp safely, retaining the text.
        # This ordinary enabled regression deliberately exposes an observed
        # panic rather than considering an original firmware guard a pass.
        self.keys("volume_down")
        self.counter(0)
        self.full_text(0, NAME, "full-name-after-right-clamp")
        self.home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 contact-field E2Es")
class Factory9555PhonebookFieldsE2ETests(PhonebookFieldChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 contact-field E2Es")
class Factory9575PhonebookFieldsE2ETests(PhonebookFieldChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
