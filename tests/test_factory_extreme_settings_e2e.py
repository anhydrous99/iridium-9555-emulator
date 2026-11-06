"""Saved local 9575 Location/Emergency options through original HTTP widgets."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from gps_receiver_frames import GPSReceiverFixture


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
SETUP = "890e354045721f1f847576665d56bcf9290fbb524519885da4c18680a8023055"
LOCATION_OPTIONS = "f334446c9f1779679334002e8f0dd7d63f345fa6ec7269d0a1ea52559bee653e"
GPS_LOCK_MENU = "3bfcf1766bcf93b8ca39470e3a7faee540ffae7d4f99f7a7fee38e8c7ee44775"
GPS_UPDATE_MENU = "1d933f9048d8c450268f74bb4d83ae6b36a74aecb0b036dffad41b1a6e7ead52"
GPS_POWER_MENU = "1cfe36c23ce7003322ba1b2cc56e0f370a6802bb1355be60bf59558ac9377637"
ONE_TIME = "2940ed0c851b2d5a16be3e0e371399234d8591dc7e0f17f272b5ec5a92ecb720"
REAL_TIME = "42d71ea0dd8578a21301dc585c31d9c20f154c624f18d5a28786398411823edf"
DISABLED = "5929111ee90ab80c3d37e0f7e5acfec0495ed50fe0ee3e5320129668a5e469d2"
ENABLED = "2477d86a84857f6906f9a4c8c463d2e4c6ac58852a3f82fd146509d44e0994be"
POSITION_MENU = "0e764ad4cc7266325a21fc5b2495685030e34c2dc3cc1082d7c7613cbdb4dbef"
ALTITUDE_MENU = "521786d6793d3eccb06b82074c3969d1a860edf2222fe72caefc155970cf3efc"
DEGREES_MINUTES_SECONDS = "35aa5c52e7968959cf560fa2d5648bb7faa4ba06a88d4b0d6be180dc75337c3a"
DECIMAL_DEGREES = "e651d7e5e46d4fd5ed70113201b8eafcb4a87e48a608704d9de3bd915072f71d"
FEET = "bc52540ac5d8d88cc7946fe486da88f7539094beeb44a495492a11c26a56eb9b"
METERS = "fdc8427cdbfc2379f6075b5e5cf6823c7c94f17db3c17544ca144e44cb5e47ca"
GPS_PIN = "6d239a76c62fc19663f8922290c9945dcd724a9354ab6fb4e06e2f67c10f00d5"
GPS_PIN_THREE_MASKS = "eeee7040dbe619934a4df74d569d0a3607087487fbb15f2e614c5670f3c54feb"
GPS_PIN_FOUR_MASKS = "1481581fdb2061779aa7345eb533fa48136aed9f2836f75117bb5a8f8e320d18"
GPS_PIN_LENGTH_ERROR = "87f483ffe00af82f8ef492b9314e077a99c5dbeacc3f0f456ad70f1a7af2ffd5"
INCORRECT_PIN = "ecb08e423ed7f7337615e403fecb66767d1057db0d61b566e8f6fccda4dcb963"
GPS_LOCKED = "47f61c8a53eb3c17ddd35b9500a51b91589bc96f57993ae276106ce8ff6f05e7"
EMERGENCY_MENU = "8d9bc11ad739a5716cc46cffaa078489ce8091119a064d25fe105140a6c84556"
EMERGENCY_ACTION_MENU = "be337d87fa94c79a3737481386fd49199420ca331c135a9eff428983de1315e8"
EMERGENCY_BEEP_MENU = "b7c78854e66a8c3f728d01eaa0ffae45f3df49117f7dc4b33210f8625b4fd595"
MESSAGE_AND_CALL = "2321c6c1abe7ffd411d72df522c9f9b89a1ed25067000ea3108e136d640fb1fb"
MESSAGE_ONLY = "b09c043f670b9e71540c14db2ec5e19977ba65b8a08f5a276e35b459dd38cbd9"
MESSAGE_RECIPIENT_MENU = "6ab078b404358189da1e8eb77ce0b0df9c9c91050996d259650e070bbbe375d3"
EMPTY_RECIPIENTS = "440094b85f09ac530f39a99f8e0e2dde3164af7bb1dbab54ff5eef4aabfb30de"
RECIPIENT_OPTIONS = "f866049289cf2780db5cf275431a1599f65e6804c2b864d8f0899f836cf0e49b"
SELECT_RECIPIENT = "412f2e6b49a0b4cc6c02da3c0eafe505a93c8ad1cd8bf79deb9b2576cbc55a8e"
NUMBER_EMPTY = "b551d20c6f98d8b469c3cfdf8c098fbfa017fddf7ad54934d9da5554ffc957d5"
INVALID_NUMBER = "3a8bee2817324ec8fd6fac54be04dba85be1f8775459ac556359c32f270a7366"
NUMBER_12345 = "46edd99f1a0e30e841d97834c7e394d3c448e27d13f66f522c4bd9ec436b6904"
RECIPIENT_12345 = "a6eaf571d1ec499d10b3e6a5ab2bb33a7bae5aaa614d7b16fffc8eb7548080da"
DELETE_RECIPIENT = "14659f6a0afbb4a4c0e4e3783e6f9b0ee8607da77006f0bdb85668c38880418f"
IERCC_MENU = "4fc4b88a110184815d1eb328816afd50acc6864bb58aef057cf69adcc4404dac"
IERCC_UNCONFIGURED = "81b9018fd6b2183dc3a2bb4820dc1be5b29dd61e64d702d168001c478fbf3106"
IERCC_REGISTRATION_CONFIRMATION = "ca73341e7d4d4972e72112ddf2e72b8423430701e7126642c8c7c801f4105965"
IERCC_PIN = "63186a085a439f0a9e619ce759ffda944f9a70a57f8b44f6805012ccb2e7708d"
IERCC_PIN_ONE_MASK = "b1e61f39ebc50b62716f972ef8dbe133ae9299378ecee77bee9632338e43ed87"
IERCC_PIN_REJECTED = "ba11ee5f438b440cb68a9dcf621e5b27dcd7463d73ab210f724a3f4d6c29f39f"
DECIMAL_METERS_COORDINATES = "4798b7ac5e376193abafdf14faf3b301198422b456d0a606fadf58365b311133"
DMS_FEET_COORDINATES = "d3699df0a4f80f857d2002856f02e34672fbc051d56ba783185ee01bce6edd74"
GPS_ENABLE_PROMPT = "ccab0537fb15d496f17cc97f8104369a8d402327827e54765d9819e856dd1357"
LOCATION_UPDATING = "7f211763990f11dadfc3ec8b186a8f4c2c98308e64877bceb412b2010cf30a7e"


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory Extreme settings E2E")
class Factory9575ExtremeSettingsE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", FIRMWARE_DIRECTORY)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def expect(self, expected):
        return self.handset.wait_screen(expected, max_steps=30000000)

    def open_location(self):
        handset = self.handset
        handset.press("soft_left")
        for _ in range(6):
            handset.press("down")
        handset.press("soft_left")
        self.expect(SETUP)
        handset.press("soft_left")
        self.expect(LOCATION_OPTIONS)

    def open_emergency(self, item):
        self.open_location()
        for _ in range(2):
            self.handset.press("down")
        self.handset.press("soft_left")
        self.expect(EMERGENCY_MENU)
        for _ in range(item):
            self.handset.press("down")

    def round_trip(self, parent, original, changed, change="down", restore="up",
                   changed_check=None, restored_check=None):
        handset = self.handset
        self.expect(parent)
        handset.press("soft_left")
        self.expect(original)
        handset.press(change)
        handset.press("soft_left")
        self.expect(parent)
        handset.press("soft_left")
        self.expect(changed)
        if changed_check:
            changed_check()
        handset.press(restore)
        handset.press("soft_right")
        self.expect(parent)
        handset.press("soft_left")
        self.expect(changed)
        if changed_check:
            changed_check()
        handset.press(restore)
        handset.press("soft_left")
        self.expect(parent)
        handset.press("soft_left")
        self.expect(original)
        if restored_check:
            restored_check()
        handset.press("soft_right")
        self.expect(parent)

    def assert_gps_power(self, enabled):
        pins = self.handset.request("POST", "/api/probe", {"image": "avr", "operation": "pin_state"})
        self.assertEqual(bool(pins["pins"][8] & 0x80), enabled)

    def set_external_gps_gate(self, high):
        handset = self.handset
        pins = handset.request("POST", "/api/probe", {"image": "avr", "operation": "pin_state"})
        value = pins["inputs"][8]
        value = value | 0x20 if high else value & ~0x20
        handset.request("POST", "/api/probe", {
            "image": "avr", "operation": "pins", "port": 8, "value": value,
        })

    def expect_external_gps_gate(self, high):
        # The physical role of PJ5 is unknown. Original 0x6ADFE stores its
        # inverted input in F736; 0xB8618 combines this with the user preference.
        expected = 0 if high else 1
        for _ in range(20):
            if self.read_bc5(0xF736, 1) == [expected]:
                break
            self.handset.step(1000000)
        self.assertEqual(self.read_bc5(0xF736, 1), [expected])

    def read_bc5(self, address, count):
        return self.handset.request("POST", "/api/probe", {
            "image": "bc5", "operation": "read", "address": address, "count": count,
        })["values"]

    def wait_for_receiver_standby(self):
        manager = self.read_bc5(0xF840, 1)[0]
        self.assertNotEqual(manager, 0)
        self.assertEqual(self.read_bc5(manager + 16, 8), [0] * 8)
        # 0xB8B84 schedules standby after 3 seconds when no owner remains.
        for _ in range(30):
            pins = self.handset.request("POST", "/api/probe", {"image": "avr", "operation": "pin_state"})
            if not pins["pins"][8] & 0x80:
                break
            self.handset.step(1000000)
        self.assert_gps_power(False)

    def complete_startup_receiver_acquisition(self):
        handset = self.handset

        # Original 0xB829C starts a 120-second acquisition with callback
        # 0xB8C46. Disabled releases the user preference, not this startup owner.
        manager = self.read_bc5(0xF840, 1)[0]
        self.assertNotEqual(manager, 0)
        owners = self.read_bc5(manager + 16, 8)
        self.assertNotEqual(owners[0], 0)
        self.assertEqual(owners[1:], [0] * 7)
        startup = self.read_bc5(owners[0], 6)
        self.assertEqual(startup[:2], [6, 0x462F])
        self.assertNotEqual(startup[4:6], [0, 0])
        self.assert_gps_power(True)

        GPSReceiverFixture(handset).publish_fix()
        self.wait_for_receiver_standby()
        self.expect(DISABLED)

    def enter_gps_pin(self, pin):
        for key in pin:
            self.handset.press(key)
        self.expect(GPS_PIN_FOUR_MASKS)
        self.handset.press("soft_left")

    def finish_home(self):
        self.handset.press("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def set_decimal_and_metric(self, enabled):
        handset = self.handset
        self.open_location()
        for _ in range(4):
            handset.press("down")
        handset.press("soft_left")
        self.expect(POSITION_MENU)
        handset.press("soft_left")
        self.expect(DEGREES_MINUTES_SECONDS if enabled else DECIMAL_DEGREES)
        handset.press("up" if enabled else "down")
        handset.press("soft_left")
        self.expect(POSITION_MENU)
        handset.press("down")
        handset.press("soft_left")
        self.expect(FEET if enabled else METERS)
        handset.press("down" if enabled else "up")
        handset.press("soft_left")
        self.expect(ALTITUDE_MENU)
        self.finish_home()

    def test_gps_update_and_on_off_preferences_save_cancel_restore_and_gate_prompt(self):
        handset = self.handset
        self.open_location()
        handset.press("soft_left")
        self.expect(GPS_LOCK_MENU)
        handset.press("down")
        self.round_trip(GPS_UPDATE_MENU, ONE_TIME, REAL_TIME)
        handset.press("down")
        self.round_trip(GPS_POWER_MENU, DISABLED, ENABLED, change="up", restore="down")
        handset.press("soft_left")
        self.expect(DISABLED)
        handset.press("up")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        self.finish_home()
        handset.press("convenience")
        self.expect(LOCATION_UPDATING)
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.open_location()
        handset.press("soft_left")
        handset.press("down")
        handset.press("down")
        handset.press("soft_left")
        self.expect(ENABLED)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        self.finish_home()
        handset.press("convenience")
        self.expect(GPS_ENABLE_PROMPT)
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

    def test_external_gpio_gate_and_user_preference_control_receiver_power(self):
        handset = self.handset
        self.open_location()
        handset.press("soft_left")
        handset.press("down")
        self.expect(GPS_UPDATE_MENU)
        handset.press("soft_left")
        self.expect(ONE_TIME)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_UPDATE_MENU)
        handset.press("down")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(DISABLED)
        self.complete_startup_receiver_acquisition()
        pins = handset.request("POST", "/api/probe", {"image": "avr", "operation": "pin_state"})
        self.assertTrue(pins["inputs"][8] & 0x20)
        self.expect_external_gps_gate(True)
        handset.press("up")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(ENABLED)
        self.assert_gps_power(False)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(DISABLED)

        self.addCleanup(self.set_external_gps_gate, True)
        self.set_external_gps_gate(False)
        self.expect_external_gps_gate(False)
        self.assert_gps_power(False)
        handset.press("up")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(ENABLED)
        for _ in range(20):
            pins = handset.request("POST", "/api/probe", {"image": "avr", "operation": "pin_state"})
            if pins["pins"][8] & 0x80:
                break
            handset.step(1000000)
        self.assert_gps_power(True)
        handset.press("down")
        handset.press("soft_right")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(ENABLED)
        self.assert_gps_power(True)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(DISABLED)
        self.wait_for_receiver_standby()
        handset.press("soft_right")
        handset.press("up")
        handset.press("soft_left")
        self.expect(REAL_TIME)
        handset.press("up")
        handset.press("soft_left")
        self.expect(GPS_UPDATE_MENU)
        self.set_external_gps_gate(True)
        self.expect_external_gps_gate(True)
        self.assert_gps_power(False)
        self.finish_home()

    def test_position_and_altitude_formats_save_cancel_and_restore(self):
        handset = self.handset
        self.open_location()
        for _ in range(4):
            handset.press("down")
        handset.press("soft_left")
        self.round_trip(POSITION_MENU, DEGREES_MINUTES_SECONDS, DECIMAL_DEGREES,
                        change="up", restore="down")
        handset.press("down")
        self.round_trip(ALTITUDE_MENU, FEET, METERS)
        self.finish_home()

    def test_position_and_altitude_formats_change_actual_receiver_coordinates(self):
        handset = self.handset
        self.set_decimal_and_metric(True)
        handset.press("convenience")
        self.expect(GPS_ENABLE_PROMPT)
        handset.press("soft_left")
        self.expect(LOCATION_UPDATING)
        GPSReceiverFixture(handset).publish_fix()
        # Inspected receiver result: 37.774900, -122.419400, +30 m.
        state = handset.wait_screen(DECIMAL_METERS_COORDINATES, first=16, last=60,
                                    max_steps=10000000)
        handset.save_artifacts("decimal-meters-receiver-coordinates", state)
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

        self.set_decimal_and_metric(False)
        handset.press("convenience")
        # The same saved fix now renders DMS and +98 ft after restoration.
        state = handset.wait_screen(DMS_FEET_COORDINATES, first=16, last=60,
                                    max_steps=2000000)
        handset.save_artifacts("restored-dms-feet-receiver-coordinates", state)
        handset.press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

        self.open_location()
        handset.press("soft_left")
        handset.press("down")
        handset.press("down")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(ENABLED)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_POWER_MENU)
        handset.press("soft_left")
        self.expect(DISABLED)
        handset.press("soft_right")
        self.finish_home()

    def test_emergency_action_and_beep_save_cancel_and_restore(self):
        handset = self.handset
        self.open_emergency(1)
        self.round_trip(EMERGENCY_ACTION_MENU, MESSAGE_AND_CALL, MESSAGE_ONLY)
        handset.press("down")
        self.round_trip(EMERGENCY_BEEP_MENU, DISABLED, ENABLED, change="up", restore="down")
        self.finish_home()

    def test_emergency_message_recipient_validation_save_cancel_delete_and_restore(self):
        handset = self.handset
        self.open_emergency(3)
        self.expect(MESSAGE_RECIPIENT_MENU)
        handset.press("soft_left")
        self.expect(EMPTY_RECIPIENTS)
        handset.press("soft_left")
        self.expect(RECIPIENT_OPTIONS)
        handset.press("soft_left")
        self.expect(SELECT_RECIPIENT)
        handset.press("soft_left")
        self.expect(NUMBER_EMPTY)
        handset.press("soft_left")
        self.expect(INVALID_NUMBER)
        self.expect(NUMBER_EMPTY)
        for key in "12345":
            handset.press(key)
        self.expect(NUMBER_12345)
        handset.press("soft_left")
        self.expect(RECIPIENT_12345)
        handset.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        handset.press("soft_left")
        self.expect(RECIPIENT_12345)
        for confirm in ("soft_right", "soft_left"):
            handset.press("soft_left")
            handset.press("down")
            handset.press("soft_left")
            self.expect(DELETE_RECIPIENT)
            handset.press(confirm)
            self.expect(RECIPIENT_12345 if confirm == "soft_right" else EMPTY_RECIPIENTS)
        handset.press("soft_right")
        self.expect(MESSAGE_RECIPIENT_MENU)
        self.finish_home()

    def test_iercc_registration_cancel_and_empty_short_pin_rejection(self):
        handset = self.handset
        self.open_emergency(5)
        self.expect(IERCC_MENU)
        handset.press("soft_left")
        self.expect(IERCC_UNCONFIGURED)
        handset.press("soft_left")
        self.expect(IERCC_REGISTRATION_CONFIRMATION)
        handset.press("soft_right")
        self.expect(IERCC_MENU)

        for entry in ("", "1"):
            with self.subTest(entry="empty" if not entry else "one digit"):
                handset.press("soft_left")
                self.expect(IERCC_UNCONFIGURED)
                handset.press("soft_left")
                self.expect(IERCC_REGISTRATION_CONFIRMATION)
                handset.press("soft_left")
                self.expect(IERCC_PIN)
                if entry:
                    handset.press(entry)
                    self.expect(IERCC_PIN_ONE_MASK)
                handset.press("soft_left")
                self.expect(IERCC_PIN_REJECTED)
                self.expect(IERCC_MENU)
                handset.press("soft_left")
                self.expect(IERCC_UNCONFIGURED)
                handset.press("soft_right")
                self.expect(IERCC_MENU)
        self.finish_home()
        state = handset.state()
        self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr"})
        self.assertFalse(state["processor_link"]["connected"])

    def test_gps_settings_lock_rejects_invalid_pin_and_protects_saved_mode(self):
        handset = self.handset
        self.open_location()
        handset.press("soft_left")
        handset.press("soft_left")
        self.expect(DISABLED)
        handset.press("up")
        handset.press("soft_left")
        self.expect(GPS_PIN)
        handset.press("soft_left")
        self.expect(GPS_PIN_LENGTH_ERROR)
        self.expect(GPS_PIN)
        # The supplied manual specifies the factory GPS settings PIN as 3333.
        self.enter_gps_pin("3333")
        self.expect(GPS_LOCKED)
        self.expect(GPS_LOCK_MENU)
        handset.press("soft_left")
        self.expect(ENABLED)
        handset.press("soft_right")
        handset.press("down")
        self.expect(GPS_UPDATE_MENU)
        handset.press("soft_left")
        self.expect(ONE_TIME)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_PIN)
        self.enter_gps_pin("3334")
        self.expect(INCORRECT_PIN)
        # Error notifications expire back to the still-masked attempted PIN.
        self.expect(GPS_PIN_FOUR_MASKS)
        handset.press("soft_right")
        self.expect(GPS_PIN_THREE_MASKS)
        handset.press("3")
        self.expect(GPS_PIN_FOUR_MASKS)
        handset.press("soft_left")
        self.expect(GPS_UPDATE_MENU)
        handset.press("soft_left")
        self.expect(REAL_TIME)
        handset.press("up")
        handset.press("soft_left")
        self.expect(GPS_PIN)
        self.enter_gps_pin("3333")
        self.expect(GPS_UPDATE_MENU)
        handset.press("soft_left")
        self.expect(ONE_TIME)
        handset.press("soft_right")
        handset.press("up")
        handset.press("soft_left")
        self.expect(ENABLED)
        handset.press("down")
        handset.press("soft_left")
        self.expect(GPS_PIN)
        self.enter_gps_pin("3333")
        self.expect(GPS_LOCK_MENU)
        handset.press("soft_left")
        self.expect(DISABLED)
        handset.press("soft_right")
        self.finish_home()


if __name__ == "__main__":
    unittest.main()
