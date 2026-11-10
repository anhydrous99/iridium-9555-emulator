from datetime import datetime, timezone
import unittest

from iridium.fixtures import GPSPeer, SIMPeer, SyntheticSIM, ubx
from iridium.engine import EngineError


class UART:
    def __init__(self):
        self.state = {"steps": 0}
        self.tx = bytearray()
        self.rx = bytearray()
        self.accept = 255
        self.gps_power = True

    def request(self, operation, **arguments):
        if operation == "pin_state":
            return {"pins": [0] * 8 + [128 if self.gps_power else 0]}
        if operation == "uart_pins":
            return {"inputs": 1, "outputs": 0x34}
        offered = bytes(arguments.get("rx", []))
        accepted = min(self.accept, len(offered))
        self.rx.extend(offered[:accepted])
        tx = list(self.tx)
        self.tx.clear()
        return {"values": tx, "accepted": accepted, "dropped": 0}


class FixtureTests(unittest.TestCase):
    def test_card_supports_both_phonebook_and_message_writes_without_changing_read_protocol(self):
        card = SyntheticSIM()
        card.controls(1, 0x34)
        card.accepted(len(card.pending))
        for file_id, record, body in ((0x6F3A, 2, b"A" * 32),
                                     (0x6F3C, 1, b"B" * 176),
                                     (0x6F42, 1, b"C" * 32)):
            card.selected = file_id
            card.feed(bytes((0xA0, 0xDC, record, 4, len(body))))
            self.assertEqual(card.pending, b"\xDC")
            card.accepted(1)
            card.feed(body)
            self.assertEqual(card.pending, b"\x90\x00")
            self.assertEqual(card.records[file_id][record - 1], body)
            card.accepted(2)
        card.controls(0, 0)
        self.assertEqual(card.records[0x6F3A][1], b"A" * 32)

    def test_sim_peer_keeps_unaccepted_bytes(self):
        uart, card = UART(), SyntheticSIM()
        uart.accept = 1
        peer = SIMPeer(uart, card)
        peer.exchange()
        self.assertEqual(uart.rx, b"\x3B")
        self.assertEqual(card.pending, b"\x00")
        peer.exchange()
        self.assertEqual(uart.rx, b"\x3B\x00")

    def test_gps_requires_valid_complete_commands_and_acknowledges_real_configuration(self):
        uart = UART()
        gps = GPSPeer(uart, 37.7749, -122.4194, 30,
                      utc=datetime(2026, 11, 4, 12, tzinfo=timezone.utc))
        self.assertTrue(gps.position.startswith(b"\xb5\x62\x01\x02"))
        command = ubx(6, 1, b"\x01\x02\x01")
        uart.tx.extend(command[:-1])
        gps.exchange()
        self.assertEqual(gps.configurations, 0)
        uart.tx.extend(command[-1:])
        gps.exchange()
        self.assertEqual(gps.configurations, 1)
        self.assertEqual(gps.pending, ubx(5, 1, b"\x06\x01"))
        uart.tx.extend(command[:-1] + bytes((command[-1] ^ 1,)))
        gps.exchange()
        self.assertEqual(gps.configurations, 1)
        self.assertFalse(gps.pending)

    def test_gps_partial_delivery_and_reset_never_replay_the_accepted_prefix(self):
        uart = UART()
        uart.accept = 3
        gps = GPSPeer(uart, 0, 0, 0)
        for _ in range(20):
            gps.exchange()
        self.assertEqual(uart.rx, gps.position)
        gps.exchange(avr_reset=True)
        self.assertEqual(gps.pending, gps.position)
        self.assertEqual(gps.configurations, 0)

    def test_gps_rejects_nonfinite_or_out_of_range_coordinates(self):
        for latitude, longitude, altitude in ((float("nan"), 0, 0), (91, 0, 0),
                                              (0, -181, 0), (0, 0, float("inf")),
                                              (True, 0, 0), (10**1000, 0, 0)):
            with self.assertRaises(ValueError):
                GPSPeer(UART(), latitude, longitude, altitude)

    def test_gps_power_off_discards_old_configuration_and_never_injects_bytes(self):
        uart = UART()
        gps = GPSPeer(uart, 0, 0, 0)
        gps.exchange()
        gps.configurations = 20
        gps.pending.extend(b"old acknowledgement")
        uart.gps_power = False
        uart.tx.extend(ubx(6, 1, b"\x01\x02\x01"))
        before = bytes(uart.rx)
        gps.exchange()
        self.assertEqual(uart.rx, before)
        self.assertEqual(gps.configurations, 0)
        self.assertFalse(gps.powered)
        self.assertFalse(uart.tx)
        uart.gps_power = True
        gps.exchange()
        self.assertEqual(uart.rx[len(before):], gps.position)
        self.assertEqual(gps.configurations, 0)
        self.assertTrue(gps.powered)


if __name__ == "__main__":
    unittest.main()
