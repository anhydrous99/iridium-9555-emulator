"""Every local audible-call-alert preference through factory HTTP controls.

All three original processors run with no SIM peer. Saved radio marks and
complete labels prove preference storage, cancellation and bounds; no active
call, elapsed alert, sound, authentication or network behavior is supplied.
"""

from hashlib import sha256
import os
from pathlib import Path
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from factory_modem import FactoryModemChecks
from iridium.assets import BC5Assets
from iridium.engine import Engine
from test_factory_call_settings_e2e import (
    SharedCallSettingsChecks as _Calls, AUDIBLE_SINGLE_MENU, AUDIBLE_REPETITIVE_MENU,
)
from test_factory_information_help_e2e import original_strings
from test_factory_messages_local_e2e import MessagesLocalChecks as _Text
from test_factory_phonebook_capacity_e2e import OriginalASCII1


LABELS = ("Off", "1 minute", "5 minutes", "10 minutes", "15 minutes", "30 minutes", "60 minutes")
MINUTES = (0, 1, 5, 10, 15, 30, 60)
PARENTS = {"Single Alert": AUDIBLE_SINGLE_MENU, "Repetitive Alert": AUDIBLE_REPETITIVE_MENU}


class CallAlertChoiceChecks:
    # Reuse only helpers, without discovering the older independent tests.
    # Coupled-modem runs exposed unconsumed edge-only Save/Up contacts. Use
    # the established held contact while retaining the 2M budget for every key.
    expect = _Calls.expect
    open_history = _Calls.open_history
    open_meters = _Calls.open_meters
    expect_meter = _Calls.expect_meter
    text = _Text.text
    title = _Text.title
    boot_with_modem_alerts = FactoryModemChecks.boot_with_modem_alerts

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key, hold_steps=500000, settle_steps=1500000)

    def setUp(self):
        self.evidence = []
        self.saved_values = []
        self.boots = 0
        self.request_method = Engine.request
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.workers = {
            image: {"pid": engine._process.pid,
                    "executable_sha256": sha256(Path(f"/proc/{engine._process.pid}/exe").read_bytes()).hexdigest()}
            for image, engine in self.handset.session.engines.items()
        }
        self.addCleanup(self.finish)
        firmware = self.handset.session.firmware["bc5"]
        self.font = OriginalASCII1(firmware)
        strings = original_strings(firmware, 0)
        self.assertEqual(tuple(strings[0x10A3 + i] for i in range(7)), LABELS)
        self.assertEqual(tuple(strings[0x10AA + i] for i in range(7)), LABELS)
        self.assertEqual((strings[0x1149], strings[0x114A]), ("Single Alert", "Repetitive Alert"))
        assets = BC5Assets(firmware.data, firmware.profile)
        radio = 7 if self.model == "9575" else 5
        self.assertEqual(sha256(assets.file_bytes(radio)).hexdigest(),
                         "7b0ee05692b8f09f5909302a7f6f051dc662b5422dd03dbd49c271ed63ec4e99")
        self.radio = tuple(assets.bitmap(radio, frame).pixels for frame in range(2))
        self.boot_with_modem_alerts()

    def snapshot(self, label, state=None):
        state = self.handset.state() if state is None else state
        unique = f"{len(self.evidence):03d}-{label}"
        path = self.handset.save_artifacts(unique, state)
        self.evidence.append({"label": unique, "artifact": str(path),
                              "steps": {cpu["image"]: cpu["steps"] for cpu in state["processors"]},
                              "frame_sha256": sha256(bytes(state["lcd"]["pixels"])).hexdigest()})
        print(f"{self.model}: {unique} TRX "
              f"{next(cpu['steps'] for cpu in state['processors'] if cpu['image'] == 'trx')}", flush=True)
        return path

    def parent(self, family, label):
        state = self.expect(PARENTS[family])
        self.snapshot(label, state)
        self.evidence[-1]["oracle"] = {"kind": "audible-parent", "focused_family": family,
                                       "body_sha256": PARENTS[family]}

    def choice(self, family, selected, stored, label):
        # Original B99F4 may position the viewport around a reopened selection.
        # Every visible row and saved mark must match that actual viewport;
        # focus and stored value are deliberately independent while drafting.
        for elapsed in range(0, 20000001, 200000):
            state = self.handset.assert_healthy()
            pixels = state["lcd"]["pixels"]
            for top in range(max(0, selected - 4), selected + 1):
                visible = LABELS[top:top + 5]
                if (self.title(state, family) and
                    all(self.text(state, value, 16 + 17 * row, 13, 107,
                                  selected=top + row == selected)
                        for row, value in enumerate(visible)) and
                    all(bytes(pixels[(19 + 17 * row + y) * 128 + 2 + x]
                              for y in range(9) for x in range(9)) == self.radio[top + row == stored]
                        for row in range(len(visible))) and
                    not any(pixels[y * 128 + x] for y in range(16 + 17 * len(visible), 111)
                            for x in range(13, 120)) and
                    self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)):
                    self.assertEqual(state["keys"], [])
                    self.snapshot(label, state)
                    self.evidence[-1]["oracle"] = {"kind": "call-alert-choices", "title": family,
                        "ordered_labels": LABELS, "first_visible_index": top,
                        "visible_labels": visible, "focused_index": selected, "stored_index": stored,
                        "stored_minutes": MINUTES[stored], "stored_mark_visible": top <= stored < top + len(visible),
                        "original_radio_marks": True, "unused_text_rows_blank": True}
                    return state
            if elapsed < 20000000:
                self.handset.step(200000)
        self.snapshot(label + "-timeout", state)
        self.fail(f"Original {family} labels/focus/saved marks did not match selected={selected}, stored={stored}")

    def all_choices(self, family):
        self.open_meters()
        self.keys(*(["down"] * 5), "soft_left")
        if family == "Repetitive Alert":
            self.keys("down")
        self.parent(family, "audible-family-selected")
        self.keys("soft_left")
        self.choice(family, 0, 0, "original-Off-selected-and-saved")
        self.keys("up")
        self.choice(family, 0, 0, "Off-upper-bound-clamps")
        for index in range(1, len(LABELS)):
            self.keys("down")
            self.choice(family, index, index - 1, f"draft-{MINUTES[index]}-minutes-keeps-prior-stored-mark")
            self.keys("soft_left")
            self.parent(family, f"saved-{MINUTES[index]}-minutes-returned-to-parent")
            self.keys("soft_left")
            self.choice(family, index, index, f"reopened-{MINUTES[index]}-minutes-checked-and-focused")
            self.saved_values.append(MINUTES[index])
        self.keys("down")
        self.choice(family, 6, 6, "sixty-minute-lower-bound-clamps")

        self.keys(*(["up"] * 6))
        self.choice(family, 0, 6, "visible-Off-draft-before-cancel")
        self.keys("soft_right")
        self.parent(family, "Off-draft-cancelled-to-parent")
        self.keys("soft_left")
        self.choice(family, 6, 6, "cancelled-Off-draft-retains-checked-sixty-minutes")

        self.keys(*(["up"] * 6))
        self.choice(family, 0, 6, "Off-restoration-draft")
        self.keys("soft_left")
        self.parent(family, "Off-restoration-saved-parent")
        self.keys("soft_left")
        self.choice(family, 0, 0, "restored-Off-reopened-checked-and-focused")
        self.keys("up")
        self.choice(family, 0, 0, "restored-Off-upper-bound-clamps")
        self.assertEqual(self.saved_values, [1, 5, 10, 15, 30, 60])
        self.keys("red")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])
        self.snapshot("all-alert-choices-restored-Off-finished-home", state)

    def test_all_single_alert_choices_save_reopen_cancel_restore_and_clamp(self):
        self.all_choices("Single Alert")

    def test_all_repetitive_alert_choices_save_reopen_cancel_restore_and_clamp(self):
        self.all_choices("Repetitive Alert")

    def finish(self):
        try:
            state = self.handset.state()
            self.final_state = state
            self.final_images = state["images"]
            self.final_artifact = str(self.handset.save_artifacts("final", state))
        finally:
            thread = self.handset.thread
            self.handset.close()
            self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                                   for image, worker in self.workers.items()}
            self.http_server_thread_closed = thread is not None and not thread.is_alive()
            self.engine_request_method_unchanged = Engine.request is self.request_method
            self.assertTrue(all(self.worker_closure.values()))
            self.assertTrue(self.http_server_thread_closed)
            self.assertTrue(self.engine_request_method_unchanged)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555CallAlertChoicesE2ETests(CallAlertChoiceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575CallAlertChoicesE2ETests(CallAlertChoiceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")
