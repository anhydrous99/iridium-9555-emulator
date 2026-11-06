"""Factory settings/contact retention through shutdown and Reset to Defaults."""

from hashlib import sha256
import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED
from test_factory_phonebook_details_e2e import EMPTY_NOTE, NOTE_ADG, NOTE_OPTIONS, NOTE_SIXTY_ONE_REMAINING
from test_factory_reset_e2e import RESET_CONFIRMATION, SETTINGS_RESET
from test_factory_security_e2e import (
    FIRMWARE_IDENTITY_WARNING, IERCC_DISABLED, IERCC_NOT_CONFIGURED,
    SOS_MESSAGE_RECIPIENT_WARNING, STARTUP_SIM_ERROR,
)
from test_factory_settings_e2e import RINGER_DEFAULT, RINGER_LOUDER, VOLUME_MENU


class SharedPersistenceChecks:
    def setUp(self):
        # Original modem startup initializes the phonebook's saved-record index.
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.boot_with_modem_alerts()

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def boot_with_modem_alerts(self):
        handset = self.handset
        handset.control("initialize_ui")
        handset.control("pause")
        alerts = {STARTUP_SIM_ERROR: "absent-sim"}
        required = {"absent-sim"}
        if self.model == "9575":
            alerts.update({IERCC_NOT_CONFIGURED: "iercc-not-configured",
                           IERCC_DISABLED: "iercc-disabled",
                           SOS_MESSAGE_RECIPIENT_WARNING: "sos-message-recipient"})
            required = {"iercc-not-configured", "iercc-disabled", "sos-message-recipient"}
        seen = set()
        elapsed = 0
        while elapsed <= 200000000:
            state = handset.assert_healthy(require_lcd=False)
            body = handset.screen_hash(state=state)
            self.assertNotEqual(body, FIRMWARE_IDENTITY_WARNING, "Factory release metadata was rejected")
            if body in alerts:
                label = alerts[body]
                self.assertNotIn(label, seen, "Modem startup repeated a recognized alert")
                seen.add(label)
                handset.save_artifacts(f"startup-{label}", state)
                handset.press("soft_right", hold_steps=1000000, settle_steps=10000000)
                elapsed += 11300000
            elif required <= seen and handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr", "trx"})
                self.assertTrue(state["processor_link"]["connected"])
                self.assertEqual(state["keys"], [])
                return
            else:
                handset.step(1000000)
                elapsed += 1000000
        handset.save_artifacts("unknown-startup-screen")
        self.fail("Original modem startup did not reach home after its recognized alerts")

    def expect(self, screen, first=16, last=113):
        return self.handset.wait_screen(screen, first=first, last=last, max_steps=20000000)

    def home(self):
        for _ in range(3):
            self.keys("red")
            state = self.handset.assert_healthy()
            if self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                break
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])

    def open_setup(self, item):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (item + (self.model == "9575"))), "soft_left")

    def open_ringer(self):
        self.open_setup(1)
        self.expect(VOLUME_MENU)
        self.keys("soft_left")

    def change_ringer(self):
        self.open_ringer()
        self.expect(RINGER_DEFAULT)
        self.keys("up", "soft_left")
        self.expect(VOLUME_MENU)
        self.keys("soft_left")
        self.expect(RINGER_LOUDER)
        self.home()

    def create_contact(self, note=False):
        self.keys("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.keys("soft_left", "soft_left", "2", "3", "4", "down", "1", "2", "3", "soft_left")
        self.expect(ENTRY_ADDED)
        self.keys("soft_right")
        self.expect(ADG_SELECTED)
        if note:
            self.keys("soft_left", *(["down"] * 6), "soft_left")
            self.expect(EMPTY_NOTE)
            self.keys("2", "3", "4")
            self.assert_note()
            self.keys("soft_left")
            self.expect(NOTE_OPTIONS)
            self.keys("soft_left")
            self.expect(ADG_SELECTED)
        self.home()

    def assert_contact(self, note=False):
        self.keys("soft_left", "soft_left")
        self.expect(ADG_SELECTED)
        self.keys("soft_left", "down", "down", "soft_left")
        # Original saved-content crops, independent of the blinking editor caret.
        self.expect("43c71edf6ac92194c1abec64dc583fd5baab48ab44d7286c4d8f335b18fed362", 16, 27)
        self.expect("4de915bd746339b62d06fa4d2421c33fdf8efb3e228659e016f08bf000f2f76c", 32, 43)
        self.home()
        if note:
            self.keys("soft_left", "soft_left", "soft_left", *(["down"] * 6), "soft_left")
            self.assert_note()
            self.home()

    def assert_note(self):
        state = self.expect(NOTE_SIXTY_ONE_REMAINING, 0, 14)
        glyphs = bytes(state["lcd"]["pixels"][y * 128 + x]
                       for y in range(19, 30) for x in range(4, 26))
        self.assertEqual(sha256(glyphs).hexdigest(), NOTE_ADG)

    def shutdown_and_restart(self):
        handset = self.handset
        state = handset.press("power", settle_steps=0)
        self.assertFalse(state["ui_initialized"])
        for _ in range(50):
            primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
            if primary["power_state"] == 8:
                break
            state = handset.step(200000)
        primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
        self.assertEqual(primary["power_state"], 8,
                         "Original firmware did not complete shutdown within 10 million instructions")
        self.assertEqual(state["keys"], [])
        # The existing handset startup invokes original setup and retains guest
        # flash through a warm reset; it does not reload the source image.
        self.boot_with_modem_alerts()

    def test_saved_setting_contact_and_note_survive_completed_shutdown_and_warm_startup(self):
        self.change_ringer()
        self.create_contact(note=True)
        self.shutdown_and_restart()
        self.open_ringer()
        self.expect(RINGER_LOUDER)
        self.home()
        self.assert_contact(note=True)
        self.handset.save_artifacts("retained-after-restart")

    def test_reset_defaults_preserves_saved_contact_and_note(self):
        self.create_contact(note=True)
        self.open_setup(9)
        self.expect(RESET_CONFIRMATION)
        self.keys("soft_left")
        self.expect(SETTINGS_RESET)
        self.keys("soft_right")
        self.home()
        self.assert_contact(note=True)
        self.handset.save_artifacts("reset-retained-contact-and-note")

    def test_reset_default_setting_survives_completed_shutdown_and_warm_startup(self):
        self.change_ringer()
        self.open_setup(9)
        self.expect(RESET_CONFIRMATION)
        self.keys("soft_left")
        self.expect(SETTINGS_RESET)
        self.keys("soft_right")
        self.home()
        self.shutdown_and_restart()
        self.open_ringer()
        self.expect(RINGER_DEFAULT)
        self.home()
        self.handset.save_artifacts("reset-default-setting-after-restart")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 persistence E2E")
class Factory9555PersistenceE2ETests(SharedPersistenceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 persistence E2E")
class Factory9575PersistenceE2ETests(SharedPersistenceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
