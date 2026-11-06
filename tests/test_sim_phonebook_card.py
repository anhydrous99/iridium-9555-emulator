"""Pure external-card contracts; no firmware worker or native execution."""

import unittest

from sim_phonebook_card import EMPTY_ADN, PhonebookSIM


# TS51.01110.5.1: alpha18, length includes TON/NPI, low-nibble-first digits,
# FF number padding and absent capability/extension identifiers.
ADG_ADN = b"Adg" + b"\xFF" * 15 + bytes.fromhex("04 91 21 43 F5") + b"\xFF" * 9
Z_ADN = b"Z" + b"\xFF" * 17 + bytes.fromhex("03 91 89 F7") + b"\xFF" * 10
B_ADN = b"B" + b"\xFF" * 17 + bytes.fromhex("02 81 76") + b"\xFF" * 11
ADN_METADATA = bytes.fromhex("00 00 00 40 6F 3A 04 00 11 F0 22 01 02 01 20")


class PhonebookSIMTests(unittest.TestCase):
    def setUp(self):
        self.card = PhonebookSIM()
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")

    def take(self):
        value = bytes(self.card.pending)
        self.card.accepted(len(value))
        return value

    def select(self, file_id=0x6F3A):
        directory = 0x7F20 if file_id == 0x6F05 else 0x7F10
        for value in (directory, file_id):
            self.card.feed(b"\xA0\xA4\x00\x00\x02")
            self.assertEqual(self.take(), b"\xA4")
            self.card.feed(value.to_bytes(2, "big"))
            self.assertEqual(self.take(), b"\x9F\x16" if value == directory else b"\x9F\x0F")

    def read_record(self, record=1):
        self.card.feed(bytes((0xA0, 0xB2, record, 4, 32)))
        return self.take()

    def write_record(self, body, record=1):
        self.card.feed(bytes((0xA0, 0xDC, record, 4, 32)))
        self.assertEqual(self.take(), b"\xDC")
        self.card.feed(body)
        self.assertEqual(self.take(), b"\x90\x00")

    def test_finite_original_geometry_two_empty_records_and_no_extra_files(self):
        self.assertEqual(self.card.metadata[0x6F3A], ADN_METADATA)
        self.assertEqual(self.card.contents[0x6F38], b"\xCC\x00")
        self.assertNotIn(0x6F43, self.card.metadata)
        self.select()
        self.card.feed(b"\xA0\xC0\x00\x00\x0F")
        self.assertEqual(self.take(), b"\xC0" + ADN_METADATA + b"\x90\x00")
        self.assertEqual(self.read_record(1), b"\xB2" + EMPTY_ADN + b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + EMPTY_ADN + b"\x90\x00")

    def test_fragmented_create_commits_only_after_complete_body_and_reads_back(self):
        self.select()
        for part in (b"\xA0", b"\xDC\x01", b"\x04"):
            self.card.feed(part)
            self.assertFalse(self.take())
        self.card.feed(b"\x20")
        self.assertEqual(self.take(), b"\xDC")
        for part in (ADG_ADN[:1], ADG_ADN[1:18], ADG_ADN[18:31]):
            self.card.feed(part)
            self.assertFalse(self.take())
            self.assertEqual(self.card.records[0x6F3A], (EMPTY_ADN, EMPTY_ADN))
        self.card.feed(ADG_ADN[31:])
        self.assertEqual(self.take(), b"\x90\x00")
        self.assertEqual(self.read_record(), b"\xB2" + ADG_ADN + b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + EMPTY_ADN + b"\x90\x00")
        self.assertEqual(self.card.metadata[0x6F3A], ADN_METADATA)

    def test_edit_replaces_shorter_record_and_preserves_other_slot(self):
        self.select()
        self.write_record(Z_ADN, 1)
        self.write_record(ADG_ADN, 2)
        self.write_record(B_ADN, 2)
        self.assertEqual(self.read_record(1), b"\xB2" + Z_ADN + b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + B_ADN + b"\x90\x00")
        self.assertEqual(self.card.records[0x6F3A][1][21:], b"\xFF" * 11)

    def test_all_ff_delete_and_reuse_preserve_distinct_other_record(self):
        self.select()
        self.write_record(ADG_ADN, 1)
        self.write_record(Z_ADN, 2)
        self.write_record(EMPTY_ADN, 1)
        self.assertEqual(self.read_record(1), b"\xB2" + EMPTY_ADN + b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + Z_ADN + b"\x90\x00")
        self.write_record(B_ADN, 1)
        self.assertEqual(self.read_record(1), b"\xB2" + B_ADN + b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + Z_ADN + b"\x90\x00")

    def test_matched_memory_rejection_has_no_procedure_or_mutation_then_recovers(self):
        self.select()
        self.write_record(ADG_ADN)
        self.card.adn_write_memory_failure = True
        before = (dict(self.card.contents), dict(self.card.records))
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\x92\x40")
        self.assertIsNone(self.card._write)
        self.assertFalse(self.card.buffer)
        self.assertEqual((self.card.contents, self.card.records), before)
        self.assertEqual(self.read_record(), b"\xB2" + ADG_ADN + b"\x90\x00")
        self.card.adn_write_memory_failure = False
        self.write_record(B_ADN)
        self.assertEqual(self.read_record(), b"\xB2" + B_ADN + b"\x90\x00")

    def test_bad_class_record_mode_and_length_leave_all_card_bytes_unchanged(self):
        self.select()
        before = (dict(self.card.contents), dict(self.card.records))
        for header, status in (
            ("00 DC 01 04 20", "6E 00"), ("A0 DC 01 03 20", "94 08"),
            ("A0 DC 01 14 20", "94 08"), ("A0 DC 00 04 20", "94 02"),
            ("A0 DC 03 04 20", "94 02"), ("A0 DC FF 04 20", "94 02"),
            ("A0 DC 01 04 1F", "67 00"), ("A0 DC 01 04 21", "67 00"),
            ("A0 DC 01 04 00", "67 00"), ("A0 D6 00 00 20", "6D 00"),
            ("A0 32 00 00 20", "6D 00"),
        ):
            with self.subTest(header=header):
                self.card.feed(bytes.fromhex(header))
                self.assertEqual(self.take(), bytes.fromhex(status))
                self.assertEqual((self.card.contents, self.card.records), before)
                self.assertIsNone(self.card._write)

    def test_sms_transparent_and_directory_writes_are_not_exposed(self):
        before = (dict(self.card.contents), dict(self.card.records))
        self.select(0x6F3C)
        self.card.feed(b"\xA0\xDC\x01\x04\xB0")
        self.assertEqual(self.take(), b"\x6D\x00")
        self.select(0x6F05)
        self.card.feed(b"\xA0\xD6\x00\x00\x02")
        self.assertEqual(self.take(), b"\x6D\x00")
        self.card.feed(b"\xA0\xA4\x00\x00\x02")
        self.assertEqual(self.take(), b"\xA4")
        self.card.feed(b"\x3F\x00")
        self.assertEqual(self.take(), b"\x9F\x16")
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\x94\x00")
        self.assertEqual((self.card.contents, self.card.records), before)

    def test_reset_aborts_partial_header_body_but_committed_data_survives_reinsert(self):
        self.select()
        self.card.feed(b"\xA0\xDC\x01")
        self.card.controls(1, 0x54)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.select()
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\xDC")
        self.card.feed(ADG_ADN[:-1])
        self.card.controls(0, 0x40)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.select()
        self.assertEqual(self.read_record(), b"\xB2" + EMPTY_ADN + b"\x90\x00")
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.assertEqual(self.take(), b"\xDC")
        self.card.feed(ADG_ADN)
        self.assertEqual(bytes(self.card.pending), b"\x90\x00")
        self.card.controls(0, 0x40)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.select()
        self.assertEqual(self.read_record(), b"\xB2" + ADG_ADN + b"\x90\x00")

    def test_clock_stop_and_response_backpressure_preserve_partial_write(self):
        self.select()
        self.card.feed(b"\xA0\xDC\x01\x04\x20")
        self.card.controls(1, 0x70)
        self.assertFalse(self.card.ready)
        with self.assertRaises(AssertionError):
            self.card.feed(ADG_ADN)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\xDC")
        self.card.feed(ADG_ADN[:-1])
        self.card.controls(1, 0x70)
        self.card.controls(1, 0x74)
        self.assertEqual(bytes(self.card.buffer), ADG_ADN[:-1])
        self.card.feed(ADG_ADN[-1:])
        self.card.accepted(1)
        with self.assertRaises(AssertionError):
            self.card.feed(b"\xA0\xB2\x01\x04\x20")
        self.assertEqual(self.take(), b"\x00")
        self.assertEqual(self.read_record(), b"\xB2" + ADG_ADN + b"\x90\x00")

    def test_finite_initial_records_are_copied_and_binary_bodies_are_opaque(self):
        source = bytearray(ADG_ADN)
        card = PhonebookSIM(adn_records=(source, Z_ADN))
        source[0] = 0
        self.assertEqual(card.records[0x6F3A], (ADG_ADN, Z_ADN))
        self.assertEqual(self.card.records[0x6F3A], (EMPTY_ADN, EMPTY_ADN))
        for invalid in ((EMPTY_ADN,), (EMPTY_ADN,) * 3,
                        (b"\xFF" * 31, EMPTY_ADN), (EMPTY_ADN, b"\xFF" * 33),
                        (32, EMPTY_ADN)):
            with self.subTest(records=invalid), self.assertRaises(ValueError):
                PhonebookSIM(adn_records=invalid)
        self.select()
        opaque = bytes(range(32))
        self.write_record(opaque)
        self.assertEqual(self.read_record(), b"\xB2" + opaque + b"\x90\x00")


if __name__ == "__main__":
    unittest.main()
