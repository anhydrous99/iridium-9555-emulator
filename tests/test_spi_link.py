import unittest

from iridium.board import SpiLink
from iridium.engine import EngineError


def serial(value=None, *, sequence=0, active=False, remaining=0,
           output=0x8000, direction=0x8010, reset_count=0):
    return {"value": value, "sequence": sequence, "active": active,
            "remaining": remaining,
            "gpio": {"output": output, "direction": direction, "reset_count": reset_count}}


class Bc5:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, op, **arguments):
        self.calls.append((op, arguments))
        if op == "serial":
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        if op == "pins":
            return {}
        raise AssertionError(op)


class Avr:
    def __init__(self, *replies, pins=(0, 0, 0)):
        self.replies = list(replies)
        self.pins = list(pins)
        self.calls = []
        self.state = {"steps": 0}

    def advance(self, steps=128):
        self.state["steps"] += steps

    def request(self, op, **arguments):
        self.calls.append((op, arguments))
        if op == "pin_state":
            return {"pins": self.pins}
        if op == "spi":
            response = self.replies.pop(0)
            if isinstance(response, Exception):
                raise response
            return {"value": response}
        if op == "warm_reset":
            self.pins = [0, 0, 0]
            self.state["steps"] = 0
            return {}
        raise AssertionError(op)


