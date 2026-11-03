#!/usr/bin/env python3
"""Repeatable host/UI benchmarks; optionally include user-supplied original firmware."""

import argparse
import cProfile
import hashlib
import http.client
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from iridium.engine import Engine
from iridium.firmware import load_firmware, parse_firmware
from iridium.lcd import ST7541
from iridium.server import Server
from iridium.session import Session


def measure(function, samples, iterations=1):
    function()  # Warm caches before sampling.
    durations = []
    for _ in range(samples):
        start = time.perf_counter_ns()
        for _ in range(iterations):
            function()
        durations.append((time.perf_counter_ns() - start) / iterations / 1e6)
    return {"median_ms": statistics.median(durations), "samples_ms": durations,
            "iterations_per_sample": iterations}


def full_frame():
    return bytes.fromhex("AF A1") + b"".join(
        bytes([0xB0 + page, 0x10, 0, 0xE8, 255]) + bytes(range(256))
        for page in range(16))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--engine", type=Path, default=ROOT / "zig-out/bin/iridium-core")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path, help="Write a cProfile of 100 state polls")
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("Use at least three samples")
    metrics = {}
    result = {"environment": {"python": platform.python_version(),
              "platform": platform.platform(), "node": subprocess.check_output(
                  ["node", "--version"], text=True).strip(),
              "zig": subprocess.check_output(["zig", "version"], text=True).strip(),
              "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in ("iridium/firmware.py", "iridium/lcd.py", "ui/app.js", "native/main.zig", "native/vendor/common/bus.zig")},
              "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest()},
              "metrics": metrics}
    lcd = ST7541(segment_zero_on_right=True)
    stream = full_frame()
    lcd.feed(stream)
    assert lcd.state()["known_pixels"] == 16384
    metrics["lcd_unchanged"] = measure(lcd.state, args.samples, 100)

    def changed():
        lcd.feed(stream)
        assert lcd.state()["known_pixels"] == 16384

    metrics["lcd_changed"] = measure(changed, args.samples, 30)
    # A real worker with a synthetic same-layout AVR loop keeps host tests public.
    firmware = parse_firmware(b"\xff\xcf" + b"\xff" * 8676, "avr.bin")
    with Session(args.engine.resolve(), [firmware]) as session:
        session.lcd = lcd
        session.lcd_seen = True
        metrics["session_state"] = measure(session.state, args.samples, 100)
        encode = lambda: json.dumps(session.state(), separators=(",", ":"))
        metrics["state_json"] = measure(encode, args.samples, 100)
        result["response_bytes"] = len(encode().encode())
        if args.profile:
            profiler = cProfile.Profile()
            profiler.runcall(lambda: [encode() for _ in range(100)])
            profiler.dump_stats(str(args.profile))
        with Server(("127.0.0.1", 0), session, ROOT / "ui") as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def poll():
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                    try:
                        connection.request("GET", "/api/state")
                        response = connection.getresponse()
                        assert response.status == 200
                        assert json.loads(response.read())["lcd"]["known_pixels"] == 16384
                    finally:
                        connection.close()
                metrics["http_poll"] = measure(poll, args.samples, 20)
            finally:
                server.shutdown()
                thread.join()
    if args.firmware:
        print("Measuring original firmware execution and application initialization...", file=sys.stderr, flush=True)
        images = load_firmware(args.firmware)
        result["firmware"] = [item.describe() for item in images]
        with tempfile.TemporaryDirectory() as temporary:
            for item in images:
                path = Path(temporary) / f"{item.image}.bin"
                path.write_bytes(item.data)
                with Engine(args.engine.resolve(), item.image, path) as worker:
                    def boot():
                        worker.request("reset")
                        state = worker.request("run", steps=7_000_000)
                        assert state["halt"] is None and state["steps"] == 7_000_000
                        return state
                    metrics[f"{item.image}_boot_7m"] = measure(boot, args.samples)
                    state = boot()
                    result.setdefault("native_states", {})[item.image] = hashlib.sha256(
                        json.dumps(state, sort_keys=True).encode()).hexdigest()
        bc5 = [item for item in images if item.image == "bc5"]
        with Session(args.engine.resolve(), bc5) as session:
            def initialize():
                session.control("reset")
                session.control("initialize_ui")
                assert session.ui_initialized
            metrics["application_initialize"] = measure(initialize, args.samples)
            initialize()
            start = time.perf_counter_ns()
            for _ in range(600):
                session.control("step", 200_000)
            result["animation_120m_ms"] = (time.perf_counter_ns() - start) / 1e6
            metrics["original_session_state"] = measure(session.state, args.samples, 100)
            metrics["original_state_json"] = measure(
                lambda: json.dumps(session.state(), separators=(",", ":")), args.samples, 100)
            assert session.state()["lcd"]["known_pixels"] == 16384
            result["home_pixels_sha256"] = hashlib.sha256(bytes(session.state()["lcd"]["pixels"])).hexdigest()
    ui = subprocess.check_output(["node", str(ROOT / "tools/benchmark-ui.js"), str(args.samples)], text=True)
    metrics.update(json.loads(ui))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for name, metric in metrics.items():
        print(f"{name:30} {metric['median_ms']:10.4f} ms", flush=True)


if __name__ == "__main__":
    main()
