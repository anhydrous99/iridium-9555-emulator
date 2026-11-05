"""External-card data integrity and T=0 checks; no firmware execution required."""

import unittest

from sim_message_card import MessageSIM


# Opaque wire bytes, including command-looking bytes, exercise storage framing.
# They are not asserted to be a complete subscriber message or valid TPDU.
RECORD = b"\x07" + bytes(range(100)) + b"\xA0\xDC\x01\x04\xB0" + bytes(range(70))
EMPTY = b"\x00" + b"\xFF" * 175


class MessageSIMTests(unittest.TestCase):
    def setUp(self):
        self.card = MessageSIM()
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")

    def take(self):
        response = bytes(self.card.pending)
        self.card.accepted(len(response))
        return response

    def select(self, file_id):
        directory = 0x7F20 if file_id in (0x6F05, 0x6F38) else 0x7F10
        for selected in (directory, file_id):
            self.card.feed(b"\xA0\xA4\x00\x00\x02")
            self.assertEqual(self.take(), b"\xA4")
            self.card.feed(selected.to_bytes(2, "big"))
            self.assertEqual(self.take(), b"\x9F\x16" if selected == directory else b"\x9F\x0F")

    def read_record(self, record):
        self.card.feed(bytes((0xA0, 0xB2, record, 4, 176)))
        return self.take()

    def begin_record(self, record=1):
        self.card.feed(bytes((0xA0, 0xDC, record, 4, 176)))
        self.assertEqual(self.take(), b"\xDC")

    def test_sms_smss_metadata_and_reads_declare_only_finite_storage(self):
        self.select(0x6F3C)
        self.card.feed(b"\xA0\xC0\x00\x00\x0F")
        sms = bytes.fromhex("00 00 01 60 6F 3C 04 00 11 F0 44 01 02 01 B0")
        self.assertEqual(self.take(), b"\xC0" + sms + b"\x90\x00")
        for record in (1, 2):
            self.assertEqual(self.read_record(record), b"\xB2" + EMPTY + b"\x90\x00")
        self.select(0x6F43)
        self.card.feed(b"\xA0\xC0\x00\x00\x0F")
        smss = bytes.fromhex("00 00 00 02 6F 43 04 00 11 F0 44 01 02 00 00")
        self.assertEqual(self.take(), b"\xC0" + smss + b"\x90\x00")
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\xB0\x00\xFF\x90\x00")
        self.select(0x6F38)
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\xB0\xCC\x00\x90\x00")
        self.card.feed(b"\xA0\xA4\x00\x00\x02")
        self.take()
        self.card.feed(b"\x6F\x07")  # No subscriber identity is declared.
        self.assertEqual(self.take(), b"\x94\x04")

    def test_fragmented_record_write_is_atomic_and_reads_back_both_slots(self):
        self.select(0x6F3C)
        for fragment in (b"\xA0", b"\xDC\x01", b"\x04"):
            self.card.feed(fragment)
            self.assertEqual(self.take(), b"")
        self.card.feed(b"\xB0")
        self.assertEqual(self.take(), b"\xDC")
        for fragment in (RECORD[:7], RECORD[7:89], RECORD[89:175]):
            self.card.feed(fragment)
            self.assertEqual(self.card.records[0x6F3C], (EMPTY, EMPTY))
            self.assertEqual(self.take(), b"")
        self.card.feed(RECORD[175:])
        self.assertEqual(self.take(), b"\x90\x00")
        self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + EMPTY + b"\x90\x00")
        second = b"\x07" + b"\xA5" * 175
        self.begin_record(2)
        self.card.feed(second)
        self.assertEqual(self.take(), b"\x90\x00")
        self.assertEqual(self.read_record(2), b"\xB2" + second + b"\x90\x00")
        self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")

    def test_procedure_and_status_suffixes_must_be_accepted_before_further_input(self):
        self.select(0x6F3C)
        self.card.feed(b"\xA0\xDC\x01\x04\xB0")
        self.card.accepted(0)
        with self.assertRaises(AssertionError):
            self.card.feed(RECORD)
        self.assertEqual(self.card.records[0x6F3C], (EMPTY, EMPTY))
        self.assertFalse(self.card.buffer)
        self.assertEqual(self.take(), b"\xDC")
        self.card.feed(RECORD)
        self.card.accepted(1)
        self.assertEqual(bytes(self.card.pending), b"\x00")
        with self.assertRaises(AssertionError):
            self.card.feed(b"\xA0\xB2\x01\x04\xB0")
        self.card.accepted(0)
        with self.assertRaises(ValueError):
            self.card.accepted(2)
        self.assertEqual(self.take(), b"\x00")
        self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")

    def test_sms_memory_failure_rejects_only_record_update_without_ack_or_mutation(self):
        self.card = MessageSIM(sms_write_memory_failure=True)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.select(0x6F43)
        self.card.feed(b"\xA0\xD6\x00\x00\x02")
        self.assertEqual(self.take(), b"\xD6")
        self.card.feed(b"\x29\xFE")
        self.assertEqual(self.take(), b"\x90\x00", "The matched fault must not intercept SMSS first")
        self.select(0x6F3C)
        self.card.feed(b"\xA0\xDC\x01\x04\xB0")
        self.assertEqual(self.take(), b"\x92\x40")
        self.assertFalse(self.card.buffer)
        self.assertEqual(self.card.records[0x6F3C], (EMPTY, EMPTY))
        self.assertEqual(self.card.contents[0x6F43], b"\x29\xFE")
        self.assertEqual(self.read_record(1), b"\xB2" + EMPTY + b"\x90\x00")
        self.card.sms_write_memory_failure = False
        self.begin_record()
        self.card.feed(RECORD)
        self.assertEqual(self.take(), b"\x90\x00")
        self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")
        self.card.sms_write_memory_failure = True
        self.card.feed(b"\xA0\xDC\x01\x04\xB0")
        self.assertEqual(self.take(), b"\x92\x40")
        self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")

    def test_rejected_write_commands_preserve_all_declared_card_data(self):
        before = (dict(self.card.contents), dict(self.card.records))
        cases = (
            (0x6F3C, "00 DC 01 04 B0", "6E 00"),
            (0x6F3C, "A0 DC 01 03 B0", "94 08"),
            (0x6F3C, "A0 DC 00 04 B0", "94 02"),
            (0x6F3C, "A0 DC 03 04 B0", "94 02"),
            (0x6F3C, "A0 DC 01 04 AF", "67 00"),
            (0x6F3C, "A0 DC 01 04 00", "67 00"),
            (0x6F3C, "A0 D6 00 00 02", "94 08"),
            (0x6F3A, "A0 DC 01 04 20", "6D 00"),
            (0x6F05, "A0 D6 00 00 02", "6D 00"),
            (0x6F38, "A0 D6 00 00 02", "6D 00"),
            (0x6F43, "A0 DC 01 04 02", "94 08"),
            (0x6F43, "A0 D6 00 00 03", "94 02"),
            (0x6F43, "A0 D6 00 01 02", "94 02"),
            (0x6F43, "A0 D6 00 02 01", "94 02"),
            (0x6F43, "A0 D6 80 00 01", "94 02"),
            (0x6F43, "A0 D6 00 00 00", "94 02"),
            (0x6F43, "A0 D2 00 00 02", "6D 00"),
        )
        for file_id, command, status in cases:
            with self.subTest(file_id=hex(file_id), command=command):
                self.select(file_id)
                self.card.feed(bytes.fromhex(command))
                self.assertEqual(self.take(), bytes.fromhex(status))
                self.assertEqual((self.card.contents, self.card.records), before)
                self.assertFalse(self.card.buffer)
        self.card.feed(b"\xA0\xA4\x00\x00\x02")
        self.take()
        self.card.feed(b"\x3F\x00")
        self.take()
        self.card.feed(b"\xA0\xDC\x01\x04\xB0")
        self.assertEqual(self.take(), b"\x94\x00")
        self.assertEqual((self.card.contents, self.card.records), before)

    def test_smss_binary_updates_are_atomic_and_preserve_unwritten_bytes(self):
        self.select(0x6F43)
        self.card.feed(b"\xA0\xD6\x00")
        self.assertEqual(self.take(), b"")
        self.card.feed(b"\x00\x02")
        self.assertEqual(self.take(), b"\xD6")
        self.card.feed(b"\x31")
        self.assertEqual(self.card.contents[0x6F43], b"\x00\xFF")
        self.assertEqual(self.take(), b"")
        self.card.feed(b"\xFE")
        self.assertEqual(self.take(), b"\x90\x00")
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\xB0\x31\xFE\x90\x00")
        self.card.feed(b"\xA0\xD6\x00\x01\x01")
        self.assertEqual(self.take(), b"\xD6")
        self.card.feed(b"\xFF")
        self.assertEqual(self.take(), b"\x90\x00")
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\xB0\x31\xFF\x90\x00")
        self.assertEqual(self.card.records[0x6F3C], (EMPTY, EMPTY))

    def test_reset_aborts_partial_header_body_and_unaccepted_procedure(self):
        for partial in ("header", "procedure", "record-body", "binary-body"):
            with self.subTest(partial=partial):
                self.select(0x6F43 if partial == "binary-body" else 0x6F3C)
                if partial == "header":
                    self.card.feed(b"\xA0\xDC\x01")
                elif partial == "binary-body":
                    self.card.feed(b"\xA0\xD6\x00\x00\x02")
                    self.take()
                    self.card.feed(b"\x53")
                else:
                    self.card.feed(b"\xA0\xDC\x01\x04\xB0")
                    if partial == "record-body":
                        self.take()
                        self.card.feed(RECORD[:-1])
                self.card.controls(1, 0x54)
                self.assertFalse(self.card.ready)
                self.assertFalse(self.card.pending)
                self.assertFalse(self.card.buffer)
                self.assertEqual(self.card.selected, 0x3F00)
                self.assertEqual(self.card.records[0x6F3C], (EMPTY, EMPTY))
                self.assertEqual(self.card.contents[0x6F43], b"\x00\xFF")
                with self.assertRaises(AssertionError):
                    self.card.feed(b"\x00")
                self.card.controls(1, 0x70)
                self.assertFalse(self.card.pending, "Reset release waits for clock")
                self.card.controls(1, 0x74)
                self.assertEqual(self.take(), b"\x3B\x00")
                self.select(0x6F3C)
                self.assertEqual(self.read_record(1), b"\xB2" + EMPTY + b"\x90\x00")

    def test_committed_card_data_survives_reset_and_removal_before_status_acceptance(self):
        self.select(0x6F43)
        self.card.feed(b"\xA0\xD6\x00\x00\x02")
        self.take()
        self.card.feed(b"\x7F\xFE")
        self.take()
        self.select(0x6F3C)
        self.begin_record()
        self.card.feed(RECORD)
        self.assertEqual(bytes(self.card.pending), b"\x90\x00")
        for inputs, outputs in ((1, 0x54), (0, 0x74)):
            self.card.controls(inputs, outputs)
            self.assertFalse(self.card.pending)
            self.card.controls(1, 0x74)
            self.assertEqual(self.take(), b"\x3B\x00")
            self.select(0x6F3C)
            self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")
            self.assertEqual(self.read_record(2), b"\xB2" + EMPTY + b"\x90\x00")
            self.select(0x6F43)
            self.card.feed(b"\xA0\xB0\x00\x00\x02")
            self.assertEqual(self.take(), b"\xB0\x7F\xFE\x90\x00")

    def test_clock_stop_preserves_write_and_each_pending_response_suffix(self):
        self.select(0x6F3C)
        self.card.feed(b"\xA0\xDC\x01\x04\xB0")
        self.card.controls(1, 0x70)
        self.assertFalse(self.card.ready)
        self.assertEqual(bytes(self.card.pending), b"\xDC")
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\xDC", "Clock restart does not emit ATR")
        self.card.feed(RECORD[:-1])
        self.card.controls(1, 0x70)
        self.assertEqual(bytes(self.card.buffer), RECORD[:-1])
        self.assertEqual(self.card.records[0x6F3C], (EMPTY, EMPTY))
        self.card.controls(1, 0x74)
        self.assertFalse(self.card.pending)
        self.card.feed(RECORD[-1:])
        self.card.accepted(1)
        self.card.controls(1, 0x70)
        self.assertEqual(bytes(self.card.pending), b"\x00")
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x00")
        self.assertEqual(self.read_record(1), b"\xB2" + RECORD + b"\x90\x00")


if __name__ == "__main__":
    unittest.main()
