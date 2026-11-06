"""Factory HTTP call-option unavailable gates and local Fixed Dialling drafts.

These BC5/AVR journeys have no SIM or network service. They do not enable a
supplementary service, authenticate PIN2, or assert a completed call.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


# Complete, static 128×128 factory LCDs, inspected on both models. Full frames
# retain the title, feature-specific error text, selection/radio marks and footer.
# Original dispatchers: HT25003 0x73A7C; HL25003 0x73C02. Both select resources
# 0x1069–0x106C. Error bodies are the distinct original 0x11C3/0x11C1/0x11C6.
CALL_OPTIONS = (
    "ee3beadf836f1a9bd707228d4ac3da5479b8e152c50b982b77db5d0ac2cea255",
    "de846d6b8fcd9f81c0e5b49dd8f5422d5f41e48da26900ff3d7b9cf2015bbdd6",
    "1d95d77bf801d69b7eff0071b50303729e47dbc1dadb4fbb4563935d0824fb63",
    "02bc47b9332b3e5fa3429071b14eafd68c5a3197352c9da2efaf09ac6e5cf775",
)
UNAVAILABLE = (
    ("waiting", "318704869af012ef3ef6bea331eaaa39542f536a29dc51f6b936421b96ce338d"),
    ("forwarding", "27e5d23384a319a9e453e5ba736c3c76914f4a2ad846ff7e7faf918cfc9c6290"),
    ("barring", "d270218a9d44bfec22ee659d74789ff9af0738a29e56cb5a8ab1331837de8408"),
)
FIXED_DISABLED = "7af0869b25a08b4fd93f84aceeb4ce27962b2c1f0671c52e20e592a01fd94ec5"
# Disabled retains its saved radio mark while Enabled has the tentative focus.
FIXED_ENABLED_DRAFT = "38aead6d4139c03cc440cb95cda296635e3f00f75441e9885af08f91cfdd40ce"


class SharedCallOptionsChecks:
    def setUp(self):
        self.evidence = []
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, label, expected):
        state = self.handset.wait_screen(expected, first=0, last=128, max_steps=20000000)
        self.assertEqual(state["keys"], [])
        target = self.handset.save_artifacts(label, state)
        self.evidence.append({"label": label, "frame_sha256": expected, "artifact": str(target)})
        return state

    def open_call_options(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left")
        # HL25003 inserts Location Options before the shared Call Options row.
        self.keys(*(["down"] * (self.model == "9575")), "soft_left")
        self.expect("call-options-waiting", CALL_OPTIONS[0])

    def home(self):
        self.keys("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=20000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def test_waiting_forwarding_and_barring_report_network_unavailable_then_reopen(self):
        self.open_call_options()
        for index, (feature, error) in enumerate(UNAVAILABLE):
            if index:
                self.keys("down")
            self.expect(f"{feature}-selected", CALL_OPTIONS[index])
            self.keys("soft_left")
            self.expect(f"{feature}-network-unavailable", error)
            self.keys("soft_right")
            self.expect(f"{feature}-dismissed", CALL_OPTIONS[index])
            self.keys("soft_left")
            self.expect(f"{feature}-network-unavailable-reopened", error)
            self.keys("soft_right")
            self.expect(f"{feature}-dismissed-again", CALL_OPTIONS[index])
        self.home()

    def test_fixed_dialling_enabled_draft_cancel_preserves_disabled_on_reopen(self):
        self.open_call_options()
        self.keys("down", "down", "down")
        self.expect("fixed-dialling-selected", CALL_OPTIONS[3])
        self.keys("soft_left")
        self.expect("fixed-dialling-saved-disabled", FIXED_DISABLED)
        self.keys("down")
        self.expect("fixed-dialling-enabled-draft", FIXED_ENABLED_DRAFT)
        self.keys("soft_right")  # Back cancels the draft; never submit Enabled.
        self.expect("fixed-dialling-draft-cancelled", CALL_OPTIONS[3])
        self.keys("soft_left")
        self.expect("fixed-dialling-disabled-after-cancel", FIXED_DISABLED)
        self.keys("soft_right")
        self.expect("fixed-dialling-parent", CALL_OPTIONS[3])
        self.home()
        self.open_call_options()
        self.keys("down", "down", "down", "soft_left")
        self.expect("fixed-dialling-disabled-after-leaving-setup", FIXED_DISABLED)
        self.keys("soft_right")
        self.expect("fixed-dialling-final-parent", CALL_OPTIONS[3])
        self.home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 call-options E2E tests")
class Factory9555CallOptionsE2ETests(SharedCallOptionsChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 call-options E2E tests")
class Factory9575CallOptionsE2ETests(SharedCallOptionsChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
