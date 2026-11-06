"""Bounded JSON-lines transport to the original-instruction Zig executor."""

import json
from contextlib import ExitStack
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
        self._link_snapshot = None
        try:
            self._process = subprocess.Popen(
                [str(executable), "--image", image, "--firmware", str(firmware), "--model", model],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr)
            os.set_blocking(self._process.stdin.fileno(), False)
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            self._accept_state(self._receive(time.monotonic() + self._timeout))
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
            self._require_alive()
            cached = self._link_response(op, arguments)
            if cached is not None:
                return cached
            deadline = self._begin_request(self._encode_request(op, arguments))
            return self._finish_request(deadline)

    def drive_pins(self, *, mask, value) -> None:
        """Update board inputs without requesting a state reply for unchanged levels."""
        if type(self) is Engine and "request" not in self.__dict__:
            with self._lock:
                self._require_alive()
                snapshot = self._link_snapshot
                if (snapshot is not None and snapshot.get("bc5_inputs") is not None
                        and type(mask) is int and type(value) is int
                        and 0 <= mask <= 65535 and 0 <= value <= 65535
                        and (snapshot["bc5_inputs"] ^ value) & mask == 0):
                    return
        self.request("pins", mask=mask, value=value)

    @staticmethod
    def run_group(workers, steps):
        """Advance independent workers within one board quantum, retaining response order."""
        if len(set(workers)) != len(workers):
            raise ValueError("A worker cannot run twice in one group")
        data = Engine._encode_request("run", {"steps": steps})
        with ExitStack() as locks:
            for worker in sorted(workers, key=id):
                locks.enter_context(worker._lock)
            for worker in workers:
                worker._require_alive()
            pending, deadlines, responses = [], [], []
            try:
                for worker in workers:
                    pending.append(worker)
                    deadlines.append(worker._begin_request(data))
                for worker, deadline in zip(workers, deadlines):
                    try:
                        responses.append(worker._finish_request(deadline))
                    except EngineError:
                        # The failed reply was consumed, or its transport was closed.
                        pending.pop(0)
                        raise
                    pending.pop(0)
            except BaseException:
                # No request IDs: never leave a later worker's reply for another caller.
                for worker in pending:
                    if worker._process is not None:
                        worker._fail("Coupled execution interrupted with an outstanding response")
                raise
            return responses

    def _require_alive(self):
        if self._process is None or self._process.poll() is not None:
            self._fail("CPU worker is no longer running")
            raise EngineError("CPU worker is no longer running")

    @staticmethod
    def _encode_request(op, arguments):
        data = json.dumps({"op": op, **arguments}, separators=(",", ":")).encode() + b"\n"
        if len(data) > 65536:
            raise EngineError("CPU request exceeds 64 KiB")
        return data

    def _begin_request(self, data):
        deadline = time.monotonic() + self._timeout
        # Any real command may change a device, including a failed partial transfer.
        self._link_snapshot = None
        try:
            self._send(data, deadline)
        except (OSError, EngineError) as error:
            self._transport_failure(error)
        return deadline

    def _finish_request(self, deadline):
        try:
            response = self._receive(deadline)
        except (OSError, EngineError) as error:
            self._transport_failure(error)
        if response.get("error"):
            if response.get("fatal"):
                self._fail(str(response["error"]))
            raise EngineError(str(response["error"]))
        if "registers" in response:
            self._accept_state(response)
        return response

    def _accept_state(self, response):
        self._link_snapshot = response.pop("_links", None)
        if self._link_snapshot is not None:
            # Public replies are mutable; cached replies must retain the native values.
            self._link_snapshot["uart_dropped"] = tuple(response.get("uart_tx_dropped") or ())
            if response.get("image") == "bc5":
                self._link_snapshot["bc5_inputs"] = response["gpio"]["inputs"]
        self._state = response

    def _transport_failure(self, error):
        message = f"CPU worker disconnected: {error}" if isinstance(error, OSError) else str(error)
        self._fail(message)
        raise EngineError(message) from error

    def _link_response(self, op, arguments):
        snapshot = self._link_snapshot
        if snapshot is None:
            return None
        if op == "pin_state" and not arguments and snapshot.get("pins") is not None:
            return {"pins": list(snapshot["pins"]), "inputs": list(snapshot["inputs"])}
        if op == "serial" and not arguments and snapshot.get("serial") is not None:
            serial = snapshot["serial"]
            return {**serial, "gpio": dict(serial["gpio"])}
        if op == "uart_io" and arguments.keys() == {"port"}:
            port = arguments["port"]
            empty = snapshot.get("uart_empty")
            if type(port) is int and empty is not None and 0 <= port < len(empty) and empty[port]:
                return {"accepted": 0, "values": [], "dropped": snapshot["uart_dropped"][port]}
        return None

    def _wait(self, selector, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
            self._process.kill()
            self._process.wait()
            raise EngineError("CPU worker timed out and was stopped")

    def _send(self, data: bytes, deadline: float) -> None:
        pending = memoryview(data)
        while pending:
            try:
                written = os.write(self._process.stdin.fileno(), pending)
            except BlockingIOError:
                with selectors.DefaultSelector() as selector:
                    selector.register(self._process.stdin, selectors.EVENT_WRITE)
                    self._wait(selector, deadline)
            else:
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
        self._link_snapshot = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
