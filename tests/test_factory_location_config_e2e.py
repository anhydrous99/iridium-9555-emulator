"""Local Extreme location configuration through original firmware and HTTP keys."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_extreme_settings_e2e import (
    DISABLED, ENABLED, GPS_LOCKED, GPS_LOCK_MENU, GPS_PIN,
    GPS_PIN_FOUR_MASKS, INCORRECT_PIN, LOCATION_OPTIONS, SETUP,
    DELETE_RECIPIENT, INVALID_NUMBER, NUMBER_EMPTY, NUMBER_12345,
    RECIPIENT_OPTIONS, SELECT_RECIPIENT,
)
from test_factory_security_e2e import (
    CHANGE_PIN_FORM, MASKED_CHANGE_PIN_FIELDS, NEW_PINS_DO_NOT_MATCH,
)
from test_factory_phonebook_e2e import ADG_SELECTED, EMPTY_PHONEBOOK, ENTRY_ADDED
from test_factory_phonebook_details_e2e import DELETE_ADG


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
SECURITY = "aff33e5301f81c65719736fff7d485cb6c9b023e3af3dcdd76ac0a042ebe4038"
CHANGE_PINS = "075b0ccb40d7fee89d249fb9114be37ed20e9d5ed79403f8e8f4db56718ab05a"
CHANGE_GPS_PIN = "aef6d3091579a2bfe0ae12a71d4c4c8d84d13533d874176854d2d4b05bc97122"
PIN_CHANGED = "9085c2df3c47422e470d8db80de975e657512daae8eaaa82ae06b9b7e0c91248"
MESSAGE_OPTIONS = "6000ac85fe54cd577403f68b29321c0def22b9c0a1b1135e2e47442d754673ff"
UPDATE_FREQUENCY = "d684ecacc7ec98937f90120e07002958497ca92eb2e6d24fa289121bd04fdb94"
UPDATE_RECIPIENT = "dbe2fee3b637465fd0d6b702c76ffe5464935f1090643d30ed054c70e1befa86"
NO_UPDATE = "e39abf66c0f62f2745ccbcddb876082639e09fa1cb532dfe553a71aca58a2ecf"
STARTUP_ONLY = "b03e1d9eab15ab46c4dd088b897cd1bf2061e396db20b852674cf6e2a8612339"
FIVE_MINUTES = "c0f503942202e6910a39ce782e0e7f15a10e3e8a69486f56b96b2e9005d54627"
EMPTY_UPDATE_RECIPIENT = "f0bb99c0d9ad6dab20383db2bf2d3e16567b3812cb41b235ff8829e742c391cc"
UPDATE_RECIPIENT_12345 = "360b95ef814edb602d21ae594c3575e89638d59986667558c0544fabae0fa6ab"
PORTAL_REGISTER_MENU = "124e217d163f9a9ad2b2071e5442f5bab0fb8f5d12b6f128afa1b71183511f88"
PORTAL_STATUS_MENU = "274fc285786d998e6c44617d35ceb6b8ed14888c3429226ac01fbb45246abed5"
PORTAL_NOT_REGISTERED = "f500f6ed9eb0a9132c93f72fb4626908bdddccfb6a6d9daed41aa1cb2e3f8b5b"
PORTAL_REGISTRATION_FORM = "3d78a074ea2538b0c88b9bd86b3c57d7595f2aad8673f01a0bae0ae033631091"
QUICK_GPS_MENU = "7efba3292d37f250cf52ee9e785579b1d3b915d2f5ee8ec9a3be2e00bab22f79"
EMPTY_QUICK_GPS_RECIPIENTS = "e6933a0b81588dccc278fcce841f6efa40ded05b7de9d677788e94040a9a8759"
QUICK_GPS_FIRST_RECIPIENT = "e4957cd8020933d9900447867fc27c719b5fee268289ca71c3da3a1568fbce0f"
QUICK_GPS_FIFTH_SELECTED = "5cf3762c950ee6563e6150eb73db2675a3799a96f18d78bf9af5660fb9086c6b"
QUICK_GPS_TWO_RECIPIENTS_LAST_ROW_SELECTED = "426dd5fc7d048f41378dc2f5cb1c06549514955ece9f8f5d6a3b950b5dc39c8a"
QUICK_GPS_RECIPIENTS_REOPENED = "cbdeeb394b8e472ae3d2e3ea4b66821f8afdc158bad90ab81fdda237029b48d0"
DELETE_ALL_RECIPIENTS = "6a175314fe8ed0f932eaf4271e331ad433d1da241cdf1f66f8d36ad11cdd7ec8"
SELECT_RECIPIENT_WITH_ADG = "faecbc95024ac096b8c73521de34a907cdc4aebe010f7c8bb143c20d7505433d"
UPDATE_RECIPIENT_123 = "fface1cc76ce6fd63c42fcbd389617563b3b037d74f83475067a2d259324dbb9"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory location configuration E2E")
class Factory9575LocationConfigurationE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def expect(self, screen):
        return self.handset.wait_screen(screen, max_steps=30000000)

    def press(self, *keys):
        for key in keys:
            self.handset.press(key)

    def open_location(self):
        self.press("soft_left", *(["down"] * 6), "soft_left")
        self.expect(SETUP)
        self.press("soft_left")
        self.expect(LOCATION_OPTIONS)

    def open_change_gps_pin(self):
        self.press("soft_left", *(["down"] * 7), "soft_left")
        self.expect(SECURITY)
        self.press("down", "down", "soft_left")
        self.expect(CHANGE_PINS)
        self.press(*(["down"] * 4))
        self.expect(CHANGE_GPS_PIN)
        self.press("soft_left")
        self.expect(CHANGE_PIN_FORM)

    def open_messages(self):
        self.open_location()
        self.press("down", "down", "down", "soft_left")
        self.expect(MESSAGE_OPTIONS)

    def open_portal(self):
        self.open_location()
        self.press("down", "soft_left")
        self.expect(PORTAL_REGISTER_MENU)

    def fill_change_pin(self, old, new, verify):
        self.press(*old, "down", *new, "down", *verify)
        self.expect(MASKED_CHANGE_PIN_FIELDS)

    def enter_gps_pin(self, pin):
        self.expect(GPS_PIN)
        self.press(*pin)
        self.expect(GPS_PIN_FOUR_MASKS)
        self.press("soft_left")

    def finish_home(self):
        self.press("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128,
                                         max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def test_gps_pin_change_rejects_mismatch_and_old_pin_accepts_new_and_restores_default(self):
        # The supplied Extreme manual specifies GPS PIN 3333 and this change path.
        self.open_change_gps_pin()
        self.fill_change_pin("3333", "2468", "2469")
        self.press("soft_left")
        self.expect(NEW_PINS_DO_NOT_MATCH)
        self.handset.save_artifacts("gps-pin-confirmation-mismatch")
        self.press("soft_right")
        self.expect(MASKED_CHANGE_PIN_FIELDS)
        self.press("red")
        self.expect(CHANGE_GPS_PIN)
        self.press("soft_left")
        self.expect(CHANGE_PIN_FORM)

        self.fill_change_pin("3333", "2468", "2468")
        self.press("soft_left")
        self.expect(PIN_CHANGED)
        self.handset.save_artifacts("gps-pin-changed")
        self.expect(CHANGE_GPS_PIN)
        self.finish_home()

        self.open_location()
        self.press("soft_left")
        self.expect(GPS_LOCK_MENU)
        self.press("soft_left")
        self.expect(DISABLED)
        self.press("up", "soft_left")
        self.enter_gps_pin("3333")
        self.expect(INCORRECT_PIN)
        self.handset.save_artifacts("gps-old-pin-rejected")
        self.expect(GPS_PIN_FOUR_MASKS)
        self.press(*(["soft_right"] * 4))
        self.enter_gps_pin("2468")
        self.expect(GPS_LOCKED)
        self.expect(GPS_LOCK_MENU)
        self.press("soft_left")
        self.expect(ENABLED)
        self.handset.save_artifacts("gps-new-pin-enabled-lock")
        self.press("down", "soft_left")
        self.enter_gps_pin("2468")
        self.expect(GPS_LOCK_MENU)
        self.press("soft_left")
        self.expect(DISABLED)
        self.finish_home()

        self.open_change_gps_pin()
        self.fill_change_pin("2468", "3333", "3333")
        self.press("soft_left")
        self.expect(PIN_CHANGED)
        self.expect(CHANGE_GPS_PIN)
        self.finish_home()

        self.open_location()
        self.press("soft_left", "soft_left")
        self.expect(DISABLED)
        self.press("up", "soft_left")
        self.enter_gps_pin("3333")
        self.expect(GPS_LOCKED)
        self.expect(GPS_LOCK_MENU)
        self.press("soft_left")
        self.expect(ENABLED)
        self.press("down", "soft_left")
        self.enter_gps_pin("3333")
        self.expect(GPS_LOCK_MENU)
        self.press("soft_left")
        self.expect(DISABLED)
        self.handset.save_artifacts("gps-default-pin-restored-and-lock-disabled")
        self.finish_home()

    def test_regular_update_frequency_save_reopen_cancel_and_restore_no_update(self):
        self.open_messages()
        self.press("soft_left")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(NO_UPDATE)
        self.press("down", "soft_left")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(STARTUP_ONLY)
        self.handset.save_artifacts("regular-update-startup-only-saved")
        self.press("up", "soft_right")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(STARTUP_ONLY)

        self.press("down", "down", "soft_left")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(FIVE_MINUTES)
        self.handset.save_artifacts("regular-update-five-minutes-saved")
        self.press("up", "soft_right")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(FIVE_MINUTES)
        self.press("up", "up", "up", "soft_left")
        self.expect(UPDATE_FREQUENCY)
        self.press("soft_left")
        self.expect(NO_UPDATE)
        self.handset.save_artifacts("regular-update-no-update-restored")
        self.press("soft_right", "down", "soft_left")
        self.expect(EMPTY_UPDATE_RECIPIENT)
        self.finish_home()

    def test_regular_update_recipient_validation_save_delete_cancel_and_restore(self):
        self.open_messages()
        self.press("soft_left", "down")
        self.expect(UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(EMPTY_UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        self.press("soft_left")
        self.expect(NUMBER_EMPTY)
        self.press("soft_left")
        self.expect(INVALID_NUMBER)
        self.expect(NUMBER_EMPTY)
        self.press(*"12345")
        self.expect(NUMBER_12345)
        self.press("soft_left")
        self.expect(UPDATE_RECIPIENT_12345)
        self.handset.save_artifacts("regular-update-recipient-saved")
        self.press("soft_right")
        self.expect(UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(UPDATE_RECIPIENT_12345)
        for confirm in ("soft_right", "soft_left"):
            with self.subTest(confirm=confirm):
                self.press("soft_left", "down", "soft_left")
                self.expect(DELETE_RECIPIENT)
                self.press(confirm)
                self.expect(UPDATE_RECIPIENT_12345 if confirm == "soft_right"
                            else EMPTY_UPDATE_RECIPIENT)
        self.handset.save_artifacts("regular-update-recipient-empty-restored")
        self.press("soft_right", "up", "soft_left")
        self.expect(NO_UPDATE)
        self.finish_home()

    def test_portal_registration_cancel_preserves_unregistered_status(self):
        self.open_portal()
        self.press("down", "soft_left")
        self.expect(PORTAL_NOT_REGISTERED)
        self.press("soft_right")
        self.expect(PORTAL_STATUS_MENU)
        self.press("up", "soft_left")
        # No modem identity or portal service is supplied to this local fixture.
        self.expect(PORTAL_REGISTRATION_FORM)
        self.handset.save_artifacts("portal-registration-form-before-cancel")
        self.finish_home()
        self.open_portal()
        self.press("down", "soft_left")
        self.expect(PORTAL_NOT_REGISTERED)
        self.handset.save_artifacts("portal-not-registered-after-cancel")
        self.finish_home()

    def test_quick_gps_add_from_last_empty_row_compacts_recipients_and_delete_all_cancel_restore(self):
        self.open_messages()
        self.press("down")
        self.expect(QUICK_GPS_MENU)
        self.press("soft_left")
        self.expect(EMPTY_QUICK_GPS_RECIPIENTS)
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        self.press("soft_left")
        self.expect(NUMBER_EMPTY)
        self.press(*"12345", "soft_left")
        self.expect(QUICK_GPS_FIRST_RECIPIENT)
        self.press(*(["down"] * 4))
        self.expect(QUICK_GPS_FIFTH_SELECTED)
        self.press("soft_left", "soft_left", "soft_left")
        self.expect(NUMBER_EMPTY)
        self.press(*"67890", "soft_left")
        self.expect(QUICK_GPS_TWO_RECIPIENTS_LAST_ROW_SELECTED)
        self.handset.save_artifacts("quick-gps-two-recipients-saved-from-last-row")
        self.press("soft_right")
        self.expect(QUICK_GPS_MENU)
        self.press("soft_left")
        # Both addresses already occupy the first two rows after saving.
        self.expect(QUICK_GPS_RECIPIENTS_REOPENED)
        for confirm in ("soft_right", "soft_left"):
            with self.subTest(confirm=confirm):
                self.press("soft_left", "down", "down", "soft_left")
                self.expect(DELETE_ALL_RECIPIENTS)
                self.press(confirm)
                self.expect(QUICK_GPS_RECIPIENTS_REOPENED if confirm == "soft_right"
                            else EMPTY_QUICK_GPS_RECIPIENTS)
        self.handset.save_artifacts("quick-gps-five-empty-recipients-restored")
        self.finish_home()

    def test_regular_update_recipient_copies_saved_phonebook_number_and_retains_it_after_contact_deletion(self):
        self.press("soft_left", "soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.press("soft_left", "soft_left", "2", "3", "4", "down",
                   "1", "2", "3", "soft_left")
        self.expect(ENTRY_ADDED)
        self.press("soft_right")
        self.expect(ADG_SELECTED)
        self.handset.save_artifacts("phonebook-contact-for-location-recipient")
        self.finish_home()

        self.open_messages()
        self.press("soft_left", "down", "soft_left")
        self.expect(EMPTY_UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        self.press("soft_left")
        # Original HL lists the saved Adg contact after Enter Number/Enter Email.
        self.expect(SELECT_RECIPIENT_WITH_ADG)
        self.press("down", "down", "soft_left")
        self.expect(UPDATE_RECIPIENT_123)
        self.handset.save_artifacts("regular-update-number-copied-from-phonebook")
        self.press("soft_right")
        self.expect(UPDATE_RECIPIENT)
        self.press("soft_left")
        self.expect(UPDATE_RECIPIENT_123)
        self.finish_home()

        self.press("soft_left", "soft_left")
        self.expect(ADG_SELECTED)
        self.press("soft_left", "down", "down", "down", "soft_left")
        self.expect(DELETE_ADG)
        self.press("soft_left")
        self.expect(EMPTY_PHONEBOOK)
        self.handset.save_artifacts("source-contact-deleted")
        self.finish_home()

        self.open_messages()
        self.press("soft_left", "down", "soft_left")
        self.expect(UPDATE_RECIPIENT_123)
        self.handset.save_artifacts("copied-recipient-retained-after-source-contact-deletion")
        self.press("soft_left", "down", "soft_left")
        self.expect(DELETE_RECIPIENT)
        self.press("soft_left")
        self.expect(EMPTY_UPDATE_RECIPIENT)
        self.press("soft_right", "up", "soft_left")
        self.expect(NO_UPDATE)
        self.finish_home()


if __name__ == "__main__":
    unittest.main()
