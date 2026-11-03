import tempfile
from pathlib import Path
import unittest

from tools.download_firmware import decode_avr_hex, extract_payloads, write_outputs


class FirmwareAcquisitionTests(unittest.TestCase):
    def test_hex_checks_records_and_contiguous_layout(self):
        self.assertEqual(decode_avr_hex(":0400000001020304F2\n:00000001FF"), b"\1\2\3\4")
        for text in [":0400000001020304F3\n:00000001FF",  # checksum
                     ":0400000001020304F2",  # missing EOF
                     ":00000001FF",  # empty image
                     ":0400010001020304F1\n:00000001FF",  # gap
                     ":0400000001020304F2\n:00000001FF\n:00000001FF"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                decode_avr_hex(text)

    def test_unverified_updater_rejected_before_offsets_used(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            extract_payloads(b"MZ unverified updater")

    def test_existing_experiment_is_preserved_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "main.dfu").write_bytes(b"patched")
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                write_outputs(output, {"new.bin": b"new", "main.dfu": b"original"})
            self.assertFalse((output / "new.bin").exists())
            self.assertEqual((output / "main.dfu").read_bytes(), b"patched")
            write_outputs(output, {"main.dfu": b"patched", "avr.bin": b"new"})
            self.assertEqual((output / "avr.bin").read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
