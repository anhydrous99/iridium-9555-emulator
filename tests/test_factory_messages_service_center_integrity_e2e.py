"""Saving an unchanged Service Center must preserve the represented address.

The original query carries its type separately from digits. This property
checks the actual external SMSP record after a no-edit GUI Save; no assumption
about displaying a plus sign or sending a message is used.
"""

from copy import deepcopy
import os
import unittest

from sim_service_center_card import INITIAL_SMSP
from test_factory_messages_local_e2e import SETTINGS
from test_factory_messages_service_center_e2e import MessagesServiceCenterChecks as _Service


class ServiceCenterIntegrityChecks:
    # Select fixture/helpers without inheriting the independent save/fault tests.
    start = _Service.start
    finish = _Service.finish
    read = _Service.read
    press = _Service.press
    text = _Service.text
    title = _Service.title
    menu = _Service.menu
    submit = _Service.submit
    keys = _Service.keys
    field = _Service.field
    blank = staticmethod(_Service.blank)
    reopen_messages = _Service.reopen_messages
    expect = _Service.expect
    original_home_and_scan = _Service.original_home_and_scan
    record = _Service.record
    settings_from_home = _Service.settings_from_home
    number = _Service.number
    open_number = _Service.open_number
    writes = _Service.writes

    def test_unchanged_service_center_save_preserves_complete_card_address_and_type(self):
        self.start(memory_failure=False)
        self.original_home_and_scan()
        self.assertEqual(self.card.records[0x6F42], (INITIAL_SMSP,))
        self.assertEqual(INITIAL_SMSP[18], 0x91)
        self.settings_from_home()
        self.open_number("12345", "complete-original-service-center-before-no-edit-save")
        self.assertEqual(self.writes(), [])
        wire_start = len(self.peer.wire)
        self.submit()
        self.menu(SETTINGS, 0, "unchanged-number-save-returned", max_steps=12000000)
        # A no-op may avoid a write entirely. Otherwise wait for the actual
        # deferred card transaction; the immediate setter callback is insufficient.
        for elapsed in range(0, 16000001, 200000):
            self.handset.assert_healthy()
            self.peer.check()
            completed = any(e["kind"] == "updated-record" for e in self.card.events)
            drained = (not self.card.pending and not self.card.buffer and
                       not self.card.selecting and self.card._write is None)
            if completed and drained:
                break
            if elapsed < 16000000:
                self.handset.step(200000)
        self.assertFalse(self.card.pending)
        self.assertFalse(self.card.buffer)
        self.assertFalse(self.card.selecting)
        self.assertIsNone(self.card._write)
        writes = self.writes()
        self.assertLessEqual(len(writes), 1)
        wire = deepcopy(self.peer.wire[wire_start:])
        transmitted = bytes(v for row in wire for v in row["tx"])
        received = bytes(v for row in wire for v in row["offered"][:row["accepted"]])
        actual = self.card.records[0x6F42][0]
        self.card_observations.append({"label": "unchanged-GUI-save-card-observation",
            "wire": wire, "transmitted": list(transmitted), "accepted_reply": list(received),
            "actual_record": list(actual), "expected_unchanged_record": list(INITIAL_SMSP),
            "input_changed": False})
        if writes:
            header = bytes.fromhex("A0 DC 01 04 20")
            self.assertEqual(writes[0]["bytes"], list(header))
            self.assertEqual(transmitted.count(header), 1)
            self.assertEqual(transmitted.split(header, 1)[1], actual)
            self.assertTrue(received.endswith(b"\xDC\x90\x00"))
        self.record("actual-record-after-unchanged-service-center-save")
        self.evidence[-1]["oracle"] = {"input_changed": False,
            "expected_record": list(INITIAL_SMSP), "actual_record": list(actual),
            "expected_address_type": 0x91, "actual_address_type": actual[18],
            "card_write_observed": bool(writes), "early_callback_is_not_commit": True}
        self.assertEqual(actual, INITIAL_SMSP,
                         "Saving the unchanged service-center number must preserve its address type and data")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555ServiceCenterIntegrityE2ETests(ServiceCenterIntegrityChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575ServiceCenterIntegrityE2ETests(ServiceCenterIntegrityChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
