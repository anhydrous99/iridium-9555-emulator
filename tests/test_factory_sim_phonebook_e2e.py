"""Read-only SIM contacts must reach the actual factory handset phonebook.

The manual reserves SIM programming to external software. These cases test
empty and populated display, not handset editing, authentication or calls.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from factory_sim_peer import FactorySIMPeer
from sim_language_card import StorageSIM
from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_messages_local_e2e import MessagesLocalChecks as _Local
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_sim_phonebook_contract import ADG_ADN, EMPTY_ADN


class SIMPhonebookChecks:
    finish = _Local.finish
    read = _Local.read
    press = _Local.press
    submit = _Local.submit
    original_home_and_scan = _Local.original_home_and_scan
    text = _Local.text
    title = _Local.title
    blank = staticmethod(_Editor.blank)

    def start(self, *, populated):
        self.evidence = []
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        card = StorageSIM()
        card.records[0x6F3A] = (ADG_ADN if populated else EMPTY_ADN, EMPTY_ADN)
        self.initial_records = dict(card.records)
        self.initial_contents = dict(card.contents)
        self.peer = FactorySIMPeer(self, self.handset, card=card)
        self.addCleanup(self.finish)
        self.addCleanup(self.verify_card_unchanged)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])

    def verify_card_unchanged(self):
        self.assertEqual(self.peer.card.records, self.initial_records)
        self.assertEqual(self.peer.card.contents, self.initial_contents)

    def record(self, label):
        return _Local.record(self, f"{len(self.evidence):03d}-{label}")

    def expect(self, label, predicate, oracle, *, budget=12000000):
        for elapsed in range(0, budget + 1, 200000):
            state = self.handset.assert_healthy()
            self.peer.check()
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < budget:
                self.handset.step(200000)
        self.record(label + "-timeout")
        self.evidence[-1]["oracle"] = oracle
        self.fail(f"Original SIM phonebook did not match {label}: {oracle}")

    def original_card_consumed(self, *, populated):
        self.assertEqual(self.read("trx", 0x400AA9F8, 8),
                         [0, 0, 0, 1, int(populated), 0, 2, 100])
        self.assertEqual(self.read("trx", 0x400ABEFA), [18])
        self.assertEqual(self.read("trx", 0x400ABEFC, 4), [0] * 4)
        if populated:
            self.assertEqual(self.read("trx", 0x400AACED + 101 * 16, 16),
                             list(b"Adg" + b"\0" * 13))
            self.assertEqual(self.read("trx", 0x400AA9FD + 101 * 3, 3), [0x21, 0x43, 0xF5])
        headers = [event for event in self.peer.card.events if event["kind"] == "header"]
        reads = [event["bytes"] for event in headers
                 if event["selected"] == 0x6F3A and event["bytes"][1] == 0xB2]
        initial_scan = [[0xA0, 0xB2, 1, 4, 32], [0xA0, 0xB2, 2, 4, 32]]
        self.assertEqual(reads[:2], initial_scan)
        # The original BC5 enumeration can legitimately request another read.
        self.assertTrue(all(header in initial_scan for header in reads))
        header = None
        for event in self.peer.card.events:
            if event["kind"] == "header":
                header = event
            elif (event["kind"] == "read-record" and header is not None and
                  header["selected"] == 0x6F3A):
                record = self.initial_records[0x6F3A][header["bytes"][2] - 1]
                self.assertEqual(event["bytes"], [0xB2, *record, 0x90, 0])
        self.record("original-trx-consumed-external-adn")
        self.evidence[-1]["card_oracle"] = {
            "file": "6F3A", "records": [list(v) for v in self.initial_records[0x6F3A]],
            "capacity": 2, "used": int(populated), "initialized": True,
            "full_gui_number_not_yet_asserted": True}

    def open_sim(self):
        self.submit()
        self.expect("main-menu-before-sim", lambda s: self.title(s, "Menu"), {"title": "Menu"})
        self.press("down")
        self.expect("sim-phonebook-selected", lambda s: (
            self.title(s, "Menu") and self.text(s, "SIM Phonebook", 33, selected=True)),
            {"title": "Menu", "focused_item": "SIM Phonebook", "row": 33})
        self.submit()

    def back_home(self):
        self.press("soft_right")
        self.expect("sim-back-to-main-menu", lambda s: self.title(s, "Menu"), {"title": "Menu"})
        self.press("soft_right")
        self.expect("sim-returned-home", lambda s: (
            self.handset.screen_hash(113, 128, s) == HOME_CAPTIONS and s["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def test_original_empty_sim_card_shows_readonly_empty_phonebook_and_returns_home(self):
        self.start(populated=False)
        self.original_home_and_scan()
        self.original_card_consumed(populated=False)
        self.open_sim()
        self.expect("empty-sim-phonebook-without-options", lambda s: (
            self.title(s, "Phonebook") and self.text(s, "(Empty)", 16) and
            self.blank(s, 32, 111) and self.blank(s, 112, 127, 0, 70) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Phonebook", "literal_empty_row": "(Empty)",
             "unused_rows_blank": True, "left_caption_blank": True, "right_caption": "Back"})
        self.back_home()

    def test_original_populated_sim_record_is_available_with_readonly_contact_actions(self):
        self.start(populated=True)
        self.original_home_and_scan()
        self.original_card_consumed(populated=True)
        self.open_sim()
        # The initialized original TRX cache is necessary, but the handset must
        # actually display the supplied entry. Empty is an ordinary regression.
        # B5824 lists highlight x0..118 through row33; B9886 menus differ.
        self.expect("populated-sim-entry-visible", lambda s: (
            self.title(s, "Phonebook") and self.text(s, "Adg", 16, width=117, selected=True) and
            self.blank(s, 34, 111) and self.text(s, "Options", 112, 2, 45) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Phonebook", "selected_name": "Adg", "logical_index": 101,
             "card_digits": "12345", "card_address_type": 0x91,
             "selected_row_rect": [0, 15, 118, 33], "row_text_width": 117,
             "unused_rows_start": 34,
             "full_gui_number_not_yet_asserted": True})
        self.submit()
        labels = ("Call", "SMS", "Copy")
        self.expect("sim-contact-has-only-original-readonly-actions", lambda s: (
            self.title(s, "Adg") and all(self.text(s, item, 16 + 17 * i, selected=i == 0)
                                         for i, item in enumerate(labels)) and
            self.blank(s, 67, 111) and self.text(s, "Select", 112, 2, 36) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Adg", "ordered_actions": labels, "focused_index": 0,
             "edit_delete_new_absent": True})
        self.press("soft_right")
        self.back_home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555SIMPhonebookE2ETests(SIMPhonebookChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575SIMPhonebookE2ETests(SIMPhonebookChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
