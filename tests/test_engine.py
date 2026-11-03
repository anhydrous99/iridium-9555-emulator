import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from iridium.engine import Engine, EngineError


FAILURES = (
    ("stopped unexpectedly: fixture EOF", """
        os.write(1, b'{"registers":')
        print('fixture EOF', file=sys.stderr, flush=True)
        os.close(1)
    """),
    ("malformed JSON", "os.write(1, b'{\\n{\"registers\":[99]}\\n')"),
    ("malformed JSON", "os.write(1, b'\\xff\\n{\"registers\":[99]}\\n')"),
    # Older Python decoders reject nesting before the response type check.
    ("malformed JSON|not an object", "os.write(1, b'[' * 2000 + b'0' + b']' * 2000 + b'\\n{\"registers\":[99]}\\n')"),
    ("not an object", "os.write(1, b'[]\\n{\"registers\":[99]}\\n')"),
    ("not an object", "os.write(1, b'null\\n{\"registers\":[99]}\\n')"),
    ("exceeds 4 MiB", "os.write(1, b'x' * (4 * 1024 * 1024 + 1) + b'\\n')"),
)


class EngineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="iridium-worker-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.firmware = self.directory / "synthetic.bin"
        self.firmware.write_bytes(b"synthetic firmware")

    def start(self, source, timeout=2):
        executable = self.directory / "worker.py"
        executable.write_text(
            f"#!{sys.executable}\nimport json, os, signal, sys, time\n"
            + textwrap.dedent(source))
        executable.chmod(0o700)
        # Retain the failed instance and real Popen to check constructor cleanup too.
        self.engine = Engine.__new__(Engine)
        self.addCleanup(self.engine.close)
        popen = subprocess.Popen

        def spawn(*args, **kwargs):
            self.process = popen(*args, **kwargs)
            return self.process

        with patch("iridium.engine.subprocess.Popen", side_effect=spawn):
            self.engine.__init__(executable, "avr", self.firmware, timeout)
        return self.engine

    def assert_closed(self):
        self.assertIsNotNone(self.process.poll(), "worker was left alive")
        with self.assertRaises(ProcessLookupError):
            os.kill(self.process.pid, 0)
        self.assertTrue(self.process.stdin.closed)
        self.assertTrue(self.process.stdout.closed)
        self.assertTrue(self.engine._stderr.closed)
        self.assertIsNone(self.engine._selector.get_map())
        self.assertIsNone(self.engine._process)
        self.assertFalse(self.engine._buffer)
        self.engine.close()

    def test_startup_arguments_state_updates_and_context_cleanup(self):
        engine = self.start("""
            assert sys.argv[1:4] == ['--image', 'avr', '--firmware']
            with open(sys.argv[4], 'rb') as firmware:
                assert firmware.read() == b'synthetic firmware'
            print(json.dumps({'registers': [0], 'steps': 0}), flush=True)
            for line in sys.stdin:
                request = json.loads(line)
                if request['op'] == 'read':
                    reply = {'values': [request['address']]}
                else:
                    reply = {'registers': [1], 'steps': request['steps']}
                print(json.dumps(reply), flush=True)
        """)
        with engine:
            self.assertEqual(engine.state, {"registers": [0], "steps": 0})
            self.assertEqual(engine.request("read", address=7), {"values": [7]})
            self.assertEqual(engine.state["steps"], 0)
            state = engine.request("run", steps=42)
            self.assertEqual(state, {"registers": [1], "steps": 42})
            self.assertEqual(engine.state, state)
        self.assert_closed()
        with self.assertRaisesRegex(EngineError, "no longer running"):
            engine.request("state")

    def test_startup_timeout_is_bounded_and_cleans_up(self):
        started = time.monotonic()
        with self.assertRaisesRegex(EngineError, "timed out"):
            self.start("time.sleep(10)", timeout=1)
        self.assertLess(time.monotonic() - started, 5)
        self.assert_closed()

    def test_launch_failure_closes_resources(self):
        engine = Engine.__new__(Engine)
        with self.assertRaises(FileNotFoundError):
            engine.__init__(self.directory / "missing", "avr", self.firmware)
        self.assertIsNone(engine._process)
        self.assertTrue(engine._stderr.closed)
        self.assertIsNone(engine._selector.get_map())
        engine.close()

    def test_startup_failures_clean_up(self):
        for message, source in (*FAILURES, ("BadImage", "print('{\"error\":\"BadImage\",\"fatal\":true}', flush=True)")):
            with self.subTest(message=message, source=source):
                with self.assertRaisesRegex(EngineError, message):
                    self.start(textwrap.dedent(source) + "\ntime.sleep(10)\n")
                self.assert_closed()

    def test_request_protocol_failures_cannot_consume_a_later_reply(self):
        for message, source in FAILURES:
            with self.subTest(message=message, source=source):
                engine = self.start(
                    "print('{\"registers\":[0]}', flush=True)\nsys.stdin.readline()\n"
                    + textwrap.dedent(source) + "\ntime.sleep(10)\n")
                with self.assertRaisesRegex(EngineError, message):
                    engine.request("run", steps=1)
                with self.assertRaisesRegex(EngineError, "no longer running"):
                    engine.request("state")
                self.assertEqual(engine.state, {"registers": [0]})
                self.assert_closed()

    def test_request_timeout_includes_a_worker_that_does_not_read_stdin(self):
        for read_request in (True, False):
            with self.subTest(read_request=read_request):
                engine = self.start(
                    "print('{\"registers\":[0]}', flush=True)\n"
                    + ("sys.stdin.readline()\n" if read_request else "")
                    + "time.sleep(10)\n")
                engine._timeout = 0.5
                started = time.monotonic()
                with self.assertRaisesRegex(EngineError, "timed out"):
                    engine.request("run", padding="x" * 60000)
                self.assertLess(time.monotonic() - started, 5)
                self.assert_closed()
                with self.assertRaisesRegex(EngineError, "no longer running"):
                    engine.request("state")

    def test_native_request_error_and_oversized_request_allow_recovery(self):
        engine = self.start("""
            print('{"registers":[0]}', flush=True)
            request = json.loads(sys.stdin.readline())
            assert request['op'] == 'bad'
            print('{"error":"StepLimit","fatal":false}', flush=True)
            request = json.loads(sys.stdin.readline())
            assert request == {'op': 'run', 'steps': 3}
            print('{"registers":[3]}', flush=True)
            time.sleep(10)
        """)
        with self.assertRaisesRegex(EngineError, "exceeds 64 KiB"):
            engine.request("run", padding="x" * 65536)
        with self.assertRaisesRegex(EngineError, "StepLimit"):
            engine.request("bad")
        self.assertIsNone(self.process.poll())
        self.assertEqual(engine.state, {"registers": [0]})
        self.assertEqual(engine.request("run", steps=3), {"registers": [3]})
        engine.close()
        self.assert_closed()

    def test_large_request_and_response_at_the_size_limit(self):
        engine = self.start("""
            print('{"registers":[0]}', flush=True)
            request = json.loads(sys.stdin.readline())
            assert request == {'op': 'read', 'padding': 'x' * 60000}
            reply = json.dumps({'values': ''}, separators=(',', ':'))
            count = 4 * 1024 * 1024 - len(reply)
            print(json.dumps({'values': 'x' * count}, separators=(',', ':')), flush=True)
            time.sleep(10)
        """)
        with engine:
            reply = engine.request("read", padding="x" * 60000)
            self.assertEqual(reply, {"values": "x" * (4 * 1024 * 1024 - 13)})
        self.assert_closed()

    def test_fatal_native_error_closes_the_transport(self):
        engine = self.start("""
            print('{"registers":[0]}', flush=True)
            sys.stdin.readline()
            print('{"error":"WorkerFailure","fatal":true}', flush=True)
            time.sleep(10)
        """)
        with self.assertRaisesRegex(EngineError, "WorkerFailure"):
            engine.request("run", steps=1)
        self.assert_closed()

    def test_close_kills_a_worker_that_ignores_termination(self):
        engine = self.start("""
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            print('{"registers":[0]}', flush=True)
            time.sleep(10)
        """)
        started = time.monotonic()
        engine.close()
        self.assertLess(time.monotonic() - started, 5)
        self.assert_closed()


if __name__ == "__main__":
    unittest.main()
