"""Local BC5 draft text retained across completed shutdown and warm startup.

Real HTTP keypad input and original LCD glyphs; the external SIM stays read-only.
GUI Save as draft uses local phone flash, separately from modem CMGW storage.
"""

import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_drafts_e2e import MessagesDraftChecks as _Drafts
from test_factory_messages_local_e2e import (
    ALERTS, CAPACITY, SCAN_READY, MessagesLocalChecks as _Messages,
)
from test_factory_persistence_e2e import SharedPersistenceChecks as _Persistence


class MessagesDraftPersistenceChecks:
    # Reuse the calibrated helpers without inheriting their independent tests.
    finish = _Messages.finish
    read = _Messages.read
    record = _Messages.record
    press = _Messages.press
    text = _Messages.text
    title = _Messages.title
    menu = _Messages.menu
    open_messages = _Messages.open_messages
    keys = _Drafts.keys
    blank = staticmethod(_Drafts.blank)
    field = _Drafts.field
    options = _Drafts.options
    editor = _Drafts.editor
    numeric_mode = _Drafts.numeric_mode
    save = _Drafts.save
    create_saved = _Drafts.create_saved
    drafts = _Drafts.drafts
    reopen_messages = _Drafts.reopen_messages
    reopen_draft = _Drafts.reopen_draft
    actions = _Drafts.actions
    edit = _Drafts.edit
    shutdown_and_restart = _Persistence.shutdown_and_restart

    def setUp(self):
        self.boots = 0
        _Messages.setUp(self)

    def expect(self, label, predicate, oracle, *, max_steps=4000000):
        # Warm startup can retain absolute modem counters; bound each UI wait.
        for elapsed in range(0, max_steps + 1, 200000):
            state = self.handset.assert_healthy()
            self.peer.check()
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < max_steps:
                self.handset.step(200000)
        self.handset.save_artifacts(label + "-timeout", state)
        self.fail(f"Original LCD did not match {label}: {oracle}")

    def original_home_and_scan(self):
        if self.boots:
            state = self.handset.state()
            primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
            self.assertEqual(primary["power_state"], 8)
            self.assertFalse(state["ui_initialized"])
            target = self.handset.save_artifacts("completed-shutdown-before-warm-startup", state)
            self.evidence.append({"label": "completed-shutdown-before-warm-startup",
                "artifact": str(target), "oracle": {"bc5_power_state": 8, "ui_initialized": False}})
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        initial = self.handset.state()
        origin = next(cpu["steps"] for cpu in initial["processors"] if cpu["image"] == "bc5")
        seen = set()
        home_seen = False
        while True:
            state = self.handset.assert_healthy(require_lcd=False)
            elapsed = next(cpu["steps"] for cpu in state["processors"] if cpu["image"] == "bc5") - origin
            self.assertTrue(0 <= elapsed <= 240000000,
                            "Original startup/scan exceeded its relative240M BC5 instruction budget")
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, seen, "Repeated recognized startup modal")
                seen.add(body)
                self.record(f"boot-{self.boots + 1}-startup-" + ALERTS[body])
                self.press("soft_right")
            elif self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                if not home_seen:
                    self.record(f"boot-{self.boots + 1}-home-before-original-scan")
                    home_seen = True
                if self.read("bc5", SCAN_READY[self.model]) == [1]:
                    break
                self.handset.step(2000000)
            else:
                self.assertFalse(home_seen, "Original scan wait left Home for an unknown screen")
                self.handset.step(1000000)
            self.peer.check()
        self.assertEqual(self.read("bc5", CAPACITY[self.model]), [2])
        self.assertEqual(self.read("trx", 0x400AA2D6), [2])
        self.assertEqual(self.read("trx", 0x400AA2D3), [3])
        self.assertEqual(self.read("trx", 0x400AA30C, 4), [0, 0, 0, 1])
        self.boots += 1
        self.record(f"boot-{self.boots}-original-scan-ready-at-home")
        self.evidence[-1]["oracle"] = {"boots": self.boots, "scan_ready": True,
                                       "capacity": 2, "relative_bc5_steps": elapsed}

    def boot_with_modem_alerts(self):
        # The existing shutdown helper calls this after power_state8; its
        # initialize_ui path resets volatile state while preserving guest flash.
        self.original_home_and_scan()

    def test_saved_local_draft_survives_completed_shutdown_and_warm_startup(self):
        self.create_saved()
        state = self.handset.assert_healthy()
        self.assertEqual(self.handset.screen_hash(113, 128, state), HOME_CAPTIONS)
        self.assertEqual(state["keys"], [])
        self.record("saved-local-flash-draft-before-shutdown")
        self.shutdown_and_restart()
        self.assertEqual(self.boots, 2)
        self.reopen_draft("123")
        self.edit("123")
        state = self.record("retained-full-draft-after-warm-startup")
        self.assertTrue(state["ui_initialized"])
        self.assertEqual(state["keys"], [])
        self.evidence[-1]["oracle"] = {"boots": 2, "complete_saved_text": "123",
            "title": "Edit", "input_mode": "abc", "remaining_characters": 997,
            "persistence": "local phone flash across completed shutdown and initialize_ui warm startup",
            "preview_and_full_editor_both_asserted": True}


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 local-draft persistence")
class Factory9555MessagesDraftPersistenceE2ETests(MessagesDraftPersistenceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 local-draft persistence")
class Factory9575MessagesDraftPersistenceE2ETests(MessagesDraftPersistenceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
