from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from iridium.firmware import (BC5_CODE_BYTES, BC5_DATA_BYTES, BC5_PAYLOAD_BYTES,
                              FirmwareError, load_firmware, parse_firmware)
from iridium.profiles import PROFILES


def make_dfu(model="9555"):
    profile = PROFILES[model]
    header = 0x3C8
    end = header + 24 + profile.payload_bytes
    data = bytearray(end + 20)
    struct.pack_into("<8sHIH", data, 0, b"CSR-dfu2", 2, len(data) - 16, header)
    struct.pack_into("<8s4I", data, header, b"CSRbcfw1", 0,
                     profile.code_bytes + 4, profile.data_bytes + 0x10000, 0)
    struct.pack_into("<I", data, header + 8, zlib.crc32(data[header + 12:end]) ^ 0xFFFFFFFF)
    struct.pack_into("<I", data, end, zlib.crc32(data[:end]) ^ 0xFFFFFFFF)
    struct.pack_into("<HHHH3sBI", data, end + 4, 0xFB23, profile.product, 0x1EDD, 0x100, b"UFD", 16, 0)
    struct.pack_into("<I", data, end + 16, zlib.crc32(data[:-4]) ^ 0xFFFFFFFF)
    return bytes(data)


class FirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dfu = make_dfu()

    def test_dfu_validates_three_checksums_and_strips_container(self):
        image = parse_firmware(self.dfu, "main.dfu")
        self.assertEqual(image.data, bytes(BC5_PAYLOAD_BYTES))
        self.assertEqual(image.sha256, sha256(self.dfu).hexdigest())
        self.assertEqual(image.warnings, ())

    def test_descriptions_identify_the_payload_and_keep_mutable_fields_isolated(self):
        original = parse_firmware(self.dfu, "main.dfu")
        patched = parse_firmware(b"\x04\x00" + original.data[2:], "patched.bin", "bc5")
        for image in (original, patched):
            report = image.describe()
            self.assertEqual(report["payload_sha256"], sha256(image.data).hexdigest())
            report["warnings"].append("caller modification")
            self.assertNotIn("caller modification", image.describe()["warnings"])
        self.assertNotEqual(original.describe()["sha256"], original.describe()["payload_sha256"])
        self.assertNotEqual(original.describe()["payload_sha256"], patched.describe()["payload_sha256"])

    def test_patched_dfu_requires_explicit_checksum_override(self):
        patched = bytearray(self.dfu)
        patched[0x3E0] = 0x91
        with self.assertRaisesRegex(FirmwareError, "CRC mismatch"):
            parse_firmware(bytes(patched), "patch.dfu")
        image = parse_firmware(bytes(patched), "patch.dfu", allow_invalid_crc=True)
        self.assertEqual(image.data[0], 0x91)
        self.assertEqual(len(image.warnings), 3)

    def test_invalid_crc_flag_does_not_relax_bounds_or_device_validation(self):
        for offset, value in ((14, 0xFF), (0x3C8 + 12, 0), (len(self.dfu) - 12, 0)):
            data = bytearray(self.dfu)
            data[offset] = value
            with self.assertRaises(FirmwareError):
                parse_firmware(bytes(data), "main.dfu", allow_invalid_crc=True)

    def test_truncated_and_unrecognized_images_rejected(self):
        for data in (b"", b"CSR-dfu2", self.dfu[:-1], b"unrecognized"):
            with self.assertRaises(FirmwareError):
                parse_firmware(data, "firmware.bin")

    def test_raw_patch_uses_exact_supplied_bytes_and_excludes_tail_crc(self):
        data = bytearray(BC5_PAYLOAD_BYTES + 4)
        data[0] = 4
        data[-4:] = b"CRC!"
        image = parse_firmware(bytes(data), "changed.bin")
        self.assertEqual(image.image, "bc5")
        self.assertEqual(image.data[0], 4)
        self.assertEqual(len(image.data), BC5_PAYLOAD_BYTES)

    def test_processor_flash_bounds_and_alignment(self):
        for image, data in (("avr", b"123"), ("avr", bytes(0x4002)),
                            ("trx", b"123"), ("ptt", bytes(0x400004))):
            with self.assertRaises(FirmwareError):
                parse_firmware(data, "patched.bin", image)
        for image, size in (("avr", 8678), ("trx", 0x260760), ("ptt", 0xA7BF8)):
            self.assertEqual(parse_firmware(bytes(size), "patched.bin", image).image, image)
            self.assertEqual(parse_firmware(bytes(size), "patched.bin").image, image)
            with self.assertRaises(FirmwareError):
                parse_firmware(bytes(4), "patched.bin", image)

    def test_loading_does_not_change_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.dfu"
            path.write_bytes(self.dfu)
            self.assertEqual(load_firmware(Path(directory))[0].format, "CSR-dfu2")
            self.assertEqual(path.read_bytes(), self.dfu)

    def test_extreme_container_selects_its_own_layout_and_checks_device(self):
        dfu = make_dfu("9575")
        image = parse_firmware(dfu, "renamed.dfu")
        self.assertEqual(image.model, "9575")
        self.assertEqual(image.describe()["firmware_version"], "HL25003")
        self.assertEqual(len(image.data), 0x36BB22)
        self.assertEqual(image.warnings, ())
        with self.assertRaisesRegex(FirmwareError, "not the selected"):
            parse_firmware(dfu, "main.dfu", model="9555")
        wrong_device = bytearray(dfu)
        struct.pack_into("<H", wrong_device, len(dfu) - 14, 0xA555)
        with self.assertRaisesRegex(FirmwareError, "suffix"):
            parse_firmware(wrong_device, "main.dfu", allow_invalid_crc=True)
        patched = bytearray(dfu)
        patched[0x3E0] = 4
        with self.assertRaisesRegex(FirmwareError, "CRC mismatch"):
            parse_firmware(patched, "main.dfu")
        self.assertEqual(len(parse_firmware(patched, "main.dfu", allow_invalid_crc=True).warnings), 3)

    def test_extreme_raw_images_and_explicit_model_validation(self):
        for processor in ("bc5", "avr"):
            raw = bytes(PROFILES["9575"].image_sizes[processor])
            image = parse_firmware(raw, "patched.bin")
            self.assertEqual((image.model, image.image), ("9575", processor))
            with self.assertRaises(FirmwareError):
                parse_firmware(raw, "patched.bin", model="9555")
        image = parse_firmware(bytes(0x36BB22) + b"CRC!", "patch.bin")
        self.assertEqual(len(image.data), 0x36BB22)
        with self.assertRaises(FirmwareError):
            parse_firmware(bytes(8678), "avr.bin", model="9575")
        with self.assertRaises(FirmwareError):
            parse_firmware(bytes(8678), "avr.bin", model="invalid")

    def test_directory_propagates_primary_model_to_shared_modem_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.dfu").write_bytes(make_dfu("9575"))
            (root / "avr.bin").write_bytes(bytes(14296))
            (root / "trx_seg1_0x10000.bin").write_bytes(bytes(0x260760))
            self.assertEqual([image.model for image in load_firmware(root)], ["9575"] * 3)
            self.assertEqual(load_firmware(root, "trx")[0].model, "9575")
            self.assertEqual(len(load_firmware(root, "bc5")), 1)


if __name__ == "__main__":
    unittest.main()
