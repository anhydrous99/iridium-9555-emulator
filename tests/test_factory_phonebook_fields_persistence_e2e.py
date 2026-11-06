"""Six distinct contact fields and a note retained by original modem startup.

Real shutdown/warm startup preserves guest flash and lets the original TRX
rebuild the saved index. No card, service reply, guest state or DSP consumer is
supplied by this test; any original modem halt remains an ordinary failure.
"""

from hashlib import sha256
import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_persistence_e2e import SharedPersistenceChecks as _Persistence
from test_factory_phonebook_fields_e2e import (
    PhonebookFieldChecks as _Fields, SHORT_VALUES, COUNTER, LIST_HEADER,
)
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_phonebook_details_e2e import (
    SharedPhonebookDetailChecks as _Details, EMPTY_NOTE,
)
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED


class SharedExtendedPersistenceChecks:
    # Select helpers without discovering the older independent test journeys.
    type_keys = _Fields.type_keys
    expect = _Persistence.expect
    home = _Persistence.home
    field_pixels = _Fields.field_pixels
    save = _Fields.save
    reopen = _Fields.reopen
    open_notes = _Details.open_notes
    save_notes = _Details.save_notes
    assert_note = _Persistence.assert_note
    shutdown_and_restart = _Persistence.shutdown_and_restart

    def keys(self, *keys, settle=2000000):
        for key in keys:
            hold = 500000 if settle >= 2000000 else 0
            self.handset.press(key, hold_steps=hold, settle_steps=settle - hold)

    def setUp(self):
        self.evidence = []
        self.boots = 0
        _Persistence.setUp(self)  # Includes factory BC5/AVR/TRX and actual startup alerts.
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.assertEqual(self.font.message(("Entry added", "successfully"), divider=False), ENTRY_ADDED)
        for remaining in (0, 1):
            self.assertEqual(sha256(self.expected_counter(remaining)).hexdigest(), COUNTER[remaining])

    def snapshot(self, label, state=None):
        target = self.handset.save_artifacts(label, state)
        self.evidence.append({"label": label, "artifact": str(target)})
        return target

    def boot_with_modem_alerts(self):
        if self.boots:
            state = self.handset.state()
            primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
            self.assertEqual(primary["power_state"], 8)
            self.assertFalse(state["ui_initialized"])
            self.snapshot("completed-shutdown-before-restart", state)
        _Persistence.boot_with_modem_alerts(self)
        self.boots += 1
        self.snapshot(f"boot-{self.boots}-home", self.handset.assert_healthy())

    def expected_counter(self, remaining):
        pixels, width = self.font.render(str(remaining), 128)
        # Contact headers right-align at128 and retain their divider before the
        # count. This exactly reproduces the older native0/1 counter crops.
        left = 128 - width
        return bytes(3 if y == 7 and x < left else
                     pixels[y * 128 + x - left] if left <= x < left + width else 0
                     for y in range(14) for x in range(114, 128))

    def assert_field(self, field, text, label):
        expected, _ = self.font.render(text, 112)
        # Original chosen glyphs have no ink in row14, where the active caret
        # blinks. Keep every other glyph pixel and all trailing blank columns.
        self.assertFalse(any(expected[14 * 112:]))
        remaining = (64 if field == 5 else 24) - len(text)
        expected_count = self.expected_counter(remaining)
        for elapsed in range(0, 20000001, 200000):
            state = self.handset.assert_healthy()
            actual = b"".join(row[:112] for row in self.field_pixels(state, field)[:14])
            pixels = state["lcd"]["pixels"]
            count = bytes(pixels[y * 128 + x] for y in range(14) for x in range(114, 128))
            # The inspected native focus box has a solid x127 edge on exactly
            # one field. Equal-length phone counters alone cannot identify it.
            focused = [index for index in range(6)
                       if all(row[-1] == 3 for row in self.field_pixels(state, index))]
            if actual == expected[:14 * 112] and count == expected_count and focused == [field]:
                self.assertEqual(state["keys"], [])
                path = self.snapshot(label, state)
                self.evidence[-1].update({"field": field, "text": text, "remaining": remaining,
                                          "focused_field": field,
                                          "font_sha256": sha256(self.font.data).hexdigest()})
                return path
            if elapsed < 20000000:
                self.handset.step(200000)
        self.snapshot(label + "-timeout", state)
        self.assertEqual(actual, expected[:14 * 112], f"Complete saved field {field}: {text!r}")
        self.assertEqual(count, expected_count, f"Field {field} must have exactly {len(text)} characters")
        self.assertEqual(focused, [field], "The intended field must visibly own the original focus box")

    def read_all_fields(self, label):
        self.reopen()
        for field, text in enumerate(SHORT_VALUES):
            if field:
                self.keys("down")
            self.assert_field(field, text, f"{label}-field-{field}")

    def test_all_six_fields_and_note_survive_shutdown_with_cancelled_work_edit_discarded(self):
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left")
        self.type_keys("234", settle=500000)
        for digits in ("123", "456", "789", "246"):
            self.keys("down")
            self.type_keys(digits, settle=500000)
        self.keys("down")
        self.type_keys(("2", "1", "1", "2", "2", "1", "2", "2", "2"), settle=500000)
        self.save()
        self.expect(ADG_SELECTED)
        self.open_notes()
        self.expect(EMPTY_NOTE)
        self.type_keys("234", settle=500000)
        self.assert_note()
        self.save_notes()
        self.snapshot("saved-contact-and-note")
        self.read_all_fields("before-restart")
        self.keys("red")
        self.expect(LIST_HEADER, 0, 14)
        self.reopen()
        self.assert_field(0, SHORT_VALUES[0], "draft-start-name")
        self.keys("down")
        self.assert_field(1, SHORT_VALUES[1], "draft-start-home")
        self.keys("down")
        self.assert_field(2, SHORT_VALUES[2], "draft-start-work")
        self.keys("soft_right")
        self.assert_field(2, "+45", "visible-work-short-draft")
        self.keys("0")
        self.assert_field(2, "+450", "visible-work-draft-before-cancel")
        self.keys("red")
        self.expect(LIST_HEADER, 0, 14)
        self.home()
        self.snapshot("cancelled-draft-home-before-shutdown")
        self.shutdown_and_restart()

        self.keys("soft_left", "soft_left")
        self.expect(ADG_SELECTED)
        self.read_all_fields("after-restart")
        self.keys("red")
        self.expect(LIST_HEADER, 0, 14)
        self.open_notes()
        self.assert_note()
        self.snapshot("retained-note-after-restart")
        self.home()
        self.assertEqual(self.boots, 2)
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertTrue(state["processor_link"]["connected"])
        self.assertEqual(state["keys"], [])
        self.snapshot("retained-six-fields-and-note-final-home", state)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 extended contact persistence")
class Factory9555PhonebookFieldsPersistenceE2ETests(SharedExtendedPersistenceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 extended contact persistence")
class Factory9575PhonebookFieldsPersistenceE2ETests(SharedExtendedPersistenceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
