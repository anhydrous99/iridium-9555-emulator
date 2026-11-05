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

from factory_handset import FactoryHandset, HOME_CAPTIONS
from iridium.engine import Engine
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED
from test_factory_phonebook_fields_e2e import (
    PhonebookFieldChecks as _Fields, NAME, NAME_KEYS, PHONES,
    EMAIL_LOCAL, EMAIL_DOMAIN, EMAIL_64, LIST_HEADER, COUNTER,
)
from test_factory_phonebook_fields_persistence_e2e import SharedExtendedPersistenceChecks as _Extended
from test_factory_persistence_e2e import SharedPersistenceChecks as _Persistence
from test_factory_text_entry_e2e import TEXT_MULTI_TAP, TEXT_LANGUAGE_MENU
from test_factory_security_e2e import (
    FIRMWARE_IDENTITY_WARNING, IERCC_DISABLED, IERCC_NOT_CONFIGURED,
    SOS_MESSAGE_RECIPIENT_WARNING, STARTUP_SIM_ERROR,
)
from test_factory_settings_e2e import (
    VOLUME_MENU, KEYPAD_TONE_MENU, KEYPAD_SINGLE_TONE, KEYPAD_NO_TONE,
)


VALUES = (NAME, *PHONES, EMAIL_64)


class MaximumFieldPersistenceChecks:
    # Reuse helpers only; the prior modules' independent cases stay undiscovered.
    type_keys = _Fields.type_keys
    expect = _Persistence.expect
    home = _Persistence.home
    field_pixels = _Fields.field_pixels
    counter = _Fields.counter
    save = _Fields.save
    reopen = _Fields.reopen
    expected_counter = _Extended.expected_counter
    shutdown_and_restart = _Persistence.shutdown_and_restart

    def setUp(self):
        self.evidence = []
        self.accepted_inputs = []
        self.cursor_observations = []
        self.cursor_field = None
        self.no_tone_saved = False
        self.single_tone_restored = False
        self.fast_no_tone_input = False
        self.language_from_volume = False
        self.boots = 0
        self.request_method = Engine.request
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.workers = {
            image: {"pid": engine._process.pid,
                    "executable_sha256": sha256(Path(f"/proc/{engine._process.pid}/exe").read_bytes()).hexdigest()}
            for image, engine in self.handset.session.engines.items()
        }
        self.addCleanup(self.finish)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.assertEqual(self.font.message(("Entry added", "successfully"), divider=False), ENTRY_ADDED)
        for remaining in (0, 1):
            self.assertEqual(sha256(self.expected_counter(remaining)).hexdigest(), COUNTER[remaining])
        self.boot_with_modem_alerts()

    def physical(self, key, *, hold=300000, released=100000):
        self.assertTrue(self.handset.key(key, True)["delivered"])
        try:
            self.handset.step(hold)
        finally:
            self.assertTrue(self.handset.key(key, False)["delivered"])
        return self.handset.step(released) if released else self.handset.assert_healthy()

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

    def snapshot(self, label, state=None):
        state = self.handset.state() if state is None else state
        label = f"{len(self.evidence):03d}-{label}"
        target = self.handset.save_artifacts(label, state)
        self.evidence.append({"label": label, "artifact": str(target), "boot": self.boots,
                              "steps": {cpu["image"]: cpu["steps"] for cpu in state["processors"]},
                              "frame_sha256": sha256(bytes(state["lcd"]["pixels"])).hexdigest()})
        print(f"{self.model}: {label} boot{self.boots} TRX "
              f"{next(cpu['steps'] for cpu in state['processors'] if cpu['image'] == 'trx')}", flush=True)
        return target

    def finish(self):
        try:
            state = self.handset.state()
            self.final_state = state
            self.final_images = state["images"]
            self.final_artifact = str(self.handset.save_artifacts("final", state))
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
            server_thread = self.handset.thread
            self.handset.close()
            self.http_server_thread_closed = server_thread is not None and not server_thread.is_alive()
            self.engine_request_method_unchanged = Engine.request is self.request_method
            self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                                   for image, worker in self.workers.items()}
            self.assertTrue(all(self.worker_closure.values()))
            self.assertTrue(self.http_server_thread_closed)
            self.assertTrue(self.engine_request_method_unchanged)

    def boot_with_modem_alerts(self):
        handset = self.handset
        if self.boots:
            state = handset.state()
            self.assertEqual(next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")["power_state"], 8)
            self.assertFalse(state["ui_initialized"])
            self.snapshot("completed-shutdown-before-original-warm-startup", state)
        handset.control("initialize_ui")
        handset.control("pause")
        alerts = {STARTUP_SIM_ERROR: "absent-sim", FIRMWARE_IDENTITY_WARNING: "firmware-identity"}
        required = {"absent-sim"}
        if self.model == "9575":
            alerts.update({IERCC_NOT_CONFIGURED: "iercc-not-configured", IERCC_DISABLED: "iercc-disabled",
                           SOS_MESSAGE_RECIPIENT_WARNING: "sos-message-recipient"})
            required = {"iercc-not-configured", "iercc-disabled", "sos-message-recipient"}
        seen = set()
        for elapsed in range(0, 200000001, 1000000):
            state = handset.assert_healthy(require_lcd=False)
            body = handset.screen_hash(state=state)
            if body in alerts:
                label = alerts[body]
                self.assertNotIn(label, seen, "Original startup repeated an alert")
                seen.add(label)
                self.snapshot("startup-" + label, state)
                self.assertTrue(handset.key("soft_right", True)["delivered"])
                handset.step(500000)
                self.assertTrue(handset.key("soft_right", False)["delivered"])
                handset.step(500000)
            elif required <= seen and handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr", "trx"})
                self.assertTrue(state["processor_link"]["connected"])
                self.assertEqual(state["keys"], [])
                self.assertEqual({image: engine._process.pid for image, engine in handset.session.engines.items()},
                                 {image: worker["pid"] for image, worker in self.workers.items()})
                self.boots += 1
                self.snapshot(f"original-boot-{self.boots}-home", state)
                return
            else:
                handset.step(1000000)
        self.snapshot("unknown-startup-screen")
        self.fail("Original modem startup did not reach Home after recognized alerts")

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
