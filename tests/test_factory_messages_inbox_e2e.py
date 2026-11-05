"""Stored synthetic SIM Inbox actions through the original three-core handset.

The fixture is a preloaded EF_SMS SMS-DELIVER, not network reception. Physical
UART3 card inputs service original commands; Send and Call are never selected.
"""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from factory_sim_peer import FactorySIMPeer
from sim_message_card import MessageSIM
from test_factory_messages_local_e2e import MessagesLocalChecks as _Local
from test_factory_messages_drafts_e2e import MessagesDraftChecks as _Draft
from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_phonebook_capacity_e2e import OriginalASCII1


# TS100977 10.5.3:03 unread/01 read,176-byte record. TS23.040 9.2.2.1:
# SMSC+67890,DELIVER(MMS1),OA+12345,PID0,DCS0,SCTS2024-01-02T03:04:05Z,
# UDL3 and GSM7 packed "adg". The remaining SIM record is unused FF padding.
DELIVER_PDU = bytes.fromhex("04 91 76 98 F0 04 05 91 21 43 F5 00 00 42 10 20 30 40 50 00 03 61 F2 19")
UNREAD_RECORD = b"\x03" + DELIVER_PDU + b"\xFF" * (175 - len(DELIVER_PDU))
READ_RECORD = b"\x01" + UNREAD_RECORD[1:]
EMPTY_RECORD = b"\x00" + b"\xFF" * 175
# Original CMGD changes the free/status byte; the old PDU bytes remain.
DELETED_RECORD = b"\x00" + UNREAD_RECORD[1:]


