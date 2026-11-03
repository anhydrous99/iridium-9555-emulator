import struct
import unittest
import zlib

from iridium.assets import AssetError, BC5Assets


DIRECTORY = 0x1000
DATA = DIRECTORY + BC5Assets.DIRECTORY_SLOTS * 10


def image_with_file(content, size=None):
    image = bytearray(BC5Assets.WINDOW_OFFSET + 2 * BC5Assets.DIRECTORY_POINTER + 4)
    address = DIRECTORY // 2 + BC5Assets.ADDRESS_BIAS
    struct.pack_into("<HH", image, BC5Assets.WINDOW_OFFSET + 2 * BC5Assets.DIRECTORY_POINTER, address >> 16, address & 0xFFFF)
    for slot in range(BC5Assets.DIRECTORY_SLOTS):
        struct.pack_into("<5H", image, DIRECTORY + slot * 10, 0xFFFF, 0, 0, 0, 0)
    address = DATA // 2 + BC5Assets.ADDRESS_BIAS
    length = len(content) if size is None else size
    struct.pack_into("<5H", image, DIRECTORY, 19, address >> 16, address & 0xFFFF, length >> 16, length & 0xFFFF)
    image[DATA:DATA + len(content)] = content
    return image


class AssetsTest(unittest.TestCase):
    def test_page_order_planes_frames_and_partial_page(self):
        header = struct.pack("<4H", 3, 2, 9, 2)
        words = (0x0101, 0x0200, 0x0001, 0x0100, 0, 0, 0, 0)
        assets = BC5Assets(image_with_file(header + struct.pack("<8H", *words)))
        frame = assets.bitmap(19)
        self.assertEqual((frame.width, frame.height, frame.frame_count), (2, 9, 2))
        self.assertEqual(frame.pixels, bytes((3, 0, 0, 2)) + bytes(12) + bytes((1, 2)))
        self.assertEqual(assets.bitmap(19, 1).pixels, bytes(18))
        with self.assertRaises(AssetError):
            assets.bitmap(19, -1)
        with self.assertRaises(AssetError):
            assets.bitmap(19, 2)

    def test_byte_stream_swaps_words_and_trims_odd_length(self):
        assets = BC5Assets(image_with_file(b"BADC", size=3))
        self.assertEqual(assets.file_bytes(19), b"ABC")

    def test_rejects_truncated_bad_pointer_and_duplicate_directory(self):
        with self.assertRaises(AssetError):
            BC5Assets(b"\0\0")
        image = image_with_file(b"\0\0")
        pointer = BC5Assets.WINDOW_OFFSET + 2 * BC5Assets.DIRECTORY_POINTER
        struct.pack_into("<HH", image, pointer, 0xFFFF, 0xFFFF)
        with self.assertRaises(AssetError):
            BC5Assets(image)
        image = image_with_file(b"\0\0")
        image[DIRECTORY + 10:DIRECTORY + 20] = image[DIRECTORY:DIRECTORY + 10]
        with self.assertRaises(AssetError):
            BC5Assets(image)

    def test_rejects_file_outside_resource_region(self):
        image = image_with_file(b"\0\0")
        struct.pack_into("<HH", image, DIRECTORY + 6, 0xFFFF, 0xFFFF)
        with self.assertRaises(AssetError):
            BC5Assets(image)

    def test_rejects_bitmap_length_mismatch_and_unknown_file(self):
        assets = BC5Assets(image_with_file(struct.pack("<4H", 3, 128, 128, 98)))
        with self.assertRaises(AssetError):
            assets.bitmap(19)
        with self.assertRaises(AssetError):
            assets.bitmap(20)

    def test_png_contains_exact_decoded_grayscale_rows(self):
        assets = BC5Assets(image_with_file(struct.pack("<4H2H", 3, 2, 1, 1, 0x0101, 0x0001)))
        png = assets.bitmap(19).to_png()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        offset = 8
        compressed = bytearray()
        while offset < len(png):
            length = struct.unpack_from(">I", png, offset)[0]
            kind = png[offset + 4:offset + 8]
            payload = png[offset + 8:offset + 8 + length]
            crc = struct.unpack_from(">I", png, offset + 8 + length)[0]
            self.assertEqual(crc, zlib.crc32(kind + payload))
            if kind == b"IDAT":
                compressed.extend(payload)
            offset += length + 12
        self.assertEqual(zlib.decompress(compressed), b"\0\0\xaa")


if __name__ == "__main__":
    unittest.main()
