"""Valid GPS coordinate boundaries through receiver UART0 and factory LCD.

Expected numbers use exact integer receiver units and the original ASCII1
font. Near-boundary quarter degrees and 0.0125 degrees have exact milliminute
representations; no tolerance, invalid-coordinate policy or RF fix is inferred.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from gps_receiver_frames import GPSReceiverFixture, ubx
from test_factory_extreme_settings_e2e import (
    DECIMAL_DEGREES, DEGREES_MINUTES_SECONDS, GPS_UPDATE_MENU, ONE_TIME,
    POSITION_MENU, REAL_TIME,
)
from test_factory_gps_e2e import GPS_PROMPT
from test_factory_phonebook_capacity_e2e import OriginalASCII1


UNITS = 10_000_000
INITIAL = (377749000, -1224194000, 8)


def coordinate_parts(value):
    degrees, remainder = divmod(abs(value), UNITS)
    minutes_milli, residual = divmod(remainder * 60_000, UNITS)
    assert residual == 0, "Fixtures must have exact milliminute representations"
    minutes, fraction = divmod(minutes_milli, 1000)
    return [int(value < 0), degrees, minutes, fraction]


def receiver_epoch(number, latitude, longitude, satellites=9):
    """Complete checksum-valid external 3D epoch; no handset state writes."""
    assert -90 * UNITS <= latitude <= 90 * UNITS
    assert -180 * UNITS <= longitude <= 180 * UNITS
    assert 1 <= number < 60 and 4 <= satellites <= 32
    tow = 123000 + 1000 * number
    frames = [
        ubx(1, 2, struct.pack("<IiiiiII", tow, longitude, latitude,
                              32000, 30000, 1000, 1000)),
        ubx(1, 6, struct.pack("<IihBBiiiIiiiIHBBI", tow, 0, 2200, 3, 1,
                              0, 0, 0, 1000, 0, 0, 0, 100, 100, 0, satellites, 0)),
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
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory GPS coordinate boundaries")
class Factory9575GPSCoordinateLimitsE2ETests(unittest.TestCase):
    def setUp(self):
        self.handset = FactoryHandset(self, "9575", os.environ["IRIDIUM_TEST_9575_FIRMWARE"])
        self.addCleanup(self.handset.save_artifacts, "final")
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.decimal = False
        self.evidence = []
        self.handset.boot()
        self.keys("soft_left", *(["down"] * 6), "soft_left", "soft_left",
                  "soft_left", "down", "soft_left")
        self.expect(ONE_TIME)
        self.keys("down", "soft_left")
        self.expect(GPS_UPDATE_MENU)
        self.keys("soft_left")
        self.expect(REAL_TIME)
        self.keys("soft_right", "red")
        self.expect(HOME_CAPTIONS, 113, 128)

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=20000000)

    def read(self, image, address, count):
        return self.handset.request("POST", "/api/probe", {
            "image": image, "operation": "read", "address": address, "count": count,
        })["values"]

    def position(self):
        manager = self.read("bc5", 0xF840, 1)[0]
        self.assertGreater(manager, 0)
        pointer = self.read("bc5", manager, 1)[0]
        self.assertGreater(pointer, 0)
        return self.read("bc5", pointer, 13)

    def gps_powered(self):
        pins = self.handset.request("POST", "/api/probe", {
            "image": "avr", "operation": "pin_state",
        })
        self.assertTrue(pins["pins"][8] & 0x80, "Original receiver power PJ7 must be high")

    def set_decimal(self, enabled):
        self.keys("soft_left", *(["down"] * 6), "soft_left", "soft_left",
                  *(["down"] * 4), "soft_left")
        self.expect(POSITION_MENU)
        self.keys("soft_left")
        self.expect(DECIMAL_DEGREES if self.decimal else DEGREES_MINUTES_SECONDS)
        self.keys("up" if enabled else "down", "soft_left")
        self.expect(POSITION_MENU)
        self.keys("soft_left")
        self.expect(DECIMAL_DEGREES if enabled else DEGREES_MINUTES_SECONDS)
        self.keys("soft_right", "soft_right", "soft_right", "soft_right", "soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.decimal = enabled

    def line(self, label, value, width):
        negative, degrees, minutes, fraction = coordinate_parts(value)
        sign = "-" if negative else ""
        if self.decimal:
            # Current Location passes original decimal-format flag 0x2:
            # reserve the sign column with a space for nonnegative values.
            sign = "-" if negative else " "
            remainder = abs(value) % UNITS
            self.assertEqual(remainder % 10, 0)
            number = f"{degrees:0{width}d}.{remainder // 10:06d}"
        else:
            seconds = fraction * 60 // 1000
            number = f"{degrees:2d}deg{minutes:02d}'{seconds:02d}\""
        return label + sign + number

    def expected(self, latitude, longitude, satellites):
        lat, lon = coordinate_parts(latitude), coordinate_parts(longitude)
        position = [1, *lat, *lon, 1, 0, 30, satellites]
        lines = [(16, self.line("Lat:", latitude, 2)),
                 (32, self.line("Lon:", longitude, 3)),
                 (96, f"Satellites: {satellites}")]
        return position, lines

    def row(self, state, first):
        pixels = state["lcd"]["pixels"]
        return bytes(pixels[(first + y) * 128 + x] for y in range(15) for x in range(2, 128))

    def assert_fix(self, latitude, longitude, satellites, label):
        expected, lines = self.expected(latitude, longitude, satellites)
        glyphs = [(row, text, self.font.render(text, 126)[0]) for row, text in lines]
        state = self.handset.assert_healthy()
        for elapsed in range(0, 20000001, 200000):
            position = self.position()
            if position == expected and all(self.row(state, row) == pixels for row, _, pixels in glyphs):
                self.assertEqual(state["keys"], [])
                self.assertFalse(state["satellite"]["firmware_connected"])
                snapshot = state | {"receiver_diagnostics": {
                    "bc5_cached_position": position,
                    "avr_publication_sequence": self.read("avr", 0x905, 1),
                    "avr_position_buffers": self.read("avr", 0x36A, 28),
                }}
                path = self.handset.save_artifacts(label, snapshot)
                item = {"latitude_1e7": latitude, "longitude_1e7": longitude,
                        "satellites": satellites, "decimal": self.decimal,
                        "expected_position": expected, "lines": lines,
                        "font_sha256": sha256(self.font.data).hexdigest(), "capture": str(path)}
                self.evidence.append(item)
                Path(str(path) + "-expectation.json").write_text(json.dumps(item, indent=2) + "\n")
                return state
            if elapsed < 20000000:
                state = self.handset.step(200000)
        self.handset.save_artifacts(label + "-timeout", state | {"bc5_cached_position": position})
        self.assertEqual(position, expected, label)
        for row, text, wanted in glyphs:
            self.assertEqual(self.row(state, row), wanted, f"{label}: full original-font line {text!r}")

    def start_receiver(self):
        self.keys("convenience")
        self.expect(GPS_PROMPT)
        self.keys("soft_left")
        self.gps_powered()
        self.receiver = GPSReceiverFixture(self.handset)
        self.receiver.publish_fix()
        self.assert_fix(*INITIAL, "initial-fix")

    def publish(self, number, latitude, longitude):
        self.gps_powered()
        sequence = self.read("avr", 0x905, 1)[0]
        frames = receiver_epoch(number, latitude, longitude)
        for frame in frames:
            self.receiver.receive(frame)
        self.assert_fix(latitude, longitude, 9, f"epoch-{number}")
        self.assertNotEqual(self.read("avr", 0x905, 1)[0], sequence,
                            "The original receiver must publish a new complete epoch")
        target = self.handset.save_artifacts(f"epoch-{number}-wire")
        Path(str(target) + "-frames.json").write_text(json.dumps({
            "epoch": number, "frames_hex": [frame.hex() for frame in frames],
        }, indent=2) + "\n")

    def reopen_and_change_format(self, latitude, longitude):
        cached = self.position()
        self.keys("soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("convenience")
        self.assert_fix(latitude, longitude, 9, "reopened-cache")
        self.assertEqual(self.position(), cached)
        self.keys("soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.set_decimal(not self.decimal)
        self.keys("convenience")
        self.assert_fix(latitude, longitude, 9, "alternate-format-cache")
        self.assertEqual(self.position(), cached,
                         "Changing format/reopening must retain the original parsed fix")
        self.keys("soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)

    def test_decimal_zero_crossings_update_cache_and_reopen_as_dms(self):
        self.set_decimal(True)
        self.start_receiver()
        for number, (latitude, longitude) in enumerate([
                (125000, -125000), (0, 0), (-125000, 125000),
                (2500000, -2500000)], 1):
            self.publish(number, latitude, longitude)
        self.reopen_and_change_format(2500000, -2500000)

    def test_exact_poles_and_near_pole_recovery_render_in_both_formats(self):
        self.start_receiver()
        for number, (latitude, longitude) in enumerate([
                (0, 0), (900000000, 450000000),
                (897500000, 452500000), (-900000000, -450000000)], 1):
            self.publish(number, latitude, longitude)
        self.reopen_and_change_format(-900000000, -450000000)

    def test_dateline_endpoints_and_nearby_recovery_reopen_as_dms(self):
        self.set_decimal(True)
        self.start_receiver()
        for number, (latitude, longitude) in enumerate([
                (125000000, 1797500000), (125000000, 1800000000),
                (-125000000, -1800000000), (-125000000, -1797500000),
                (125000000, 1800000000)], 1):
            self.publish(number, latitude, longitude)
        self.reopen_and_change_format(125000000, 1800000000)


if __name__ == "__main__":
    unittest.main()
