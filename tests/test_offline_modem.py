"""Finite training-peer framing and service contracts, no proprietary firmware."""
import unittest

from iridium.engine import EngineError
from iridium.offline_modem import OfflineModem
from iridium.satellite import Satellite


class AVR:
    def __init__(self):
        self.state = {"steps": 0}
        self.tx, self.rx = bytearray(), bytearray()
        self.accept = 255
        self.pins = [0, 0, 0, 0]
        self.rises = 0
        self.dropped = 0

    def request(self, command, **kwargs):
        if command == "pin_state":
            return {"pins": self.pins, "modem_power_rises": self.rises}
        if command != "uart_io":
            raise AssertionError("The peer must use only pins and UART")
        offered = kwargs.get("rx", [])
        accepted = min(len(offered), self.accept)
        self.rx.extend(offered[:accepted])
        limit = kwargs.get("tx_limit", 255)
        result = list(self.tx[:limit]); del self.tx[:limit]
        return {"accepted": accepted, "values": result, "dropped": self.dropped}


class OfflineModemTests(unittest.TestCase):
    def setUp(self):
        self.avr, self.satellite = AVR(), Satellite()
        self.modem = OfflineModem(self.avr, self.satellite)
        self.modem._frames.clear()
        self.modem._scenario = (0, 5, "idle", "")

    def texts(self):
        frames = list(self.modem._frames)
        self.modem._frames.clear()
        return b"".join(frame[6:-2] for frame in frames if frame[2] & 127 != 7 or frame[4] == 6).decode("ascii")

    def command(self, command, flag=1):
        text = command.encode("ascii")
        self.modem._receive(OfflineModem.frame(bytes((flag, 3, 0, len(text))) + text))
        return self.texts()

    def test_bootstrap_matches_observed_original_envelope(self):
        self.modem._bootstrap()
        self.assertEqual(self.modem._frames[0], bytes.fromhex("04 04 00 03 00 00 03 03"))

    def test_partial_uart_acceptance_preserves_suffix_and_waits_for_ack(self):
        self.modem._packet("\r\nOK\r\n", 2)
        expected = self.modem._frames[0]
        self.modem._packet("next", 4)
        self.avr.accept = 2
        for _ in range(len(expected)):
            self.modem.exchange()
        self.assertEqual(bytes(self.avr.rx), expected)
        self.assertEqual(len(self.modem._frames), 1)
        self.avr.tx.append(6)
        self.modem.exchange()
        self.assertEqual(bytes(self.avr.rx), expected + self.modem._awaiting[:2])

    def test_bad_checksum_is_naked_and_duplicate_request_is_not_executed(self):
        payload = bytes((1, 3, 0, 3)) + b"AT\r"
        frame = OfflineModem.frame(payload)
        corrupt = frame[:-2] + bytes((frame[-2] ^ 1, 3))
        self.modem._receive(corrupt)
        self.assertEqual(self.modem._controls, b"\x15")
        self.assertEqual(list(self.modem.commands), [])
        self.modem._receive(frame[:4]); self.modem._receive(frame[4:])
        self.modem._receive(frame)
        self.assertEqual(list(self.modem.commands), ["AT"])
        self.assertEqual(self.modem._controls, b"\x15\x06\x06")
        self.assertEqual(self.texts(), "\r\nOK\r\n")

    def test_unsupported_command_reports_error(self):
        self.assertEqual(self.command("AT+NOTREAL\r"), "\r\nERROR\r\n")
        self.assertEqual(list(self.modem.unsupported), ["AT+NOTREAL"])

    def test_unregistered_call_finishes_with_no_carrier(self):
        self.assertIn("\r\nNO CARRIER\r\n", self.command("ATD+123;\r"))
        self.assertEqual(self.satellite.call_state, "idle")

    def test_registered_call_and_end_update_scenario(self):
        self.satellite.register(); self.satellite.advance(1000)
        self.modem.notify_scenario(); self.texts()
        self.assertIn("OK", self.command("ATD+123;\r"))
        self.assertEqual(self.satellite.call_state, "active")
        self.assertEqual(self.satellite.number, "+123")
        busy = self.command("ATD+456;\r", 129)
        self.assertIn("BUSY", busy)
        self.assertNotIn("+XCSI", busy)
        self.assertEqual(self.satellite.number, "+123")
        self.assertIn("OK", self.command("ATH\r"))
        self.assertEqual(self.satellite.call_state, "idle")

    def test_call_reports_bind_dialing_and_stage_incoming_caller_id(self):
        self.satellite.register(); self.satellite.advance(1000)
        self.modem.notify_scenario(); self.texts()
        output = self.command("ATD+123456789;\r")
        dialing = "+XCSI=16,1,0,0,255,0,1"
        active = "+XCSI=1,4,0,0,255,0,1"
        self.assertLess(output.index(dialing), output.index(active))
        self.command("ATH\r", 129)
        self.satellite.incoming_call("+123")
        self.modem.notify_scenario()
        # Ringing remains AT-ready so the physical Green key can issue ATA.
        self.assertTrue(all(frame[4] == 1 for frame in self.modem._frames))
        output = self.texts()
        ringing = "+XCSI=3,2,0,255,255,0,1"
        self.assertEqual(output.count(ringing), 2)
        self.assertLess(output.index(ringing), output.index("+CLIP:"))
        self.assertLess(output.index("+CLIP:"), output.rindex(ringing))
        self.command("AT+CHLD=0\r")
        self.assertEqual(self.satellite.call_state, "idle")

    def test_incoming_sms_is_available_to_original_cmgl_cmgr_and_delete(self):
        self.command("AT+CNMI=2,1,0,0,0\r")
        index = self.modem.incoming_sms("+123", "Hello")
        self.assertEqual(self.texts(), '\r\n+CMTI:"SM",001\r\n')
        pdu = self.modem.messages[index][1]
        self.assertEqual(pdu[-5:], bytes.fromhex("C8329BFD06"))
        self.assertIn(pdu.hex().upper(), self.command("AT+CMGL=4\r", 129))
        self.assertIn("+CMGR:000", self.command("AT+CMGR=1\r"))
        self.assertEqual(self.modem.messages[index][0], 1)
        self.assertIn("OK", self.command("AT+CMGD=1\r", 129))
        self.assertEqual(self.modem.messages, {})

    def test_data_entry_keeps_split_sms_until_control_z_and_validates_length(self):
        pdu = self.modem.sms_pdu("+123", "Hello")
        n = self.modem._pdu_length(pdu)
        self.assertIn("> ", self.command(f"AT+CMGW={n},2\r"))
        self.modem._body(pdu.hex().encode()[:10])
        self.assertEqual(self.modem.messages, {})
        self.modem._body(pdu.hex().encode()[10:] + b"\x1a")
        self.assertIn("+CMGW:001", self.texts())
        self.assertEqual(self.modem.messages[1], (2, pdu))
        self.command("AT+CMGW=999\r", 129)
        self.modem._body(pdu.hex().encode() + b"\x1a")
        self.assertIn("+CMS ERROR:304", self.texts())
        self.assertEqual(len(self.modem.messages), 1)

    def test_power_cycle_discards_partial_transport_but_retains_training_sms(self):
        modem = OfflineModem(self.avr, self.satellite, power_pin=(1, 2))
        modem.incoming_sms("123", "Retained")
        self.avr.pins[1] = 4; self.avr.rises = 1
        modem.exchange()
        self.assertTrue(modem.powered)
        self.satellite.call_state = "active"
        self.avr.pins[1] = 0; modem.exchange()
        self.assertEqual(self.satellite.call_state, "idle")
        self.avr.pins[1] = 4; self.avr.rises = 2; modem.exchange()
        self.assertEqual(modem.power_resets, 2)
        self.assertEqual(len(modem.messages), 1)
        self.assertEqual(modem._awaiting, bytes.fromhex("04 04 00 03 00 00 03 03"))

    def test_uart_overflow_is_explicit_and_sticky(self):
        self.avr.dropped = 1
        with self.assertRaisesRegex(EngineError, "overflow"):
            self.modem.exchange()
        self.avr.dropped = 0
        with self.assertRaisesRegex(EngineError, "overflow"):
            self.modem.exchange()

    def test_storage_is_shared_across_restart_and_absent_sim_rejects_access(self):
        storage = {}
        self.modem = OfflineModem(self.avr, self.satellite, storage=storage)
        self.modem._frames.clear()
        self.modem._scenario = (0, 5, "idle", "")
        self.assertIn("OK", self.command('AT+CPBW=101,"+123",145,"Adg"\r'))
        self.assertIn("OK", self.command('AT+CSCA="+456",145\r', 129))
        self.modem.incoming_sms("+123", "Retained")
        self.modem = OfflineModem(self.avr, self.satellite, storage=storage)
        self.modem._frames.clear()
        self.modem._scenario = (0, 5, "idle", "")
        self.assertIn('"Adg"', self.command("AT+CPBR=101\r"))
        self.assertIn('"+456"', self.command("AT+CSCA?\r", 129))
        self.assertEqual(len(self.modem.messages), 1)
        self.modem.sim_present = False
        self.assertIn("+CME ERROR:010", self.command("AT+CPIN?\r"))
        self.assertIn("+CMS ERROR:310", self.command("AT+CMGL=4\r", 129))
        with self.assertRaisesRegex(ValueError, "SIM"):
            self.modem.incoming_sms("123", "Absent")

    def test_network_time_is_explicit_and_deterministic_after_registration(self):
        self.assertIn("no network service", self.command("AT-MSSTM\r"))
        self.satellite.register(); self.satellite.advance(1000)
        expected = self.modem._network_counter()
        self.assertIn(f"-MSSTM: {expected:x}", self.command("AT-MSSTM\r", 129))
        self.satellite.advance(900)
        self.assertEqual(self.modem._network_counter(), expected + 10)
        clock = self.modem.state()["network_time"]
        self.assertTrue(clock["simulation"])
        self.assertEqual(clock["origin_utc"], "2026-11-09T00:00:00+00:00")
        self.satellite.advance(10 ** 30)
        clock = self.modem.state()["network_time"]
        self.assertLess(clock["counter"], 2 ** 32)
        self.assertIn("T", clock["utc"])

    def test_unicode_sms_length_is_in_utf16_units(self):
        self.assertTrue(self.modem.sms_pdu("123", "漢" * 70))
        with self.assertRaises(ValueError):
            self.modem.sms_pdu("123", "漢" * 71)
        with self.assertRaises(ValueError):
            self.modem.sms_pdu("123", "🙂" * 36)


if __name__ == "__main__":
    unittest.main()
