"""External UBX/NMEA receiver stimulus, not handset firmware or GPS state.

Receiver publication fixture: 37.7749 N, 122.4194 W, 30 m, eight satellites,
2026-11-04 12:00:00 UTC, iTOW 123000 ms and zero velocity.
"""

import struct


def ubx(message_class, message_id, payload):
    body = bytes((message_class, message_id)) + len(payload).to_bytes(2, "little") + payload
    checksum_a = checksum_b = 0
    for value in body:
        checksum_a = (checksum_a + value) & 255
        checksum_b = (checksum_b + checksum_a) & 255
    return b"\xb5\x62" + body + bytes((checksum_a, checksum_b))


POSITION = ubx(1, 2, struct.pack("<IiiiiII", 123000, -1224194000, 377749000,
                               32000, 30000, 1000, 1000))
SOLUTION = ubx(1, 6, struct.pack("<IihBBiiiIiiiIHBBI", 123000, 0, 2200, 3, 1,
                               0, 0, 0, 1000, 0, 0, 0, 100, 100, 0, 8, 0))
UTC = ubx(1, 0x21, struct.pack("<IIiHBBBBBB", 123000, 1000, 0, 2026, 11, 4, 12, 0, 0, 7))
VELOCITY = ubx(1, 0x12, struct.pack("<IiiiIIiII", 123000, 0, 0, 0, 0, 0, 0, 100, 100))
ERROR_ESTIMATES = b"$GPGST,120000.00,1.2,1.0,1.0,0.0,1.0,1.0,1.5*53\r\n"
CONFIGURATION_ACK = ubx(5, 1, b"\x06\x01")

# Original HL25003 AVR SPI register20: sequence, flags, latitude D/M/fraction,
# longitude D/M/fraction, altitude, satellite count. Fractions are big endian.
PACKED_POSITION = bytes.fromhex("00 b0 25 2e 01 ee 7a 19 00 a4 00 00 1e 08")


class GPSReceiverFixture:
    """External receiver wire peer for a paused HTTP FactoryHandset."""

    def __init__(self, handset):
        self.handset = handset
        self.test = handset.test

    def uart(self, **arguments):
        return self.handset.request("POST", "/api/probe", {
            "image": "avr", "operation": "uart_io", "port": 0, **arguments,
        })

    def receive(self, frame):
        remaining = frame
        for _ in range(20):
            response = self.uart(rx=list(remaining), tx_limit=0)
            accepted = response["accepted"]
            self.test.assertGreaterEqual(accepted, 0)
            self.test.assertLessEqual(accepted, len(remaining))
            self.test.assertEqual(response["dropped"], 0)
            # Only the accepted prefix belongs to uart_io; never replay it.
            remaining = remaining[accepted:]
            self.handset.step(200000)
            if not remaining:
                return
        self.test.fail("Receiver UART input backlog did not clear within the execution budget")

    def configuration_request(self, *, required=True):
        request = bytearray()
        # A real serial frame can straddle host execution boundaries.
        for _ in range(10):
            response = self.uart(tx_limit=255)
            self.test.assertEqual(response["dropped"], 0)
            request.extend(response["values"])
            if len(request) >= 11:
                break
            self.handset.step(200000)
        if not request and not required:
            return None
        self.test.assertEqual(request[:6], b"\xb5\x62\x06\x01\x03\x00")
        self.test.assertEqual(len(request), 11)
        self.test.assertEqual(request, ubx(6, 1, request[6:9]))
        return request

    def publish_fix(self):
        self.receive(POSITION)
        for _ in range(20):
            # ACK only actual, checksum-verified original CFG-MSG requests.
            self.configuration_request()
            self.receive(CONFIGURATION_ACK)
        for frame in (POSITION, SOLUTION, UTC, VELOCITY, ERROR_ESTIMATES):
            self.receive(frame)
        request = self.configuration_request(required=False)
        if request is not None:
            self.test.assertEqual(request, ubx(6, 1, b"\x0b\x32\x00"))
            self.receive(CONFIGURATION_ACK)
