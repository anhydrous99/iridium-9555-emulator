"""Original 100-entry phonebook boundary, failed save, and freed-slot reuse."""

from bisect import bisect_left
from hashlib import sha256
from itertools import product
import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from iridium.assets import BC5Assets
from test_factory_customization_e2e import EDITOR_MULTI_TAP, TEXT_LANGUAGE_MENU, TEXT_MULTI_TAP
from test_factory_phonebook_details_e2e import DELETE_ADG, MEMORY_ZERO
from test_factory_phonebook_e2e import EMPTY_PHONEBOOK, ENTRY_ADDED


LIST_HEADER = "6b27989b3ffe5922cd7ad45cfd6e494295de62763fcb0e8efc4cc3f03b66821e"
LIST_CAPTIONS = "91bcc6b3d50d2aefda9c6d577195f7aebdb823044b9e2909f5cf215009382d8a"
MEMORY_HEADER = "865af4961a5a9098047928e3910ddc6e16d1d12d8335a29b9beb92742b83ebec"
SUCCESS_HEADER = "e8896801a7b9f56eb5da4cd4480ba75b5f0f024c4e38a235ff99a8ee3a10a98b"


class OriginalASCII1:
    """Independent expected glyphs from the pinned font, never guest UI state."""

    def __init__(self, firmware):
        assets = BC5Assets(firmware.data, firmware.profile)
        self.data = assets.file_bytes(34 if firmware.model == "9575" else 32)
        assert sha256(self.data).hexdigest() == "c3af6f17a60d62bd3b984e06886ed801a10899432a6433f0493dac909d3cca03"
        assert self.data[:4] == bytes.fromhex("f0420101")
        self.count = int.from_bytes(self.data[4:6], "big")
        self.width, self.height = self.data[6:8]
        self.metrics, self.bitmap, table = [int.from_bytes(self.data[a:a + 4], "big") for a in (8, 12, 16)]
        assert (self.count, self.width, self.height) == (9011, 20, 15)
        assert table == self.metrics + 2 * self.count and self.bitmap == table + 2 * self.count
        assert self.bitmap + self.count * self.width * 2 == len(self.data)
        self.codes = [int.from_bytes(self.data[table + i * 2:table + i * 2 + 2], "big")
                      for i in range(self.count)]
        assert all(a < b for a, b in zip(self.codes, self.codes[1:]))

    def render(self, text, width):
        pixels = bytearray(width * self.height)
        cursor = 0
        for char in text:
            index = bisect_left(self.codes, ord(char))
            assert self.codes[index] == ord(char)
            raw = self.data[self.bitmap + index * 40:self.bitmap + (index + 1) * 40]
            for y in range(15):
                for x in range(20):
                    if raw[(y // 8) * 20 + x] & (1 << (y % 8)):
                        assert 0 <= cursor + x < width
                        pixels[y * width + cursor + x] = 3
            cursor += self.data[self.metrics + 2 * index]
        return bytes(pixels), cursor

    def message(self, lines, divider=True):
        # These one/two-line layouts independently reproduce existing native
        # add-success and named-delete crops before new error expectations run.
        assert 1 <= len(lines) <= 2
        body = bytearray(128 * 97)
        for line_number, line in enumerate(lines):
            _, width = self.render(line, 128)
            glyphs, _ = self.render(line, width)
            left, top = (128 - width) // 2, (126 - 15 * len(lines)) // 2 + 15 * line_number - 16
            for y in range(15):
                body[(top + y) * 128 + left:(top + y) * 128 + left + width] = glyphs[y * width:(y + 1) * width]
        if divider:
            body[(111 - 16) * 128:(112 - 16) * 128] = bytes([3]) * 128
        return sha256(body).hexdigest()


class SharedPhonebookCapacityChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.assertEqual(self.font.message(("Entry added", "successfully"), divider=False), ENTRY_ADDED)
        self.assertEqual(self.font.message(("Are you sure you", "want to delete Adg?")), DELETE_ADG)
        self.handset.boot()
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))),
                  "soft_left", "down", "soft_left")
        self.expect(TEXT_MULTI_TAP)
        self.keys("down", "down", "down", "soft_left")
        self.expect(TEXT_LANGUAGE_MENU)
        self.handset.press("red")
        self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def type_keys(self, sequence):
        # Short input spacing is checked against complete rendered fields.
        # Menu transitions use the fixture's longer ordinary press interval.
        for key in sequence:
            self.handset.press(key, settle_steps=500000)

    def navigate_list(self, key, count):
        self.list_ready()
        for _ in range(count):
            self.handset.press(key)

    def submit(self):
        self.handset.press("soft_left", hold_steps=1000000, settle_steps=0)

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=20000000)

    def expect_text(self, text, *, row, left, width):
        expected, _ = self.font.render(text, width)
        for elapsed in range(0, 20000001, 200000):
            state = self.handset.assert_healthy()
            actual = bytes(state["lcd"]["pixels"][(row + y) * 128 + left + x]
                           for y in range(15) for x in range(width))
            if actual == expected:
                return state
            if elapsed < 20000000:
                self.handset.step(200000)
        self.handset.save_artifacts(f"text-{text}-timeout", state)
        self.assertEqual(actual, expected, f"Original LCD must render {text!r}")

    def list_ready(self):
        self.expect(LIST_HEADER, 0, 14)
        return self.expect(LIST_CAPTIONS, 113, 128)

    def back_to_list(self):
        for _ in range(3):
            self.handset.press("red")
            state = self.handset.assert_healthy()
            if (self.handset.screen_hash(0, 14, state) == LIST_HEADER and
                    self.handset.screen_hash(113, 128, state) == LIST_CAPTIONS):
                return state
            if self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.keys("soft_left", "soft_left")
                return self.list_ready()
        return self.list_ready()

    def memory(self, count):
        self.keys("soft_left", *(["down"] * (5 if count else 1)), "soft_left")
        self.expect(MEMORY_HEADER, 0, 14)
        self.expect_text(f"Used {count} of 100", row=80, left=2, width=126)
        if not count:
            self.expect(MEMORY_ZERO)
        self.handset.save_artifacts(f"memory-{count}")
        self.keys("soft_right", "soft_right")
        self.list_ready()

    def new_draft(self, keys, number, occupied):
        self.keys("soft_left", *(["down"] * 4 if occupied else []), "soft_left")
        self.expect(EDITOR_MULTI_TAP, 0, 14)
        self.type_keys(keys)
        self.keys("down")
        self.type_keys(number)
        name = "".join(dict(zip("23456789", "adgjmptw"))[key] for key in keys).capitalize()
        self.expect_text(name, row=16, left=15, width=113)
        self.keys("up")
        self.expect_text("+" + number, row=32, left=15, width=113)
        return name

    def add(self, keys, number, occupied=True):
        name = self.new_draft(keys, number, occupied)
        self.keys("soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.list_ready()
        return name

    def read_selected(self, name, number):
        self.keys("soft_left", "down", "down", "soft_left")
        self.expect_text("+" + number, row=32, left=15, width=113)
        self.keys("down")
        self.expect_text(name, row=16, left=15, width=113)
        self.handset.save_artifacts(f"saved-{name}-{number}")
        self.back_to_list()

    def test_number_requires_a_name_before_save_consumes_a_contact_slot(self):
        self.memory(0)
        self.keys("soft_left", "soft_left")
        self.expect(EDITOR_MULTI_TAP, 0, 14)
        self.keys("down", "1", "up")
        self.expect_text("+1", row=32, left=15, width=113)
        self.submit()
        self.handset.save_artifacts("unnamed-number-after-save")
        self.expect(self.font.message(("Please enter a name",), divider=False))
        self.keys("soft_right")
        self.expect(EDITOR_MULTI_TAP, 0, 14)
        self.expect_text("+1", row=32, left=15, width=113)
        self.handset.save_artifacts("unnamed-number-draft-retained")
        self.back_to_list()
        self.memory(0)

        # The same form/Save path must work once its required name is present.
        self.keys("soft_left", "soft_left")
        self.expect(EDITOR_MULTI_TAP, 0, 14)
        self.type_keys("234")
        self.keys("down", "1", "up")
        self.expect_text("+1", row=32, left=15, width=113)
        self.submit()
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.list_ready()
        self.memory(1)
        self.read_selected("Adg", "1")
        self.handset.press("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])

    def test_hundred_entry_limit_rejects_extra_preserves_records_and_reuses_deleted_slot(self):
        self.memory(0)
        sequences = ["".join(chars) for chars in product("23456789", repeat=3)
                     if chars[0] != chars[1] and chars[1] != chars[2]][1:102]
        # Starting at Adg reuses its independently inspected delete confirmation.
        contacts = []
        for index, keys in enumerate(sequences[:100]):
            number = str(100 + index)
            name = self.add(keys, number, occupied=bool(index))
            contacts.append((name, number))
            if index == 98:
                self.memory(99)
            if (index + 1) % 10 == 0:
                print(f"{self.model}: {index + 1} original contact saves completed", flush=True)
        self.memory(100)

        self.navigate_list("up", 100)
        self.read_selected(*contacts[0])
        self.navigate_list("down", 49)
        self.read_selected(*contacts[49])
        self.navigate_list("down", 50)
        self.read_selected(*contacts[99])

        failed_name = self.new_draft(sequences[100], "200", occupied=True)
        self.submit()
        self.expect(self.font.message(("Failed to add entry",), divider=False))
        self.handset.save_artifacts("entry-101-rejected")
        self.keys("soft_right")
        self.expect_text("+200", row=32, left=15, width=113)
        self.keys("down")
        self.expect_text(failed_name, row=16, left=15, width=113)
        self.back_to_list()
        self.memory(100)
        self.navigate_list("down", 100)
        self.read_selected(*contacts[99])
        self.keys("down")
        self.read_selected(*contacts[99])  # Failed name sorts after the real last entry.

        self.navigate_list("up", 100)
        self.read_selected(*contacts[0])
        self.keys("soft_left", "down", "down", "down", "soft_left")
        self.expect(DELETE_ADG)
        self.keys("soft_right", "soft_right")
        self.list_ready()
        self.memory(100)
        self.read_selected(*contacts[0])
        self.keys("soft_left", "down", "down", "down", "soft_left")
        self.expect(DELETE_ADG)
        self.keys("soft_left")
        for _ in range(100):
            state = self.handset.assert_healthy()
            if self.handset.screen_hash(113, 128, state) == LIST_CAPTIONS:
                break
            if self.handset.screen_hash(0, 14, state) == SUCCESS_HEADER:
                self.keys("soft_right")
            else:
                self.handset.step(200000)
        self.list_ready()
        self.memory(99)
        self.navigate_list("up", 100)
        self.read_selected(*contacts[1])
        self.assertEqual(self.add(sequences[100], "200"), failed_name)
        self.memory(100)
        self.navigate_list("down", 100)
        self.read_selected(failed_name, "200")
        self.handset.press("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 capacity E2E")
class Factory9555PhonebookCapacityE2ETests(SharedPhonebookCapacityChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 capacity E2E")
class Factory9575PhonebookCapacityE2ETests(SharedPhonebookCapacityChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
