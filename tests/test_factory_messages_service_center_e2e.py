"""Original handset Service Center form and actual external SMSP persistence.

HTTP keys drive factory BC5/AVR/TRX. The card acknowledges real UART3 writes;
an early modem callback or immediate GUI readback is not a persistence oracle.
No identity, authentication, RF, delivery or cold-power claim is made.
"""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from factory_sim_peer import FactorySIMPeer
from sim_service_center_card import INITIAL_SMSP, ServiceCenterSIM
from test_factory_messages_draft_persistence_e2e import MessagesDraftPersistenceChecks as _Startup
from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_messages_local_e2e import MESSAGES, SETTINGS, MessagesLocalChecks as _Messages
from test_factory_phonebook_capacity_e2e import OriginalASCII1


# The GUI emits CSCA="<text>" without TON. Original TRX defaults to81h and
# removes '+'. Its query returns quoted digits, which BC5 extracts without TON.
# These cases assert those exact bytes, not international-prefix preservation.
SAVED_SMSP = b"SMSC\xE1" + b"\xFF" * 12 + bytes.fromhex("04 81 76 98 F0") + b"\xFF" * 7 + b"\x00" * 3


class MessagesServiceCenterChecks:
    read = _Messages.read
    press = _Messages.press
    text = _Messages.text
    title = _Messages.title
    menu = _Messages.menu
    submit = _Messages.submit
    keys = _Editor.keys
    field = _Editor.field
    blank = staticmethod(_Editor.blank)
    reopen_messages = _Editor.reopen_messages
    expect = _Startup.expect
    original_home_and_scan = _Startup.original_home_and_scan
    boot_with_modem_alerts = _Startup.boot_with_modem_alerts
    shutdown_and_restart = _Startup.shutdown_and_restart

    def start(self, *, memory_failure):
        self.boots = 0
        self.evidence = []
        self.memory_failure = memory_failure
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.card = ServiceCenterSIM(smsp_write_memory_failure=memory_failure)
        self.initial_records = deepcopy(self.card.records)
        self.initial_contents = dict(self.card.contents)
        self.peer = FactorySIMPeer(self, self.handset, card=self.card)
        self.addCleanup(self.finish)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.card_observations = []

    def record(self, label):
        return _Messages.record(self, f"{len(self.evidence):03d}-{label}")

    def finish(self):
        path = None
        try:
            try:
                state = self.handset.state()
                path = self.handset.save_artifacts("final", state)
                self.final_images = state["images"]
            finally:
                self.peer.close()
        finally:
            try:
                self.peer_evidence = self.peer.evidence()
                if path:
                    Path(str(path) + ".peer.json").write_text(
                        json.dumps(self.peer_evidence, indent=2) + "\n")
                writes = [e for e in self.card.events if e["kind"] == "header"
                          and e["bytes"][1] in (0xDC, 0xD6, 0x32)]
                self.assertTrue(all(e["selected"] == 0x6F42 and
                                    e["bytes"] == [0xA0, 0xDC, 1, 4, 32] for e in writes),
                                "Only the declared absolute SMSP update is allowed")
                self.assertEqual(self.card.contents, self.initial_contents)
                self.assertEqual({k: v for k, v in self.card.records.items() if k != 0x6F42},
                                 {k: v for k, v in self.initial_records.items() if k != 0x6F42})
            finally:
                self.handset.close()
                self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                                       for image, worker in self.peer.workers.items()}
                self.assertTrue(all(self.worker_closure.values()))

    def home(self, label):
        return self.expect(label, lambda state: (
            self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS and state["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def settings_from_home(self):
        self.reopen_messages()
        self.keys("down", "down", "down", "down")
        self.menu(MESSAGES, 4, "messages-settings-selected")
        self.keys("soft_left")
        self.menu(SETTINGS, 0, "service-center-selected")

    def number(self, value, label):
        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, "Service Center") and
                    self.text(state, "Number:", 16, 4, 122) and self.field(state, value, 33) and
                    all(pixels[y * 128 + x] == 3 for y in (32, 48) for x in range(2, 128)) and
                    all(pixels[y * 128 + x] == 3 for y in range(32, 49) for x in (2, 127)) and
                    self.blank(state, 49, 111) and
                    self.text(state, "OK", 112, 2, 18) and self.text(state, "Clear", 112, 97, 30))
        return self.expect(label, matches, {"title": "Service Center", "label": "Number:",
            "complete_number": value, "actions": ["OK", "Clear"],
            "active_field_border": [2, 32, 127, 48],
            "allowed_caret": "exact five-pixel underline after text, on/off"}, max_steps=12000000)

    def open_number(self, expected, label):
        self.keys("soft_left")
        self.number(expected, label)

    def smsp_reads(self, events):
        result = []
        header = None
        for event in events:
            if event["kind"] == "header":
                header = event
            elif event["kind"] == "read-record" and header is not None and header["selected"] == 0x6F42:
                result.append({"header": header["bytes"], "response": event["bytes"]})
        return result

    def writes(self):
        return [e for e in self.card.events if e["kind"] == "header" and e["bytes"][1] in (0xDC, 0xD6, 0x32)]

    def observe_write(self, wire_start):
        # A genuine early setter callback can close the form before card TX.
        expected_kind = "smsp-write-memory-failure" if self.memory_failure else "updated-record"
        for elapsed in range(0, 12000001, 200000):
            self.handset.assert_healthy()
            self.peer.check()
            if (any(e["kind"] == expected_kind for e in self.card.events) and
                    not self.card.pending and not self.card.buffer and not self.card.selecting and
                    self.card._write is None):
                break
            self.assertLess(elapsed, 12000000, "Original SMSP write did not complete")
            self.handset.step(200000)
        expected = INITIAL_SMSP if self.memory_failure else SAVED_SMSP
        self.assertEqual(self.writes(), [{"kind": "header", "bytes": [0xA0, 0xDC, 1, 4, 32], "selected": 0x6F42}])
        self.assertEqual(self.card.records[0x6F42], (expected,))
        wire = deepcopy(self.peer.wire[wire_start:])
        transmitted = bytes(v for row in wire for v in row["tx"])
        received = bytes(v for row in wire for v in row["offered"][:row["accepted"]])
        header = bytes.fromhex("A0 DC 01 04 20")
        self.assertEqual(transmitted.count(header), 1)
        body = transmitted.split(header, 1)[1]
        if self.memory_failure:
            self.assertEqual(body, b"")
            self.assertNotIn(0xDC, received, "Rejected write must not receive a procedure ACK")
            self.assertTrue(received.endswith(b"\x92\x40"))
        else:
            self.assertEqual(body, SAVED_SMSP)
            self.assertTrue(received.endswith(b"\xDC\x90\x00"))
        self.card_observations.append({"label": "actual-SMSP-write", "wire": wire,
            "transmitted_body": list(body), "accepted_card_reply": list(received),
            "committed": not self.memory_failure, "final_record": list(expected)})
        self.record("actual-smsp-rejected" if self.memory_failure else "actual-smsp-committed")
        self.evidence[-1]["oracle"] = {"physical_write_header": list(header),
            "transmitted_body_length": len(body), "card_status": "9240" if self.memory_failure else "9000",
            "card_committed": not self.memory_failure, "early_callback_is_not_commit": True}

    def flow(self, *, memory_failure):
        self.start(memory_failure=memory_failure)
        self.original_home_and_scan()
        self.assertIn({"header": [0xA0, 0xB2, 1, 4, 32],
                       "response": [0xB2, *INITIAL_SMSP, 0x90, 0]}, self.smsp_reads(self.card.events))
        self.settings_from_home()
        self.open_number("12345", "initial-complete-card-number")
        self.keys("soft_right", "6")
        self.number("12346", "visible-unsaved-change")
        self.keys("red")
        self.menu(SETTINGS, 0, "number-edit-cancelled")
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.card.records[0x6F42], (INITIAL_SMSP,))
        self.open_number("12345", "cancel-retains-original-number")
        self.keys(*(["soft_right"] * 5))
        self.number("", "old-digits-cleared")
        # Original number handler inserts '+' on the physical long0 event;
        # its held flag prevents the release from also inserting a zero.
        self.press("0", hold=8000000, settle=500000)
        self.number("+", "original-long-zero-inserts-plus")
        self.keys("6", "7", "8", "9", "0")
        self.number("+67890", "complete-visible-new-service-center")
        self.assertEqual(self.writes(), [])
        wire_start = len(self.peer.wire)
        self.submit()
        self.menu(SETTINGS, 0, "setter-returned-to-settings", max_steps=12000000)
        self.observe_write(wire_start)
        self.open_number("67890", "immediate-original-ui-readback")
        self.keys("red", "red")
        self.home("home-before-completed-shutdown")
        event_start = len(self.card.events)
        self.shutdown_and_restart()
        self.assertEqual(self.boots, 2)
        expected = INITIAL_SMSP if memory_failure else SAVED_SMSP
        self.assertEqual(self.card.records[0x6F42], (expected,))
        self.assertIn({"header": [0xA0, 0xB2, 1, 4, 32],
                       "response": [0xB2, *expected, 0x90, 0]}, self.smsp_reads(self.card.events[event_start:]))
        self.assertEqual(self.read("trx", 0x400A94D0, 12), list(expected[17:29]))
        self.settings_from_home()
        self.open_number("12345" if memory_failure else "67890", "fresh-original-ui-number-after-warm-startup")
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.handset.state()["keys"], [])
        self.evidence[-1]["oracle"].update({"boots": 2, "original_fresh_SMSP_read_observed": True,
            "failed_write_not_persistent": memory_failure,
            "GUI_query_displays_digits_only": True,
            "GUI_setter_default_TON": 0x81,
            "international_prefix_preservation_asserted": False,
            "restart": "completed shutdown then existing initialize_ui warm startup"})

    def test_service_center_cancel_save_actual_card_commit_and_warm_startup_retention(self):
        self.flow(memory_failure=False)

    def test_service_center_rejected_card_write_is_not_retained_after_warm_startup(self):
        self.flow(memory_failure=True)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesServiceCenterE2ETests(MessagesServiceCenterChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesServiceCenterE2ETests(MessagesServiceCenterChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
