"""Saved handset shortcuts reach an externally populated, read-only SIM book.

Only the original Call/SMS/Copy choices are displayed. No action initiates a
call/message, programs the card, authenticates a subscriber or establishes RF.
"""

from hashlib import sha256
import os
import unittest

from factory_handset import HOME_CAPTIONS
from iridium.assets import BC5Assets
from test_factory_convenience_e2e import SIM_CANCEL_DRAFT, SIM_PHONEBOOK
from test_factory_customization_e2e import (
    CONVENIENCE_DEFAULT, KEY_SETUP_CONVENIENCE, KEY_SETUP_RIGHT,
    PHONEBOOK_CAPTIONS,
)
from test_factory_sim_phonebook_e2e import SIMPhonebookChecks as _SIM
from test_factory_messages_local_e2e import ALERTS, CAPACITY, SCAN_READY


class SIMShortcutChecks:
    # Alias observations/fixtures without rediscovering another module's tests.
    start = _SIM.start
    finish = _SIM.finish
    read = _SIM.read
    press = _SIM.press
    submit = _SIM.submit
    original_card_consumed = _SIM.original_card_consumed
    text = _SIM.text
    title = _SIM.title
    blank = staticmethod(_SIM.blank)
    record = _SIM.record
    expect = _SIM.expect
    verify_card_unchanged = _SIM.verify_card_unchanged

    def setUp(self):
        self.start(populated=True)
        assets = BC5Assets(self.handset.session.firmware["bc5"].data,
                           self.handset.session.firmware["bc5"].profile)
        radio_id = 7 if self.model == "9575" else 5
        self.assertEqual(sha256(assets.file_bytes(radio_id)).hexdigest(),
                         "7b0ee05692b8f09f5909302a7f6f051dc662b5422dd03dbd49c271ed63ec4e99")
        self.radio = tuple(assets.bitmap(radio_id, frame).pixels for frame in range(2))

    def keys(self, *keys):
        for key in keys:
            self.press(key)

    def original_home(self):
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        seen = set()
        for _ in range(125):
            state = self.handset.state()
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, seen, "Repeated original startup modal")
                seen.add(body)
                self.record("startup-" + ALERTS[body])
                self.press("soft_right")
            elif self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.record("original-home-before-natural-scan")
                return
            else:
                self.handset.step(1000000)
                self.peer.check()
        self.record("startup-timeout")
        self.fail("Original startup did not reach Home")

    def wait_original_scan(self):
        # Setup uses the original retry interval productively. The SIM book is
        # not activated until the original scan itself has completed.
        while self.read("bc5", SCAN_READY[self.model]) != [1]:
            state = self.handset.assert_healthy()
            self.peer.check()
            self.assertLess(next(cpu["steps"] for cpu in state["processors"]
                                 if cpu["image"] == "trx"), 240000000,
                            "Original initial SIM scan did not complete")
            self.assertEqual(self.handset.screen_hash(113, 128, state), PHONEBOOK_CAPTIONS)
            self.handset.step(2000000)
        self.assertEqual(self.read("bc5", CAPACITY[self.model]), [2])
        self.assertEqual(self.read("trx", 0x400AA2D6), [2])
        self.assertEqual(self.read("trx", 0x400AA2D3), [3])
        self.assertEqual(self.read("trx", 0x400AA30C, 4), [0, 0, 0, 1])
        self.original_card_consumed(populated=True)

    def body(self, expected, label):
        return self.expect(label, lambda s: self.handset.screen_hash(16, 113, s) == expected,
                           {"rows": [16, 113], "known_native_sha256": expected})

    def home(self, *, sim_assigned):
        self.press("red")
        footer = PHONEBOOK_CAPTIONS if sim_assigned else HOME_CAPTIONS
        return self.expect("home-with-" + ("sim-shortcut" if sim_assigned else "restored-help"),
                           lambda s: (self.handset.screen_hash(113, 128, s) == footer and
                                      s["keys"] == []),
                           {"footer": ["Menu", "Phonebook" if sim_assigned else "Help"],
                            "all_keys_released": True})

    def open_key_setup(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (7 if self.model == "9575" else 6)), "soft_left")
        self.body(KEY_SETUP_CONVENIENCE, "key-setup-convenience-focused")

    def right_assignment(self, focused, stored, label):
        labels = ("Show Help", "SIM Phonebook", "My Phonebook")

        def matches(state):
            pixels = state["lcd"]["pixels"]
            return (self.title(state, "Right Key Action") and
                    all(self.text(state, item, 16 + row * 17, 13, 107,
                                  selected=row == focused)
                        for row, item in enumerate(labels)) and
                    all(bytes(pixels[(19 + row * 17 + y) * 128 + 2 + x]
                              for y in range(9) for x in range(9)) == self.radio[row == stored]
                        for row in range(3)) and self.blank(state, 67, 111) and
                    self.text(state, "Select", 112, 2, 36) and
                    self.text(state, "Back", 112, 99, 28))

        return self.expect(label, matches, {"title": "Right Key Action", "labels": labels,
                           "focused_index": focused, "stored_index": stored,
                           "independent_original_radio_asset": True})

    def populated_destination(self, label):
        self.expect(label + "-adg-list", lambda s: (
            self.title(s, "Phonebook") and self.text(s, "Adg", 16, width=117, selected=True) and
            self.blank(s, 34, 111) and self.text(s, "Options", 112, 2, 45) and
            self.text(s, "Back", 112, 99, 28)),
            {"title": "Phonebook", "complete_selected_name": "Adg", "text_width": 117,
             "unused_rows_start": 34, "options_and_back_visible": True})
        self.submit()
        labels = ("Call", "SMS", "Copy")
        self.expect(label + "-readonly-actions", lambda s: (
            self.title(s, "Adg") and
            all(self.text(s, item, 16 + 17 * row, selected=row == 0)
                for row, item in enumerate(labels)) and self.blank(s, 67, 111) and
            self.text(s, "Select", 112, 2, 36) and self.text(s, "Back", 112, 99, 28)),
            {"title": "Adg", "complete_ordered_actions": labels, "focused_index": 0,
             "new_edit_delete_absent": True, "actions_not_activated": True})
        self.press("soft_right")
        self.expect(label + "-back-to-same-adg", lambda s: (
            self.title(s, "Phonebook") and self.text(s, "Adg", 16, width=117, selected=True) and
            self.blank(s, 34, 111)),
            {"title": "Phonebook", "selected_name": "Adg", "unused_rows_start": 34})
        self.home(sim_assigned=True)

    def test_saved_sim_shortcuts_cancel_changed_assignments_open_populated_actions_and_restore_defaults(self):
        self.original_home()
        self.open_key_setup()
        self.press("soft_left")
        self.body(CONVENIENCE_DEFAULT[self.model], "convenience-original-default")
        self.keys(*(["up"] * 4 if self.model == "9575" else ["down"] * 4))
        self.submit()
        self.body(KEY_SETUP_CONVENIENCE, "convenience-saved-parent")
        self.press("soft_left")
        self.body(SIM_PHONEBOOK, "convenience-sim-saved-readback")
        self.press("up")
        self.body(SIM_CANCEL_DRAFT, "convenience-visible-redial-draft-with-sim-saved")
        self.keys("soft_right", "soft_left")
        self.body(SIM_PHONEBOOK, "convenience-cancel-preserved-sim")
        self.keys("soft_right", "down", "soft_left")
        self.right_assignment(0, 0, "right-original-help")
        self.press("down")
        self.submit()
        self.body(KEY_SETUP_RIGHT, "right-saved-parent")
        self.press("soft_left")
        self.right_assignment(1, 1, "right-sim-saved-readback")
        self.press("up")
        self.right_assignment(0, 1, "right-visible-help-draft-still-saved-sim")
        self.keys("soft_right", "soft_left")
        self.right_assignment(1, 1, "right-cancel-preserved-sim")
        self.home(sim_assigned=True)
        self.wait_original_scan()

        self.press("soft_right")
        self.populated_destination("saved-right-soft-key")
        self.press("convenience")
        self.populated_destination("saved-convenience-key")

        self.open_key_setup()
        self.press("soft_left")
        self.body(SIM_PHONEBOOK, "convenience-still-sim-after-real-activation")
        self.keys(*(["down"] * 4 if self.model == "9575" else ["up"] * 4))
        self.submit()
        self.body(KEY_SETUP_CONVENIENCE, "convenience-default-restored-parent")
        self.press("soft_left")
        self.body(CONVENIENCE_DEFAULT[self.model], "convenience-default-restored-readback")
        self.keys("soft_right", "down", "soft_left")
        self.right_assignment(1, 1, "right-still-sim-after-real-activation")
        self.press("up")
        self.submit()
        self.body(KEY_SETUP_RIGHT, "right-help-restored-parent")
        self.press("soft_left")
        self.right_assignment(0, 0, "right-help-restored-readback")
        self.home(sim_assigned=False)
        self.verify_card_unchanged()
        self.record("both-shortcuts-complete-card-unchanged")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555SIMShortcutsE2ETests(SIMShortcutChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575SIMShortcutsE2ETests(SIMShortcutChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