class SpiLinkTests(unittest.TestCase):
    def test_partial_avr_execution_preserves_the_inter_byte_service_phase(self):
        bc5 = Bc5(serial(0x11, sequence=1, active=True, remaining=2),
                  *(serial(sequence=1, active=True, remaining=2) for _ in range(3)),
                  serial(0x22, sequence=2, active=True, remaining=1), serial(sequence=3))
        avr = Avr(0xAA, 0xBB)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        for elapsed in (1, 30, 96):
            avr.advance(elapsed)
            link.exchange()
            self.assertEqual(link.transferred, 1)
            self.assertEqual(link.quantum, 128 - avr.state["steps"])
        avr.advance(1)
        link.exchange()
        self.assertEqual(link.transferred, 2)
        self.assertEqual(link.quantum, 128)
        avr.advance()
        link.exchange()
        self.assertFalse(link.pending)
        self.assertEqual([args for op, args in bc5.calls if op == "serial"],
                         [{}, {}, {}, {}, {"received": 0xAA, "sequence": 1},
                          {"received": 0xBB, "sequence": 2}])

    def test_cancelled_clocked_byte_keeps_its_service_time_before_replacement(self):
        bc5 = Bc5(serial(0x11, sequence=1, active=True), serial(sequence=2),
                  serial(0x22, sequence=2, active=True), serial(sequence=2, active=True))
        avr = Avr(0xAA, 0xBB)
        link = SpiLink(bc5, avr, "9575")
        link.exchange()
        avr.advance(40)
        link.exchange(acknowledge=False)
        self.assertFalse(link.pending)
        self.assertEqual(link.quantum, 88)
        link.exchange(acknowledge=False)
        self.assertEqual(link.transferred, 1)
        avr.advance(88)
        link.exchange()
        self.assertEqual(link.transferred, 2)
        self.assertEqual(link.stale, 1)
        self.assertEqual([args for op, args in bc5.calls if op == "serial"], [{}, {}, {}, {}])

    def test_reset_discards_the_old_service_phase_before_released_traffic(self):
        bc5 = Bc5(serial(0x11, sequence=1, active=True),
                  serial(0x22, sequence=2, active=True, output=0, reset_count=1),
                  serial(sequence=2, active=True, reset_count=1))
        avr = Avr(0xAA, 0xBB)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        avr.advance(3)
        link.exchange(acknowledge=False)
        self.assertTrue(link.hold_reset)
        self.assertEqual(link.quantum, 128)
        link.exchange(acknowledge=False)
        self.assertFalse(link.hold_reset)
        self.assertEqual(link.transferred, 2)
        self.assertEqual(avr.state["steps"], 0)

    def test_pre_service_sync_retains_reply_and_applies_reset_without_acknowledging(self):
        bc5 = Bc5(serial(0x11, sequence=1, active=True, remaining=2),
                  serial(sequence=1, active=True, remaining=2),
                  serial(0x22, sequence=2, active=True, remaining=1),
                  serial(sequence=3, output=0, reset_count=1))
        avr = Avr(0xAA, 0xBB)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        link.exchange(acknowledge=False)
        self.assertEqual(link.transferred, 1)
        self.assertEqual([args for op, args in bc5.calls if op == "serial"], [{}, {}])
        avr.advance()
        link.exchange()  # The scheduler has now executed the AVR.
        link.exchange(acknowledge=False)
        self.assertTrue(link.hold_reset)
        self.assertEqual(link.resets, 1)
        self.assertEqual([args for op, args in bc5.calls if op == "serial"],
                         [{}, {}, {"received": 0xAA, "sequence": 1}, {}])
        self.assertEqual(link.transferred, 2)

    def test_pre_service_replacement_waits_until_avr_consumes_the_old_clocked_byte(self):
        bc5 = Bc5(serial(0x11, sequence=1, active=True),
                  serial(0x22, sequence=2, active=True),
                  serial(sequence=2, active=True), serial(sequence=3))
        avr = Avr(0xAA, 0xBB)
        link = SpiLink(bc5, avr, "9575")
        link.exchange()
        link.exchange(acknowledge=False)
        self.assertEqual(link.transferred, 1)
        self.assertEqual(link.stale, 1)
        avr.advance()
        link.exchange()  # Consume the old byte before clocking its replacement.
        avr.advance()
        link.exchange()
        self.assertEqual(link.transferred, 2)
        self.assertFalse(link.pending)
        self.assertEqual([args for op, args in bc5.calls if op == "serial"],
                         [{}, {}, {}, {"received": 0xBB, "sequence": 2}])

    def test_reset_baseline_ignores_history_but_detects_held_lines_and_later_pulses(self):
        bc5 = Bc5(serial(reset_count=7), serial(reset_count=7, output=0),
                  serial(reset_count=7, output=0), serial(reset_count=7), serial(reset_count=8))
        avr = Avr()
        link = SpiLink(bc5, avr, "9555", reset_count=7)
        link.exchange()
        self.assertEqual(link.resets, 0)
        link.exchange()
        self.assertTrue(link.hold_reset)
        self.assertEqual(link.resets, 1)
        link.exchange()
        self.assertEqual(link.resets, 1)
        link.exchange()
        self.assertFalse(link.hold_reset)
        link.exchange()
        self.assertEqual(link.resets, 2)

    def test_bytes_and_replies_are_pipelined_across_separate_exchanges(self):
        bc5 = Bc5(serial(0x81, sequence=10, active=True, remaining=2),
                  serial(0x0B, sequence=11, active=True, remaining=1),
                  serial(sequence=12))
        avr = Avr(0x00, 0x80)
        link = SpiLink(bc5, avr, "9555")
        self.assertEqual(link.quantum, 4096)
        link.exchange()
        self.assertEqual([args for op, args in bc5.calls if op == "serial"], [{}])
        self.assertEqual([args for op, args in avr.calls if op == "spi"], [{"value": 0x81}])
        self.assertEqual(link.quantum, 128)
        # The scheduler executes the AVR ISR between these exchanges.
        avr.pins[1] = 1
        avr.advance()
        link.exchange()
        avr.advance()
        link.exchange()
        self.assertEqual([args for op, args in bc5.calls if op == "serial"],
                         [{}, {"received": 0, "sequence": 10}, {"received": 0x80, "sequence": 11}])
        self.assertEqual([args for op, args in avr.calls if op == "spi"],
                         [{"value": 0x81}, {"value": 0x0B}])
        self.assertEqual(link.state()["transferred"], 2)
        self.assertFalse(link.pending)
        self.assertEqual(link.quantum, 4096)

    def test_handshake_and_attention_follow_model_specific_pins(self):
        for model, pins in (("9555", [8, 1, 0]), ("9575", [0x80, 0, 4])):
            with self.subTest(model=model):
                bc5, avr = Bc5(serial(), serial()), Avr(pins=pins)
                link = SpiLink(bc5, avr, model)
                link.exchange()
                self.assertEqual(bc5.calls[-1], ("pins", {"mask": 0x5000, "value": 0x5000}))
                avr.pins = [0x77, 0xFE, 0xFB]
                link.exchange()
                self.assertEqual(bc5.calls[-1], ("pins", {"mask": 0x5000, "value": 0}))

    def test_reset_assertion_resets_once_and_byte_waits_until_release(self):
        bc5 = Bc5(serial(0x80, sequence=4, active=True, output=0, reset_count=1),
                  serial(sequence=4, active=True, output=0, reset_count=1),
                  serial(sequence=4, active=True, reset_count=1),
                  serial(sequence=5, reset_count=1))
        avr = Avr(0x23, pins=(8, 1, 0))
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        self.assertTrue(link.hold_reset)
        self.assertTrue(link.pending)
        self.assertEqual([op for op, _ in avr.calls].count("warm_reset"), 1)
        self.assertNotIn("spi", [op for op, _ in avr.calls])
        self.assertEqual(bc5.calls[-1], ("pins", {"mask": 0x5000, "value": 0}))
        link.exchange()
        self.assertEqual([op for op, _ in avr.calls].count("warm_reset"), 1)
        self.assertNotIn("spi", [op for op, _ in avr.calls])
        link.exchange()
        self.assertFalse(link.hold_reset)
        self.assertEqual([args for op, args in avr.calls if op == "spi"], [{"value": 0x80}])
        avr.advance()
        link.exchange()
        self.assertEqual(link.state()["reset_count"], 1)
        self.assertEqual(link.state()["resets"], 1)

    def test_reset_pulse_between_quanta_is_detected_from_counter(self):
        bc5, avr = Bc5(serial(reset_count=2)), Avr()
        link = SpiLink(bc5, avr, "9575")
        link.exchange()
        self.assertFalse(link.hold_reset)
        self.assertIn(("warm_reset", {}), avr.calls)
        self.assertEqual(link.state()["reset_count"], 2)

    def test_reset_pin_only_holds_avr_when_configured_as_output(self):
        bc5, avr = Bc5(serial(7, sequence=1, active=True, output=0, direction=0x10)), Avr(5)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        self.assertFalse(link.hold_reset)
        self.assertNotIn(("warm_reset", {}), avr.calls)
        self.assertIn(("spi", {"value": 7}), avr.calls)

    def test_queued_byte_waits_for_driven_low_chip_select(self):
        for model in ("9555", "9575"):
            for gpio in ({"output": 0x8010}, {"direction": 0x8000}):
                with self.subTest(model=model, gpio=gpio):
                    bc5 = Bc5(serial(0x22, sequence=4, active=True),
                              serial(sequence=4, active=True, **gpio),
                              serial(sequence=4, active=True), serial())
                    avr = Avr(None, 0x55)
                    link = SpiLink(bc5, avr, model)
                    link.exchange()  # The slave is not ready, so the byte remains queued.
                    link.exchange()  # Deselect it before the retry.
                    self.assertEqual([args for op, args in avr.calls if op == "spi"], [{"value": 0x22}])
                    self.assertTrue(link.pending)
                    link.exchange()  # Selecting it again permits exactly one transfer.
                    self.assertEqual(link.transferred, 1)
                    avr.advance()
                    link.exchange()
                    self.assertFalse(link.pending)
                    self.assertEqual(bc5.calls[-2], ("serial", {"received": 0x55, "sequence": 4}))

    def test_undriven_slave_retains_byte_without_fabricating_reply(self):
        bc5 = Bc5(serial(0x81, sequence=2, active=True),
                  serial(sequence=2, active=True), serial(sequence=3))
        avr = Avr(None, 0xFF)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        self.assertEqual(link.state()["undriven"], 1)
        self.assertEqual(link.state()["transferred"], 0)
        link.exchange()
        self.assertEqual([args for op, args in bc5.calls if op == "serial"], [{}, {}])
        avr.advance()
        link.exchange()
        self.assertEqual([args for op, args in bc5.calls if op == "serial"][-1],
                         {"received": 0xFF, "sequence": 2})
        self.assertEqual(link.state()["transferred"], 1)

    def test_replaced_unclocked_byte_is_discarded_by_sequence(self):
        bc5 = Bc5(serial(1, sequence=4, active=True), serial(2, sequence=5, active=True))
        avr = Avr(None, 9)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        link.exchange()
        self.assertEqual(link.state()["stale"], 1)
        self.assertEqual([args for op, args in avr.calls if op == "spi"],
                         [{"value": 1}, {"value": 2}])
        self.assertEqual([args for op, args in bc5.calls if op == "serial"], [{}, {}])

    def test_cancelled_unclocked_byte_is_never_sent_again(self):
        bc5 = Bc5(serial(1, sequence=4, active=True), serial(sequence=5), serial(sequence=5))
        avr = Avr(None)
        link = SpiLink(bc5, avr, "9555")
        for _ in range(3):
            link.exchange()
        self.assertEqual(link.state()["stale"], 1)
        self.assertFalse(link.pending)
        self.assertEqual([args for op, args in avr.calls if op == "spi"], [{"value": 1}])

    def test_reset_discards_old_reply_and_uses_native_sequence_to_reject_it(self):
        bc5 = Bc5(serial(1, sequence=4, active=True),
                  serial(sequence=5, output=0, reset_count=1))
        avr = Avr(8)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        avr.advance()
        link.exchange()
        self.assertEqual([args for op, args in bc5.calls if op == "serial"][-1],
                         {"received": 8, "sequence": 4})
        self.assertEqual(link.state()["stale"], 1)
        self.assertFalse(link.pending)
        self.assertTrue(link.hold_reset)

    def test_duplicate_outstanding_byte_is_a_latched_protocol_error(self):
        bc5 = Bc5(serial(1, sequence=4, active=True), serial(1, sequence=4, active=True))
        avr = Avr(None)
        link = SpiLink(bc5, avr, "9555")
        link.exchange()
        with self.assertRaisesRegex(EngineError, "reissued"):
            link.exchange()
        calls = len(bc5.calls)
        with self.assertRaisesRegex(EngineError, "reissued"):
            link.exchange()
        self.assertEqual(len(bc5.calls), calls)

    def test_native_failure_is_latched_before_replaying_any_byte(self):
        bc5, avr = Bc5(serial(1, sequence=4, active=True)), Avr(EngineError("SPI worker stopped"))
        link = SpiLink(bc5, avr, "9555")
        with self.assertRaisesRegex(EngineError, "worker stopped"):
            link.exchange()
        calls = len(avr.calls)
        with self.assertRaisesRegex(EngineError, "worker stopped"):
            link.exchange()
        self.assertEqual(len(avr.calls), calls)
        self.assertEqual(link.state()["transferred"], 0)

    def test_invalid_native_values_and_counter_regression_stop_link(self):
        bad = [serial(True, active=True), serial(sequence=-1), serial(1, active=False),
               serial(remaining=-1), serial(remaining=1), serial(reset_count=-1), {"value": None}]
        for response in bad:
            with self.subTest(response=response):
                link = SpiLink(Bc5(response), Avr(), "9555")
                with self.assertRaisesRegex(EngineError, "Invalid serial"):
                    link.exchange()
                self.assertIsNotNone(link.state()["error"])
        link = SpiLink(Bc5(serial(reset_count=1), serial(reset_count=0)), Avr(), "9555")
        link.exchange()
        with self.assertRaisesRegex(EngineError, "Invalid serial"):
            link.exchange()

    def test_invalid_avr_reply_is_not_acknowledged(self):
        bc5, avr = Bc5(serial(1, sequence=4, active=True)), Avr(256)
        link = SpiLink(bc5, avr, "9575")
        with self.assertRaisesRegex(EngineError, "Invalid AVR response"):
            link.exchange()
        self.assertEqual([args for op, args in bc5.calls if op == "serial"], [{}])

    def test_invalid_pin_snapshot_stops_before_clocking_byte(self):
        for snapshot in (None, {}, {"pins": [0, 0]}, {"pins": [0, 0, 256]}):
            with self.subTest(snapshot=snapshot):
                avr = Avr()
                request = avr.request
                avr.request = lambda op, **args: snapshot if op == "pin_state" else request(op, **args)
                link = SpiLink(Bc5(serial(1, sequence=1, active=True)), avr, "9555")
                with self.assertRaisesRegex(EngineError, "Invalid AVR pins"):
                    link.exchange()
                self.assertNotIn("spi", [op for op, _ in avr.calls])


if __name__ == "__main__":
    unittest.main()
