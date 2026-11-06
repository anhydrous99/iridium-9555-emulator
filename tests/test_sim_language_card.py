"""Finite external-card framing/reset checks; no proprietary firmware required."""

import unittest

from sim_language_card import LanguageSIM, StorageSIM


class LanguageSIMTests(unittest.TestCase):
    def setUp(self):
        self.card = LanguageSIM()
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")

    def take(self):
        response = bytes(self.card.pending)
        self.card.accepted(len(response))
        return response

    def select(self, file_id):
        self.card.feed(b"\xA0\xA4\x00\x00\x02")
        self.assertEqual(self.take(), b"\xA4")
        self.card.feed(file_id.to_bytes(2, "big"))
        return self.take()

    def test_fragmented_select_metadata_and_read_keep_header_body_and_file_bytes(self):
        for fragment in (b"\xA0", b"\xA4\x00", b"\x00", b"\x02"):
            self.card.feed(fragment)
        self.assertEqual(self.take(), b"\xA4")
        self.card.feed(b"\x7F")
        self.assertEqual(self.take(), b"")
        self.card.feed(b"\x20")
        self.assertEqual(self.take(), b"\x9F\x16")
        self.assertEqual(self.select(0x6F05), b"\x9F\x0F")
        self.card.feed(b"\xA0\xC0\x00\x00\x0F")
        expected = b"\x00\x00\x00\x02\x6F\x05\x04\x00\x01\xF0\x44\x01\x02\x00\x00"
        self.assertEqual(self.take(), b"\xC0" + expected + b"\x90\x00")
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\xB0\x01\x04\x90\x00")

    def test_unaccepted_suffix_is_retained_without_replaying_accepted_prefix(self):
        self.card.feed(b"\xA0\xC0\x00\x00\x16")
        complete = bytes(self.card.pending)
        self.card.accepted(2)
        self.assertEqual(bytes(self.card.pending), complete[2:])
        self.card.accepted(0)
        self.assertEqual(bytes(self.card.pending), complete[2:])
        with self.assertRaises(AssertionError):
            self.card.queue(b"\x90\x00", "would-overwrite")
        with self.assertRaises(ValueError):
            self.card.accepted(len(self.card.pending) + 1)
        self.assertEqual(self.take(), complete[2:])

    def test_removal_and_reset_abort_partial_command_and_require_a_new_atr(self):
        self.select(0x7F20)
        self.card.feed(b"\xA0\xA4")
        self.card.controls(1, 0x54)
        self.assertFalse(self.card.buffer)
        self.assertFalse(self.card.pending)
        self.assertEqual(self.card.selected, 0x3F00)
        with self.assertRaises(AssertionError):
            self.card.feed(b"\x00")
        self.card.controls(0, 0x74)
        self.assertFalse(self.card.pending)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")
        self.card.controls(1, 0x74)
        self.assertFalse(self.card.pending)

    def test_unsupported_files_commands_lengths_and_ranges_return_card_errors(self):
        self.assertEqual(self.select(0x7F20), b"\x9F\x16")
        self.assertEqual(self.select(0x6FAE), b"\x94\x04")
        self.assertEqual(self.card.selected, 0x7F20)
        for header, status in ((b"\x00\xC0\x00\x00\x16", b"\x6E\x00"),
                               (b"\xA0\xDC\x00\x00\x02", b"\x6D\x00"),
                               (b"\xA0\xC0\x00\x00\x17", b"\x67\x00"),
                               (b"\xA0\xC0\x01\x00\x16", b"\x6B\x00"),
                               (b"\xA0\xB0\x00\x00\x02", b"\x94\x00")):
            with self.subTest(header=header.hex()):
                self.card.feed(header)
                self.assertEqual(self.take(), status)
        self.select(0x6F05)
        self.card.feed(b"\xA0\xB0\x00\x01\x02")
        self.assertEqual(self.take(), b"\x94\x02")

    def test_injected_card_memory_fault_returns_status_without_data_or_ack(self):
        self.card.memory_failure = True
        self.select(0x7F20)
        self.select(0x6F05)
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\x92\x40")
        self.assertEqual(self.card.languages, b"\x01\x04")

    def test_clock_stop_preserves_selection_partial_command_and_pending_response(self):
        self.select(0x7F20)
        self.card.feed(b"\xA0\xA4")
        self.card.controls(1, 0x70)
        self.assertFalse(self.card.ready)
        self.assertEqual(self.card.buffer, b"\xA0\xA4")
        self.assertEqual(self.card.selected, 0x7F20)
        self.card.controls(1, 0x74)
        self.assertFalse(self.card.pending, "Clock restart is not another ATR")
        self.card.feed(b"\x00\x00\x02")
        self.assertEqual(self.take(), b"\xA4")
        self.card.feed(b"\x6F\x05")
        response = bytes(self.card.pending)
        self.card.controls(1, 0x70)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), response)
        self.assertEqual(response, b"\x9F\x0F")

    def test_reset_release_waits_for_clock_before_first_atr(self):
        self.card.controls(1, 0x40)
        self.card.controls(1, 0x70)
        self.assertFalse(self.card.pending)
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")


