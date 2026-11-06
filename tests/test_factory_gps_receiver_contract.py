"""Factory HL25003 AVR UART0 receiver → packed SPI contract.

These are original-firmware peripheral contract tests. They do not establish
that the BC5 Current Location screen displays a receiver fix.
"""

import os
from pathlib import Path
import tempfile
import unittest

from factory_handset import EXECUTABLE, factory_firmware
from gps_receiver_frames import (CONFIGURATION_ACK, ERROR_ESTIMATES, PACKED_POSITION,
                                 POSITION, SOLUTION, UTC, VELOCITY, ubx)
from iridium.engine import Engine


FIRMWARE_DIRECTORY = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


@unittest.skipUnless(FIRMWARE_DIRECTORY, "Set IRIDIUM_TEST_9575_FIRMWARE for factory AVR GPS contracts")
class Factory9575GPSReceiverContractTests(unittest.TestCase):
    def setUp(self):
        firmware = next(image for image in factory_firmware("9575", FIRMWARE_DIRECTORY)
                        if image.image == "avr")
        temporary = tempfile.TemporaryDirectory(prefix="iridium-gps-contract-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "avr.bin"
        path.write_bytes(firmware.data)
        self.engine = Engine(EXECUTABLE, "avr", path, model="9575")
        self.addCleanup(self.engine.close)
        self.run_firmware(1000000)
        # Actual SPI command0/register19/argument0 starts the receiver.
        self.assertEqual(self.spi(bytes.fromhex("80 00 4f 00 00 00 00"))[4:], b"\x80\x00\x00")
        self.assertTrue(self.engine.request("pin_state")["pins"][8] & 0x80,
                        "Original GPS start must raise physical PJ7")

    def run_firmware(self, steps):
        state = self.engine.request("run", steps=steps)
        self.assertIsNone(state["halt"])
        self.assertIsNone(state["model_error"])
        self.assertEqual(state["uart_tx_dropped"], [0, 0, 0, 0])
        return state

    def spi(self, data):
        reply = bytearray()
        for value in data:
            reply.append(self.engine.request("spi", value=value)["value"])
            self.run_firmware(1000)
        return bytes(reply)

    def published_position(self):
        length = 14
        reply = self.spi(bytes((0x81, length, (20 << 2) | 1, 0, 0, 0, 0)) +
                         bytes(length + 4))
        self.assertEqual(reply[4:7], b"\x80\x00\xfe")
        return reply[7:7 + length]

    def receive(self, frame, steps=200000):
        response = self.engine.request("uart_io", port=0, rx=list(frame), tx_limit=0)
        self.assertEqual(response["accepted"], len(frame))
        self.assertEqual(response["dropped"], 0)
        self.run_firmware(steps)

    def acknowledge_receiver_configuration(self):
        # ACK only actual, checksum-correct CFG-MSG requests from the original
        # AVR. These are receiver acknowledgements, not handset success replies.
        for count in range(32):
            response = self.engine.request("uart_io", port=0, tx_limit=255)
            self.assertEqual(response["dropped"], 0)
            request = bytes(response["values"])
            if not request:
                self.assertEqual(count, 21)
                return
            self.assertEqual(request[:6], b"\xb5\x62\x06\x01\x03\x00")
            self.assertEqual(len(request), 11)
            self.assertEqual(request, ubx(6, 1, request[6:9]))
            self.receive(CONFIGURATION_ACK, steps=30000)
        self.fail("Original receiver configuration did not complete in 32 requests")

    def stop_receiver(self):
        self.assertEqual(self.spi(bytes.fromhex("80 01 4f 00 00 00 00"))[4:], b"\x80\x00\x00")
        self.assertFalse(self.engine.request("pin_state")["pins"][8] & 0x80)
        self.assertIsNone(self.engine.state["last_call"])

    def test_bad_ubx_position_checksum_cannot_publish_a_fix(self):
        corrupt = bytearray(POSITION)
        corrupt[-1] ^= 1
        self.receive(corrupt)
        self.assertEqual(self.engine.request("uart_io", port=0)["values"], [])

        self.receive(SOLUTION)
        self.acknowledge_receiver_configuration()
        for frame in (UTC, VELOCITY, ERROR_ESTIMATES):
            self.receive(frame)
        # Every other epoch component is present. A corrupt position must still
        # leave the published buffer empty; a valid position is the control.
        self.assertEqual(self.published_position(), bytes(14))
        self.receive(POSITION)
        self.assertEqual(self.published_position(), PACKED_POSITION)
        self.stop_receiver()

    def test_incomplete_epoch_and_bad_nmea_checksum_do_not_publish(self):
        self.receive(POSITION)
        self.acknowledge_receiver_configuration()
        for frame in (SOLUTION, UTC, VELOCITY):
            self.receive(frame)
        self.assertEqual(self.published_position(), bytes(14))

        corrupt = ERROR_ESTIMATES.replace(b"*53", b"*52")
        self.receive(corrupt)
        self.assertEqual(self.published_position(), bytes(14))
        self.receive(ERROR_ESTIMATES[:-2])
        self.assertEqual(self.published_position(), bytes(14))
        self.receive(ERROR_ESTIMATES[-2:])
        self.assertEqual(self.published_position(), PACKED_POSITION)
        self.stop_receiver()


if __name__ == "__main__":
    unittest.main()
