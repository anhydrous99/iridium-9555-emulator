"""Original handset persistence with the explicitly synthetic serial modem.

These are training-mode regressions, not evidence of TRX/DSP execution or RF.
They retain the research tests' complete original-font draft readback checks.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from iridium.assets import BC5Assets
from test_factory_messages_draft_limits_e2e import MessagesDraftLimitChecks as _Limits
from test_factory_messages_local_e2e import ALERTS, SCAN_READY
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED


class TrainingPersistenceChecks(_Limits):
    # Keep the unchanged research journeys in their own explicitly named suite.
    test_201_character_local_draft_crosses_flash_chunk_and_reopens_every_glyph = None
    test_1000_character_local_draft_limit_rejects_extra_and_reopens_every_glyph = None

    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "training-final")
        self.handset.request("POST", "/api/control", {"action": "mode", "mode": "training"})
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        firmware = self.handset.session.firmware["bc5"]
        assets = BC5Assets(firmware.data, firmware.profile)
        radio_id = 7 if self.model == "9575" else 5
        self.radio = tuple(assets.bitmap(radio_id, frame).pixels for frame in range(2))
        self.evidence, self.input_holds, self.viewport_coverage, self.heap_diagnostics = [], [], [], []
        self._views = {}

    def healthy(self):
        state = self.handset.assert_healthy()
        self.assertEqual(state["mode"], "training")
        self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr"})
        self.assertEqual(state["processor_link"]["modem"], "offline-training")
        self.assertFalse(state["processor_link"].get("error"))
        return state

    def record(self, label):
        state = self.healthy()
        self.evidence.append({"label": label, "artifact": str(self.handset.save_artifacts(
            f"{len(self.evidence):04d}-{label}", state))})
        print(f"{self.model} training: {label}", flush=True)
        return state

    def press(self, key, *, hold=500000, settle=2000000):
        return self.handset.press(key, hold_steps=hold, settle_steps=settle)

    def original_home_and_scan(self):
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        seen = set()
        for _ in range(250):
            state = self.handset.assert_healthy(require_lcd=False)
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, seen, "Repeated startup modal")
                seen.add(body)
                self.press("soft_right")
            elif (self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS
                  and self.read("bc5", SCAN_READY[self.model]) == [1]):
                self.record("original-home-and-scan-ready")
                return
            else:
                self.handset.step(1000000)
        self.handset.save_artifacts("training-startup-timeout")
        self.fail("Training modem did not complete original handset startup and SMS scan")

    def enter_one(self, key, remaining):
        _Limits.enter_one(self, key, remaining)
        # The same released execution budget used by browser key events.
        self.handset.step(2000000)
        self.healthy()

    def test_training_201_character_draft_saves_and_reopens_every_glyph(self):
        _Limits.test_201_character_local_draft_crosses_flash_chunk_and_reopens_every_glyph(self)
        self.assertEqual(len(self.input_holds), 201)
        self.assertEqual(self.viewport_coverage[-1]["covered_indices"], list(range(201)))

    def test_training_restart_retains_contact_and_rebuilds_original_index(self):
        self.original_home_and_scan()
        self.keys("soft_left", "soft_left")
        self.handset.wait_screen(EMPTY_PHONEBOOK, max_steps=2000000)
        self.keys("soft_left", "soft_left", "2", "3", "4", "down", "1", "2", "3", "soft_left")
        self.handset.wait_screen(ENTRY_ADDED, max_steps=2000000)
        self.keys("soft_right")
        self.handset.wait_screen(ADG_SELECTED, max_steps=2000000)
        self.keys("red")
        self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=4000000)
        workers = dict(self.handset.session.engines)
        self.handset.control("restart")
        self.handset.control("pause")
        self.original_home_and_scan()
        for image, worker in workers.items():
            self.assertIs(self.handset.session.engines[image], worker, "Restart must retain worker flash")
        self.keys("soft_left", "soft_left")
        self.handset.wait_screen(ADG_SELECTED, max_steps=4000000)
        self.keys("soft_left", "down", "down", "soft_left")
        self.handset.wait_screen("43c71edf6ac92194c1abec64dc583fd5baab48ab44d7286c4d8f335b18fed362",
                                 first=16, last=27, max_steps=2000000)
        self.handset.wait_screen("4de915bd746339b62d06fa4d2421c33fdf8efb3e228659e016f08bf000f2f76c",
                                 first=32, last=43, max_steps=2000000)
        self.record("contact-retained-after-restart")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Training9555PersistenceE2ETests(TrainingPersistenceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Training9575PersistenceE2ETests(TrainingPersistenceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