class StorageSIMTests(unittest.TestCase):
    take = LanguageSIMTests.take
    select = LanguageSIMTests.select

    def setUp(self):
        self.card = StorageSIM()
        self.card.controls(1, 0x74)
        self.assertEqual(self.take(), b"\x3B\x00")

    def test_declared_sms_geometry_and_both_empty_records_match_wire_and_reject_writes(self):
        self.select(0x7F20)
        self.assertEqual(self.select(0x7F10), b"\x9F\x16")
        self.assertEqual(self.select(0x6F3C), b"\x9F\x0F")
        self.card.feed(b"\xA0\xC0\x00\x00\x0F")
        metadata = b"\x00\x00\x01\x60\x6F\x3C\x04\x00\x11\xF0\x44\x01\x02\x01\xB0"
        self.assertEqual(self.take(), b"\xC0" + metadata + b"\x90\x00")
        for record in (1, 2):
            self.card.feed(bytes((0xA0, 0xB2, record, 4, 176)))
            self.assertEqual(self.take(), b"\xB2\x00" + b"\xFF" * 175 + b"\x90\x00")
        for command, error in ((b"\xA0\xB2\x03\x04\xB0", b"\x94\x02"),
                               (b"\xA0\xB2\x01\x04\xAF", b"\x67\x00"),
                               (b"\xA0\xB0\x00\x00\x02", b"\x94\x08"),
                               (b"\xA0\xDC\x01\x04\xB0", b"\x6D\x00")):
            self.card.feed(command)
            self.assertEqual(self.take(), error)
        self.assertEqual(self.card.records[0x6F3C], (b"\x00" + b"\xFF" * 175,) * 2)
        self.select(0x6F3A)
        self.card.feed(b"\xA0\xB2\x01\x04\x20")
        self.assertEqual(self.take(), b"\xB2" + b"\xFF" * 32 + b"\x90\x00")

    def test_service_gate_changes_only_sst_data_while_retaining_identical_storage_geometry(self):
        disabled = StorageSIM(sms_available=False)
        self.assertEqual(disabled.metadata, self.card.metadata)
        self.assertEqual(disabled.records, self.card.records)
        self.assertEqual(self.card.contents[0x6F38], b"\xCC\x00")
        self.assertEqual(disabled.contents[0x6F38], b"\x0C\x00")
        self.card = disabled
        self.card.controls(1, 0x74)
        self.take()
        self.select(0x7F20)
        self.select(0x6F38)
        self.card.feed(b"\xA0\xB0\x00\x00\x02")
        self.assertEqual(self.take(), b"\xB0\x0C\x00\x90\x00")


if __name__ == "__main__":
    unittest.main()
