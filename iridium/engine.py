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
        try:
            self._process = subprocess.Popen(
                [str(executable), "--image", image, "--firmware", str(firmware), "--model", model],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr)
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            self.state = self._receive()
        except BaseException:
            self.close()
            raise

    def request(self, op: str, **arguments) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                raise EngineError("CPU worker is no longer running")
            data = json.dumps({"op": op, **arguments}, separators=(",", ":")).encode() + b"\n"
            if len(data) > 65536:
                raise EngineError("CPU request exceeds 64 KiB")
            try:
                self._process.stdin.write(data)
                self._process.stdin.flush()
                response = self._receive()
            except (BrokenPipeError, OSError) as error:
                raise EngineError(f"CPU worker disconnected: {error}") from error
            if response.get("error"):
                raise EngineError(str(response["error"]))
            if "registers" in response:
                self.state = response
            return response

    def _receive(self) -> dict:
        deadline = time.monotonic() + self._timeout
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._selector.select(remaining):
                self._process.kill()
                self._process.wait()
                raise EngineError("CPU worker timed out and was stopped")
            block = os.read(self._process.stdout.fileno(), 65536)
            if not block:
                self._stderr.seek(0)
                detail = self._stderr.read(4096).decode(errors="replace").strip()
                raise EngineError(f"CPU worker stopped unexpectedly: {detail}")
            self._buffer.extend(block)
            if len(self._buffer) > 4 * 1024 * 1024:
                raise EngineError("CPU response exceeds 4 MiB")
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = bytearray(rest)
        try:
            response = json.loads(line)
        except (ValueError, UnicodeDecodeError) as error:
            raise EngineError("CPU worker returned malformed JSON") from error
        if not isinstance(response, dict):
            raise EngineError("CPU worker response is not an object")
        if response.get("error"):
            raise EngineError(str(response["error"]))
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

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
