"""Original modem startup and release metadata across a completed warm power cycle."""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from iridium.profiles import PROFILES
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_security_e2e import (
    FIRMWARE_IDENTITY_WARNING, IERCC_DISABLED, IERCC_NOT_CONFIGURED,
    SOS_MESSAGE_RECIPIENT_WARNING, STARTUP_SIM_ERROR,
)


class ReleaseVersionChecks:
    def boot_without_version_warning(self):
        handset = self.handset
        handset.control("initialize_ui")
        handset.control("pause")
        alerts = {STARTUP_SIM_ERROR, IERCC_NOT_CONFIGURED, IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING}
        required = {STARTUP_SIM_ERROR} if self.model == "9555" else {
            IERCC_NOT_CONFIGURED, IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING}
        seen = set()
        elapsed = 0
        while elapsed <= 200000000:
            state = handset.assert_healthy(require_lcd=False)
            body = handset.screen_hash(state=state)
            self.assertNotEqual(body, FIRMWARE_IDENTITY_WARNING, "Original firmware rejected the release metadata")
            if body in alerts:
                self.assertNotIn(body, seen, "Startup repeated an alert")
                seen.add(body)
                handset.press("soft_right", hold_steps=1000000, settle_steps=10000000)
                elapsed += 11300000
            elif required <= seen and handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                return
            else:
                handset.step(1000000)
                elapsed += 1000000
        self.fail("Original modem startup did not reach home")

    def assert_information_version(self):
        handset = self.handset
        for key in (["soft_left"] + ["down"] * 6 + ["soft_left"]
                    + ["down"] * (8 + (self.model == "9575")) + ["soft_left"]):
            handset.press(key)
        width, height = 118, 15
        expected, _ = self.font.render(f"FW: {PROFILES[self.model].version}", width)
        for elapsed in range(0, 5000001, 200000):
            state = handset.assert_healthy()
            actual = bytes(state["lcd"]["pixels"][(16 + y) * 128 + x]
                           for y in range(height) for x in range(width))
            if actual == expected[:width * height]:
                handset.save_artifacts("verified-release-version", state)
                return
            if elapsed < 5000000:
                handset.step(200000)
        self.assertEqual(actual, expected[:width * height], "Phone Information must show the actual release")

    def test_original_release_version_survives_warm_startup_without_inconsistent_firmware(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        for cycle in range(2):
            self.boot_without_version_warning()
            self.assert_information_version()
            if cycle == 0:
                self.handset.press("red")
                self.handset.press("power", settle_steps=0)
                for _ in range(50):
                    state = self.handset.state()
                    primary = next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")
                    if primary["power_state"] == 8:
                        break
                    self.handset.step(200000)
                else:
                    self.fail("Original firmware did not complete shutdown")
        # A deliberately wrong compatibility record must still fail the original check.
        session = self.handset.session
        worker = session.engines["bc5"]
        session._idle(worker)
        profile = PROFILES[self.model]
        fields = profile.release_manifest.split(",")
        fields[1 if self.model == "9555" else 4] = "0"
        words = [ord(char) for char in ",".join(fields)] + [0]
        buffer = session._call(worker, 0xFD3A, al=len(words))["last_call"]["al"]
        self.assertNotEqual(buffer, 0)
        session.probe("bc5", "write", {"address": buffer, "values": words})
        result = session._call(worker, profile.version_store, al=0x2B3, ah=buffer,
                               stack=[len(words) - 1], steps=1000000)
        self.assertEqual(result["last_call"]["al"], 1)
        session._call(worker, 0x6DFE, al=buffer)
        entry = 0x8C766 if self.model == "9555" else 0x93210
        version = session._call(worker, entry)["last_call"]["al"]
        actual = session.probe("bc5", "read", {"address": version, "count": 8})["values"]
        self.assertEqual(actual, [ord(char) for char in profile.version[:2] + "xxxxx"] + [0])
        session._call(worker, 0x6DFE, al=version)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "Set IRIDIUM_TEST_FIRMWARE for factory 9555 release tests")
class Factory9555ReleaseVersionE2ETests(ReleaseVersionChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 release tests")
class Factory9575ReleaseVersionE2ETests(ReleaseVersionChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
