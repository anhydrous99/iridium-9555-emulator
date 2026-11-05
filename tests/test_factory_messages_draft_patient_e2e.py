"""Patient local SMS draft journeys alongside the unchanged rapid-input cases.

Every accepted electrical key gets an additional2M original CPU instructions
released. The source-backed outgoing command queue can drain naturally; all
original 201/1000-character, overflow and complete saved-text checks remain.
"""

import os
import unittest

from test_factory_messages_draft_limits_e2e import MessagesDraftLimitChecks as _Limits


class PatientMessagesDraftChecks:
    # Explicit aliases avoid inheriting the previously published test methods.
    setUp = _Limits.setUp
    finish = _Limits.finish
    capture_heap = _Limits.capture_heap
    read = _Limits.read
    press = _Limits.press
    original_home_and_scan = _Limits.original_home_and_scan
    text = _Limits.text
    title = _Limits.title
    menu = _Limits.menu
    open_messages = _Limits.open_messages
    keys = _Limits.keys
    blank = staticmethod(_Limits.blank)
    field = _Limits.field
    options = _Limits.options
    reopen_messages = _Limits.reopen_messages
    numeric_mode = _Limits.numeric_mode
    save = _Limits.save
    drafts = _Limits.drafts
    reopen_draft = _Limits.reopen_draft
    actions = _Limits.actions
    edit = _Limits.edit
    record = _Limits.record
    healthy = _Limits.healthy
    expect = _Limits.expect
    counter_pixels = _Limits.counter_pixels
    count_matches = _Limits.count_matches
    counter = _Limits.counter
    type_value = _Limits.type_value
    view = _Limits.view
    body_with_original_caret = staticmethod(_Limits.body_with_original_caret)
    matched_view = _Limits.matched_view
    editor = _Limits.editor
    complete_readback = _Limits.complete_readback
    new_numeric = _Limits.new_numeric
    save_and_read_every_character = _Limits.save_and_read_every_character

    def enter_one(self, key, remaining):
        _Limits.enter_one(self, key, remaining)
        # All processors advance normally with the real contact released.
        # No callback, queue consumer, internal ready flag or modem is changed.
        self.handset.step(2000000)
        self.healthy()
        self.input_holds[-1]["additional_patient_released_steps"] = 2000000

    def test_patient_201_character_local_draft_crosses_chunk_and_reopens_every_glyph(self):
        _Limits.test_201_character_local_draft_crosses_flash_chunk_and_reopens_every_glyph(self)

    def test_patient_1000_character_limit_rejects_extra_and_reopens_every_glyph(self):
        _Limits.test_1000_character_local_draft_limit_rejects_extra_and_reopens_every_glyph(self)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555PatientMessagesDraftE2ETests(PatientMessagesDraftChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575PatientMessagesDraftE2ETests(PatientMessagesDraftChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
