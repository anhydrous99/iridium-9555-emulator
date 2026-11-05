"""Original information pages and complete Help bodies through factory HTTP UI.

Help expectations use the pinned original language tables and bitmap font.
Setup's modem placeholders remain literal; the genuine *#06# keypad route
also exposes the local BC5 build string. No hardware identity is invented.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from iridium.assets import BC5Assets
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_customization_e2e import LANGUAGE_MENU
from test_factory_e2e import HELP


RESOURCE_FILES = {
    "9555": (43, "ebe6ba2fdd6869a32b14c5a98cef0b790817c8dfeafb094b7d49af3e792c902a"),
    "9575": (45, "e8d73ece965b22507ddf17d511b5553c220a57426f45010360485630a8e8fd79"),
}
INFO_TITLE = "fb863a5dc70339d11a51c2f092bd0f2d2cec79e0cf73e51f2be1c1daddef3c7e"
BACK = {0: "2fa08a31cb57c635182af1bd80f7e0bc81a6d6f97de60a0b54feb4ee3c08a986",
        12: "16946f534e24559026c167586ad6399a7bb1d2781dbf5a2182af516bcf267809"}
TEXT_HELP = {0: "35b7748c77f82ed5cf78b6d57ffe2bfe300b46ae846fc143f6b6931f966f6a29",
             12: "8240468a41a778fbd339fdc7e0a277a93cc2f5c5ea364133108e49c837034f90"}
SPANISH_MENU_PARENT = "5e99ccba64ec7fac040edae233ab4ceaf0e770f878d46653e27a68e5587adf10"
SPANISH_TEXT_PARENT = "7583d7063f07cc285ed4b9d9bbd5afc6b37f9e7dd282d05390118e88c1523367"
LOCAL_FW_LINES = {"9555": ("FW: 13506352_3-96", "56-XXXX"),
                  "9575": ("FW: 13578033_3-11", "407-XXXX")}


def original_strings(firmware, language):
    file_id, digest = RESOURCE_FILES[firmware.model]
    raw = BC5Assets(firmware.data, firmware.profile).file_bytes(file_id)
    assert sha256(raw).hexdigest() == digest
    words = struct.unpack(">" + str(len(raw) // 2) + "H", raw)
    offset = 0
    found = None
    while offset < len(words):
        kind, locale, size = words[offset:offset + 3]
        payload = words[offset + 3:offset + 3 + size]
        assert len(payload) == size and kind in (3, 4)
        offset += 3 + size
        if kind == 4 and locale == language:
            count = payload[0]
            indices, blob = payload[1:1 + count], payload[1 + count:]
            assert len(indices) == count
            found = {}
            for index, start in enumerate(indices):
                length = blob[start]
                assert start + 1 + length <= len(blob)
                found[0x1000 + index] = "".join(map(chr, blob[start + 1:start + 1 + length]))
    assert offset == len(words) and found is not None
    return found


class InformationHelpChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.handset.boot()
        self.help_evidence = []

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=30000000)

    def glyphs(self, text, row, left=0, width=118, height=15):
        expected, _ = self.font.render(text, width)
        state = self.handset.assert_healthy()
        for elapsed in range(0, 30000001, 200000):
            actual = bytes(state["lcd"]["pixels"][(row + y) * 128 + left + x]
                           for y in range(height) for x in range(width))
            if actual == expected[:width * height]:
                return state
            if elapsed < 30000000:
                state = self.handset.step(200000)
        self.handset.save_artifacts("information-text-timeout", state)
        self.assertEqual(actual, expected[:width * height], text)

    def wrap(self, text):
        lines, line = [], ""
        for word in text.split(" "):
            self.assertLess(self.font.render(word, 2048)[1], 118)
            candidate = line + " " + word if line else word
            if self.font.render(candidate, 2048)[1] >= 118:
                lines.append(line)
                line = word
            else:
                line = candidate
        return lines + [line]

    def help_items(self, strings, resource, *, predictive_language=0):
        # The paragraph is prewrapped into separate list items. Punctuation
        # Internal lines are 15 pixels apart; separate items add one pixel
        # (HT7EE4A/7EF4A, HL7F372/7F472).
        items = [[line] for line in self.wrap(strings[resource])]
        if resource == 0x126A:
            start = 0x1270 if predictive_language == 12 else 0x126C
            for resource_id in (0x126B, *range(start, start + 4), 0x1274):
                items.append(self.wrap(strings[resource_id]))
        return items

    def help_view(self, items, first):
        expected = bytearray(118 * 111)
        top = 0
        for item in items[first:]:
            for line_number, line in enumerate(item):
                glyphs, _ = self.font.render(line, 118)
                for y in range(15):
                    row = top + line_number * 15 + y
                    if row < 111:
                        expected[row * 118:(row + 1) * 118] = glyphs[y * 118:(y + 1) * 118]
            top += 15 * len(item) + 1
            if top >= 111:
                break
        return bytes(expected)

    def expect_help_view(self, items, first, language, resource):
        wanted = self.help_view(items, first)
        state = self.handset.assert_healthy()
        for elapsed in range(0, 30000001, 200000):
            pixels = state["lcd"]["pixels"]
            actual = bytes(pixels[y * 128 + x] for y in range(111) for x in range(2, 120))
            if actual == wanted and self.handset.screen_hash(113, 128, state) == BACK[language]:
                self.handset.assert_healthy(state)
                self.assertEqual(state["keys"], [])
                return state
            if elapsed < 30000000:
                state = self.handset.step(200000)
        self.handset.save_artifacts(f"help-{language}-{resource:04x}-{first:02d}-timeout", state)
        self.assertEqual(actual, wanted, f"Help resource 0x{resource:04x}, locale {language}, top item {first}")
        self.assertEqual(self.handset.screen_hash(113, 128, state), BACK[language])

    def scan_help(self, strings, resource, language=0, *, reverse=False, predictive_language=0):
        items = self.help_items(strings, resource, predictive_language=predictive_language)
        heights = [15 * len(item) + 1 for item in items]
        maximum, tail = len(items) - 1, heights[-1] - 1
        while maximum and tail + heights[maximum - 1] <= 111:
            maximum -= 1
            tail += heights[maximum]
        state = self.expect_help_view(items, 0, language, resource)
        self.keys("up")
        self.expect_help_view(items, 0, language, resource)
        captures = []
        for first in range(maximum + 1):
            if first:
                self.keys("down")
            state = self.expect_help_view(items, first, language, resource)
            path = self.handset.save_artifacts(f"help-{language}-{resource:04x}-{first:02d}", state)
            captures.append(str(path))
        self.keys("down")
        self.expect_help_view(items, maximum, language, resource)
        if reverse:
            for first in reversed(range(maximum)):
                self.keys("up")
                self.expect_help_view(items, first, language, resource)
            self.keys("up")
            self.expect_help_view(items, 0, language, resource)
        self.help_evidence.append({"resource": hex(resource), "language": language,
                                   "items": items, "last_top_item": maximum, "captures": captures})
        target = self.handset.save_artifacts(f"help-{language}-{resource:04x}-complete")
        Path(str(target) + "-text.json").write_text(json.dumps(self.help_evidence[-1], ensure_ascii=False, indent=2) + "\n")

    def information_page(self, *, local=False, hardware=False):
        self.expect(INFO_TITLE, 0, 14)
        self.glyphs("Phone Information", 0, 9, 109, 14)
        if hardware:
            self.glyphs("HW: GRev@-XXXX", 16)
        elif local:
            for row, text in zip((16, 31), LOCAL_FW_LINES[self.model]):
                self.glyphs(text, row)
            self.glyphs("IMEI: XXXX", 48)
        else:
            self.glyphs("FW: HTxxxxx", 16)
            self.glyphs("IMEI: XXXX", 33)
        self.expect(BACK[0], 113, 128)
        self.handset.save_artifacts(f"information-{'local' if local else 'setup'}-{'hardware' if hardware else 'firmware'}")

    def test_setup_and_keypad_information_show_original_builds_and_honest_placeholders(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (8 + (self.model == "9575"))), "soft_left")
        self.information_page()
        self.keys("up")
        self.information_page()
        self.keys("down")
        self.information_page(hardware=True)
        self.keys("down")
        self.information_page(hardware=True)
        self.keys("up", "soft_right", "soft_left")
        self.information_page()  # Back to Setup and reopen resets the page.
        self.keys("soft_right", "soft_right", "soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("*", "#", "0", "6", "#", "green")
        self.information_page(local=True)
        self.keys("down")
        self.information_page(local=True, hardware=True)
        self.keys("up")
        self.information_page(local=True)
        self.keys("soft_right", "red")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])

    def test_every_available_english_help_body_scrolls_clamps_and_reopens(self):
        strings = original_strings(self.handset.session.firmware["bc5"], 0)
        self.keys("soft_right")
        self.expect(HELP)
        count = 9 if self.model == "9575" else 6
        for index in range(count):
            if index:
                self.keys("down")
            self.keys("soft_left")
            if index == 5:
                self.expect(TEXT_HELP[0])
                self.keys("soft_left")
                self.scan_help(strings, 0x126A)
                self.keys("soft_right", "down", "soft_left")
                self.scan_help(strings, 0x1275)
                self.keys("soft_right", "soft_right")
            else:
                resource = 0x1265 + index if index < 5 else 0x1333 + index - 6
                self.scan_help(strings, resource, reverse=index == 1)
                self.keys("soft_right")
        bottom = self.handset.screen_hash(0, 113)
        self.keys("down")
        self.assertEqual(self.handset.screen_hash(0, 113), bottom)
        self.keys(*(["up"] * (count - 1)))
        self.expect(HELP)
        self.keys("up")
        self.expect(HELP)
        self.keys("soft_left")
        self.expect_help_view(self.help_items(strings, 0x1265), 0, 0, 0x1265)
        self.keys("soft_right", "soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)

    def test_spanish_predictive_punctuation_and_multitap_help_use_original_text(self):
        strings = original_strings(self.handset.session.firmware["bc5"], 12)
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))), "soft_left")
        self.expect(LANGUAGE_MENU)
        self.keys("soft_left", *(["down"] * 12), "soft_left")
        self.expect(SPANISH_MENU_PARENT, 0, 128)
        self.keys("down", "soft_left", "up", "up", "up", "down", "down", "soft_left")
        self.expect(SPANISH_TEXT_PARENT)
        self.keys("soft_right", "soft_right", "soft_right", "soft_right",
                  "down", "down", "down", "down", "down", "soft_left")
        self.expect(TEXT_HELP[12])
        self.keys("soft_left")
        self.scan_help(strings, 0x126A, 12, reverse=True, predictive_language=12)
        self.keys("soft_right", "down", "soft_left")
        self.scan_help(strings, 0x1275, 12)
        self.keys("soft_right", "soft_right", "soft_right")
        # Restore both independent language preferences through their widgets.
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))), "soft_left",
                  "down", "soft_left", "up", "up", "up", "soft_left")
        self.expect(SPANISH_TEXT_PARENT)
        self.keys("up", "soft_left", *(["up"] * 23), "soft_left")
        self.expect(LANGUAGE_MENU)
        self.keys("soft_right", "soft_right", "soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 information/Help E2Es")
class Factory9555InformationHelpE2ETests(InformationHelpChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 information/Help E2Es")
class Factory9575InformationHelpE2ETests(InformationHelpChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
