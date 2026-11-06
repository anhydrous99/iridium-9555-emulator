from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call


SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "benchmark-coupled.py"


def load_benchmark(optimization):
    namespace = {"__name__": "benchmark_coupled", "__file__": str(SCRIPT)}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec", optimize=optimization), namespace)
    return namespace


class CoupledBenchmarkTests(unittest.TestCase):
    def test_key_tap_executes_both_edges_with_python_optimization(self):
        for optimization in (0, 1, 2):
            with self.subTest(optimization=optimization):
                benchmark = load_benchmark(optimization)
                session = SimpleNamespace(key=Mock(return_value={"delivered": True}))
                benchmark["tap_key"](session, "soft_left")
                self.assertEqual(session.key.call_args_list,
                                 [call("soft_left", True), call("soft_left", False)])

    def test_key_tap_rejects_undelivered_events_with_python_optimization(self):
        benchmark = load_benchmark(1)
        for delivered in ((False,), (True, False)):
            with self.subTest(delivered=delivered):
                session = SimpleNamespace(key=Mock(side_effect=[{"delivered": value} for value in delivered]))
                with self.assertRaisesRegex(RuntimeError, "Key event was not delivered"):
                    benchmark["tap_key"](session, "soft_left")
                self.assertEqual(session.key.call_count, len(delivered))
