"""Reject impossible receiver coordinates without replacing a valid GPS fix.

Checksum-valid external UART0 input exercises the original AVR/SPI/BC5 path.
All three factory processors run normally; no GPS cache or callback is patched.
These robustness cases do not establish physical receiver or RF behavior.
"""

from hashlib import sha256
import os
from pathlib import Path
import struct
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from factory_modem import FactoryModemChecks
from gps_receiver_frames import GPSReceiverFixture, ubx
from iridium.engine import Engine
from test_factory_extreme_settings_e2e import GPS_UPDATE_MENU, ONE_TIME, REAL_TIME
from test_factory_gps_e2e import GPS_PROMPT
from test_factory_phonebook_capacity_e2e import OriginalASCII1
import test_factory_gps_coordinate_limits_e2e as _coordinates


INITIAL = (377749000, -1224194000, 8)
RECOVERY = (-250000000, 1512500000, 9)


def external_epoch(number, latitude, longitude):
    """Allow deliberately invalid geography while retaining valid wire framing."""
    assert 1 <= number < 60
    assert all(-(1 << 31) <= value < (1 << 31) for value in (latitude, longitude))
    tow = 123000 + number * 1000
    frames = [
        ubx(1, 2, struct.pack("<IiiiiII", tow, longitude, latitude,
                              32000, 30000, 1000, 1000)),
        ubx(1, 6, struct.pack("<IihBBiiiIiiiIHBBI", tow, 0, 2200, 3, 1,
                              0, 0, 0, 1000, 0, 0, 0, 100, 100, 0, 9, 0)),
        ubx(1, 0x21, struct.pack("<IIiHBBBBBB", tow, 1000, 0, 2026, 11, 4,
                                 12, 0, number, 7)),
        ubx(1, 0x12, struct.pack("<IiiiIIiII", tow, 0, 0, 0, 0, 0, 0, 100, 100)),
    ]
    body = f"GPGST,1200{number:02d}.00,1.2,1.0,1.0,0.0,1.0,1.0,1.5".encode()
    checksum = 0
    for byte in body:
        checksum ^= byte
    return frames + [b"$" + body + f"*{checksum:02X}\r\n".encode()]


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "9575 factory firmware not supplied")
class Factory9575GPSRangeE2ETests(unittest.TestCase):
    model = "9575"
    read = _coordinates.Factory9575GPSCoordinateLimitsE2ETests.read
    position = _coordinates.Factory9575GPSCoordinateLimitsE2ETests.position
    gps_powered = _coordinates.Factory9575GPSCoordinateLimitsE2ETests.gps_powered
    row = _coordinates.Factory9575GPSCoordinateLimitsE2ETests.row
    line = _coordinates.Factory9575GPSCoordinateLimitsE2ETests.line
    expected = _coordinates.Factory9575GPSCoordinateLimitsE2ETests.expected
    boot_with_modem_alerts = FactoryModemChecks.boot_with_modem_alerts

    def setUp(self):
        self.evidence = []
        self.wire_epochs = []
        self.boots = 0
        self.decimal = False
        self.receiver = None
        self.request_method = Engine.request
        self.handset = FactoryHandset(self, self.model,
                                     os.environ["IRIDIUM_TEST_9575_FIRMWARE"], modem=True)
        self.workers = {
            image: {"pid": engine._process.pid,
                    "executable_sha256": sha256(Path(f"/proc/{engine._process.pid}/exe").read_bytes()).hexdigest()}
            for image, engine in self.handset.session.engines.items()
        }
        self.addCleanup(self.finish)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        self.boot_with_modem_alerts()
        self.keys("soft_left", *(["down"] * 6), "soft_left", "soft_left",
                  "soft_left", "down", "soft_left")
        self.expect(ONE_TIME)
        self.keys("down", "soft_left")
        self.expect(GPS_UPDATE_MENU)
        self.keys("soft_left")
        self.expect(REAL_TIME)
        self.keys("soft_right", "red")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("convenience")
        self.expect(GPS_PROMPT)
        self.keys("soft_left")
        self.gps_powered()
        self.receiver = GPSReceiverFixture(self.handset)
        self.receiver.publish_fix()
        self.assert_fix(*INITIAL, "initial-valid-fix")

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key)

    def expect(self, digest, first=16, last=113):
        return self.handset.wait_screen(digest, first=first, last=last, max_steps=20000000)

    def snapshot(self, label, state=None):
        state = self.handset.state() if state is None else state
        diagnostic = self.diagnostics()
        path = self.handset.save_artifacts(f"{len(self.evidence):03d}-{label}",
                                           state | {"receiver_diagnostics": diagnostic})
        self.evidence.append({"label": label, "artifact": str(path), **diagnostic,
                              "frame_sha256": sha256(bytes(state["lcd"]["pixels"])).hexdigest()})
        return path

    def diagnostics(self):
        if self.receiver is None:
            return {}
        return {"bc5_cached_position": self.position(),
                "avr_publication_sequence": self.read("avr", 0x905, 1),
                "avr_position_buffers": self.read("avr", 0x36A, 28)}

    def glyph_lines(self, latitude, longitude, satellites):
        _, lines = self.expected(latitude, longitude, satellites)
        return lines + [(48, "Alt:+98 ft")]

    def assert_fix(self, latitude, longitude, satellites, label):
        expected, _ = self.expected(latitude, longitude, satellites)
        lines = self.glyph_lines(latitude, longitude, satellites)
        glyphs = [(first, self.font.render(text, 126)[0]) for first, text in lines]
        for elapsed in range(0, 20000001, 200000):
            state = self.handset.assert_healthy()
            if self.position() == expected and all(self.row(state, first) == pixels for first, pixels in glyphs):
                self.assertEqual(state["keys"], [])
                self.assertFalse(state["satellite"]["firmware_connected"])
                self.snapshot(label, state)
                self.evidence[-1]["expected_position"] = expected
                self.evidence[-1]["expected_lines"] = lines
                return
            if elapsed < 20000000:
                self.handset.step(200000)
        self.snapshot(label + "-timeout", state)
        self.assertEqual(self.position(), expected, label)
        for first, pixels in glyphs:
            self.assertEqual(self.row(state, first), pixels, label)

    def publish(self, number, latitude, longitude):
        self.gps_powered()
        frames = external_epoch(number, latitude, longitude)
        self.wire_epochs.append({"number": number, "latitude_1e7": latitude,
                                 "longitude_1e7": longitude,
                                 "frames_hex": [frame.hex() for frame in frames]})
        for frame in frames:
            self.receiver.receive(frame)

    def invalid_then_recover(self, latitude, longitude):
        retained = self.position()
        sequence = self.read("avr", 0x905, 1)
        self.publish(1, latitude, longitude)
        self.handset.step(10000000)
        state = self.handset.assert_healthy()
        self.snapshot("invalid-geography-after-original-parser-and-polls", state)
        self.evidence[-1]["invalid_coordinates"] = [latitude, longitude]
        self.evidence[-1]["sequence_before"] = sequence
        self.evidence[-1]["expected_position"] = retained
        self.evidence[-1]["expected_lines"] = self.glyph_lines(*INITIAL)
        self.assertEqual(self.position(), retained,
                         "Impossible receiver coordinates replaced the last valid handset fix")
        for first, text in self.glyph_lines(*INITIAL):
            self.assertEqual(self.row(state, first), self.font.render(text, 126)[0])
        self.publish(2, *RECOVERY[:2])
        self.assert_fix(*RECOVERY, "valid-coordinate-recovery")
        self.keys("soft_right")
        self.expect(HOME_CAPTIONS, 113, 128)
        self.keys("convenience")
        self.assert_fix(*RECOVERY, "reopened-valid-recovery")
        self.keys("soft_right")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])
        self.snapshot("invalid-range-recovery-finished-home", state)

    def test_latitude_above_north_pole_is_rejected_and_valid_fix_recovers(self):
        self.invalid_then_recover(910000000, 450000000)

    def test_latitude_below_south_pole_is_rejected_and_valid_fix_recovers(self):
        self.invalid_then_recover(-910000000, -450000000)

    def test_longitude_above_east_dateline_is_rejected_and_valid_fix_recovers(self):
        self.invalid_then_recover(125000000, 1810000000)

    def test_longitude_below_west_dateline_is_rejected_and_valid_fix_recovers(self):
        self.invalid_then_recover(-125000000, -1810000000)

    def finish(self):
        try:
            state = self.handset.state()
            self.final_images = state["images"]
            self.final_state = state
            diagnostic = self.diagnostics()
            self.final_artifact = str(self.handset.save_artifacts(
                "final", state | {"receiver_diagnostics": diagnostic}))
            self.evidence.append({"label": "final", "artifact": self.final_artifact,
                                  **diagnostic})
        finally:
            thread = self.handset.thread
            self.handset.close()
            self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                                   for image, worker in self.workers.items()}
            self.http_server_thread_closed = thread is not None and not thread.is_alive()
            self.engine_request_method_unchanged = Engine.request is self.request_method
            self.assertTrue(all(self.worker_closure.values()))
            self.assertTrue(self.http_server_thread_closed)
            self.assertTrue(self.engine_request_method_unchanged)