class MessagesInboxChecks:
    read = _Local.read
    press = _Local.press
    submit = _Local.submit
    text = _Local.text
    title = _Local.title
    keys = _Editor.keys
    blank = staticmethod(_Editor.blank)
    field = _Editor.field
    options = _Editor.options
    original_home_and_scan = _Local.original_home_and_scan
    expect = _Draft.expect
    editor = _Draft.editor

    def setUp(self):
        self.evidence = []
        self.card_observations = []
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.card = MessageSIM()
        # External card contents are declared before its physical insertion.
        self.card.records[0x6F3C] = (UNREAD_RECORD, EMPTY_RECORD)
        self.initial_records = deepcopy(self.card.records)
        self.initial_contents = dict(self.card.contents)
        self.peer = FactorySIMPeer(self, self.handset, card=self.card)
        self.addCleanup(self.finish)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.assertEqual(len(UNREAD_RECORD), 176)
        packed = int.from_bytes(DELIVER_PDU[-3:], "little")
        self.assertEqual("".join(chr((packed >> (7 * i)) & 127) for i in range(3)), "adg")

    def record(self, label):
        return _Local.record(self, f"{len(self.evidence):03d}-{label}")

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
                    Path(str(path) + ".peer.json").write_text(json.dumps(self.peer_evidence, indent=2) + "\n")
                writes = [event for event in self.card.events if event["kind"] == "header"
                          and event["bytes"][1] in (0xDC, 0xD6, 0x32)]
                self.assertTrue(all(event["selected"] in (0x6F3C, 0x6F43) for event in writes))
                self.assertEqual({key: rows for key, rows in self.card.records.items() if key != 0x6F3C},
                                 {key: rows for key, rows in self.initial_records.items() if key != 0x6F3C})
                self.assertEqual({key: value for key, value in self.card.contents.items() if key != 0x6F43},
                                 {key: value for key, value in self.initial_contents.items() if key != 0x6F43})
            finally:
                self.handset.close()
                self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                                       for image, worker in self.peer.workers.items()}
                self.assertTrue(all(self.worker_closure.values()))

    def home(self, label):
        return self.expect(label, lambda state: (
            self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS and state["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def messages(self, selected, unread, label, *, max_steps=12000000):
        labels = ("Create Message", "Inbox (1 unread)" if unread else "Inbox", "Drafts", "Outbox", "Settings")
        return self.expect(label, lambda state: (
            self.title(state, "Messages") and
            all(self.text(state, value, 16 + 17 * row, selected=row == selected)
                for row, value in enumerate(labels)) and self.blank(state, 101, 111) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Messages", "ordered_labels": labels, "focused_index": selected,
             "unread": unread, "unused_rows_blank": True}, max_steps=max_steps)

    def open_messages(self, *, unread):
        self.keys("soft_left", "down", "down", "soft_left")
        self.messages(0, unread, "messages-original-unread-count")

    def inbox(self, label):
        _, width = self.font.render("Read", 128)
        return self.expect(label, lambda state: (
            self.title(state, "Inbox") and self.text(state, "adg", 16, 13, 107, selected=True) and
            self.blank(state, 33, 111) and self.text(state, "Read", 112, 2, width) and
            self.blank(state, 112, 127, 2 + width, 97) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Inbox", "complete_preview": "adg", "focused_index": 0,
             "actions": ["Read", "Back"], "unused_rows_blank": True}, max_steps=12000000)

    def open_inbox(self, *, unread):
        self.open_messages(unread=unread)
        self.keys("down")
        self.messages(1, unread, "inbox-selected")
        self.keys("soft_left")
        self.inbox("preloaded-original-sim-message-listed")
        self.observe_sms(READ_RECORD, "inbox-enumeration-consumed-card-and-read-status")

    def reader(self, label):
        glyphs, _ = self.font.render("adg", 122)
        caret = bytearray(glyphs)
        for y in range(15):
            caret[y * 122] = 3

        def matches(state):
            pixels = state["lcd"]["pixels"]
            body = bytes(pixels[(16 + y) * 128 + 4 + x] for y in range(15) for x in range(122))
            return (self.title(state, "+12345") and body in (glyphs, bytes(caret)) and
                    self.blank(state, 32, 110, 4, 126) and
                    all(pixels[y * 128 + x] == 3 for y in range(15, 112) for x in (3, 126)) and
                    all(pixels[y * 128 + x] == 3 for y in (15, 111) for x in range(3, 127)) and
                    self.text(state, "Options", 112, 2, 45) and self.text(state, "Back", 112, 99, 28))
        return self.expect(label, matches, {"title": "+12345", "complete_text": "adg",
            "read_only_body": True, "body_border": [3, 15, 126, 111],
            "allowed_caret": "exact vertical line at initial position0, on/off (84DD0 callsB87F6 with0)",
            "actions": ["Options", "Back"], "unused_rows_blank": True}, max_steps=12000000)

    def actions(self, selected, label):
        labels = ("Reply", "Forward", "Call", "Delete", "Delete All")
        return self.expect(label, lambda state: (
            self.title(state, "+12345") and
            all(self.text(state, value, 16 + 17 * row, selected=row == selected)
                for row, value in enumerate(labels)) and self.blank(state, 101, 111) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "+12345", "ordered_labels": labels, "focused_index": selected,
             "unused_rows_blank": True})

    def observe_sms(self, expected, label):
        # Original completion can precede the asynchronous physical card write.
        for elapsed in range(0, 12000001, 200000):
            self.handset.assert_healthy()
            self.peer.check()
            if (self.card.records[0x6F3C] == (expected, EMPTY_RECORD) and
                    self.card._write is None and not self.card.pending and not self.card.buffer):
                break
            self.assertLess(elapsed, 12000000, "Original card update did not complete")
            self.handset.step(200000)
        self.assertEqual(self.card.records[0x6F3C], (expected, EMPTY_RECORD))
        reads, writes, header = [], [], None
        for event in self.card.events:
            if event["kind"] == "header":
                header = event
                if header["bytes"][1] in (0xDC, 0xD6, 0x32):
                    writes.append(deepcopy(header))
            elif (event["kind"] == "read-record" and header is not None
                  and header["selected"] == 0x6F3C):
                reads.append({"header": header["bytes"], "response": event["bytes"]})
        self.assertTrue(any(row["response"] == [0xB2] + list(UNREAD_RECORD) + [0x90, 0]
                            for row in reads), "Original TRX must read the declared unread record")
        self.assertTrue(any(row["bytes"] == [0xA0, 0xDC, 1, 4, 176]
                            and row["selected"] == 0x6F3C for row in writes))
        self.record(label)
        observation = {"records": [list(row) for row in self.card.records[0x6F3C]],
                       "expected_first_record": list(expected), "reads": reads, "writes": writes,
                       "external_card_only": True}
        self.evidence[-1]["sms_card_observation"] = observation
        self.card_observations.append(observation)

    def original_recipients(self, *, present, label):
        address = 0xF78C if self.model == "9555" else 0xF7A2
        context = self.read("bc5", address)[0]
        self.assertNotEqual(context, 0)
        head = self.read("bc5", context + 0x13)[0]
        observation = {"read_only": True, "context_pointer_address": address,
                       "context": context, "head": head}
        if present:
            self.assertNotEqual(head, 0)
            node = self.read("bc5", head, 5)
            self.assertEqual(node[0:2], [0, 0])
            self.assertNotEqual(node[2], 0)
            self.assertEqual(node[3:], [0, 0])
            number = self.read("bc5", node[2], 7)
            self.assertEqual(number, list(map(ord, "+12345")) + [0])
            observation.update({"node": node, "number": number, "name": None})
        else:
            self.assertEqual(head, 0)
        self.record(label)
        self.evidence[-1]["original_recipient_list"] = observation

    def discard_editor(self, label):
        self.keys("soft_left")
        self.options(0, label + "-options")
        exit_index = 6 if self.model == "9575" else 5
        self.keys(*(["down"] * exit_index))
        self.options(exit_index, label + "-exit-selected")
        self.keys("soft_left")
        self.home(label + "-home")

    def empty_folder(self, label):
        return self.expect(label + "-empty", lambda state: (
            self.title(state, label) and self.text(state, "(empty)", 16, selected=True) and
            self.blank(state, 32, 110)),
            {"title": label, "placeholder": "(empty)", "unused_rows_blank": True}, max_steps=12000000)

    def test_preloaded_sim_inbox_read_reply_forward_cancel_preserves_stored_message(self):
        self.original_home_and_scan()
        self.open_inbox(unread=True)
        self.keys("soft_left")
        self.reader("complete-stored-message-read")
        self.original_recipients(present=True, label="read-original-sender-node")
        self.keys("soft_right")
        self.inbox("read-back-keeps-complete-message-preview")
        self.keys("soft_left")
        self.reader("stored-message-reopened-before-reply")
        self.keys("soft_left")
        self.actions(0, "reply-selected-never-send")
        self.keys("soft_left")
        # Original mode2 retains the loaded body and sender; it is not a blank
        # reply oracle. Never select its Send: mode2 dispatches directly to TX.
        self.editor("adg", "reply-original-body-count", title="Reply")
        self.original_recipients(present=True, label="reply-retains-exact-original-sender")
        self.keys("2")
        self.editor("adga", "reply-edited-complete-body", title="Reply")
        self.keys("soft_left")
        self.options(0, "reply-options-without-send")
        self.keys("soft_right")
        self.editor("adga", "reply-options-back-keeps-edit", title="Reply")
        self.discard_editor("reply-exit-without-saving")

        self.open_inbox(unread=False)
        self.keys("soft_left")
        self.reader("original-body-unchanged-after-reply-exit")
        self.keys("soft_left", "down")
        self.actions(1, "forward-selected")
        self.keys("soft_left")
        self.editor("adg", "forward-complete-original-body", title="Forward")
        self.original_recipients(present=False, label="forward-clears-original-recipient-list")
        self.keys("soft_left")
        self.options(0, "forward-options-without-send")
        self.keys("soft_right")
        self.editor("adg", "forward-options-back-keeps-body", title="Forward")
        self.discard_editor("forward-exit-without-saving")
        self.observe_sms(READ_RECORD, "cancelled-editors-preserve-complete-sim-record")
        self.open_messages(unread=False)
        self.keys("down", "down")
        self.messages(2, False, "drafts-selected-after-unsaved-reply-forward")
        self.keys("soft_left")
        self.empty_folder("Drafts")
        self.keys("red")
        self.home("restored-home-no-transmission")

    def test_preloaded_sim_inbox_delete_no_preserves_then_yes_frees_actual_record(self):
        self.original_home_and_scan()
        self.open_inbox(unread=True)
        self.keys("soft_left")
        self.reader("complete-stored-message-before-delete")
        self.keys("soft_left", "down", "down", "down")
        self.actions(3, "delete-selected")
        self.keys("soft_left")
        self.delete_confirmation("delete-confirmation-before-no")
        self.keys("soft_right")
        self.actions(3, "delete-no-retains-action-selection")
        self.keys("soft_right")
        self.reader("delete-no-retains-complete-body")
        self.observe_sms(READ_RECORD, "delete-no-preserves-actual-record")
        self.keys("soft_left", "down", "down", "down")
        self.actions(3, "delete-reselected-before-yes")
        self.keys("soft_left")
        self.delete_confirmation("delete-confirmation-before-yes")
        self.keys("soft_left")
        deleted = self.font.message(("Message Deleted",), divider=False)
        self.expect("message-deleted-original-completion", lambda state: (
            self.title(state, "+12345") and self.handset.screen_hash(state=state) == deleted),
            {"title": "+12345", "literal_message": "Message Deleted"}, max_steps=12000000)
        self.observe_sms(DELETED_RECORD, "delete-yes-frees-real-external-record-with-pdu-retained")
        exhausted = self.font.message(("No more messages",), divider=False)
        self.expect("last-message-original-exhausted-toast", lambda state: (
            self.title(state, "Inbox") and self.handset.screen_hash(state=state) == exhausted),
            {"title": "Inbox", "literal_message": "No more messages"}, max_steps=24000000)
        self.messages(1, False, "deleted-inbox-parent-after-toast", max_steps=24000000)
        self.keys("soft_left")
        self.empty_folder("Inbox")
        self.keys("red")
        self.home("restored-home-after-real-card-delete")

    def delete_confirmation(self, label):
        expected = self.font.message(("Delete Message?",))
        _, no_width = self.font.render("No", 128)
        return self.expect(label, lambda state: (
            self.title(state, "+12345") and self.handset.screen_hash(state=state) == expected and
            self.text(state, "Yes", 112, 2, 22) and self.text(state, "No", 112, 127 - no_width, no_width)),
            {"title": "+12345", "literal_message": "Delete Message?", "actions": ["Yes", "No"]})


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesInboxE2ETests(MessagesInboxChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesInboxE2ETests(MessagesInboxChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
