"""Original Messages editor and local recipient cancellation, with a read-only SIM.

The number guard rejects empty text and the bare configured '+' prefix. These
journeys do not establish broader telephone-number validation, card writes or
delivery. Held intervals are guest instructions, not physical timing claims.
"""

import os
import unittest

from factory_handset import HOME_CAPTIONS
from test_factory_e2e import MAIN_MENU
from test_factory_messages_local_e2e import MESSAGES, MessagesLocalChecks


OPTIONS = {
    "9555": ("Send", "Insert symbol", "Enter digits", "Save as draft", "Predictive text", "Exit"),
    "9575": ("Send", "Insert symbol", "Insert Location", "Enter digits",
             "Save as draft", "Predictive text", "Exit"),
}


class MessagesEditorChecks:
    # Reuse only fixture/observation methods: inheriting the old mixin would
    # discover its preference tests again in this independent module.
    setUp = MessagesLocalChecks.setUp
    finish = MessagesLocalChecks.finish
    read = MessagesLocalChecks.read
    record = MessagesLocalChecks.record
    press = MessagesLocalChecks.press
    submit = MessagesLocalChecks.submit
    original_home_and_scan = MessagesLocalChecks.original_home_and_scan
    text = MessagesLocalChecks.text
    title = MessagesLocalChecks.title
    menu = MessagesLocalChecks.menu
    open_messages = MessagesLocalChecks.open_messages
    empty_mailbox = MessagesLocalChecks.empty_mailbox

    def keys(self, *keys):
        for key in keys:
            self.press(key)

    def expect(self, label, predicate, oracle):
        for elapsed in range(0, 4000001, 200000):
            state = self.handset.assert_healthy()
            self.peer.check()
            self.assertLess(next(cpu["steps"] for cpu in state["processors"]
                                 if cpu["image"] == "trx"), 300000000)
            if predicate(state):
                self.record(label)
                self.evidence[-1]["oracle"] = oracle
                return state
            if elapsed < 4000000:
                self.handset.step(200000)
        self.handset.save_artifacts(label + "-timeout", state)
        self.fail(f"Original LCD did not match {label}: {oracle}")

    @staticmethod
    def blank(state, top, bottom, left=2, right=120):
        return not any(state["lcd"]["pixels"][row * 128 + x]
                       for row in range(top, bottom) for x in range(left, right))

    def field(self, state, value, row, width=122, *, vertical=False):
        expected, advance = self.font.render(value, width)
        pixels = state["lcd"]["pixels"]
        # Text and numeric widgets blink a vertical caret and a five-pixel
        # underline respectively. Accept exactly the fully on/off renderings;
        # every glyph and every other trailing pixel remains compared.
        caret = ([y * width + advance for y in range(15)] if vertical else
                 [14 * width + x for x in range(advance, advance + 5)])
        self.assertTrue(all(not expected[index] for index in caret))
        visible = bytearray(expected)
        for index in caret:
            visible[index] = 3
        actual = bytes(pixels[(row + y) * 128 + 4 + x]
                       for y in range(15) for x in range(width))
        return actual in (expected, bytes(visible))

    def editor(self, value, label):
        counter = str(1000 - len(value))
        _, counter_width = self.font.render(counter, 128)

        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, "New") and
                    self.text(state, counter, 0, 128 - counter_width, counter_width) and
                    self.field(state, value, 16, vertical=True) and self.blank(state, 32, 110, 4, 126) and
                    all(pixels[y * 128 + x] == 3 for y in range(15, 112) for x in (3, 126)) and
                    all(pixels[y * 128 + x] == 3 for y in (15, 111) for x in range(3, 127)) and
                    self.text(state, "Options", 112, 2, 45) and
                    self.text(state, "Clear", 112, 97, 30))

        return self.expect(label, matches, {"title": "New", "complete_text": value,
            "remaining_characters": int(counter), "active_field_border": [3, 15, 126, 111],
            "allowed_caret": "vertical 15-pixel line on/off after text", "unused_text_rows_blank": True})

    def options(self, selected, label, *, numeric=False):
        # Original84378/872C2 choose11FC after numeric recipient input has
        # changed the shared text mode; otherwise they choose11FB.
        labels = tuple("Enter letters" if numeric and item == "Enter digits" else item
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

    def recipients(self, value, selected, label):
        labels = ("New Recipient",) + ((value,) if value else ())
        right = "Remove" if selected else "Add"
        _, right_width = self.font.render(right, 128)
        return self.expect(label, lambda state: (
            self.title(state, "Send To") and
            all(self.text(state, item, 16 + 17 * row, selected=row == selected)
                for row, item in enumerate(labels)) and
            self.blank(state, 16 + 17 * len(labels), 111) and
            (self.text(state, "Send", 112, 2, 29) if value else
             self.blank(state, 112, 127, 2, 31)) and
            self.text(state, right, 112, 127 - right_width, right_width)),
            {"title": "Send To", "complete_rows": labels, "focused_index": selected,
             "empty_list_has_no_send_caption": not bool(value), "right_action": right})

    def chooser(self, label):
        return self.expect(label, lambda state: (
            self.title(state, "Select Recipient") and
            self.text(state, "Enter Number...", 16, width=117, selected=True) and
            self.text(state, "Select", 112, 2, 36) and self.text(state, "Back", 112, 99, 28)),
            {"title": "Select Recipient", "focused_first_row": "Enter Number..."})

    def number(self, value, label):
        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, "Send To") and
                    self.text(state, "Number:", 16, 4, 122) and self.field(state, value, 32) and
                    all(pixels[y * 128 + x] == 3 for y in (31, 47) for x in range(2, 128)) and
                    all(pixels[y * 128 + x] == 3 for y in range(31, 48) for x in (2, 127)) and
                    self.blank(state, 48, 111) and
                    self.text(state, "OK", 112, 2, 18) and
                    self.text(state, "Clear", 112, 97, 30))
        return self.expect(label, matches, {"title": "Send To", "label": "Number:",
            "complete_number": value, "active_field_border": [2, 31, 127, 47],
            "allowed_caret": "five-pixel underline on/off after text"})

    def rejected_number(self, label):
        expected = self.font.message(("Enter a valid number",), divider=False)
        return self.expect(label, lambda state: (
            self.title(state, "Error") and self.handset.screen_hash(state=state) == expected),
            {"title": "Error", "literal_message": "Enter a valid number"})

    def home(self, label):
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.record(label)

    def reopen_messages(self):
        self.keys("soft_left")
        self.handset.wait_screen(MAIN_MENU[0][1], last=97, max_steps=2000000)
        self.keys("down", "down")
        self.handset.wait_screen(MAIN_MENU[2][1], last=97, max_steps=2000000)
        self.keys("soft_left")
        self.menu(MESSAGES, 0, "messages-reopened-after-discard")

    def discard(self, label, *, numeric=False):
        self.keys("soft_left")
        self.options(0, label + "-options", numeric=numeric)
        exit_index = len(OPTIONS[self.model]) - 1
        self.keys(*(["down"] * exit_index))
        self.options(exit_index, label + "-visible-exit", numeric=numeric)
        # Original9555 8467E /9575 8760C free the editor context.
        # Save-as-draft (C48A6) and actual Send (8570E) are separate actions.
        self.keys("soft_left")
        self.home(label + "-home")

    def test_compose_number_guards_local_recipient_cancel_remove_and_discard(self):
        self.open_messages()
        self.keys("soft_left")
        self.editor("", "empty-new-editor")
        self.keys("2", "3", "4")
        self.editor("adg", "literal-adg-count-997")
        self.keys("soft_left")
        self.options(0, "compose-options-send-focus")
        self.keys("soft_left")
        empty = self.recipients(None, 0, "empty-recipient-list")
        self.keys("soft_left")
        unchanged = self.recipients(None, 0, "empty-send-has-no-action")
        self.assertEqual(empty["lcd"]["pixels"], unchanged["lcd"]["pixels"])
        self.keys("soft_right")
        self.chooser("add-recipient-chooser")
        self.keys("soft_left")
        self.number("+", "bare-prefix-number-draft")
        self.submit()
        self.rejected_number("bare-prefix-rejected")
        self.keys("soft_right")
        self.number("+", "prefix-retained-after-error")
        self.keys("soft_right")
        self.number("", "empty-number-draft")
        self.submit()
        self.rejected_number("empty-number-rejected")
        self.keys("soft_right")
        self.number("", "empty-retained-after-error")
        self.keys("red")
        self.chooser("empty-number-form-cancelled")
        self.keys("soft_left")
        self.number("+", "fresh-number-after-cancel")
        self.keys("1", "2")
        self.number("+12", "local-number-draft")
        self.submit()
        self.recipients("+12", 0, "local-recipient-added-without-send")
        self.keys("soft_right", "soft_left", "1", "3")
        self.number("+13", "second-number-visible-cancel-draft")
        self.keys("red")
        self.chooser("second-number-cancelled")
        self.keys("soft_right")
        self.recipients("+12", 0, "only-original-recipient-survives-cancel")
        self.keys("down")
        self.recipients("+12", 1, "remove-recipient-focus")
        self.keys("soft_right")
        self.recipients(None, 0, "local-recipient-removed")
        self.keys("red")
        self.options(0, "send-to-cancelled-back-to-options", numeric=True)
        self.keys("soft_right")
        self.editor("adg", "complete-text-survives-recipient-cancel")
        self.keys("soft_right")
        self.editor("ad", "clear-deletes-one-character-count-998")
        self.discard("discard-visible-ad", numeric=True)
        self.reopen_messages()
        self.keys("down", "down")
        self.menu(MESSAGES, 2, "drafts-selected-after-explicit-exit")
        self.empty_mailbox(2, "Drafts")
        self.keys("up", "up")
        self.menu(MESSAGES, 0, "create-selected-after-empty-drafts-readback")
        self.keys("soft_left")
        self.editor("", "discarded-text-not-reopened")
        self.discard("discard-empty-editor")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555MessagesEditorE2ETests(MessagesEditorChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575MessagesEditorE2ETests(MessagesEditorChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")
