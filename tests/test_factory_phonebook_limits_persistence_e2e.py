"""All six maximum-length contact fields across original shutdown/warm startup.

Numeric input waits for its actual count, focused field and complete suffix.
Default tones remain enabled and every original processor runs normally.
Separate No Tone journeys use the genuine saved preference after the default
contact runs demonstrated the original command-queue allocation boundary.
Any original native halt remains an ordinary failure. Reached input fields are
partial evidence until Save, completed shutdown and every reopened glyph pass.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from factory_modem import FactoryModemChecks
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED
from test_factory_phonebook_fields_e2e import (
    PhonebookFieldChecks as _Fields, NAME, NAME_KEYS, PHONES,
    EMAIL_LOCAL, EMAIL_DOMAIN, EMAIL_64, LIST_HEADER, COUNTER,
)
from test_factory_phonebook_fields_persistence_e2e import SharedExtendedPersistenceChecks as _Extended
from test_factory_persistence_e2e import SharedPersistenceChecks as _Persistence
from test_factory_text_entry_e2e import TEXT_MULTI_TAP, TEXT_LANGUAGE_MENU
from test_factory_settings_e2e import (
    VOLUME_MENU, KEYPAD_TONE_MENU, KEYPAD_SINGLE_TONE, KEYPAD_NO_TONE,
)


VALUES = (NAME, *PHONES, EMAIL_64)


class MaximumFieldPersistenceChecks(FactoryModemChecks):
    # Reuse helpers only; the prior modules' independent cases stay undiscovered.
    type_keys = _Fields.type_keys
    home = _Persistence.home
    field_pixels = _Fields.field_pixels
    counter = _Fields.counter
    save = _Fields.save
    reopen = _Fields.reopen
    expected_counter = _Extended.expected_counter
    shutdown_and_restart = _Persistence.shutdown_and_restart

    def setUp(self):
        self.accepted_inputs = []
        self.cursor_observations = []
        self.cursor_field = None
        self.no_tone_saved = False
        self.single_tone_restored = False
        self.fast_no_tone_input = False
        self.language_from_volume = False
        self.start_handset()
        self.assertEqual(self.font.message(("Entry added", "successfully"), divider=False), ENTRY_ADDED)
        for remaining in (0, 1):
            self.assertEqual(sha256(self.expected_counter(remaining)).hexdigest(), COUNTER[remaining])
        self.boot_with_modem_alerts()

    def keys(self, *keys, settle=1000000):
        for key in keys:
            if key == "volume_up" and self.cursor_field is not None:
                before = self.field_pixels(self.handset.assert_healthy(), self.cursor_field)
                state = self.physical(key)
                elapsed = 0
                while self.field_pixels(state, self.cursor_field) == before and elapsed < 2000000:
                    state = self.handset.step(50000)
                    elapsed += 50000
                self.cursor_observations.append({"field": self.cursor_field, "wait": elapsed,
                                                 "visible_change": self.field_pixels(state, self.cursor_field) != before})
            elif settle <= 500000:
                # Same800k total as the previously accepted500k-settle Name
                # cadence, with a real held interval and no accepted-key replay.
                self.physical(key, hold=300000, released=200000)
            else:
                self.physical(key, hold=500000, released=settle - 500000)

    def full_text(self, field, text, label):
        self.cursor_field = field
        try:
            return _Fields.full_text(self, field, text, label)
        finally:
            self.cursor_field = None

    def input_matches(self, state, field, text):
        expected, width = self.font.render(text[-min(6, len(text)):], 128)
        rows = [expected[y * 128:y * 128 + width] for y in range(14)]
        actual = self.field_pixels(state, field)
        anchor = max(range(14), key=lambda y: rows[y].count(3))
        position = actual[anchor].find(rows[anchor])
        glyphs = False
        while position >= 0:
            if all(actual[y][position:position + width] == rows[y] for y in range(14)):
                glyphs = True
                break
            position = actual[anchor].find(rows[anchor], position + 1)
        pixels = state["lcd"]["pixels"]
        count = bytes(pixels[y * 128 + x] for y in range(14) for x in range(114, 128))
        focused = [i for i in range(6) if all(row[-1] == 3 for row in self.field_pixels(state, i))]
        return (glyphs and count == self.expected_counter((64 if field == 5 else 24) - len(text))
                and focused == [field] and state["keys"] == [])

    def type_numeric(self, field, digits, *, prefix=""):
        value = prefix
        for digit in digits:
            self.assertIn(digit, "0123456789")
            value += digit
            state = (self.physical(digit, hold=250000, released=0)
                     if self.fast_no_tone_input else self.physical(digit))
            elapsed = 0
            while not self.input_matches(state, field, value) and elapsed < 4000000:
                state = self.handset.step(50000)
                elapsed += 50000
            if not self.input_matches(state, field, value):
                self.snapshot(f"numeric-field-{field}-length-{len(value)}-timeout", state)
                self.fail(f"Actual field/count/glyph acceptance missing for {field}: {value!r}")
            self.accepted_inputs.append({"field": field, "text": value, "wait": elapsed,
                                         "steps": {cpu["image"]: cpu["steps"] for cpu in state["processors"]}})
            if len(value) % 8 == 0 or len(value) == (64 if field == 5 else 24):
                self.snapshot(f"numeric-field-{field}-accepted-{len(value)}", state)
        return value

    def reject_extra(self, field, key):
        before = self.field_pixels(self.handset.assert_healthy(), field)[:14]
        self.physical(key)
        self.handset.step(2000000)  # Let the real handler consume the rejected input.
        self.counter(0)
        state = self.handset.assert_healthy()
        self.assertEqual(self.field_pixels(state, field)[:14], before)
        self.snapshot(f"maximum-field-{field}-overflow-rejected", state)

    def finish(self):
        try:
            state = self.save_final_state()
            if any(cpu.get("halt") for cpu in state["processors"]):
                # Read-only terminal evidence can distinguish the known command
                # backlog from a TRX reset; it never repairs or resumes a core.
                bc5 = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
                def read(address, count):
                    return self.handset.request("POST", "/api/probe", {
                        "image": "bc5", "operation": "read", "address": address, "count": count})["values"]
                self.terminal_diagnostics = {"bc5_stack_start": bc5["sp"],
                                             "bc5_stack": read(bc5["sp"], min(128, 0x10000 - bc5["sp"]))}
                if self.model == "9555":
                    self.terminal_diagnostics["original_F898_queue_root_and_timer"] = read(0xF898, 3)
                    pointer = self.terminal_diagnostics["original_F898_queue_root_and_timer"][0]
                    chain = []
                    while pointer and len(chain) < 128 and pointer not in [x["address"] for x in chain]:
                        words = read(pointer, 9)
                        chain.append({"address": pointer, "words": words})
                        pointer = words[8]
                    self.terminal_diagnostics["original_F898_chain"] = chain
                Path(self.final_artifact + ".diagnostics.json").write_text(json.dumps(self.terminal_diagnostics, indent=2) + "\n")
        finally:
            self.close_handset()

    def test_all_six_maximum_fields_survive_completed_shutdown_and_original_warm_startup(self):
        self.maximum_fields_journey()

    def open_keypad_tones(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (2 if self.model == "9575" else 1)), "soft_left")
        self.expect(VOLUME_MENU)
        self.keys(*(["down"] * 4))
        self.expect(KEYPAD_TONE_MENU)
        self.keys("soft_left")

    def test_no_tone_all_six_maximum_fields_survive_completed_shutdown_and_original_warm_startup(self):
        self.open_keypad_tones()
        self.snapshot("original-default-single-tone", self.expect(KEYPAD_SINGLE_TONE))
        self.keys("down", "soft_left")
        self.expect(KEYPAD_TONE_MENU)
        self.keys("soft_left")
        self.snapshot("genuine-no-tone-saved-and-reopened", self.expect(KEYPAD_NO_TONE))
        self.no_tone_saved = True
        # Return to Setup's Volume and Tones selection, then continue to the
        # adjacent Language entry rather than spending another Home/menu trip.
        self.keys("soft_right", "soft_right")
        self.language_from_volume = True
        self.fast_no_tone_input = True
        self.maximum_fields_journey()
        self.open_keypad_tones()
        self.snapshot("no-tone-retained-after-maxima-and-warm-startup", self.expect(KEYPAD_NO_TONE))
        self.keys("up", "soft_left")
        self.expect(KEYPAD_TONE_MENU)
        self.keys("soft_left")
        self.snapshot("original-single-tone-restored-and-reopened", self.expect(KEYPAD_SINGLE_TONE))
        self.single_tone_restored = True
        self.home()
        self.snapshot("configured-maxima-complete-restored-single-tone-home")

    def maximum_fields_journey(self):
        self.assertEqual(tuple(map(len, VALUES)), (24, 24, 24, 24, 24, 64))
        self.assertEqual(len(set(PHONES)), 4)
        if self.language_from_volume:
            self.keys("down", "down", "soft_left", "down", "soft_left")
        else:
            self.keys("soft_left", *(["down"] * 6), "soft_left",
                      *(["down"] * (3 + (self.model == "9575"))), "soft_left", "down", "soft_left")
        self.expect(TEXT_MULTI_TAP)
        self.keys("down", "down", "down", "soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.home()
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left")
        self.type_keys(NAME_KEYS, settle=500000)
        self.counter(0)
        self.snapshot("maximum-name-entered")
        self.reject_extra(0, "2")
        for field, phone in enumerate(PHONES, 1):
            self.keys("down")
            self.type_numeric(field, phone[1:], prefix="+")
            self.counter(0)
            self.snapshot(f"maximum-phone-{field}-entered")
            self.reject_extra(field, "9")
        self.keys("down", "#", "#")
        email = self.type_numeric(5, EMAIL_LOCAL)
        self.keys("*", "down", "soft_left")
        email = self.type_numeric(5, EMAIL_DOMAIN, prefix=email + "@")
        self.keys("*", "soft_left", "#", "#")
        self.type_keys("23", settle=500000)
        self.counter(0)
        self.reject_extra(5, "4")
        self.snapshot("all-six-maxima-before-save")
        self.save()
        self.snapshot("all-six-maxima-saved-before-shutdown")
        self.home()
        power_resets = self.handset.state()["processor_link"]["power_resets"]
        self.shutdown_and_restart()
        self.assertEqual(self.boots, 2)
        self.assertEqual(self.handset.state()["processor_link"]["power_resets"], power_resets + 1)
        self.keys("soft_left", "soft_left")
        self.expect(LIST_HEADER, 0, 14)
        self.reopen()
        for field, value in enumerate(VALUES):
            if field:
                self.keys("down")
            self.counter(0)
            self.full_text(field, value, f"after-warm-startup-field-{field}-maximum")
        self.snapshot("all-six-retained-maxima-complete-glyph-readback")
        self.home()
        self.snapshot("retained-all-six-maxima-final-home")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555PhonebookLimitsPersistenceE2ETests(MaximumFieldPersistenceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575PhonebookLimitsPersistenceE2ETests(MaximumFieldPersistenceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
