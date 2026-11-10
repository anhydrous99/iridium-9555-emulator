"""Browser SIM fixture controls through original BC5/AVR/TRX and serial card."""

import json
import os
from pathlib import Path
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_messages_local_e2e import SCAN_READY
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_security_e2e import (
    FIRMWARE_IDENTITY_WARNING, IERCC_DISABLED, IERCC_NOT_CONFIGURED,
    SOS_MESSAGE_RECIPIENT_WARNING, STARTUP_SIM_ERROR,
)
from test_factory_sim_phonebook_e2e import SIMPhonebookChecks as _Phonebook


class SIMFixtureControlChecks:
    read = _Phonebook.read
    text = _Phonebook.text
    title = _Phonebook.title
    blank = staticmethod(_Phonebook.blank)
    open_sim = _Phonebook.open_sim
    back_home = _Phonebook.back_home

    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.evidence = []
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.addCleanup(self.save_evidence)
        state = self.handset.request("POST", "/api/fixtures", {"action": "sim", "present": True})
        self.assertEqual(state["mode"], "research")
        self.assertTrue(state["fixtures"]["sim"]["present"])
        self.assertFalse(state["satellite"]["firmware_connected"])
        self.peer = self.handset.session.sim_peer
        self.assertIsNotNone(self.peer)
        self.initial_records = dict(self.peer.card.records)
        self.initial_contents = dict(self.peer.card.contents)

    def save_evidence(self):
        path = self.handset.save_artifacts("fixture-final")
        peer = self.handset.session.sim_peer
        if peer:
            Path(str(path) + ".sim.json").write_text(json.dumps({
                "card_version": peer.card.version, "events": peer.card.events,
                "pending": list(peer.card.pending), "partial_command": list(peer.card.buffer),
            }, indent=2) + "\n")

    def healthy(self, *, require_lcd=True):
        state = self.handset.assert_healthy(require_lcd=require_lcd)
        self.assertEqual(state["mode"], "research")
        self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr", "trx"})
        self.assertEqual(state["processor_link"]["modem"], "trx")
        trx = next(cpu for cpu in state["processors"] if cpu["image"] == "trx")
        self.assertLess(trx["steps"], 260000000, "Fixture journey must remain before the known DSP boundary")
        self.assertEqual(trx["uart_tx_dropped"][3], 0)
        return state

    def press(self, key, *, hold=500000, settle=2000000):
        state = self.handset.press(key, hold_steps=hold, settle_steps=settle)
        self.healthy()
        return state

    def submit(self):
        return self.press("soft_left", hold=1000000)

    def record(self, label):
        state = self.healthy()
        path = self.handset.save_artifacts(f"{len(self.evidence):03d}-{label}", state)
        self.evidence.append({"label": label, "artifact": str(path)})
        return state

    def expect(self, label, predicate, oracle, *, budget=12000000):
        for elapsed in range(0, budget + 1, 200000):
            state = self.healthy()
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < budget:
                self.handset.step(200000)
        self.record(label + "-timeout")
        self.fail(f"Original SIM phonebook did not match {label}: {oracle}")

    def test_browser_sim_fixture_reaches_original_empty_phonebook(self):
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        alerts = {IERCC_NOT_CONFIGURED, IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING}
        seen = set()
        for _ in range(230):
            state = self.healthy(require_lcd=False)
            body = self.handset.screen_hash(state=state)
            self.assertNotEqual(body, STARTUP_SIM_ERROR, "Present synthetic SIM must not produce the absent-SIM dialog")
            self.assertNotEqual(body, FIRMWARE_IDENTITY_WARNING, "Original release metadata must be accepted")
            if body in alerts:
                self.assertNotIn(body, seen, "Repeated startup alert")
                seen.add(body)
                self.press("soft_right")
            # Home appears before the original SIM scan enables Phonebook.
            elif (self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS
                  and self.read("trx", 0x400AA9F8, 4) == [0, 0, 0, 1]
                  and self.read("bc5", SCAN_READY[self.model]) == [1]):
                break
            else:
                self.handset.step(1000000)
        else:
            self.fail("Original handset did not reach home with initialized SIM contacts")

        reads = [event["bytes"] for event in self.peer.card.events
                 if event["kind"] == "header" and event["selected"] == 0x6F3A
                 and event["bytes"][1] == 0xB2]
        self.assertEqual(reads[:2], [[0xA0, 0xB2, 1, 4, 32], [0xA0, 0xB2, 2, 4, 32]])
        self.assertEqual(self.read("trx", 0x400AA9F8, 8), [0, 0, 0, 1, 0, 0, 2, 100])
        self.open_sim()
        self.expect("browser-fixture-empty-sim-phonebook", lambda state: (
            self.title(state, "Phonebook") and self.text(state, "(Empty)", 16)
            and self.blank(state, 32, 111) and self.blank(state, 112, 127, 0, 70)
            and self.text(state, "Back", 112, 99, 28)),
            {"title": "Phonebook", "literal_empty_row": "(Empty)", "right_caption": "Back"})
        self.back_home()
        self.assertEqual(self.peer.card.records, self.initial_records)
        self.assertEqual(self.peer.card.contents, self.initial_contents)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Fixture9555ControlsE2ETests(SIMFixtureControlChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Fixture9575ControlsE2ETests(SIMFixtureControlChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
