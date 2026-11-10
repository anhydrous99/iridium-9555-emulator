"""Framebuffer transcription uses font evidence, including explicit uncertainty."""

import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from iridium.assets import AssetError, BC5Assets
from iridium.display_text import DisplayText, UNKNOWN, _Font
from iridium.firmware import load_firmware


def font_resource(glyphs, *, height=15, name=b"ASCII-1"):
    """Build the documented font format independently of the reader."""
    width = max(advance for advance, _ in glyphs.values())
    metrics = 21 + len(name)
    metrics += metrics % 2
    table = metrics + len(glyphs) * 2
    bitmap = table + len(glyphs) * 2
    data = bytearray(struct.pack(">4sHBBIII", b"\xf0B\x01\x01", len(glyphs), width, height, metrics, bitmap, table))
    data.extend(bytes([len(name)]) + name)
    data.extend(b"\0" * (metrics - len(data)))
    codes = sorted(glyphs)
    for code in codes:
        data.extend(bytes((glyphs[code][0], height)))
    for code in codes:
        data.extend(struct.pack(">H", ord(code)))
    for code in codes:
        columns = glyphs[code][1]
        data.extend((columns[x] >> (page * 8)) & 255 if x < len(columns) else 0
                    for page in range((height + 7) // 8) for x in range(width))
    return bytes(data)


def glyph(rows, top=4):
    return tuple(sum((row[x] == "#") << (y + top) for y, row in enumerate(rows))
                 for x in range(len(rows[0])))


GLYPHS = {
    " ": (4, ()),
    "A": (6, glyph((".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"))),
    "B": (6, glyph(("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."))),
    "é": (6, glyph(("...#.", "..#..", ".....", ".###.", "#...#", "#####", "#....", ".####"), 2)),
    "中": (8, glyph(("...#...", ".#####.", ".#.#.#.", ".#.#.#.", ".#####.", "...#...", "...#..."))),
}


def reader_for(data):
    with patch("iridium.display_text.BC5Assets") as assets:
        assets.return_value.files = {1: None}
        assets.return_value.file_bytes.return_value = data
        return DisplayText(SimpleNamespace(data=b"fixture", profile=None))


def frame():
    return {"width": 128, "height": 128, "display_on": True,
            "pixels": [0] * 16384, "known": [True] * 16384}


def draw(state, text, glyphs=GLYPHS, *, x=2, y=16, selected=False, height=15):
    if selected:
        state["pixels"][y * 128:(y + height) * 128] = [3] * (height * 128)
    for char in text:
        advance, columns = glyphs[char]
        for cx, column in enumerate(columns):
            for cy in range(height):
                if column & (1 << cy):
                    state["pixels"][(y + cy) * 128 + x + cx] = 0 if selected else 3
        x += advance


class DisplayTextTests(unittest.TestCase):
    def setUp(self):
        self.data = font_resource(GLYPHS)
        self.reader = reader_for(self.data)

    def test_exact_visible_words_spaces_selection_and_latin1(self):
        state = frame()
        draw(state, "AB", y=0, x=58)
        state["pixels"][7 * 128:7 * 128 + 40] = [3] * 40
        state["pixels"][15 * 128:16 * 128] = [3] * 128
        draw(state, "A B é", selected=True)
        draw(state, "B", y=36)
        result = self.reader.read(state)
        self.assertEqual(result["lines"], [
            {"text": "AB", "selected": False}, {"text": "A B é", "selected": True},
            {"text": "B", "selected": False}])
        self.assertTrue(result["complete"])

    def test_unsupported_original_glyph_and_unknown_bitmap_stay_explicit(self):
        state = frame()
        draw(state, "A中B")
        state["pixels"][70 * 128 + 65] = 3
        result = self.reader.read(state)
        self.assertEqual(result["lines"][0]["text"], "A" + UNKNOWN + "B")
        self.assertEqual(result["lines"][1]["text"], UNKNOWN)
        self.assertFalse(result["complete"])

    def test_selection_with_dense_white_letter_strokes(self):
        state = frame()
        draw(state, "A" * 20, selected=True)
        self.assertEqual(self.reader.read(state)["lines"], [{"text": "A" * 20, "selected": True}])

    def test_selection_ends_before_scrollbar_gutter(self):
        state = frame()
        draw(state, "AB", selected=True)
        for y in range(16, 31):
            state["pixels"][y * 128 + 119:(y + 1) * 128] = [0] * 9
        self.assertEqual(self.reader.read(state)["lines"], [{"text": "AB", "selected": True}])

    def test_outlined_field_is_not_inverted_and_cropped_highlight_still_is(self):
        state = frame()
        draw(state, "AB", x=16)
        for y in range(15, 32):
            for x in range(13, 128):
                if y in (15, 31) or x in (13, 127):
                    state["pixels"][y * 128 + x] = 3
        result = self.reader.read(state)
        self.assertTrue(any("AB" in line["text"] for line in result["lines"]))
        self.assertFalse(any(line["selected"] for line in result["lines"]))
        state = frame()
        draw(state, "AB", selected=True)
        state["pixels"][16 * 128:20 * 128] = [0] * (4 * 128)
        self.assertEqual(self.reader.read(state)["lines"], [{"text": "AB", "selected": True}])

    def test_unknown_pixels_and_cursor_overlay_do_not_fabricate_a_letter(self):
        state = frame()
        draw(state, "AB")
        state["known"][20 * 128 + 2] = False
        result = self.reader.read(state)
        self.assertEqual(result["lines"][0]["text"], UNKNOWN + "B")
        self.assertFalse(result["complete"])
        state["known"][20 * 128 + 2] = True
        state["pixels"][16 * 128 + 2] = 3
        self.assertIn(UNKNOWN, self.reader.read(state)["lines"][0]["text"])

    def test_visually_identical_glyphs_are_not_guessed(self):
        glyphs = {**GLYPHS, "C": GLYPHS["A"]}
        reader = reader_for(font_resource(glyphs))
        state = frame()
        draw(state, "AB", glyphs)
        self.assertEqual(reader.read(state)["lines"][0]["text"], UNKNOWN + "B")

    def test_cache_uses_evidence_and_returns_isolated_snapshots(self):
        state = frame()
        draw(state, "A")
        first = self.reader.read(state)
        first["lines"][0]["text"] = "mutated"
        with patch.object(self.reader, "_read", wraps=self.reader._read) as read:
            state["version"] = 999
            self.assertEqual(self.reader.read(state)["lines"][0]["text"], "A")
            read.assert_not_called()
            state["known"][0] = False
            self.assertFalse(self.reader.read(state)["complete"])
            read.assert_called_once()

    def test_display_off_blank_and_invalid_resources_are_distinct(self):
        state = frame()
        self.assertEqual(self.reader.read(state)["lines"], [])
        state["display_on"] = False
        self.assertEqual(self.reader.read(state)["status"], "Display off")
        state["display_on"] = True
        self.assertEqual(reader_for(b"invalid").read(state)["status"], "Display text unavailable")
        for offset in (8, 12, 16, 20):
            broken = bytearray(self.data)
            broken[offset] = 255
            with self.subTest(offset=offset), self.assertRaises(AssetError):
                _Font(broken)

    def test_large_dialling_font_keeps_full_height(self):
        columns = tuple(column << 7 for column in GLYPHS["A"][1])
        large = {"1": (6, columns), "2": (6, tuple(column << 7 for column in GLYPHS["B"][1]))}
        reader = reader_for(font_resource(large, name=b"Dialling", height=27))
        state = frame()
        draw(state, "12", large, y=40, height=27)
        self.assertEqual(reader.read(state)["lines"], [{"text": "12", "selected": False}])

    def test_original_fonts_transcribe_real_menu_messages_and_dialler(self):
        directories = [("9555", os.environ.get("IRIDIUM_TEST_FIRMWARE")),
                       ("9575", os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"))]
        checked = 0
        for model, directory in directories:
            if not directory:
                continue
            firmware = load_firmware(Path(directory), image="bc5", model=model)[0]
            assets, reader = BC5Assets(firmware.data, firmware.profile), DisplayText(firmware)
            for resource, text, selected, top, right in (
                    (34 if model == "9575" else 32, "Create Message", True, 16, 128),
                    (34 if model == "9575" else 32, "Phonebook", True, 16, 119),
                    (34 if model == "9575" else 32, "Entry added", False, 45, 128),
                    (34 if model == "9575" else 32, "A£øé", False, 77, 128),
                    (22 if model == "9575" else 20, "+123", False, 44, 128)):
                data = assets.file_bytes(resource)
                count = int.from_bytes(data[4:6], "big")
                width, height = data[6:8]
                metrics, bitmap, table = [int.from_bytes(data[a:a + 4], "big") for a in (8, 12, 16)]
                glyphs = {}
                for i in range(count):
                    char = chr(int.from_bytes(data[table + i * 2:table + i * 2 + 2], "big"))
                    if char in text:
                        stride = width * ((height + 7) // 8)
                        raw = data[bitmap + i * stride:bitmap + (i + 1) * stride]
                        glyphs[char] = (data[metrics + i * 2], tuple(
                            sum(int(bool(raw[(y // 8) * width + x] & (1 << (y % 8)))) << y
                                for y in range(height)) for x in range(width)))
                state = frame()
                draw(state, text, glyphs, y=top, selected=selected, height=height)
                if selected and right < 128:
                    for y in range(top, top + height):
                        state["pixels"][y * 128 + right:(y + 1) * 128] = [0] * (128 - right)
                with self.subTest(model=model, text=text):
                    self.assertEqual(reader.read(state)["lines"], [{"text": text, "selected": selected}])
                checked += 1
        if not checked:
            self.skipTest("Set firmware environment variables for original-font checks")


if __name__ == "__main__":
    unittest.main()
