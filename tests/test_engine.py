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

    def test_link_snapshot_reads_are_isolated_and_invalidated_by_device_commands(self):
        engine = self.start('''
            print(json.dumps({'registers': [0], 'uart_tx_dropped': [3], '_links': {
                'pins': [1], 'inputs': [2], 'uart_empty': [True]}}), flush=True)
            assert json.loads(sys.stdin.readline()) == {'op': 'spi', 'value': 7}
            print('{"value":17}', flush=True)
            assert json.loads(sys.stdin.readline()) == {'op': 'pin_state'}
            print('{"pins":[9],"inputs":[2]}', flush=True)
        ''')
        self.assertNotIn('_links', engine.state)
        pins = engine.request('pin_state')
        pins['pins'][0] = 255
        self.assertEqual(engine.request('pin_state'), {'pins': [1], 'inputs': [2]})
        self.assertEqual(engine.request('uart_io', port=0), {'accepted': 0, 'values': [], 'dropped': 3})
        self.assertEqual(engine.request('spi', value=7), {'value': 17})
        self.assertEqual(engine.request('pin_state'), {'pins': [9], 'inputs': [2]})

    def test_group_sends_both_runs_before_waiting_and_updates_snapshots(self):
        marker = self.directory / 'second-started'
        first = self.start(f'''
            print('{{"registers":[0]}}', flush=True)
            request = json.loads(sys.stdin.readline())
            assert request == {{'op': 'run', 'steps': 7}}
            while not os.path.exists({str(marker)!r}):
                time.sleep(.005)
            print(json.dumps({{'registers': [11], 'steps': 7, '_links': {{
                'pins': [7], 'inputs': [9]}}}}), flush=True)
            for line in sys.stdin:
                print('{{"registers":[12],"steps":8}}', flush=True)
        ''')
        second = self.start(f'''
            print('{{"registers":[0]}}', flush=True)
            request = json.loads(sys.stdin.readline())
            assert request == {{'op': 'run', 'steps': 7}}
            open({str(marker)!r}, 'w').close()
            print('{{"registers":[21],"steps":7}}', flush=True)
            for line in sys.stdin:
                print('{{"registers":[22],"steps":8}}', flush=True)
        ''')
        replies = Engine.run_group([first, second], 7)
        self.assertEqual([reply['registers'] for reply in replies], [[11], [21]])
        self.assertEqual(first.request('pin_state'), {'pins': [7], 'inputs': [9]})
        self.assertEqual(first.request('run', steps=1)['steps'], 8)
        self.assertEqual(second.request('run', steps=1)['steps'], 8)

    def test_group_closes_outstanding_peer_when_first_reply_fails(self):
        for reply in ('{', '{"error":"StepLimit","fatal":false}'):
            with self.subTest(reply=reply):
                first = self.start(f'''
                    print('{{"registers":[0]}}', flush=True)
                    sys.stdin.readline()
                    print({reply!r}, flush=True)
                    for line in sys.stdin:
                        print('{{"registers":[9]}}', flush=True)
                ''')
                second = self.start('''
                    print('{"registers":[0]}', flush=True)
                    sys.stdin.readline()
                    print('{"registers":[7]}', flush=True)
                    time.sleep(10)
                ''')
                with self.assertRaises(EngineError):
                    Engine.run_group([first, second], 7)
                self.assertIsNone(second._process)
                with self.assertRaisesRegex(EngineError, 'no longer running'):
                    second.request('state')
                if reply == '{':
                    self.assertIsNone(first._process)
                else:
                    self.assertEqual(first.request('state'), {'registers': [9]})
                first.close()

    def test_group_send_failure_closes_already_dispatched_worker(self):
        source = '''
            print('{"registers":[0]}', flush=True)
            sys.stdin.readline()
            time.sleep(10)
        '''
        first, second = self.start(source), self.start(source)
        with patch.object(second, '_send', side_effect=BrokenPipeError('fixture send failure')):
            with self.assertRaisesRegex(EngineError, 'fixture send failure'):
                Engine.run_group([first, second], 7)
        self.assertIsNone(first._process)
        self.assertIsNone(second._process)

    def test_unchanged_pins_do_not_replay_lcd_and_invalid_arguments_reach_worker(self):
        engine = self.start('''
            print(json.dumps({'registers': [0], 'image': 'bc5', 'lcd_bytes': [175],
                'gpio': {'inputs': 4096}, '_links': {'serial': {
                    'value': None, 'sequence': 4, 'active': False, 'remaining': 0,
                    'gpio': {'output': 1, 'direction': 2, 'reset_count': 3}}}}), flush=True)
            assert json.loads(sys.stdin.readline()) == {'op': 'pins', 'mask': True, 'value': 4096}
            print('{"error":"ExpectedInteger","fatal":false}', flush=True)
            assert json.loads(sys.stdin.readline()) == {'op': 'serial'}
            print('{"value":7}', flush=True)
        ''')
        serial = engine.request('serial')
        serial['gpio']['reset_count'] = 999
        self.assertEqual(engine.request('serial')['gpio']['reset_count'], 3)
        before = engine.state
        self.assertEqual(engine.request('pins', mask=0x5000, value=0x1000)['lcd_bytes'], [])
        self.assertEqual(before['lcd_bytes'], [175])
        with self.assertRaisesRegex(EngineError, 'ExpectedInteger'):
            engine.request('pins', mask=True, value=0x1000)
        self.assertEqual(engine.request('serial'), {'value': 7})

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
                self.assertEqual(engine.state["registers"], [0])
                self.assertEqual(engine.state["halt"], "worker-failed")
                self.assertRegex(engine.state["worker_error"], message)
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
                self.assertEqual(engine.state["halt"], "worker-failed")
                self.assertIn("timed out", engine.state["worker_error"])
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
        self.assertEqual(engine.state["halt"], "worker-failed")
        self.assertEqual(engine.state["worker_error"], "WorkerFailure")
        self.assert_closed()

    def test_state_reports_an_exited_worker_without_another_request(self):
        engine = self.start("""
            print('{"registers":[7],"steps":42,"halt":null}', flush=True)
            time.sleep(10)
        """)
        self.process.kill()
        self.process.wait()
        self.assertEqual(engine.state["halt"], "worker-failed")
        self.assertIn("no longer running", engine.state["worker_error"])
        self.assertEqual(engine.state["registers"], [7])
        self.assertEqual(engine.state["steps"], 42)
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
