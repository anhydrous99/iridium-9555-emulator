import unittest

from iridium.satellite import Satellite


class SatelliteTests(unittest.TestCase):
    def test_registration_obeys_virtual_latency(self):
        satellite = Satellite(latency_ms=800)
        satellite.register()
        satellite.advance(799)
        self.assertFalse(satellite.registered)
        satellite.advance(1)
        self.assertTrue(satellite.registered)
        self.assertFalse(satellite.state()["firmware_connected"])

    def test_loss_of_coverage_cancels_registration_and_active_call(self):
        satellite = Satellite(latency_ms=0)
        satellite.register()
        satellite.incoming_call("+881612345678")
        satellite.answer()
        self.assertEqual(satellite.call_state, "active")
        satellite.configure(signal=0)
        self.assertFalse(satellite.registered)
        self.assertEqual(satellite.call_state, "idle")
        satellite.configure(signal=5)
        self.assertFalse(satellite.registered)
        satellite.register()
        satellite.incoming_sms("123", "Test")
        self.assertEqual(satellite.messages[0]["text"], "Test")

    def test_registration_lost_before_deadline_does_not_complete(self):
        satellite = Satellite()
        satellite.register()
        satellite.configure(visible=False)
        satellite.advance(1000)
        self.assertFalse(satellite.registered)

    def test_illegal_call_transitions_rejected(self):
        satellite = Satellite()
        with self.assertRaises(ValueError):
            satellite.incoming_call("123")
        satellite.configure(latency_ms=0)
        satellite.register()
        with self.assertRaises(ValueError):
            satellite.answer()
        satellite.incoming_call("123")
        with self.assertRaises(ValueError):
            satellite.incoming_call("456")
        satellite.hangup()
        self.assertEqual(satellite.number, "")

    def test_validation_is_atomic_and_messages_bounded(self):
        satellite = Satellite(latency_ms=0)
        with self.assertRaises(ValueError):
            satellite.configure(visible=False, signal=6)
        self.assertTrue(satellite.visible)
        for arguments in ({"signal": True}, {"latency_ms": -1}, {"visible": "yes"}):
            with self.assertRaises(ValueError):
                satellite.configure(**arguments)
        satellite.register()
        for number in ("+", "12+3", "++123"):
            with self.assertRaises(ValueError):
                satellite.incoming_call(number)
        for n in range(101):
            satellite.incoming_sms("123", str(n))
        self.assertEqual(len(satellite.messages), 100)
        self.assertEqual(satellite.messages[0]["text"], "1")


if __name__ == "__main__":
    unittest.main()
