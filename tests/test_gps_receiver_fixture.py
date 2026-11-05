"""Firmware-free checks that the external GPS peer preserves real wire framing."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from gps_receiver_frames import GPSReceiverFixture, ubx


class GPSReceiverFixtureTests(unittest.TestCase):
    def handset(self, replies):
        return SimpleNamespace(test=self, request=Mock(side_effect=replies), step=Mock())

    def test_rx_backpressure_retries_only_the_unaccepted_suffix(self):
        handset = self.handset([{"accepted": n, "dropped": 0} for n in (2, 0, 3)])
        GPSReceiverFixture(handset).receive(b"abcde")
        sent = [bytes(request.args[2]["rx"]) for request in handset.request.call_args_list]
        self.assertEqual(sent, [b"abcde", b"cde", b"cde"])
        self.assertEqual(handset.step.call_count, 3)

    def test_optional_configuration_waits_for_delayed_fragmented_frame(self):
        frame = ubx(6, 1, b"\x01\x06\x00")
        handset = self.handset([{"values": list(part), "dropped": 0}
                                for part in (b"", frame[:5], frame[5:])])
        self.assertEqual(GPSReceiverFixture(handset).configuration_request(required=False), frame)
        self.assertEqual(handset.step.call_count, 2)

    def test_optional_absence_is_bounded_but_partial_frame_is_an_error(self):
        for first in (b"", b"\xb5\x62\x06"):
            with self.subTest(first=first):
                handset = self.handset([{"values": list(first), "dropped": 0}] +
                                        [{"values": [], "dropped": 0}] * 9)
                peer = GPSReceiverFixture(handset)
                if first:
                    with self.assertRaises(AssertionError):
                        peer.configuration_request(required=False)
                else:
                    self.assertIsNone(peer.configuration_request(required=False))
                self.assertEqual(handset.request.call_count, 10)
                self.assertEqual(handset.step.call_count, 10)

    def test_invalid_configuration_checksum_is_rejected_before_acknowledgement(self):
        frame = bytearray(ubx(6, 1, b"\x01\x06\x00"))
        frame[-1] ^= 1
        handset = self.handset([{"values": list(frame), "dropped": 0}])
        with self.assertRaises(AssertionError):
            GPSReceiverFixture(handset).configuration_request()
        handset.step.assert_not_called()


if __name__ == "__main__":
    unittest.main()
