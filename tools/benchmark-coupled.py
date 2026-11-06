#!/usr/bin/env python3
"""Compare coupled firmware throughput and deterministic state across two builds.

Example:
  python3 tools/benchmark-coupled.py --firmware /path/to/9555 --model 9555 \
      --baseline-source /tmp/iridium-performance-baseline \
      --baseline-engine /tmp/iridium-performance-baseline-core \
      --output /tmp/coupled.json --full-home

The default short workload initializes the board, then measures fixed execution
blocks. --full-home adds original animation, startup alerts and menu navigation.
--live appends HTTP latency and three-second running throughput samples.
All three processors remain coupled with the host's existing timing contracts.
"""

import argparse
from hashlib import sha256
import http.client
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent

def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def live_workload(session, args, measure):
    from iridium.server import Server

    throughput = []
    errors = []
    stop_poll = threading.Event()
    with Server(("127.0.0.1", 0), session, args.source / "ui") as server:
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        def request(path, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=60)
            try:
                connection.request("GET" if payload is None else "POST", path,
                                   None if payload is None else json.dumps(payload),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                data = json.loads(response.read())
                if response.status != 200:
                    raise RuntimeError(f"{path}: HTTP {response.status}: {data}")
                return data
            finally:
                connection.close()

        def boundary():
            # Match the instruction counter and wall clock at a complete board boundary.
            with session._lock:
                return session.engines["bc5"].state["steps"], time.perf_counter()

        def poll_with_keys():
            try:
                while not stop_poll.is_set():
                    measure("live_poll_with_keys", lambda: request("/api/state"))
                    stop_poll.wait(0.05)
            except Exception as error:
                errors.append(error)
                stop_poll.set()

        poll_thread = None
        try:
            epoch = request("/api/state")["key_epoch"]
            session.start()
            request("/api/control", {"action": "run"})
            for _ in range(args.samples):
                before, start = boundary()
                while time.perf_counter() - start < 3:
                    measure("live_poll", lambda: request("/api/state"))
                    time.sleep(0.05)
                after, end = boundary()
                if after <= before:
                    raise RuntimeError("Live execution made no forward progress")
                throughput.append({"instructions": after - before, "seconds": end - start,
                                   "instructions_per_second": (after - before) / (end - start)})

            poll_thread = threading.Thread(target=poll_with_keys, daemon=True)
            poll_thread.start()
            sequence = 0
            for _ in range(args.samples):
                for key in ("soft_left", "down", "up", "soft_right"):
                    def tap():
                        nonlocal sequence
                        for pressed in (True, False):
                            sequence += 1
                            response = measure("live_key_edge", lambda: request("/api/key", {
                                "key": key, "pressed": pressed, "client_id": "benchmark",
                                "sequence": sequence, "epoch": epoch}))
                            if not response["delivered"]:
                                raise RuntimeError(f"Live key event was not delivered: {response}")
                    measure("live_key_pair", tap)
                    time.sleep(0.15)
            stop_poll.set()
            poll_thread.join()
            if errors:
                raise errors[0]
            request("/api/control", {"action": "pause"})
            final = request("/api/state")
            halts = {cpu["image"]: cpu["halt"] for cpu in final["processors"]}
            lcd_error = final["lcd"]["error"] if final["lcd"] else None
            if any(halts.values()) or lcd_error or final["keys"]:
                raise RuntimeError(f"Unhealthy live endpoint: {halts}, LCD={lcd_error}, keys={final['keys']}")
            return {"throughput": throughput, "halts": halts, "lcd_error": lcd_error,
                    "note": "HTTP completion timing, not key-to-visible-LCD latency. Wall-time workloads "
                            "run after deterministic checkpoints; their endpoint states are not compared."}
        finally:
            stop_poll.set()
            if poll_thread is not None:
                poll_thread.join()
            try:
                session.control("pause")
            finally:
                server.shutdown()
                server_thread.join()


def worker(args):
    # Import only this variant's host; test constants are shared reference data.
    sys.path.insert(0, str(args.source))
    from iridium.session import Session
    sys.path.insert(1, str(ROOT / "tests"))
    from factory_handset import factory_firmware, HOME_CAPTIONS
    from test_factory_e2e import MAIN_MENU
    from test_factory_security_e2e import (
        STARTUP_SIM_ERROR, FIRMWARE_IDENTITY_WARNING, IERCC_NOT_CONFIGURED,
        IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING,
    )

    images = factory_firmware(args.model, args.firmware, modem=True)
    result = {"source": str(args.source), "engine": str(args.engine),
              "engine_sha256": sha256(args.engine.read_bytes()).hexdigest(),
              "host_sha256": {str(path.relative_to(args.source)): sha256(path.read_bytes()).hexdigest()
                              for path in sorted((args.source / "iridium").glob("*.py"))},
              "firmware": {image.image: image.payload_sha256 for image in images},
              "metrics": {}, "checkpoints": {}}
    metrics = result["metrics"]

    def measure(name, function):
        start = time.perf_counter()
        value = function()
        metrics.setdefault(name, []).append(time.perf_counter() - start)
        return value

    with Session(args.engine, images) as session:
        def advance(steps):
            while steps:
                chunk = min(steps, 200_000)
                session.control("step", chunk)
                steps -= chunk

        def screen(first=16, last=113):
            return sha256(bytes(session.lcd.state()["pixels"][first * 128:last * 128])).hexdigest()

        def checkpoint(label):
            processors = {}
            memory = {}
            for name in ("bc5", "avr", "trx"):
                state = session.probe(name, "state", {})
                if state["halt"] is not None:
                    raise RuntimeError(f"{label}: {name} halted: {state['halt']}")
                processors[name] = {key: value for key, value in state.items() if key != "_links"}
                ranges = {"bc5": [(0xA000, 0xFD00)],
                          "avr": [(0x200, 0x2200)] if args.model == "9575" else [(0x100, 0x500)],
                          "trx": [(0x40000000, 0x40100000), (0x70000000, 0x700A0000)]}[name]
                for start, end in ranges:
                    checksum = sha256()
                    for address in range(start, end, 4096):
                        response = session.probe(name, "read", {"address": address, "count": min(4096, end - address)})
                        width = response["unit_bits"] // 8
                        checksum.update(b"".join(value.to_bytes(width, "little") for value in response["values"]))
                    memory[f"{name}:{start:x}:{end:x}"] = checksum.hexdigest()
            state = session.state()
            if state["lcd"] and state["lcd"]["error"]:
                raise RuntimeError(f"{label}: LCD error: {state['lcd']['error']}")
            semantic = {"processors": processors, "memory": memory, "lcd": state["lcd"],
                        "processor_link": state["processor_link"], "spi_link": state["spi_link"],
                        "keys": state["keys"], "key_epoch": state["key_epoch"],
                        "key_generations": state["key_generations"], "ui_initialized": state["ui_initialized"]}
            result["checkpoints"][label] = {"sha256": digest(semantic),
                "components": {key: digest(value) for key, value in semantic.items()},
                "processors": processors, "memory": memory,
                "lcd_pixels_sha256": digest(state["lcd"]["pixels"]) if state["lcd"] else None,
                "processor_link": state["processor_link"], "spi_link": state["spi_link"]}
            print(f"{args.model} {args.source.name}: {label}", file=sys.stderr, flush=True)

        measure("initialize", lambda: session.control("initialize_ui"))
        session.control("pause")
        checkpoint("initialized")
        if args.full_home:
            alerts = {STARTUP_SIM_ERROR: "absent-sim", FIRMWARE_IDENTITY_WARNING: "firmware-identity"}
            if args.model == "9575":
                alerts.update({IERCC_NOT_CONFIGURED: "iercc-not-configured", IERCC_DISABLED: "iercc-disabled",
                               SOS_MESSAGE_RECIPIENT_WARNING: "sos-message-recipient"})
            seen = []
            def boot():
                for steps in range(0, 200_000_001, 200_000):
                    lcd = session.lcd.state()
                    if lcd["known_pixels"] == 16384 and lcd["display_on"] and screen(113, 128) == HOME_CAPTIONS:
                        return
                    body = screen()
                    if body in alerts:
                        if alerts[body] in seen:
                            raise RuntimeError(f"Repeated startup dialog: {alerts[body]}")
                        seen.append(alerts[body])
                        session.key("soft_right", True)
                        advance(500_000)
                        session.key("soft_right", False)
                        advance(500_000)
                    advance(200_000)
                    if steps and steps % 10_000_000 == 0:
                        print(f"{args.model} {args.source.name}: boot {steps // 1_000_000}m", file=sys.stderr, flush=True)
                raise RuntimeError("Home screen did not appear within startup budget")
            measure("boot_to_home", boot)
            result["startup_alerts"] = seen
            checkpoint("home")

        for sample in range(args.samples):
            measure("coupled_steps", lambda: advance(args.steps))
            checkpoint(f"steps-{sample + 1}")

        if args.full_home:
            for index, (key, expected, first, last) in enumerate([
                ("soft_left", MAIN_MENU[0][1], 16, 97),
                ("down", MAIN_MENU[1][1], 16, 97),
                ("up", MAIN_MENU[0][1], 16, 97),
                ("soft_right", HOME_CAPTIONS, 113, 128),
            ]):
                def tap():
                    assert session.key(key, True)["delivered"]
                    assert session.key(key, False)["delivered"]
                measure("key_pair", tap)
                measure("key_settle", lambda: advance(2_000_000))
                if screen(first, last) != expected:
                    raise RuntimeError(f"Menu assertion failed after {key}: {screen(first, last)} != {expected}")
                checkpoint(f"key-{index}-{key}")
        if args.live:
            result["live"] = live_workload(session, args, measure)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--model", required=True, choices=("9555", "9575"))
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--baseline-engine", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--engine", type=Path, default=ROOT / "zig-out/bin/iridium-core")
    parser.add_argument("--samples", type=int, default=3, help="Fixed-budget blocks per variant (default 3)")
    parser.add_argument("--steps", type=int, default=2_000_000, help="BC5 instruction budget per block")
    parser.add_argument("--full-home", action="store_true", help="Also validate original home and menu journey")
    parser.add_argument("--live", action="store_true", help="After checkpoints, measure HTTP latency and live throughput")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.samples < 1 or not 1 <= args.steps <= 100_000_000:
        parser.error("samples must be positive and steps must be 1–100,000,000")
    if bool(args.baseline_source) != bool(args.baseline_engine):
        parser.error("baseline-source and baseline-engine must be supplied together")
    for name in ("firmware", "source", "engine", "baseline_source", "baseline_engine", "output"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args)
        return 0
    variants = [("optimized", args.source, args.engine)]
    if args.baseline_source:
        variants.insert(0, ("baseline", args.baseline_source, args.baseline_engine))
    report = {"model": args.model, "python": platform.python_version(), "platform": platform.platform(),
              "steps_per_sample": args.steps, "samples": args.samples, "full_home": args.full_home,
              "live": args.live, "variants": {}}
    for name, source, engine in variants:
        output = args.output.with_name(args.output.stem + "-" + name + ".json")
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--source", str(source),
                   "--engine", str(engine), "--firmware", str(args.firmware), "--model", args.model,
                   "--samples", str(args.samples), "--steps", str(args.steps), "--output", str(output)]
        if args.full_home:
            command.append("--full-home")
        if args.live:
            command.append("--live")
        subprocess.run(command, check=True, cwd=source)
        report["variants"][name] = json.loads(output.read_text())
    if args.baseline_source:
        baseline, optimized = (report["variants"][name] for name in ("baseline", "optimized"))
        differences = []
        if baseline["firmware"] != optimized["firmware"]:
            differences.append("firmware")
        if baseline.get("startup_alerts") != optimized.get("startup_alerts"):
            differences.append("startup_alerts")
        for label in baseline["checkpoints"].keys() | optimized["checkpoints"].keys():
            old, new = baseline["checkpoints"].get(label), optimized["checkpoints"].get(label)
            if old is None or new is None:
                differences.append(label)
            elif old["sha256"] != new["sha256"]:
                differences.extend(f"{label}.{component}" for component in old["components"]
                                   if old["components"][component] != new["components"].get(component))
        report["fidelity_match"] = not differences
        report["differences"] = sorted(differences)
        report["speedups"] = {name: statistics.median(values) / statistics.median(optimized["metrics"][name])
                              for name, values in baseline["metrics"].items()}
        if args.live:
            report["live_throughput_speedup"] = (
                statistics.median(item["instructions_per_second"] for item in optimized["live"]["throughput"])
                / statistics.median(item["instructions_per_second"] for item in baseline["live"]["throughput"]))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for variant, result in report["variants"].items():
        for metric, samples in result["metrics"].items():
            print(f"{variant:10} {metric:18} median {statistics.median(samples):.4f} s ({len(samples)} samples)")
        if args.live:
            rate = statistics.median(item["instructions_per_second"] for item in result["live"]["throughput"])
            print(f"{variant:10} live throughput    {rate / 1e6:.4f} million instructions/s")
    if args.baseline_source:
        print("State fidelity:", "MATCH" if report["fidelity_match"] else "DIFFERENT", report["differences"])
        for name, value in report["speedups"].items():
            print(f"{name:18} {value:.3f}x")
        if args.live:
            print(f"live throughput    {report['live_throughput_speedup']:.3f}x")
        return 0 if report["fidelity_match"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
