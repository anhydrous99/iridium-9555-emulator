"""Receiver validity and recovery through original HL25003 UART/SPI/LCD code."""

from hashlib import sha256
import os
import struct
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from gps_receiver_frames import GPSReceiverFixture, ubx
from test_factory_extreme_settings_e2e import GPS_UPDATE_MENU, ONE_TIME, REAL_TIME
from test_factory_gps_e2e import EIGHT_SATELLITES, GPS_PROMPT
from test_factory_gps_negative_e2e import FIRST_LAT_LON, NINE_SATELLITES, SECOND_LAT_LON
from test_factory_phonebook_capacity_e2e import OriginalASCII1


FIRST_POSITION = [1, 0, 37, 46, 494, 1, 122, 25, 164, 1, 0, 30, 8]
NEXT_POSITION = [1, 1, 33, 52, 128, 0, 151, 12, 558, 1, 0, 25, 9]


def receiver_epoch(number, *, valid=True):
    """External receiver messages; no handset memory or callback substitution."""
    tow = 123000 + 1000 * number
    frames = [
        ubx(1, 2, struct.pack("<IiiiiII", tow, 1512093000, -338688000,
                              27000, 25000, 1000, 1000)),
        ubx(1, 6, struct.pack("<IihBBiiiIiiiIHBBI", tow, 0, 2200,
                              3 if valid else 0, 1 if valid else 0,
                              0, 0, 0, 1000, 0, 0, 0, 100, 100, 0,
                              9 if valid else 0, 0)),
        ubx(1, 0x21, struct.pack("<IIiHBBBBBB", tow, 1000, 0, 2026, 11, 4,
                                 12, 0, number, 7)),
        ubx(1, 0x12, struct.pack("<IiiiIIiII", tow, 0, 0, 0, 0, 0, 0, 100, 100)),
    ]
    body = f"GPGST,1200{number:02d}.00,1.2,1.0,1.0,0.0,1.0,1.0,1.5".encode()
    checksum = 0
    for value in body:
        checksum ^= value
    return frames + [b"$" + body + f"*{checksum:02X}\r\n".encode()]


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory GPS validity E2E")
class Factory9575GPSValidityE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", os.environ["IRIDIUM_TEST_9575_FIRMWARE"])
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.handset.boot()
        self.keys("soft_left", *(["down"] * 6), "soft_left", "soft_left",
                  "soft_left", "down", "soft_left")
        self.expect(ONE_TIME)
        self.keys("down", "soft_left")
        self.expect(GPS_UPDATE_MENU)
        self.keys("soft_left")
        self.expect(REAL_TIME)
        self.keys("soft_right", "red")
        self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.keys("convenience")
        self.expect(GPS_PROMPT)
        self.keys("soft_left")
        self.receiver = GPSReceiverFixture(self.handset)
        self.receiver.publish_fix()
        self.assert_fix(FIRST_POSITION, FIRST_LAT_LON, EIGHT_SATELLITES, "+98 ft")

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=10000000)

    def read(self, image, address, count):
        return self.handset.request("POST", "/api/probe", {
            "image": image, "operation": "read", "address": address, "count": count,
        })["values"]

    def position(self):
        manager = self.read("bc5", 0xF840, 1)[0]
        self.assertGreater(manager, 0)
        position = self.read("bc5", manager, 1)[0]
        self.assertGreater(position, 0)
        return self.read("bc5", position, 13)

    def altitude(self, text):
        glyphs, _ = self.font.render("Alt:" + text, 126)
        crop = bytearray(128 * 16)
        for y in range(15):
            crop[y * 128 + 2:(y + 1) * 128] = glyphs[y * 126:(y + 1) * 126]
        return sha256(crop).hexdigest()

    def save_position(self, label, state=None):
        state = self.handset.state() if state is None else state
        snapshot = state | {"receiver_diagnostics": {
            "bc5_cached_position": self.position(),
            "avr_publication_sequence": self.read("avr", 0x905, 1),
            "avr_position_buffers": self.read("avr", 0x36A, 28),
        }}
        self.handset.save_artifacts(label, snapshot)
        return state

    def assert_fix(self, position, coordinates, satellites, altitude):
        self.expect(coordinates, 16, 44)
        self.expect(satellites, 96, 109)
        state = self.expect(self.altitude(altitude), 48, 64)
        self.assertEqual(self.position(), position)
        self.assertEqual(state["keys"], [])
        self.assertFalse(state["satellite"]["firmware_connected"])
        return state

    def assert_last_fix_retained(self, label):
        # Give the original parser and RealTime polls ample guest execution.
        self.handset.step(10000000)
        state = self.handset.assert_healthy()
        self.save_position(label, state)
        self.assertEqual(self.position(), FIRST_POSITION, label)
        self.assertEqual(self.handset.screen_hash(16, 44, state), FIRST_LAT_LON, label)
        self.assertEqual(self.handset.screen_hash(96, 109, state), EIGHT_SATELLITES, label)
        self.assertEqual(self.handset.screen_hash(48, 64, state), self.altitude("+98 ft"), label)

    def assert_recovered(self):
        state = self.assert_fix(NEXT_POSITION, SECOND_LAT_LON, NINE_SATELLITES, "+82 ft")
        self.handset.save_artifacts("valid-epoch-recovery", state)
        self.keys("soft_right")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def test_corrupt_ubx_position_retains_last_fix_until_valid_retransmission(self):
        frames = receiver_epoch(1)
        corrupt = bytearray(frames[0])
        corrupt[-1] ^= 1
        self.receiver.receive(corrupt)
        for frame in frames[1:]:
            self.receiver.receive(frame)
        self.assert_last_fix_retained("bad-ubx-checksum-keeps-last-fix")
        self.receiver.receive(frames[0])
        self.assert_recovered()

    def test_incomplete_epoch_bad_nmea_and_missing_line_ending_retain_last_fix(self):
        frames = receiver_epoch(1)
        for frame in frames[:-1]:
            self.receiver.receive(frame)
        self.assert_last_fix_retained("incomplete-epoch-keeps-last-fix")
        corrupt = bytearray(frames[-1])
        corrupt[-4] = ord("0") if corrupt[-4] != ord("0") else ord("1")
        self.receiver.receive(corrupt)
        self.assert_last_fix_retained("bad-nmea-checksum-keeps-last-fix")
        self.receiver.receive(frames[-1][:-2])
        self.assert_last_fix_retained("missing-nmea-line-ending-keeps-last-fix")
        self.receiver.receive(frames[-1][-2:])
        self.assert_recovered()

    def test_mixed_epochs_cannot_form_a_fix_and_a_complete_fresh_epoch_recovers(self):
        first, second = receiver_epoch(1), receiver_epoch(2)
        for frame in (first[0], first[1], second[2], first[3], first[4]):
            self.receiver.receive(frame)
        self.assert_last_fix_retained("mixed-epoch-components-keep-last-fix")
        for frame in receiver_epoch(3):
            self.receiver.receive(frame)
        self.assert_recovered()

    def solution(self, fix_type, valid):
        frames = receiver_epoch(1, valid=valid)
        solution = bytearray(frames[1][6:-2])
        solution[10] = fix_type
        self.assertEqual(solution[11], int(valid))
        frames[1] = ubx(1, 6, solution)
        for frame in frames:
            self.receiver.receive(frame)

    def test_no_fix_solution_keeps_last_valid_position_and_valid_epoch_recovers(self):
        self.solution(0, False)
        self.assert_last_fix_retained("no-fix-solution-keeps-last-valid-position")
        # A complete invalid epoch must reach original publication: this cannot
        # pass merely because the supplied receiver bytes were ignored.
        self.assertEqual(self.read("avr", 0x905, 1), [2])
        buffers = self.read("avr", 0x36A, 28)
        invalid = [1, 0x50, 33, 52, 0, 128, 151, 12, 2, 46, 0, 0, 25, 0]
        self.assertIn(invalid, (buffers[:14], buffers[14:]))
        for frame in receiver_epoch(2):
            self.receiver.receive(frame)
        self.assert_recovered()

    def test_three_dimensional_solution_with_invalid_flag_cannot_replace_last_valid_fix(self):
        # NAV-SOL byte11 bit0 qualifies validity; byte10 gpsFix=3 is insufficient.
        # u-blox6 GPS.G6-SW-10018-F sections2.3 and35.9 define these wire fields.
        self.solution(3, False)
        self.assert_last_fix_retained("invalid-three-dimensional-solution")

    def test_valid_two_dimensional_solution_updates_current_location(self):
        frames = receiver_epoch(1)
        solution = bytearray(frames[1][6:-2])
        solution[10] = 2
        self.assertEqual(solution[11], 1)
        frames[1] = ubx(1, 6, solution)
        # A 2D receiver holds its preceding altitude; vary horizontal position
        # and satellite count without requiring a new vertical solution.
        position = bytearray(frames[0][6:-2])
        struct.pack_into("<ii", position, 12, 32000, 30000)
        frames[0] = ubx(1, 2, position)
        for frame in frames:
            self.receiver.receive(frame)
        self.handset.step(10000000)
        self.save_position("valid-two-dimensional-solution")
        expected = NEXT_POSITION.copy()
        expected[11] = 30
        state = self.assert_fix(expected, SECOND_LAT_LON, NINE_SATELLITES, "+98 ft")
        self.handset.save_artifacts("valid-two-dimensional-horizontal-update", state)
        self.keys("soft_right")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)


if __name__ == "__main__":
    unittest.main()
