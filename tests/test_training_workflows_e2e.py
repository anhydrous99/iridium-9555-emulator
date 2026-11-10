"""Original handset UI driven by the explicitly simulated training UART peer."""
import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from test_factory_security_e2e import (
    STARTUP_SIM_ERROR, FIRMWARE_IDENTITY_WARNING, IERCC_NOT_CONFIGURED,
    IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING,
)

# Original LCD rows16:113, captured after finite synthetic SMS delivery.
SMS_PROMPT = "9fca4e96f6a61002b444328030f5268a24db2f32700235715ab3046497840c3f"
SMS_READ = "687df25b2b749e87190782f1e98dcacd09fd75bd387249591696181e4175b7f5"


class TrainingWorkflows:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.directory)
        self.addCleanup(self.handset.save_artifacts, "training-final")
        self.handset.request("POST", "/api/control", {"action": "mode", "mode": "training"})
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        alerts = {STARTUP_SIM_ERROR, FIRMWARE_IDENTITY_WARNING, IERCC_NOT_CONFIGURED,
                  IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING}
        for _ in range(160):
            state = self.handset.step(1000000)
            if self.handset.screen_hash(state=state) in alerts:
                self.press("soft_right")
            elif self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                break
        else:
            self.fail("Original training startup did not reach Home")
        self.scenario("register")
        self.scenario("advance", milliseconds=1000)
        self.assertTrue(self.handset.state()["satellite"]["registered"])

    def press(self, key):
        return self.handset.press(key, hold_steps=500000, settle_steps=2000000)

    def scenario(self, action, **arguments):
        return self.handset.request("POST", "/api/satellite", {"action": action, **arguments})

    def displayed_text(self, state=None):
        state = self.handset.state() if state is None else state
        return "\n".join(line["text"] for line in state["lcd"]["accessibility"]["lines"])

    def return_home_after_call(self):
        state = self.handset.state()
        self.assertEqual(state["satellite"]["call_state"], "idle")
        self.assertNotIn("Please wait", self.displayed_text(state))
        self.press("red")
        self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=10000000)

    def test_calls_answer_end_and_decline_on_original_lcd(self):
        for key in "123456789":
            self.press(key)
        self.press("green")
        state = self.handset.step(3000000)
        self.assertEqual(state["satellite"]["call_state"], "active")
        self.assertIn("00:00:", self.displayed_text(state))
        self.assertNotIn("DPL call", self.displayed_text(state))
        self.handset.save_artifacts("training-outgoing-active", state)
        self.press("red")
        self.handset.step(3000000)
        self.return_home_after_call()

        self.scenario("incoming_call", number="+881612345678")
        state = self.handset.step(3000000)
        self.assertIn("Incoming Call", self.displayed_text(state))
        self.assertIn("+881612345678", self.displayed_text(state))
        self.handset.save_artifacts("training-incoming-ring", state)
        self.press("green")
        state = self.handset.step(3000000)
        self.assertEqual(state["satellite"]["call_state"], "active")
        self.assertIn("00:00:", self.displayed_text(state))
        self.assertIn("ATA", self.handset.session.modem_link.commands)
        self.handset.save_artifacts("training-incoming-active", state)
        self.press("red")
        self.handset.step(3000000)
        self.return_home_after_call()

        self.scenario("incoming_call", number="+881612345678")
        self.handset.step(3000000)
        self.press("red")
        self.handset.step(3000000)
        self.assertIn("AT+CHLD=0", self.handset.session.modem_link.commands)
        self.return_home_after_call()

        # Original firmware interprets 12 as a call-control request; it must recover.
        for key in ("1", "2", "green"):
            self.press(key)
        state = self.handset.step(3000000)
        self.assertIn("AT+CHLD=12", self.handset.session.modem_link.commands)
        self.return_home_after_call()
        # The original firmware retries an unavailable network clock every six seconds.
        for _ in range(60):
            if "00:00 09-Nov-26" in self.displayed_text():
                break
            self.handset.step(1000000)
        else:
            self.fail("Original Home did not acquire the declared training date")
        self.handset.save_artifacts("training-home-clock")

    def test_incoming_sms_is_notified_and_read_on_original_lcd(self):
        self.scenario("incoming_sms", number="+881612345678", text="Hello training")
        state = self.handset.wait_screen(SMS_PROMPT, max_steps=10000000)
        self.assertTrue(state["satellite"]["firmware_connected"])
        self.assertEqual(state["processor_link"]["messages_stored"], 1)
        self.assertEqual(state["satellite"]["messages"][-1]["text"], "Hello training")
        self.press("soft_left")
        state = self.handset.wait_screen(SMS_READ, max_steps=10000000)
        self.assertEqual(state["keys"], [])
        self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr"})
        self.handset.save_artifacts("training-sms-read", state)
        self.press("red")
        self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=10000000)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "Set IRIDIUM_TEST_FIRMWARE")
class Training9555WorkflowTests(TrainingWorkflows, unittest.TestCase):
    model = "9555"
    directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "Set IRIDIUM_TEST_9575_FIRMWARE")
class Training9575WorkflowTests(TrainingWorkflows, unittest.TestCase):
    model = "9575"
    directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
