from dataclasses import replace
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from iridium.engine import EngineError
from iridium.firmware import parse_firmware
from iridium.session import Session


class FakeEngine:
    def __init__(self, executable, image, firmware, *, model="9555"):
        self.data = firmware.read_bytes()
        self.state = {"image": image, "handset": model, "pc": 0, "steps": 0, "halt": "ready", "registers": []}
        if image == "bc5":
            self.state["gpio"] = {"reset_count": 0}
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

    def initialize_key_handler(self):
        self.session.load(replace(self.firmware, image="bc5", name="bc5_main.bin"))
        worker = self.session.engines["bc5"]
        worker.request = Mock(return_value={"values": [1, 2], "gpio": {"reset_count": 0}})
        self.session._idle = Mock()
        self.session._call = Mock(return_value={})
        self.session.ui_initialized = True
        return worker

    def browser_key(self, client, sequence, pressed, key="1", epoch=None):
        return self.session.key(key, pressed, client_id=client, sequence=sequence,
                                epoch=self.session.key_epoch if epoch is None else epoch)

    def test_runner_pacing_accounts_for_work_and_still_yields_when_behind(self):
        self.session.running = True
        with patch.object(self.session._stop, 'wait', side_effect=[False, False, True]) as wait, \
                patch.object(self.session, '_step') as step, \
                patch('iridium.session.time.monotonic', side_effect=[0, .005, 1, 1.05]):
            self.session._loop()
        self.assertEqual([call.args for call in step.call_args_list], [(200000,), (200000,)])
        delays = [call.args[0] for call in wait.call_args_list]
        for actual, expected in zip(delays, [.02, .015, .001]):
            self.assertAlmostEqual(actual, expected)

    def test_custom_workers_keep_sequential_step_order_and_halt_reporting(self):
        first = self.session.engines['avr']
        second = Mock(state={'halt': 'ready'})
        sequence = []
        first.request = lambda op, **args: sequence.append(('avr', op, args)) or {
            'image': 'avr', 'halt': 'firmware-reset-requested', 'pc': 1}
        second.request = lambda op, **args: sequence.append(('trx', op, args)) or {
            'image': 'trx', 'halt': None, 'pc': 2}
        self.assertTrue(self.session._step_processor_group([first, second], 128))
        self.assertEqual(sequence, [('avr', 'run', {'steps': 128}), ('trx', 'run', {'steps': 128})])

    def test_patch_replacement_is_executed_and_closes_old_worker(self):
        old = self.session.engines["avr"]
        patch = parse_firmware(b"\1\2" + bytes(8676), "avr.bin")
        self.session.load(patch)
        self.assertTrue(old.closed)
        self.assertEqual(self.session.engines["avr"].data, patch.data)
        self.assertEqual(self.session.state()["firmware"]["sha256"], patch.sha256)

    def test_model_switch_retires_old_processors_and_keys(self):
        self.session.key("1", True)
        old = self.session.engines["avr"]
        with self.assertRaisesRegex(ValueError, "BC5"):
            self.session.load(parse_firmware(bytes(14296), "avr.bin"))
        self.assertFalse(old.closed)
        self.session.load(parse_firmware(bytes(0x36BB22), "bc5_main.bin"))
        state = self.session.state()
        self.assertTrue(old.closed)
        self.assertEqual(set(self.session.engines), {"bc5"})
        self.assertEqual(state["handset"]["model"], "9575")
        self.assertEqual(state["keys"], [])
        self.assertIn("sos", state["handset"]["keys"])
        self.assertFalse(self.session.key("sos", True)["delivered"])
        self.assertFalse(self.session.key("convenience", True)["delivered"])
        self.session.load(parse_firmware(bytes(14296), "avr.bin"))
        self.assertEqual(self.session.engines["avr"].state["handset"], "9575")
        with self.assertRaises(ValueError):
            self.session.load(self.firmware)

    def test_failed_model_switch_preserves_previous_experiment(self):
        old = self.session.engines["avr"]
        self.session._engine_factory = Mock(side_effect=EngineError("unsupported image"))
        with self.assertRaises(EngineError):
            self.session.load(parse_firmware(bytes(0x36BB22), "bc5_main.bin"))
        self.assertEqual(self.session.model, "9555")
        self.assertIs(self.session.engines["avr"], old)
        self.assertFalse(old.closed)
        with self.assertRaises(ValueError):
            self.session.key("sos", True)

    def test_key_waiting_behind_model_switch_is_validated_against_new_handset(self):
        self.session.load(parse_firmware(bytes(0x36BB22), "bc5_main.bin"))
        original_lock = self.session._lock
        owner = threading.current_thread()
        waiting = threading.Event()
        errors = []

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread() is not owner:
                    waiting.set()
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

        self.session._lock = ObservedLock()

        def press_sos():
            try:
                self.session.key("sos", True)
            except ValueError as error:
                errors.append(error)

        with original_lock:
            thread = threading.Thread(target=press_sos)
            thread.start()
            self.assertTrue(waiting.wait(2))
            self.session.load(parse_firmware(bytes(0x310FBA), "bc5_main.bin"))
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertNotIn("sos", self.session.keys)

    def test_mixed_handset_constructor_is_rejected_before_starting_workers(self):
        factory = Mock()
        with self.assertRaises(ValueError):
            Session(Path("unused"), [self.firmware, parse_firmware(bytes(14296), "avr.bin")], factory)
        factory.assert_not_called()

    def test_step_and_reset_preserve_truthful_fidelity(self):
        epoch = self.session.key_epoch
        self.session.control("step", 100)
        self.assertEqual(self.session.key_epoch, epoch)
        self.assertEqual(self.session.state()["processors"][0]["steps"], 100)
        self.assertFalse(self.session.state()["fidelity"]["complete"])
        self.session.control("reset")
        self.assertEqual(self.session.key_epoch, epoch + 1)
        self.assertEqual(self.session.state()["processors"][0]["steps"], 0)

    def test_strict_hardware_applies_before_execution_and_to_replacement_workers(self):
        with Session(Path("unused"), [self.firmware], FakeEngine, strict_hardware=True) as session:
            old = session.engines["avr"]
            self.assertEqual(old.calls, [("hardware", {"strict": True})])
            session.load(self.firmware)
            self.assertTrue(old.closed)
            self.assertEqual(session.engines["avr"].calls, [("hardware", {"strict": True})])
            session.probe("avr", "adc", {"channel": 0, "value": 42})
            session.probe("avr", "trace", {"enabled": True})
            self.assertEqual(session.engines["avr"].calls[-2:], [
                ("adc", {"channel": 0, "value": 42}), ("trace", {"enabled": True})])

    def test_failed_strict_configuration_closes_new_worker_and_preserves_old_experiment(self):
        old = self.session.engines["avr"]
        replacement = FakeEngine(Path("unused"), "avr", self._firmware_file())
        replacement.request = Mock(side_effect=EngineError("configuration failed"))
        self.session.strict_hardware = True
        self.session._engine_factory = Mock(return_value=replacement)
        with self.assertRaisesRegex(EngineError, "configuration failed"):
            self.session.load(self.firmware)
        self.assertTrue(replacement.closed)
        self.assertIs(self.session.engines["avr"], old)
        self.assertFalse(old.closed)

    def test_failed_input_release_closes_replacement_without_retiring_existing_processors(self):
        self.session.load(parse_firmware(bytes(0x310FBA), "bc5_main.bin"))
        primary, old_avr = self.session.engines["bc5"], self.session.engines["avr"]
        primary.state["bc5_hardware"] = True
        self.session.keys.add("1")
        primary.request = Mock(side_effect=EngineError("input release failed"))
        replacement = FakeEngine(Path("unused"), "avr", self._firmware_file())
        self.session._engine_factory = Mock(return_value=replacement)
        with self.assertRaisesRegex(EngineError, "input release failed"):
            self.session.load(self.firmware)
        self.assertTrue(replacement.closed)
        self.assertIs(self.session.engines["avr"], old_avr)
        self.assertIs(self.session.engines["bc5"], primary)
        self.assertFalse(old_avr.closed)
        self.assertFalse(primary.closed)

    def _firmware_file(self):
        path = Path(self.session._temporary.name) / "fixture.bin"
        path.write_bytes(self.firmware.data)
        return path

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

    def test_failed_key_delivery_preserves_state_and_allows_retry(self):
        self.session.engines["bc5"] = self.session.engines["avr"]
        self.session.ui_initialized = True
        worker = self.session.engines["bc5"]
        worker.request = Mock(return_value={"values": [1, 2]})
        self.session._call = Mock(return_value={})
        for pressed in (True, False):
            with self.subTest(pressed=pressed):
                self.session.keys = set() if pressed else {"1"}
                # All three idle budgets expire before the key routine is called.
                worker.request.side_effect = [
                    {"halt": None, "at_idle": False},
                    {"halt": None, "at_idle": False},
                    {"halt": None, "at_idle": False},
                ]
                before = set(self.session.keys)
                self.session._call.reset_mock()
                with self.assertRaisesRegex(EngineError, "instruction budget exhausted"):
                    self.session.key("1", pressed)
                self.assertEqual(self.session.keys, before)
                self.session._call.assert_not_called()
                worker.request.side_effect = None
                self.session._idle = Mock()
                self.assertTrue(self.session.key("1", pressed)["delivered"])
                self.session._call.assert_called_once()
                self.assertEqual("1" in self.session.keys, pressed)
                del self.session._idle

    def test_post_delivery_idle_failure_does_not_repeat_the_key_routine(self):
        self.session.engines["bc5"] = self.session.engines["avr"]
        self.session.ui_initialized = True
        self.session.engines["bc5"].request = Mock(return_value={"values": [1, 2]})
        self.session._call = Mock(return_value={})
        for pressed in (True, False):
            with self.subTest(pressed=pressed):
                self.session.keys = set() if pressed else {"1"}
                self.session._idle = Mock(side_effect=[None, EngineError("idle budget exhausted")])
                self.session._call.reset_mock()
                with self.assertRaises(EngineError):
                    self.session.key("1", pressed)
                self.assertEqual("1" in self.session.keys, pressed)
                self.assertFalse(self.session.key("1", pressed)["delivered"])
                self.session._call.assert_called_once()

    def test_release_cancels_late_press_and_cannot_release_a_new_generation(self):
        generation = self.session.state()["key_generations"]["1"]
        released = self.session.key("1", False, generation)
        self.assertEqual(released["generation"], generation + 1)
        self.assertFalse(self.session.key("1", True, generation)["delivered"])
        self.assertEqual(self.session.keys, set())
        self.session.key("1", True, generation + 1)
        self.session.key("1", False, generation)
        self.assertEqual(self.session.keys, {"1"})
        self.session.key("1", False, generation + 1)
        self.assertEqual(self.session.keys, set())

    def test_reset_and_firmware_replacement_cancel_prior_key_generations(self):
        bc5 = replace(self.firmware, image="bc5", name="bc5_main.bin")
        for reset in (lambda: self.session.control("reset"), lambda: self.session.load(bc5)):
            generation = self.session.state()["key_generations"]["1"]
            self.session.key("1", True, generation)
            reset()
            self.session.key("1", True, generation)
            self.assertEqual(self.session.keys, set())

    def test_modem_load_preserves_bc5_held_keys_and_their_releases(self):
        worker = self.initialize_key_handler()
        for sequence, image in enumerate(("trx", "ptt", "trx", "ptt"), start=1):
            with self.subTest(image=image):
                before = self.session.state()
                generation = before["key_generations"]["1"]
                self.assertTrue(self.session.key("1", True, generation)["delivered"])
                self.browser_key("tab", sequence * 2, True)
                self.session.load(replace(self.firmware, image=image))
                after = self.session.state()
                self.assertEqual(after["keys"], ["1"])
                self.assertEqual(after["key_generations"], before["key_generations"])
                self.assertEqual(after["key_epoch"], before["key_epoch"])
                self.assertTrue(after["ui_initialized"])
                self.assertIs(self.session.engines["bc5"], worker)
                self.assertFalse(worker.closed)
                self.assertFalse(self.session.key("1", False, generation)["delivered"])
                self.assertEqual(self.session.keys, {"1"})
                self.assertTrue(self.browser_key("tab", sequence * 2 + 1, False)["delivered"])
                self.assertEqual(self.session.keys, set())
        self.assertEqual([call.kwargs["ah"] for call in self.session._call.call_args_list], [1, 4] * 4)

    def test_shared_matrix_contacts_change_only_for_first_press_and_last_release(self):
        worker = self.initialize_key_handler()
        worker.state["bc5_hardware"] = True
        self.session._step = Mock()
        self.assertTrue(self.browser_key("tab-a", 1, True)["delivered"])
        self.assertFalse(self.browser_key("tab-b", 1, True)["delivered"])
        self.assertFalse(self.browser_key("tab-a", 2, False)["delivered"])
        self.assertEqual(self.session.keys, {"1"})
        self.assertTrue(self.browser_key("tab-b", 2, False)["delivered"])
        transitions = [call.kwargs["pressed"] for call in worker.request.call_args_list if call.args[0] == "key"]
        self.assertEqual(transitions, [True, False])
        self.assertEqual(self.session.keys, set())

    def test_power_on_rejects_owned_power_before_mutating_the_board(self):
        worker = self.initialize_key_handler()
        self.session._button_input = Mock()
        self.session._step = Mock()
        self.browser_key("tab-a", 1, True, key="power")
        self.session.ui_initialized = False
        worker.request.reset_mock()
        epoch = self.session.key_epoch
        with self.assertRaisesRegex(ValueError, "Release the power button"):
            self.session.control("initialize_ui")
        self.assertFalse(self.session.ui_attempted)
        self.assertEqual(self.session.key_epoch, epoch)
        self.assertEqual(self.session.keys, {"power"})
        worker.request.assert_not_called()
        self.assertEqual([call.args for call in self.session._button_input.call_args_list], [("power", True)])
        self.assertFalse(self.browser_key("tab-b", 1, True, key="power")["delivered"])
        self.assertFalse(self.browser_key("tab-a", 2, False, key="power")["delivered"])
        self.assertTrue(self.browser_key("tab-b", 2, False, key="power")["delivered"])
        self.assertEqual(self.session.keys, set())

    def test_shared_power_input_changes_only_for_first_press_and_last_release(self):
        self.initialize_key_handler()
        self.session._button_input = Mock()
        self.session._step = Mock()
        self.assertTrue(self.browser_key("tab-a", 1, True, key="power")["delivered"])
        self.assertFalse(self.browser_key("tab-b", 1, True, key="power")["delivered"])
        self.assertFalse(self.browser_key("tab-a", 2, False, key="power")["delivered"])
        self.assertEqual(self.session.keys, {"power"})
        self.assertTrue(self.browser_key("tab-b", 2, False, key="power")["delivered"])
        self.assertEqual([call.args for call in self.session._button_input.call_args_list],
                         [("power", True), ("power", False)])
        self.assertEqual([call.args[0] for call in self.session._step.call_args_list], [5200000, 150000])
        self.assertEqual(self.session.keys, set())

    def test_shared_sos_uses_avr_input_only_for_first_press_and_last_release(self):
        self.session.load(parse_firmware(bytes(0x36BB22), "bc5_main.bin"))
        self.session.load(parse_firmware(bytes(14296), "avr.bin"))
        self.session._button_input = Mock()
        self.session._step = Mock()
        self.session._call = Mock()
        self.assertTrue(self.browser_key("tab-a", 1, True, key="sos")["delivered"])
        self.assertFalse(self.browser_key("tab-b", 1, True, key="sos")["delivered"])
        self.assertFalse(self.browser_key("tab-a", 2, False, key="sos")["delivered"])
        self.assertTrue(self.browser_key("tab-b", 2, False, key="sos")["delivered"])
        self.assertEqual([call.args for call in self.session._button_input.call_args_list],
                         [("sos", True), ("sos", False)])
        self.assertEqual([call.args for call in self.session._step.call_args_list], [(150000,), (150000,)])
        self.session._call.assert_not_called()
        self.assertEqual(self.session.keys, set())

    def test_two_clients_inject_only_first_press_and_last_release(self):
        self.initialize_key_handler()
        self.assertTrue(self.browser_key("tab-a", 1, True)["delivered"])
        self.assertFalse(self.browser_key("tab-b", 1, True)["delivered"])
        self.assertFalse(self.browser_key("tab-a", 1, True)["delivered"])
        self.assertFalse(self.browser_key("tab-a", 2, False)["delivered"])
        self.assertEqual(self.session.keys, {"1"})
        self.assertTrue(self.browser_key("tab-b", 2, False)["delivered"])
        self.assertEqual(self.session.keys, set())
        # A newly opened page starts at sequence one regardless of other pages' history.
        self.assertTrue(self.browser_key("new-tab", 1, True)["delivered"])
        self.assertTrue(self.browser_key("new-tab", 2, False)["delivered"])
        self.assertEqual([call.kwargs["ah"] for call in self.session._call.call_args_list], [1, 4, 1, 4])

    def test_client_release_before_press_is_a_tombstone_only_for_that_client_and_key(self):
        self.initialize_key_handler()
        self.browser_key("tab-a", 2, False)
        self.assertTrue(self.browser_key("tab-b", 1, True)["delivered"])
        self.assertIn("Stale", self.browser_key("tab-a", 1, True)["message"])
        self.browser_key("tab-a", 3, True)
        self.browser_key("tab-a", 2, False)
        self.browser_key("tab-b", 2, False)
        self.assertEqual(self.session.keys, {"1"})
        self.assertTrue(self.browser_key("tab-a", 4, False)["delivered"])
        # Sequences are compared per key, so independent requests may arrive out of order.
        self.assertTrue(self.browser_key("tab-a", 1, True, key="2")["delivered"])
        self.assertEqual(self.session.keys, {"2"})

    def test_legacy_releases_cannot_clear_client_owned_keys(self):
        self.initialize_key_handler()
        for generation_api in (False, True):
            with self.subTest(generation_api=generation_api):
                generation = self.session.key_generations["1"] if generation_api else None
                self.browser_key("tab", 1, True)
                self.assertFalse(self.session.key("1", False, generation)["delivered"])
                self.assertEqual(self.session.keys, {"1"})
                generation = self.session.key_generations["1"] if generation_api else None
                self.assertFalse(self.session.key("1", True, generation)["delivered"])
                self.assertFalse(self.browser_key("tab", 2, False)["delivered"])
                self.assertEqual(self.session.keys, {"1"})
                self.assertTrue(self.session.key("1", False, generation)["delivered"])
                self.assertEqual(self.session.keys, set())
                self.session.control("reset")
                self.session.ui_initialized = True

    def test_reset_and_bc5_replacement_reject_old_client_presses_and_releases(self):
        bc5 = replace(self.firmware, image="bc5", name="bc5_main.bin")
        for reset in (lambda: self.session.control("reset"), lambda: self.session.load(bc5)):
            epoch = self.session.key_epoch
            self.browser_key("tab-a", 10, True)
            self.assertEqual(self.session.keys, {"1"})
            reset()
            self.assertEqual(self.session.key_epoch, epoch + 1)
            self.assertIn("epoch", self.browser_key("tab-a", 2, True, epoch=epoch)["message"])
            self.assertEqual(self.session.keys, set())
            self.browser_key("tab-a", 3, True)
            stale = self.browser_key("tab-a", 4, False, epoch=epoch)
            self.assertEqual(stale["key_epoch"], epoch + 1)
            self.assertEqual(self.session.keys, {"1"})
            self.browser_key("tab-a", 4, False)

    def test_client_limit_keeps_tombstones_until_reset(self):
        for client in range(128):
            self.browser_key(f"tab-{client}", 2, False)
        with self.assertRaisesRegex(ValueError, "128.*reset"):
            self.browser_key("one-too-many", 1, True)
        self.browser_key("tab-0", 1, True)
        self.assertEqual(self.session.keys, set())
        self.session.load(self.firmware)
        with self.assertRaisesRegex(ValueError, "128.*reset"):
            self.browser_key("one-too-many", 1, True)
        self.session.control("reset")
        self.browser_key("one-too-many", 1, True)
        self.assertEqual(self.session.keys, {"1"})

    def test_browser_delivery_failure_can_retry_without_repeating_a_delivered_event(self):
        self.initialize_key_handler()
        for sequence, pressed in ((1, True), (2, False)):
            self.session._idle = Mock(side_effect=EngineError("before injection"))
            with self.assertRaisesRegex(EngineError, "before injection"):
                self.browser_key("tab", sequence, pressed)
            self.session._call.reset_mock()
            self.session._idle = Mock(side_effect=[None, EngineError("after injection")])
            with self.assertRaisesRegex(EngineError, "after injection"):
                self.browser_key("tab", sequence, pressed)
            self.assertEqual("1" in self.session.keys, pressed)
            self.assertFalse(self.browser_key("tab", sequence, pressed)["delivered"])
            self.session._call.assert_called_once()

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

    def test_failed_worker_restart_still_resets_surviving_processors(self):
        self.session.load(parse_firmware(bytes(0x310FBA), "bc5_main.bin"))
        failed, survivor = self.session.engines["avr"], self.session.engines["bc5"]
        failed.state["halt"] = "worker-failed"
        failed.request = Mock(side_effect=EngineError("CPU worker is no longer running"))
        self.session._engine_factory = Mock(side_effect=OSError("cannot launch worker"))
        survivor.state["steps"] = 42
        with self.assertRaisesRegex(EngineError, "cannot launch worker"):
            self.session.control("reset")
        self.assertEqual(survivor.state["steps"], 0)
        self.assertIs(self.session.engines["bc5"], survivor)
        self.assertIs(self.session.engines["avr"], failed)
        self.assertFalse(self.session.running)
        self.assertIsNone(self.session.spi_link)
        self.assertIsNone(self.session.modem_link)

    def test_worker_restart_reapplies_model_and_strict_hardware(self):
        with Session(Path("unused"), [parse_firmware(bytes(14296), "avr.bin")],
                     FakeEngine, strict_hardware=True) as session:
            old = session.engines["avr"]
            old.state["halt"] = "worker-failed"
            old.request = Mock(side_effect=EngineError("CPU worker is no longer running"))
            session.control("reset")
            replacement = session.engines["avr"]
            self.assertIsNot(replacement, old)
            self.assertTrue(old.closed)
            self.assertEqual(replacement.state["handset"], "9575")
            self.assertEqual(replacement.data, session.firmware["avr"].data)
            self.assertEqual(replacement.calls, [("hardware", {"strict": True})])

    def test_firmware_staging_failure_still_resets_surviving_processors(self):
        self.session.load(parse_firmware(bytes(0x310FBA), "bc5_main.bin"))
        failed, survivor = self.session.engines["avr"], self.session.engines["bc5"]
        failed.state["halt"] = "worker-failed"
        failed.request = Mock(side_effect=EngineError("CPU worker is no longer running"))
        survivor.state["steps"] = 42
        with patch("iridium.session.tempfile.NamedTemporaryFile", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(EngineError, "Cannot start avr worker: disk full"):
                self.session.control("reset")
        self.assertEqual(survivor.state["steps"], 0)
        self.assertIs(self.session.engines["bc5"], survivor)
        self.assertIs(self.session.engines["avr"], failed)
        self.assertFalse(self.session.running)

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
