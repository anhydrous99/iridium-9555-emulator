"""Short original SMS symbol, case, numeric and English prediction journeys.

The synthetic SIM is read-only; saved drafts use original BC5 local flash.
Selected Latin-1 symbols and English examples do not establish all languages,
symbols, dictionaries, card writes or delivery. Holds are guest instructions.
"""

from hashlib import sha256
import os
import struct
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_messages_drafts_e2e import MessagesDraftChecks
from test_factory_messages_editor_e2e import OPTIONS
from test_factory_messages_local_e2e import MESSAGES, MessagesLocalChecks


# Original UTF-16 constant at HT25003 data2E89 / HL25003 data2E8B.
SYMBOLS = ".;&}->çò@'(:\"+èø/$)~#=éö,£[_|àåù!*]\\<äæü?%{"


class MessagesEditorToolChecks:
    # Aliases deliberately exclude old test methods.
    setUp = MessagesDraftChecks.setUp
    finish = MessagesDraftChecks.finish
    read = MessagesDraftChecks.read
    press = MessagesDraftChecks.press
    original_home_and_scan = MessagesDraftChecks.original_home_and_scan
    text = MessagesDraftChecks.text
    title = MessagesDraftChecks.title
    menu = MessagesDraftChecks.menu
    open_messages = MessagesDraftChecks.open_messages
    empty_mailbox = MessagesDraftChecks.empty_mailbox
    keys = MessagesDraftChecks.keys
    blank = staticmethod(MessagesDraftChecks.blank)
    field = MessagesDraftChecks.field
    reopen_messages = MessagesDraftChecks.reopen_messages
    expect = MessagesDraftChecks.expect
    drafts = MessagesDraftChecks.drafts
    reopen_draft = MessagesDraftChecks.reopen_draft
    actions = MessagesDraftChecks.actions

    def record(self, label):
        return MessagesLocalChecks.record(self, f"{len(self.evidence):03d}-{label}")

    def home(self, label):
        return self.expect(label, lambda state: (
            self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS and state["keys"] == []),
            {"footer": ["Menu", "Help"], "all_keys_released": True})

    def editor(self, value, label, *, title="New", mode="abc", predictive=False):
        counter = str(1000 - len(value))
        _, count_width = self.font.render(counter, 128)
        glyphs, mode_width = self.font.render(mode, 40)

        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, title) and
                    all(pixels[y * 128 + x] == glyphs[y * 40 + x]
                        for y in range(15) for x in range(1, mode_width)) and
                    self.text(state, counter, 0, (127 if predictive else 128) - count_width, count_width) and
                    self.field(state, value, 16, vertical=True) and
                    self.blank(state, 32, 110, 4, 126) and
                    all(pixels[y * 128 + x] == 3 for y in range(15, 112) for x in (3, 126)) and
                    all(pixels[y * 128 + x] == 3 for y in (15, 111) for x in range(3, 127)) and
                    self.text(state, "Options", 112, 2, 45) and
                    self.text(state, "Clear", 112, 97, 30))

        return self.expect(label, matches, {"title": title, "complete_text": value,
            "input_mode": mode, "predictive_widget": predictive, "remaining_characters": int(counter),
            "allowed_caret": "exact vertical line after text, on/off",
            "unused_text_rows_blank": True})

    def options(self, selected, label, *, numeric=False, predictive=False):
        labels = tuple("Enter letters" if numeric and item == "Enter digits" else
                       "Multi-tap" if predictive and item == "Predictive text" else item
                       for item in OPTIONS[self.model])

        def matches(state):
            if not self.title(state, "Options"):
                return False
            for top in range(max(0, selected - 4), selected + 1):
                visible = labels[top:top + 5]
                if (all(self.text(state, item, 16 + row * 17, selected=top + row == selected)
                        for row, item in enumerate(visible)) and
                        self.blank(state, 16 + 17 * len(visible), 111) and
                        self.text(state, "Select", 112, 2, 36) and
                        self.text(state, "Back", 112, 99, 28)):
                    return True
            return False

        return self.expect(label, matches, {"title": "Options", "ordered_labels": labels,
                                           "focused_index": selected})

    def choose_option(self, index, label, *, numeric=False, predictive=False):
        self.keys("soft_left")
        self.options(0, label + "-options", numeric=numeric, predictive=predictive)
        self.keys(*(["down"] * index))
        self.options(index, label + "-focused", numeric=numeric, predictive=predictive)
        self.keys("soft_left")

    def symbol_picker(self, index, label):
        firmware = self.handset.session.firmware["bc5"]
        address = 0x2E89 if self.model == "9555" else 0x2E8B
        words = struct.unpack_from("<44H", firmware.data,
                                   firmware.profile.code_bytes + address * 2)
        self.assertEqual(words, tuple(map(ord, SYMBOLS)) + (0,))
        self.assertEqual(sha256(self.font.data).hexdigest(),
                         "c3af6f17a60d62bd3b984e06886ed801a10899432a6433f0493dac909d3cca03")
        # B811C/CDB3C: maximum glyph advance11 plus4 spacing =>15px cells,
        # eight columns centred at x4. Draw the selected inclusive rectangle
        # before its glyph. Subsequent glyph backgrounds can erase its bottom
        # edge, matching the original BFA6E/BDBEE drawing order.
        expected = bytearray(128 * 128)
        for position, character in enumerate(SYMBOLS):
            row, column = divmod(position, 8)
            left, top = 4 + column * 15, 17 + row * 15
            if position == index:
                for y in range(top, top + 16):
                    expected[y * 128 + left] = expected[y * 128 + left + 15] = 3
                for x in range(left, left + 16):
                    expected[top * 128 + x] = expected[(top + 15) * 128 + x] = 3
            glyphs, width = self.font.render(character, 15)
            x = left + (15 - width) // 2
            for y in range(15):
                expected[(top + y) * 128 + x:(top + y) * 128 + x + width] = glyphs[y * 15:y * 15 + width]
        body = bytes(expected[16 * 128:111 * 128])
        return self.expect(label, lambda state: (
            self.title(state, "Insert symbol") and
            bytes(state["lcd"]["pixels"][16 * 128:111 * 128]) == body and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Insert symbol", "complete_ordered_grid": SYMBOLS,
             "columns": 8, "cell_pitch": 15, "focused_index": index,
             "focused_character": SYMBOLS[index], "unused_cells_blank": True})

    def save_explicit(self, *, predictive=False):
        self.choose_option(3 + (self.model == "9575"), "save-as-draft", predictive=predictive)
        # Original New-message toast differs from Edit-message toast.
        glyphs, width = self.font.render("Saved to drafts", 94)
        self.assertEqual(width, 94)
        body = bytearray(128 * 97)
        for row in range(15):
            start = (48 - 16 + row) * 128 + 17
            body[start:start + width] = glyphs[row * width:(row + 1) * width]
        expected = sha256(body).hexdigest()
        self.expect("saved-local-draft-toast", lambda state: (
            self.handset.screen_hash(state=state) == expected),
            {"literal_message": "Saved to drafts", "glyph_top": 48})
        self.expect("saved-draft-natural-close-home", lambda state: (
            self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS and state["keys"] == []),
            {"footer": ["Menu", "Help"], "original_delayed_close": True}, max_steps=24000000)

    def full_saved_readback_and_cleanup(self, value):
        self.reopen_draft(value)
        self.keys("soft_left")
        self.actions(0, "saved-draft-edit-focused")
        self.keys("soft_left")
        self.editor(value, "complete-saved-text-reopened", title="Edit")
        # Edit removes the original stored entry before opening its copy.
        # Exit discards that copy; re-entering an empty folder proves cleanup.
        self.choose_option(len(OPTIONS[self.model]) - 1, "cleanup-exit")
        self.home("cleanup-exit-home")
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "cleanup-drafts-focused")
        self.empty_mailbox(2, "Drafts")
        self.keys("red")
        self.home("restored-home")

    def test_symbol_picker_case_digits_cancel_and_saved_full_latin1_text(self):
        self.open_messages()
        self.keys("soft_left")
        self.editor("", "empty-abc-editor")
        self.keys("2")
        self.editor("a", "lowercase-a")
        self.keys("#", "3")
        self.editor("aD", "uppercase-D-preserves-a", mode="ABC")
        self.choose_option(1, "insert-pound")
        self.symbol_picker(0, "all-symbols-first-dot-focused")
        self.keys("down", "down", "down")
        self.symbol_picker(24, "comma-before-pound")
        # Original picker B83F2/CDE12 supports the physical numeric2/4/6/8
        # navigation events as well as Up/Down. Numeric6 moves one column.
        self.keys("6")
        self.symbol_picker(25, "pound-focused")
        self.keys("soft_left")
        self.editor("aD£", "pound-inserted", mode="ABC")
        self.choose_option(1, "insert-oslash")
        self.symbol_picker(0, "reopened-picker-starts-at-dot")
        self.keys("down", "4")
        self.symbol_picker(7, "numeric-left-wraps-to-o-grave")
        self.keys("down")
        self.symbol_picker(15, "oslash-focused")
        self.keys("soft_left")
        self.editor("aD£ø", "oslash-inserted", mode="ABC")
        self.choose_option(1, "cancel-symbol")
        self.keys("down", "down")
        self.symbol_picker(16, "tentative-slash-before-cancel")
        self.keys("soft_right")
        self.editor("aD£ø", "picker-back-keeps-exact-text-count", mode="ABC")
        self.choose_option(2 + (self.model == "9575"), "enter-digits")
        self.editor("aD£ø", "numeric-mode-preserves-symbols", mode="123")
        self.keys("4", "2")
        self.editor("aD£ø42", "numeric-42-preserves-symbols", mode="123")
        self.choose_option(2 + (self.model == "9575"), "enter-letters", numeric=True)
        self.keys("5")
        self.editor("aD£ø42j", "letters-resume-after-digits")
        self.keys("red")
        self.home("symbol-text-red-autosave-home")
        self.full_saved_readback_and_cleanup("aD£ø42j")

    def test_english_prediction_next_modes_and_explicit_saved_full_text(self):
        self.open_messages()
        self.keys("soft_left")
        self.editor("", "empty-before-local-predictive-toggle")
        self.choose_option(4 + (self.model == "9575"), "enable-editor-prediction")
        self.editor("", "predictive-wordwise-enabled", mode="ww", predictive=True)
        self.keys("#", "convenience")
        self.editor("", "lowercase-letterwise", mode="lw", predictive=True)
        self.keys("3")
        self.editor("f", "letterwise-first-f", mode="lw", predictive=True)
        self.keys("*")
        self.editor("d", "letterwise-next-d", mode="lw", predictive=True)
        self.keys("soft_right", "convenience", "3")
        self.editor("%", "punctuation-first-percent", mode="#?@", predictive=True)
        self.keys("*")
        self.editor("$", "punctuation-next-dollar", mode="#?@", predictive=True)
        self.keys("convenience", "4", "2")
        self.editor("$42", "prediction-to-digits-preserves-punctuation", mode="123", predictive=True)
        self.keys("convenience", "2")
        self.editor("$42a", "prediction-to-multitap-preserves-digits")
        self.keys("convenience", "0", "7", "3", "3")
        self.editor("$42a see", "wordwise-space-and-see", mode="ww", predictive=True)
        self.keys("*")
        self.editor("$42a red", "wordwise-next-red-preserves-prefix", mode="ww", predictive=True)
        self.save_explicit(predictive=True)
        self.full_saved_readback_and_cleanup("$42a red")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "Set IRIDIUM_TEST_FIRMWARE")
class Factory9555MessagesEditorToolsE2ETests(MessagesEditorToolChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "Set IRIDIUM_TEST_9575_FIRMWARE")
class Factory9575MessagesEditorToolsE2ETests(MessagesEditorToolChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
