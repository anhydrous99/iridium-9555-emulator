"""Signed GPS altitude must survive original receiver parsing and LCD formatting."""

import os
import struct
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from gps_receiver_frames import GPSReceiverFixture, ubx
from test_factory_extreme_settings_e2e import (ALTITUDE_MENU, FEET, GPS_UPDATE_MENU,
                                              ONE_TIME, POSITION_MENU, REAL_TIME)
from test_factory_gps_e2e import EIGHT_SATELLITES, GPS_PROMPT


FIRST_LAT_LON = "bf8b4de20bcb50e443367a4f42ad4f236db35b97bab47d7d684338f29d269c30"
SECOND_LAT_LON = "bd7abc5533c43242137f55782ef8fbbbfe91c0fb4e4b9baa78f4b17f101e82f1"
NINE_SATELLITES = "6e6177899ec5db847d0f0bb7db6ac11d07a9fff5c84ac30e0c51d33d595c4749"
# Correct signed lines rendered independently from original ASCII-1 glyphs at
# x2/y48, validated against three observed unsigned lines. Factory prints +.
NEGATIVE_FEET = "97694c4f02bdcec61511c002e76cc12e9e924d44c9e0ce235d267cbe9cc2d2a1"
NEGATIVE_METERS = "b3cb97e34e50dc52c3f45a527fd5339ba8c304c925059893ca60366bb5bc0dc6"


def second_epoch():
    tow = 124000
    frames = [
        ubx(1, 2, struct.pack("<IiiiiII", tow, 1512093000, -338688000,
                              -3000, -5000, 1000, 1000)),
        ubx(1, 6, struct.pack("<IihBBiiiIiiiIHBBI", tow, 0, 2200, 3, 1,
                              0, 0, 0, 1000, 0, 0, 0, 100, 100, 0, 9, 0)),
        ubx(1, 0x21, struct.pack("<IIiHBBBBBB", tow, 1000, 0, 2026, 11, 4, 12, 0, 1, 7)),
        ubx(1, 0x12, struct.pack("<IiiiIIiII", tow, 0, 0, 0, 0, 0, 0, 100, 100)),
    ]
    body = b"GPGST,120001.00,1.2,1.0,1.0,0.0,1.0,1.0,1.5"
    checksum = 0
    for value in body:
        checksum ^= value
    return frames + [b"$" + body + f"*{checksum:02X}\r\n".encode()]


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory signed-altitude E2E")
class Factory9575SignedAltitudeE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", os.environ["IRIDIUM_TEST_9575_FIRMWARE"])
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, screen):
        return self.handset.wait_screen(screen, max_steps=20000000)

    def open_location_options(self):
        self.keys("soft_left", *(["down"] * 6), "soft_left", "soft_left")

    def check_signed_altitude(self, meters):
        handset = self.handset
        self.open_location_options()
        self.keys("soft_left", "down", "soft_left")
        self.expect(ONE_TIME)
        self.keys("down", "soft_left")
        self.expect(GPS_UPDATE_MENU)
        self.keys("soft_left")
        self.expect(REAL_TIME)
        self.keys("soft_right", "red")
        handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        if meters:
            self.open_location_options()
            self.keys(*(["down"] * 4), "soft_left")
            self.expect(POSITION_MENU)
            self.keys("down", "soft_left")
            self.expect(FEET)
            self.keys("down", "soft_left")
            self.expect(ALTITUDE_MENU)
            self.keys("red")
            handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)

        self.keys("convenience")
        self.expect(GPS_PROMPT)
        self.keys("soft_left")
        receiver = GPSReceiverFixture(handset)
        receiver.publish_fix()
        handset.wait_screen(FIRST_LAT_LON, first=16, last=44, max_steps=10000000)
        handset.wait_screen(EIGHT_SATELLITES, first=96, last=109, max_steps=2000000)
        for frame in second_epoch():
            receiver.receive(frame)
        handset.wait_screen(SECOND_LAT_LON, first=16, last=44, max_steps=10000000)
        state = handset.wait_screen(NINE_SATELLITES, first=96, last=109, max_steps=2000000)
        self.assertEqual(state["keys"], [])

        def read(address, count):
            return handset.request("POST", "/api/probe", {
                "image": "bc5", "operation": "read", "address": address, "count": count,
            })["values"]

        manager = read(0xF840, 1)[0]
        position = read(read(manager, 1)[0], 13)
        self.assertEqual(position[9:12], [0, 0, 5], "Original parser must retain negative5m")
        handset.save_artifacts("negative-altitude-parsed", state)
        self.assertEqual(handset.screen_hash(48, 64), NEGATIVE_METERS if meters else NEGATIVE_FEET,
                         "Current Location must display -5m or -16ft; factory HL25003 drops the sign")

    def test_real_time_second_epoch_preserves_negative_altitude_in_feet(self):
        self.check_signed_altitude(meters=False)

    def test_real_time_second_epoch_preserves_negative_altitude_in_meters(self):
        self.check_signed_altitude(meters=True)


if __name__ == "__main__":
    unittest.main()
