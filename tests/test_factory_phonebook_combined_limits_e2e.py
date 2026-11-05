"""All six contact maxima together, including four bare 24-digit numbers.

The original font and complete hidden-window/count checks are reused without
inheriting the earlier independent journeys. No modem or restart is involved.
"""

import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_customization_e2e import (
    NUMBER_ENTRY_MENU, PREFIX_PLUS, PREFIX_NONE, DIAL_PLUS_TWELVE,
)
from test_factory_phonebook_fields_e2e import (
    PhonebookFieldChecks as _Fields, NAME, NAME_KEYS, EMAIL_LOCAL,
    EMAIL_DOMAIN, EMAIL_64, LIST_HEADER, EMPTY_PHONEBOOK,
)


BARE_BASE = "123456789024681357908642"
BARE_PHONES = tuple("".join(str((int(digit) + shift) % 10) for digit in BARE_BASE)
                    for shift in range(4))
VALUES = (NAME, *BARE_PHONES, EMAIL_64)


class CombinedLimitsChecks:
    keys = _Fields.keys
    type_keys = _Fields.type_keys
    expect = _Fields.expect
    field_pixels = _Fields.field_pixels
    counter = _Fields.counter
    reject_extra = _Fields.reject_extra
    full_text = _Fields.full_text
    save = _Fields.save
    reopen = _Fields.reopen
    home = _Fields.home

    def setUp(self):
        self.evidence = []
        _Fields.setUp(self)  # Fresh boot and original Multi-Tap form setup.
        self.home()
        self.open_number_entry()
        self.expect(PREFIX_PLUS)
        self.keys("down", "down", "soft_left")
        self.expect(NUMBER_ENTRY_MENU[self.model])
        self.keys("soft_left")
        self.snapshot("saved-no-prefix", self.expect(PREFIX_NONE))
        self.keys("soft_right")
        self.home()
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left")

    def snapshot(self, label, state=None):
        target = _Fields.snapshot(self, label, state)
        self.evidence.append({"label": label, "artifact": str(target)})
        return target

    def open_number_entry(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (7 + (self.model == "9575"))), "soft_left")

    def read_all_fields(self, label):
        self.reopen()
        for field, value in enumerate(VALUES):
            if field:
                self.keys("down")
            self.counter(0)
            self.full_text(field, value, f"{label}-field-{field}")

    def test_all_six_maxima_with_four_bare_numbers_save_full_readback_cancel_and_restore_prefix(self):
        self.assertEqual(tuple(map(len, VALUES)), (24, 24, 24, 24, 24, 64))
        self.assertEqual(len(set(BARE_PHONES)), 4)
        self.type_keys(NAME_KEYS, settle=500000)
        self.counter(0)
        for field, phone in enumerate(BARE_PHONES, 1):
            self.keys("down")
            # Active empty fields blink an underline in row14. Exclude it and
            # the fixed x127 edge; retain every glyph-bearing row/column.
            state = self.handset.assert_healthy()
            self.assertFalse(any(b"".join(row[:112] for row in self.field_pixels(state, field)[:14])))
            self.snapshot(f"field-{field}-empty-without-prefix", state)
            self.type_keys(phone)
            self.counter(0)
            self.reject_extra(field, "9")  # Distinct from every expected final digit.
        self.keys("down", "#", "#")  # Email abc -> ABC ->123.
        self.type_keys(EMAIL_LOCAL)
        self.keys("*", "down", "soft_left")  # Original symbol grid: @.
        self.type_keys(EMAIL_DOMAIN)
        self.keys("*", "soft_left", "#", "#")  # '.', then123 -> Abc ->abc.
        self.type_keys("23")  # Final ad makes the email exactly64 characters.
        self.counter(0)
        self.snapshot("all-six-maxima-before-save")
        self.save()
        self.read_all_fields("saved-maxima")

        # Reconstruct the editor so Work's cursor starts at its actual end;
        # the preceding complete readback deliberately moved every cursor left.
        self.keys("red")
        self.expect(LIST_HEADER, 0, 14)
        self.reopen()
        self.keys("down", "down", "soft_right")
        self.counter(1)
        self.type_keys("9")
        self.counter(0)
        draft = BARE_PHONES[1][:-1] + "9"
        self.assertNotEqual(draft, BARE_PHONES[1])
        self.full_text(2, draft, "visible-work-max-draft")
        self.keys("red")  # Cancel the visible changed draft through the real UI.
        self.expect(LIST_HEADER, 0, 14)
        self.read_all_fields("after-cancel-maxima")
        self.home()

        self.open_number_entry()
        self.expect(PREFIX_NONE)
        self.keys("up", "up", "soft_left")
        self.expect(NUMBER_ENTRY_MENU[self.model])
        self.keys("soft_left")
        self.snapshot("restored-prefix-plus", self.expect(PREFIX_PLUS))
        self.keys("soft_right")
        self.home()
        self.keys("1", "2")
        self.snapshot("restored-prefix-plus-dialer", self.expect(DIAL_PLUS_TWELVE))
        self.home()
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 combined contact limits")
class Factory9555PhonebookCombinedLimitsE2ETests(CombinedLimitsChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 combined contact limits")
class Factory9575PhonebookCombinedLimitsE2ETests(CombinedLimitsChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
