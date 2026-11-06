"""Factory image uploads replace real processors and their model-specific controls."""

import os
import unittest

from factory_handset import FactoryHandset, FIRMWARE_ENV, factory_firmware
from iridium.firmware import RAW_FILES


@unittest.skipUnless(all(os.environ.get(variable) for variable in FIRMWARE_ENV.values()),
                     "Set both factory firmware directories for the model-switch E2E journey")
class FactoryModelSwitchE2ETests(unittest.TestCase):
    def test_original_images_switch_both_models_and_invalidate_held_browser_input(self):
        handset = FactoryHandset(self, "9555", os.environ[FIRMWARE_ENV["9555"]])
        self.addCleanup(handset.save_artifacts, "final")
        handset.boot()

        for model in ("9575", "9555"):
            images = factory_firmware(model, os.environ[FIRMWARE_ENV[model]])
            self.assertTrue(handset.key("1", True, client_id="old-tab")["delivered"])
            epoch = handset.epoch
            for image in images:
                response = handset.request("POST", "/api/firmware", image.data,
                                           headers={"X-Filename": RAW_FILES[image.image]})
                self.assertEqual(response["firmware"]["payload_sha256"], image.payload_sha256)
                state = handset.state()
                self.assertEqual(state["handset"]["model"], model)
                self.assertGreater(state["key_epoch"], epoch)
                self.assertEqual(state["keys"], [])
                self.assertFalse(state["ui_initialized"])
                self.assertIsNone(state["lcd"])
                self.assertEqual({cpu["image"] for cpu in state["processors"]},
                                 {"bc5"} if image.image == "bc5" else {"bc5", "avr"})
                self.assertTrue(all(cpu["handset"] == model for cpu in state["processors"]))
            self.assertFalse(handset.key("1", True, client_id="old-tab", epoch=epoch)["delivered"])
            state = handset.boot()
            self.assertEqual(state["handset"]["firmware_version"], "HL25003" if model == "9575" else "HT25003")
            self.assertEqual(state["asset"]["source"], "firmware resource 21" if model == "9575" else "firmware resource 19")
            if model == "9575":
                self.assertIn("sos", state["handset"]["keys"])
                handset.press("convenience")
                handset.wait_screen("ccab0537fb15d496f17cc97f8104369a8d402327827e54765d9819e856dd1357",
                                    max_steps=2000000)
                handset.press("soft_right")
            else:
                self.assertNotIn("sos", state["handset"]["keys"])
                handset.request("POST", "/api/key", {"key": "sos", "pressed": True}, expected_status=400)
            handset.press("soft_left")
            handset.wait_screen("dd3d228fb0b974e47af552285e8fcd9175ba89a18e3cb9000ee6bd7795c59272",
                                last=97, max_steps=2000000)
            handset.press("soft_right")
            self.assertEqual(handset.state()["keys"], [])


if __name__ == "__main__":
    unittest.main()
