from pathlib import Path
import threading
import unittest

from iridium.engine import EngineError
from iridium.firmware import parse_firmware
from iridium.session import Session


class FakeEngine:
    def __init__(self, executable, image, firmware):
        self.data = firmware.read_bytes()
        self.state = {"image": image, "pc": 0, "steps": 0, "halt": "ready", "registers": []}
        self.closed = False
        self.calls = []

    def request(self, op, **arguments):
        self.calls.append((op, arguments))
        if op == "run":
            self.state["steps"] += arguments["steps"]
        elif op == "reset":
            self.state["steps"] = 0
            self.state["halt"] = "ready"
        return dict(self.state)

    def close(self):
        self.closed = True


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.firmware = parse_firmware(bytes(8678), "avr.bin")
        self.session = Session(Path("unused"), [self.firmware], FakeEngine)
        self.addCleanup(self.session.close)

    def test_patch_replacement_is_executed_and_closes_old_worker(self):
        old = self.session.engines["avr"]
        patch = parse_firmware(b"\1\2" + bytes(8676), "avr.bin")
        self.session.load(patch)
        self.assertTrue(old.closed)
        self.assertEqual(self.session.engines["avr"].data, patch.data)
        self.assertEqual(self.session.state()["firmware"]["sha256"], patch.sha256)

    def test_step_and_reset_preserve_truthful_fidelity(self):
        self.session.control("step", 100)
        self.assertEqual(self.session.state()["processors"][0]["steps"], 100)
        self.assertFalse(self.session.state()["fidelity"]["complete"])
        self.session.control("reset")
        self.assertEqual(self.session.state()["processors"][0]["steps"], 0)

    def test_halted_firmware_not_silently_resumed(self):
        self.session.engines["avr"].state["halt"] = "illegal"
        self.session.control("step", 100)
        self.assertEqual(self.session.engines["avr"].state["steps"], 0)

    def test_keys_record_transitions_without_claiming_delivery(self):
        self.assertFalse(self.session.key("1", True)["delivered"])
        self.assertEqual(self.session.state()["keys"], ["1"])
        self.assertFalse(self.session.key("1", True)["delivered"])
        self.session.key("1", False)
        self.assertEqual(self.session.state()["keys"], [])

    def test_debug_mutation_requires_paused_cpu(self):
        self.session.control("run")
        with self.assertRaises(ValueError):
            self.session.probe("avr", "write", {"address": 0x100, "values": [1]})
        self.session.control("pause")
        self.session.probe("avr", "write", {"address": 0x100, "values": [1]})

    def test_unsupported_lcd_command_is_reported_without_inventing_cpu_fault(self):
        engine = self.session.engines["avr"]
        engine.state.update(image="bc5", lcd_bytes=[0xFF], lcd_dropped=0)
        self.session.running = True
        self.session._request(engine, "state")
        lcd = self.session.state()["lcd"]
        self.assertIn("Unsupported", lcd["error"])
        self.assertEqual(engine.state["halt"], "ready")
        self.assertFalse(self.session.running)
        self.session.control("reset")
        self.assertIsNone(self.session.state()["lcd"])

    def test_experimental_initialization_requires_bc5(self):
        with self.assertRaisesRegex(ValueError, "Load BC5"):
            self.session.control("initialize_ui")
        self.assertFalse(self.session.state()["ui_initialized"])

    def test_failed_reset_invalidates_prior_display_and_input_claims(self):
        self.session.ui_initialized = True
        self.session.lcd_seen = True
        self.session.keys.add("1")

        def failed_reset(op, **arguments):
            raise EngineError("worker disconnected during reset")

        self.session.engines["avr"].request = failed_reset
        with self.assertRaises(EngineError):
            self.session.control("reset")
        state = self.session.state()
        self.assertFalse(state["ui_initialized"])
        self.assertEqual(state["keys"], [])
        self.assertIsNone(state["lcd"])

    def test_rejects_noninteger_and_out_of_range_budgets(self):
        for steps in (0, -1, True, 1.5, 10000001):
            with self.assertRaises(ValueError):
                self.session.control("step", steps)

    def test_shutdown_waits_for_active_api_step_and_rejects_later_actions(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        errors = []
        engine = self.session.engines["avr"]
        original = engine.request

        def delayed_request(op, **arguments):
            entered.set()
            release.wait(2)
            if engine.closed:
                errors.append("worker closed during its request")
            return original(op, **arguments)

        def step():
            try:
                self.session.control("step", 1)
            except BaseException as error:
                errors.append(error)

        def close():
            self.session.close()
            closed.set()

        engine.request = delayed_request
        active = threading.Thread(target=step)
        cleanup = threading.Thread(target=close)
        active.start()
        self.assertTrue(entered.wait(1))
        cleanup.start()
        self.assertFalse(closed.wait(0.05))
        release.set()
        active.join(2)
        cleanup.join(2)
        self.assertTrue(closed.is_set())
        self.assertEqual(errors, [])
        self.assertTrue(engine.closed)
        with self.assertRaises(EngineError):
            self.session.control("run")


if __name__ == "__main__":
    unittest.main()
