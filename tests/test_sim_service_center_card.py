"""Finite SMSP card protocol/data integrity checks, without firmware execution."""

import unittest

from sim_service_center_card import INITIAL_SMSP, ServiceCenterSIM


REPLACEMENT = b"SMSC\xE1" + b"\xFF" * 12 + bytes.fromhex("04 91 76 98 F0") + b"\xFF" * 7 + b"\x00" * 3


class ServiceCenterSIMTests(unittest.TestCase):
    def setUp(self):
        self.card = ServiceCenterSIM()
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")

    def take(self):
        value = bytes(self.card.pending)
        self.card.accepted(len(value))
        return value

    def select(self, file_id):
        directory = 0x7F20 if file_id == 0x6F38 else 0x7F10
        for value in (directory, file_id):
            self.card.feed(b"\xA0\xA4\x00\x00\x02")
            self.assertEqual(self.take(), b"\xA4")
            self.card.feed(value.to_bytes(2, "big"))
            self.assertEqual(self.take(), b"\x9F\x16" if value == directory else b"\x9F\x0F")

    def read_record(self):
        self.card.feed(b"\xA0\xB2\x01\x04\x20")
        return self.take()

    def begin(self):
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\xDC")

    def test_declared_service12_geometry_and_standard_sca_layout_read_back(self):
        self.assertEqual(len(INITIAL_SMSP), 32)
        self.assertEqual(INITIAL_SMSP[4], 0xE1)
        self.assertEqual(INITIAL_SMSP[17:29], bytes.fromhex("04 91 21 43 F5") + b"\xFF" * 7)
        self.select(0x6F38)
        self.card.feed(b"\xA0\xB0\x00\x00\x03")
        self.assertEqual(self.take(), b"\xB0\xCC\x00\xC0\x90\x00")
        self.select(0x6F42)
        self.card.feed(b"\xA0\xC0\x00\x00\x0F")
        self.assertEqual(self.take(), bytes.fromhex("C0 00 00 00 20 6F 42 04 00 11 F0 44 01 02 01 20 90 00"))
        self.assertEqual(self.read_record(), b"\xB2" + INITIAL_SMSP + b"\x90\x00")

    def test_fragmented_header_and_body_commit_atomically_with_actual_readback(self):
        self.select(0x6F42)
        for part in (b"\xA0\xDC", b"\x01", b"\x04"):
            self.card.feed(part)
            self.assertFalse(self.take())
        self.card.feed(b"\x20")
        self.assertEqual(self.take(), b"\xDC")
        for part in (REPLACEMENT[:1], REPLACEMENT[1:17], REPLACEMENT[17:31]):
            self.card.feed(part)
            self.assertFalse(self.take())
            self.assertEqual(self.card.records[0x6F42], (INITIAL_SMSP,))
        self.card.feed(REPLACEMENT[31:])
        self.assertEqual(self.take(), b"\x90\x00")
        self.assertEqual(self.read_record(), b"\xB2" + REPLACEMENT + b"\x90\x00")

    def test_smsp_memory_fault_has_no_ack_or_body_and_preserves_existing_data(self):
        self.select(0x6F42)
        self.begin()
        self.card.feed(REPLACEMENT)
        self.take()
        self.card.smsp_write_memory_failure = True
        before = (dict(self.card.contents), dict(self.card.records))
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\x92\x40")
        self.assertFalse(self.card.buffer)
        self.assertEqual((self.card.contents, self.card.records), before)
        self.assertEqual(self.read_record(), b"\xB2" + REPLACEMENT + b"\x90\x00")
        self.select(0x6F43)
        self.card.feed(b"\xA0\xD6\x00\x00\x02")
        self.assertEqual(self.take(), b"\xD6")
        self.card.feed(b"\x01\xFE")
        self.assertEqual(self.take(), b"\x90\x00", "SMSP fault must not intercept associated SMSS")

    def test_invalid_record_mode_range_length_and_other_writes_cannot_mutate_data(self):
        self.select(0x6F42)
        before = (dict(self.card.contents), dict(self.card.records))
        for header, expected in (
            ("00 DC 01 04 20", "6E 00"), ("A0 DC 01 03 20", "94 08"),
            ("A0 DC 00 04 20", "94 02"), ("A0 DC 02 04 20", "94 02"),
            ("A0 DC 01 04 1F", "67 00"), ("A0 DC 01 04 00", "67 00"),
            ("A0 D6 00 00 20", "94 08"), ("A0 32 00 00 20", "6D 00"),
        ):
            with self.subTest(header=header):
                self.card.feed(bytes.fromhex(header))
                self.assertEqual(self.take(), bytes.fromhex(expected))
                self.assertEqual((self.card.contents, self.card.records), before)
        self.select(0x6F3A)
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\x6D\x00")

    def test_reset_aborts_partial_body_but_committed_record_survives_removal(self):
        self.select(0x6F42)
        self.begin()
        self.card.feed(REPLACEMENT[:-1])
        self.card.controls(1, 0x54)
        self.assertFalse(self.card.buffer)
        self.assertFalse(self.card.pending)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.select(0x6F42)
        self.assertEqual(self.read_record(), b"\xB2" + INITIAL_SMSP + b"\x90\x00")
        self.begin()
        self.card.feed(REPLACEMENT)
        self.assertEqual(bytes(self.card.pending), b"\x90\x00")
        self.card.controls(0, 0x40)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.select(0x6F42)
        self.assertEqual(self.read_record(), b"\xB2" + REPLACEMENT + b"\x90\x00")

    def test_clock_stop_and_backpressure_preserve_transaction_and_pending_suffix(self):
        self.select(0x6F42)
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.card.controls(1, 0x70)
        self.assertFalse(self.card.ready)
        self.assertEqual(bytes(self.card.pending), b"\xDC")
        with self.assertRaises(AssertionError):
            self.card.feed(REPLACEMENT)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\xDC")
        self.card.feed(REPLACEMENT[:-1])
        self.card.controls(1, 0x70)
        self.card.controls(1, 0x74)
        self.assertEqual(bytes(self.card.buffer), REPLACEMENT[:-1])
        self.card.feed(REPLACEMENT[-1:])
        self.card.accepted(1)
        with self.assertRaises(AssertionError):
            self.card.feed(b"\xA0\xB2\x01\x04\x20")
        self.card.controls(1, 0x70)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x00")
        self.assertEqual(self.read_record(), b"\xB2" + REPLACEMENT + b"\x90\x00")


if __name__ == "__main__":
    unittest.main()
