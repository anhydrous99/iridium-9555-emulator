"""Original handset keypad and security workflows through real HTTP controls."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


HOME = "c5b13a7f8cb40d8e802fa101ddedc73657fc70b7ddf24b3becd757bf12fabee2"
KEYPAD_LOCKED = "da8009dac4839f5a0a82b5fac5f033aa6755a1190dd37d342c68d317717f2f43"
LOCKED_CAPTIONS = "53854577af56617ace8db361bf27e06d2074e74b661b5175f0f237eaeb205a21"
LOCKED_INPUT_REJECTED = "98fb080de2f84af6def0093b189fba280bf03b482ec6b40d6d75601de6f024bf"
UNLOCK_PROMPT = "6980b756650e61476d89955e719c3a0ecc7f844f7e11d464934b712d7e19d7d9"
KEYPAD_UNLOCKED = "69f94dcaeae4fe8f4acbf4ea6fc81ba95583f5cd4eddee55aa5330f063d425e8"
NUMBER_PLUS_TWELVE = "0202fd2bdaff65347166c5507d64b6947fe26117599393a717de476a01e50093"
PHONE_LOCK_MENU = "398b36e74f824e4fe967d2be48c5e532e9f9919db04ee7b91d56f3df39be17b7"
PHONE_PIN = "1a922175bbb2b084086dbc6ff0798282f0462a0c41be46be883b962cb24b202c"
FOUR_MASKED_PIN_DIGITS = "aeb4fa4901c1c0c6629b3aa96128630e8117fa30a8182fcaef3f54f953c25fc5"
MASKED_PIN_DIGITS = (
    "0f7b639cbd5ec8cce09a76c87e20738623476531eff9f5ff8778c7396526a367",
    "8a90e4314566c422d689435be8bcee052422c4d595d4be7d21250a498689368f",
    "9c6e69233653f9b56dc81abb3491587bbce3ee521832f355bfdefb7ff17d7292",
    FOUR_MASKED_PIN_DIGITS,
)
FIRMWARE_IDENTITY_WARNING = "31e42d1f6c9a2563c2814c57cf2c00aaa87c146a5dea4d1d85dbb998a5b48c6b"
STARTUP_SIM_ERROR = "335f89c08eb4e32d608fb00be65a2e79bc348dc178d9fcae246719f810b0b0b2"
IERCC_NOT_CONFIGURED = "5254c60ca29dcf137833d0afb401a0a159af274be86dbce5eae72e446c0a3925"
IERCC_DISABLED = "6f1ad1406b07509ccf2994e122f31f9250a7331fffa01ffca2ef37ccc0d3cd22"
SOS_MESSAGE_RECIPIENT_WARNING = "6ad04abc4cc7284c527a32dfc578bcb4fc3c2a0e1796e1ed3fd489b672a54318"
PHONE_LOCKED = "b3a226f794b8d8bf538266b45f6c8a7d976ee3ba16abd4d2856e66f7ffaba40a"
INCORRECT_PIN = "ecb08e423ed7f7337615e403fecb66767d1057db0d61b566e8f6fccda4dcb963"
CHANGE_PIN_FORM = "74ab4ab4f543188a14f4e8d4d0b81a8865ba5df92d110ba70aeb64231c377dde"
MISSING_PINS = "9f2dbd6d8abdeb920882fcb49a5b4561adff4484f74fea7488ba3bda43913dc6"
NEW_PINS_DO_NOT_MATCH = "acb018f9e519e34d340c2db076a9d63aab28d7bb881a79ce3dc6d778b4c088fb"
MASKED_CHANGE_PIN_FIELDS = "c60449c465e6314c002c683ce958a86020567c679307525d5a4a3dbbc3bea885"


class SharedSecurityChecks:
    def test_phone_lock_with_factory_modem_rejects_wrong_pin_and_unlocks_after_restart(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.addCleanup(handset.save_artifacts, "final")

        def expect(screen, budget=2000000):
            return handset.wait_screen(screen, max_steps=budget, chunk_steps=1000000)

        def press(key):
            self.assertTrue(handset.key(key, True)["delivered"])
            handset.step(1000000)
            self.assertTrue(handset.key(key, False)["delivered"])
            return handset.step(10000000)

        def boot_with_known_modem_alerts():
            handset.control("initialize_ui")
            handset.control("pause")
            alerts = {STARTUP_SIM_ERROR: "absent-sim", FIRMWARE_IDENTITY_WARNING: "firmware-identity"}
            required_alert = "absent-sim"
            if self.model == "9575":
                alerts[IERCC_NOT_CONFIGURED] = "iercc-not-configured"
                alerts[IERCC_DISABLED] = "iercc-disabled"
                alerts[SOS_MESSAGE_RECIPIENT_WARNING] = "sos-message-recipient"
                required_alert = "iercc-not-configured"
            seen = set()
            dismissed = elapsed = 0
            while elapsed <= 120000000:
                state = handset.state()
                body = handset.screen_hash(state=state)
                if body in alerts:
                    self.assertNotIn(alerts[body], seen, "Modem startup repeated a recognized alert")
                    seen.add(alerts[body])
                    handset.save_artifacts(f"modem-startup-{dismissed}-{alerts[body]}", state)
                    # SIM/identity dialogs label this OK; IERCC labels it Cancel.
                    press("soft_right")
                    dismissed += 1
                elif (required_alert in seen and
                      handset.screen_hash(113, 128, state) == HOME_CAPTIONS):
                    self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr", "trx"})
                    self.assertTrue(state["processor_link"]["connected"])
                    # Missing boot-ROM identity is still a model gap, including
                    # when this boot's visible alert sequence omits its warning.
                    identity = "with" if "firmware-identity" in seen else "without"
                    handset.save_artifacts(f"modem-home-{identity}-identity-warning", state)
                    return state
                else:
                    handset.step(1000000)
                    elapsed += 1000000
            handset.save_artifacts("unknown-modem-startup-screen")
            self.fail("Modem startup did not reach home after its recognized factory alerts")

        def enter_security():
            press("soft_left")
            for _ in range(7):
                press("down")
            press("soft_left")
            press("soft_left")
            expect(PHONE_LOCK_MENU)

        def enter_pin(pin):
            for key, masked in zip(pin, MASKED_PIN_DIGITS, strict=True):
                press(key)
                expect(masked)
            press("soft_left")

        def restart():
            state = handset.press("power", settle_steps=0)
            for _ in range(50):
                primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
                if primary["power_state"] == 8:
                    break
                state = handset.step(200000)
            else:
                self.fail("Phone did not complete shutdown")
            handset.control("initialize_ui")
            handset.control("pause")

        boot_with_known_modem_alerts()
        enter_security()
        press("soft_left")
        expect(PHONE_PIN)
        # The supplied handset manual specifies the factory phone PIN as 1234.
        enter_pin("1234")
        expect(PHONE_LOCKED, 30000000)
        handset.save_artifacts("phone-locked")
        press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

        restart()
        expect(PHONE_PIN, 120000000)
        enter_pin("1235")
        expect(INCORRECT_PIN, 30000000)
        press("soft_left")
        expect(PHONE_PIN, 30000000)
        enter_pin("1234")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128)
        enter_security()
        press("down")
        press("soft_left")
        expect(PHONE_PIN)
        enter_pin("1234")
        expect(PHONE_LOCK_MENU, 30000000)
        for _ in range(3):
            press("soft_right")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        restart()
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)

    def test_change_phone_pin_rejects_missing_fields_and_mismatched_verification(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        def expect(screen):
            return handset.wait_screen(screen, max_steps=2000000)

        handset.press("soft_left")
        for _ in range(7):
            handset.press("down")
        for key in ("soft_left", "down", "down", "soft_left", "soft_left"):
            handset.press(key)
        expect(CHANGE_PIN_FORM)
        handset.press("soft_left")
        expect(MISSING_PINS)
        handset.press("soft_right")
        expect(CHANGE_PIN_FORM)
        for field, pin in enumerate(("1234", "2468", "2469")):
            if field:
                handset.press("down")
            for key in pin:
                handset.press(key)
        expect(MASKED_CHANGE_PIN_FIELDS)
        handset.press("soft_left")
        expect(NEW_PINS_DO_NOT_MATCH)
        handset.press("soft_right")
        expect(MASKED_CHANGE_PIN_FIELDS)
        handset.press("red")
        for _ in range(3):
            handset.press("soft_right")
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)

    def test_keypad_lock_rejects_digits_and_unlock_restores_number_entry(self):
        handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        def expect(screen):
            return handset.wait_screen(screen, max_steps=2000000)

        handset.press("soft_left")
        handset.press("*")
        expect(KEYPAD_LOCKED)
        handset.press("1")
        expect(HOME)
        handset.wait_screen(LOCKED_CAPTIONS, first=113, last=128, max_steps=2000000)
        handset.press("2")
        # Original warning says 'Press Unlock then *', rather than entering a number.
        expect(LOCKED_INPUT_REJECTED)
        handset.press("red")
        handset.wait_screen(LOCKED_CAPTIONS, first=113, last=128, max_steps=2000000)
        handset.press("soft_left")
        expect(UNLOCK_PROMPT)
        handset.press("*")
        expect(KEYPAD_UNLOCKED)
        handset.press("red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        for key in "12":
            handset.press(key)
        expect(NUMBER_PLUS_TWELVE)
        handset.press("red")
        state = handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        handset.assert_healthy(state)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 security E2E tests")
class Factory9555SecurityE2ETests(SharedSecurityChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 security E2E tests")
class Factory9575SecurityE2ETests(SharedSecurityChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
