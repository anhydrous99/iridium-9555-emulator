"""Original local SMS draft chunks and the exact1000-character editor boundary.

Genuine HTTP electrical keys, original BC5/AVR/TRX execution and read-only SIM.
Complete saved text is matched against the original font in overlapping native
viewports. The1000-character journey remains enabled if original DSP execution
halts before it can reach the boundary; no modem clock or callback is changed.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from test_factory_messages_drafts_e2e import MessagesDraftChecks as _Drafts
from test_factory_messages_editor_e2e import MessagesEditorChecks as _Editor
from test_factory_messages_local_e2e import MessagesLocalChecks as _Messages


def original_digit_pattern(length):
    """Unique five-digit windows, equal seven-pixel advances, no repeated key."""
    alphabet = "12356789"
    work = [0] * 29
    cycle = []

    def visit(t, period):
        if t > 4:
            if 4 % period == 0:
                cycle.extend(work[1:period + 1])
            return
        work[t] = work[t - period]
        visit(t + 1, period)
        for digit in range(work[t - period] + 1, 7):
            work[t] = digit
            visit(t + 1, t)

    visit(1, 1)
    position = 0
    value = alphabet[position]
    for delta in cycle[:length - 1]:
        position = (position + delta + 1) % len(alphabet)
        value += alphabet[position]
    assert len(value) == length
    assert len({value[i:i + 5] for i in range(length - 4)}) == length - 4
    assert all(a != b for a, b in zip(value, value[1:]))
    return value


class MessagesDraftLimitChecks:
    # Aliases reuse fixture/observation helpers without inheriting old tests.
    read = _Messages.read
    press = _Messages.press
    original_home_and_scan = _Messages.original_home_and_scan
    text = _Messages.text
    title = _Messages.title
    menu = _Messages.menu
    open_messages = _Messages.open_messages
    keys = _Editor.keys
    blank = staticmethod(_Editor.blank)
    field = _Editor.field
    options = _Editor.options
    reopen_messages = _Editor.reopen_messages
    numeric_mode = _Drafts.numeric_mode
    save = _Drafts.save
    drafts = _Drafts.drafts
    reopen_draft = _Drafts.reopen_draft
    actions = _Drafts.actions
    edit = _Drafts.edit

    def setUp(self):
        _Messages.setUp(self)
        self.input_holds = []
        self.viewport_coverage = []
        self.heap_diagnostics = []
        self._views = {}
        self._origin = next(cpu["steps"] for cpu in self.handset.state()["processors"]
                            if cpu["image"] == "trx")
        for char in "12356789":
            self.assertEqual(self.font.render(char, 24)[1], 7)

    def capture_heap(self, label):
        # Read-only original ordinary-heap evidence. Splitting the range obeys
        # the native4096-word read limit; no guest allocation/state is changed.
        chunks = []
        for address in range(0xCA80, 0xEC60, 4096):
            chunks.append({"address": address,
                "values": self.read("bc5", address, min(4096, 0xEC60 - address))})
        snapshot = {"label": label, "globals_address": 0xEFC0,
            "globals_values": self.read("bc5", 0xEFC0, 0x14),
            "ordinary_heap_start": 0xCA80, "ordinary_heap_end_exclusive": 0xEC60,
            "ordinary_heap_chunks": chunks,
            "scratch_depth_F55A": self.read("bc5", 0xF55A)}
        self.heap_diagnostics.append(snapshot)
        return snapshot

    def finish(self):
        # Read-only diagnostics are captured before the fixture closes workers.
        # They do not alter the keypad/guest allocator or make an outcome pass.
        self.panic_diagnostics = None
        try:
            state = self.handset.state()
            bc5 = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
            if bc5["halt"] == "firmware-panic":
                start = max(0xF000, bc5["sp"] - 32)
                count = min(0xFD00 - start, 192)
                self.panic_diagnostics = {
                    "bc5": bc5, "stack_start": start,
                    "stack_values": self.read("bc5", start, count),
                    "scratch_head_A000": self.read("bc5", 0xA000, 8),
                    "scratch_depth_F55A": self.read("bc5", 0xF55A),
                    "ordinary_heap": self.capture_heap("native-panic"),
                }
                target = self.handset.save_artifacts(f"{len(self.evidence):04d}-native-panic", state)
                Path(str(target) + ".panic.json").write_text(
                    json.dumps(self.panic_diagnostics, indent=2) + "\n")
        finally:
            _Messages.finish(self)

    def record(self, label):
        # Shared menu/save helpers reuse labels; keep every actual observation.
        return _Messages.record(self, f"{len(self.evidence):04d}-{label}")

    def healthy(self):
        state = self.handset.assert_healthy()
        self.peer.check()
        trx = next(cpu for cpu in state["processors"] if cpu["image"] == "trx")
        self.assertLessEqual(trx["steps"] - self._origin, 5000000000,
                             "Local-draft journey exceeded its relative5B instruction budget")
        return state

    def expect(self, label, predicate, oracle, *, max_steps=4000000):
        for elapsed in range(0, max_steps + 1, 100000):
            state = self.healthy()
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < max_steps:
                self.handset.step(100000)
        self.handset.save_artifacts(f"{len(self.evidence):04d}-{label}-timeout", state)
        self.fail(f"Original LCD did not match {label}: {oracle}")

    def counter_pixels(self, remaining):
        value = str(remaining)
        glyphs, width = self.font.render(value, 28)
        expected = bytearray(28 * 15)
        for y in range(15):
            expected[y * 28 + 28 - width:(y + 1) * 28] = glyphs[y * 28:y * 28 + width]
        # Original title divider reaches the right-aligned numeric counter.
        for x in range(28 - width):
            expected[7 * 28 + x] = 3
        return bytes(expected)

    def count_matches(self, state, remaining):
        actual = bytes(state["lcd"]["pixels"][y * 128 + x]
                       for y in range(15) for x in range(100, 128))
        return actual == self.counter_pixels(remaining)

    def counter(self, remaining, label):
        return self.expect(label, lambda state: self.count_matches(state, remaining),
                           {"remaining_characters": remaining, "original_font_crop": [100, 0, 128, 15]})

    def enter_one(self, key, remaining):
        # Distinct physical cadence: a fixed400k total down interval followed
        # by release, then wait for the independently visible accepted count.
        # No accepted key is replayed; slow drawing can consume up to4M steps.
        self.assertTrue(self.handset.key(key, True)["delivered"])
        try:
            self.handset.step(250000)
        finally:
            self.assertTrue(self.handset.key(key, False)["delivered"])
        waited = 0
        while True:
            state = self.healthy()
            if self.count_matches(state, remaining):
                break
            self.assertLess(waited, 4000000, f"Released key {key} did not produce counter{remaining}")
            self.handset.step(25000)
            waited += 25000
        self.input_holds.append({"key": key, "remaining": remaining,
                                 "additional_held_steps": 250000,
                                 "additional_released_steps": waited})

    def type_value(self, value):
        for index, key in enumerate(value):
            self.enter_one(key, 999 - index)
            if (index + 1) % 25 == 0 or index + 1 == len(value):
                self.record(f"accepted-{index + 1}-characters")
                self.evidence[-1]["oracle"] = {"remaining_characters": 999 - index,
                                                "commanded_text_prefix": value[:index + 1],
                                                "visibly_accepted_character_count": index + 1}

    def view(self, value, start):
        key = (value, start)
        if key not in self._views:
            body = bytearray(122 * 95)
            rows = []
            for row in range(6):
                text = value[start + 17 * row:start + 17 * (row + 1)]
                glyphs, _ = self.font.render(text, 122)
                for y in range(15):
                    offset = (15 * row + y) * 122
                    body[offset:offset + 122] = glyphs[y * 122:(y + 1) * 122]
                rows.append(text)
            body[94 * 122:95 * 122] = bytes([3]) * 122  # Native lower border y110.
            self._views[key] = (bytes(body), rows)
        return self._views[key]

    @staticmethod
    def body_with_original_caret(actual, expected, rows):
        if actual == expected:
            return {"visible": False}
        differences = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
        column = differences[0] % 122
        if any(i % 122 != column or actual[i] != 3 for i in differences):
            return None
        row = (differences[0] // 122) // 15
        if row >= 6 or column % 7 or column // 7 > len(rows[row]):
            return None
        visible = bytearray(expected)
        for y in range(15 * row, 15 * row + 16):
            visible[y * 122 + column] = 3
        if actual != visible:
            return None
        return {"visible": True, "row": row, "x": column + 4,
                "height": 16, "width": 1}

    def matched_view(self, state, value):
        actual = bytes(state["lcd"]["pixels"][y * 128 + x]
                       for y in range(16, 111) for x in range(4, 126))
        found = []
        # Original B73D2 can anchor a scrolled viewport one character before
        # the caret, so inspect all possible text starts, not just row multiples.
        for start in range(max(1, len(value) - 4)):
            expected, rows = self.view(value, start)
            caret = self.body_with_original_caret(actual, expected, rows)
            if caret is not None:
                found.append({"start": start, "end": min(len(value), start + 102), "caret": caret})
        self.assertLessEqual(len(found), 1, "Expected digit windows must identify one unambiguous viewport")
        return found[0] if found else None

    def editor(self, value, label, *, title="Edit", numeric=False):
        if len(value) < 5:
            return _Drafts.editor(self, value, label, title=title, numeric=numeric)
        mode, _ = self.font.render("123" if numeric else "abc", 21)
        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, title) and self.count_matches(state, 1000 - len(value)) and
                    all(pixels[y * 128 + x] == mode[y * 21 + x]
                        for y in range(15) for x in range(1, 20)) and
                    self.matched_view(state, value) is not None and
                    all(pixels[y * 128 + x] == 3 for y in range(15, 112) for x in (3, 126)) and
                    all(pixels[y * 128 + x] == 3 for y in (15, 111) for x in range(3, 127)) and
                    self.text(state, "Options", 112, 2, 45) and self.text(state, "Clear", 112, 97, 30))
        return self.expect(label, matches, {"title": title, "complete_expected_text": value,
            "remaining_characters": 1000 - len(value), "source_wrap_width": 121,
            "digit_advance": 7, "line_height": 15, "visible_lines": 6,
            "caret": "at most one exact16-pixel vertical column at a text boundary"})

    def complete_readback(self, value):
        self.assertEqual(len({value[i:i + 5] for i in range(len(value) - 4)}), len(value) - 4)
        seen = set()
        windows = []
        for move in range((len(value) + 16) // 17 + 9):
            state = self.editor(value, f"saved-readback-up-{move}")
            match = self.matched_view(state, value)
            seen.update(range(match["start"], match["end"]))
            windows.append({"up_presses": move, **match})
            self.evidence[-1]["oracle"]["actual_matching_viewport"] = match
            if len(seen) == len(value):
                self.viewport_coverage.append({"text": value, "covered_indices": sorted(seen),
                    "viewports": windows, "complete": True, "font_sha256": sha256(self.font.data).hexdigest()})
                return
            # Original CA/CB handler B798E moves by rendered line. No direct
            # cursor/buffer manipulation, callback or guest memory write.
            self.press("up", hold=500000, settle=100000)
        self.viewport_coverage.append({"text": value, "covered_indices": sorted(seen), "viewports": windows})
        self.fail(f"Saved local draft exposed{len(seen)} of{len(value)} glyph positions")

    def new_numeric(self):
        self.open_messages()
        self.keys("soft_left")
        self.editor("", "new-empty-editor", title="New")
        self.numeric_mode("", title="New")
        self.counter(1000, "original1000-capacity")
        self.capture_heap("empty-original-editor-before-input")

    def save_and_read_every_character(self, value):
        self.editor(value, "complete-input-count-and-viewport", title="New", numeric=True)
        self.save(title="New")
        self.reopen_draft(value[:12])
        self.edit(value)
        self.complete_readback(value)

    def test_201_character_local_draft_crosses_flash_chunk_and_reopens_every_glyph(self):
        value = original_digit_pattern(201)
        self.assertNotEqual(value[199], value[200])
        self.new_numeric()
        self.type_value(value)
        self.save_and_read_every_character(value)

    def test_1000_character_local_draft_limit_rejects_extra_and_reopens_every_glyph(self):
        value = original_digit_pattern(1000)
        self.new_numeric()
        self.type_value(value)
        state = self.editor(value, "full1000-input", title="New", numeric=True)
        before = self.matched_view(state, value)
        self.press("4")  # Different glyph, rejected without replacing the suffix.
        state = self.editor(value, "overflow-rejected-at1000", title="New", numeric=True)
        after = self.matched_view(state, value)
        self.assertEqual((after["start"], after["end"]), (before["start"], before["end"]))
        self.enter_one("soft_right", 1)
        self.editor(value[:-1], "backspace-frees-one-place", title="New", numeric=True)
        self.enter_one(value[-1], 0)
        self.save_and_read_every_character(value)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesDraftLimitsE2ETests(MessagesDraftLimitChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesDraftLimitsE2ETests(MessagesDraftLimitChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
