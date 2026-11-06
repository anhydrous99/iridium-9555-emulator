"""Bounded JSON-lines transport to the original-instruction Zig executor."""

import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import threading
import time


class EngineError(RuntimeError):
    """Native execution failed or its protocol was violated."""


class Engine:
    def __init__(self, executable: Path, image: str, firmware: Path, timeout: float = 30,
                 *, model: str = "9555"):
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._timeout = timeout
        self._stderr = tempfile.TemporaryFile()
        self._selector = selectors.DefaultSelector()
        self._process = None
        self._state = {}
        try:
            self._process = subprocess.Popen(
                [str(executable), "--image", image, "--firmware", str(firmware), "--model", model],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr)
            os.set_blocking(self._process.stdin.fileno(), False)
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            self._state = self._receive(time.monotonic() + self._timeout)
            if self._state.get("error"):
                raise EngineError(str(self._state["error"]))
        except BaseException:
            self.close()
            raise

    @property
    def state(self) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._fail("CPU worker is no longer running")
            return self._state

    def _fail(self, message: str) -> None:
        if self._state.get("halt") != "worker-failed":
            self._state = {**self._state, "halt": "worker-failed", "worker_error": message}
        self.close()

    def request(self, op: str, **arguments) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._fail("CPU worker is no longer running")
                raise EngineError("CPU worker is no longer running")
            data = json.dumps({"op": op, **arguments}, separators=(",", ":")).encode() + b"\n"
            if len(data) > 65536:
                raise EngineError("CPU request exceeds 64 KiB")
            deadline = time.monotonic() + self._timeout
            try:
                self._send(data, deadline)
                response = self._receive(deadline)
            except OSError as error:
                message = f"CPU worker disconnected: {error}"
                self._fail(message)
                raise EngineError(message) from error
            except EngineError as error:
                # No request IDs: a broken exchange makes all later replies ambiguous.
                self._fail(str(error))
                raise
            if response.get("error"):
                if response.get("fatal"):
                    self._fail(str(response["error"]))
                raise EngineError(str(response["error"]))
            if "registers" in response:
                self._state = response
            return response

    def _wait(self, selector, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
            self._process.kill()
            self._process.wait()
            raise EngineError("CPU worker timed out and was stopped")

    def _send(self, data: bytes, deadline: float) -> None:
        pending = memoryview(data)
        with selectors.DefaultSelector() as selector:
            selector.register(self._process.stdin, selectors.EVENT_WRITE)
            while pending:
                self._wait(selector, deadline)
                try:
                    written = os.write(self._process.stdin.fileno(), pending)
                except BlockingIOError:
                    continue
                pending = pending[written:]

    def _receive(self, deadline: float) -> dict:
        while True:
            end = self._buffer.find(b"\n")
            if (end if end >= 0 else len(self._buffer)) > 4 * 1024 * 1024:
                raise EngineError("CPU response exceeds 4 MiB")
            if end >= 0:
                break
            self._wait(self._selector, deadline)
            block = os.read(self._process.stdout.fileno(), 65536)
            if not block:
                self._stderr.seek(0)
                detail = self._stderr.read(4096).decode(errors="replace").strip()
                raise EngineError(f"CPU worker stopped unexpectedly: {detail}")
            self._buffer.extend(block)
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = bytearray(rest)
        try:
            response = json.loads(line)
        except (ValueError, RecursionError) as error:
            raise EngineError("CPU worker returned malformed JSON") from error
        if not isinstance(response, dict):
            raise EngineError("CPU worker response is not an object")
        return response

    def close(self) -> None:
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
            self._process = None
        self._selector.close()
        self._stderr.close()
        self._buffer.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
