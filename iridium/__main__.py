"""One-command launcher for GUI, bounded execution, and firmware inspection."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

from .engine import EngineError
from .firmware import FirmwareError, load_firmware
from .server import Server
from .session import Session


ROOT = Path(__file__).resolve().parent.parent


def build_engine() -> Path:
    zig = shutil.which("zig")
    if not zig:
        raise RuntimeError("Zig 0.17.0 is required. Install it, put zig on PATH, and rerun this command.")
    # Zig's own cache checks every imported source and compiler version.
    subprocess.run([zig, "build", "-j2", "-Doptimize=ReleaseSafe"], cwd=ROOT, check=True)
    executable = ROOT / "zig-out" / "bin" / "iridium-core"
    if not executable.is_file():
        raise RuntimeError("Build did not produce zig-out/bin/iridium-core")
    return executable


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="Test Iridium 9555 / 9575 Extreme firmware on firmware-derived hardware models")
    parser.add_argument("firmware", nargs="?", type=Path,
                        help="main.dfu, raw firmware, or extracted firmware directory")
    parser.add_argument("--image", choices=("bc5", "avr", "trx", "ptt"), help="Processor for a raw binary")
    parser.add_argument("--model", choices=("9555", "9575"),
                        help="Handset profile; auto-detected from BC5 layout when omitted")
    parser.add_argument("--headless", action="store_true", help="Run bounded instructions and print JSON evidence")
    parser.add_argument("--strict-hardware", action="store_true",
                        help="Stop at unimplemented MMIO instead of using latch/open-bus fallbacks")
    parser.add_argument("--modem-image", choices=("trx", "ptt", "none"), default="trx",
                        help="AVR-linked modem image when both are loaded; none runs independent workers")
    parser.add_argument("--initialize-ui", action="store_true",
                        help="Provision factory settings and power on through AVR inputs (requires BC5 and AVR)")
    parser.add_argument("--steps", type=int, default=7000000, help="Instructions per loaded processor in headless mode")
    parser.add_argument("--inspect", action="store_true", help="Validate and identify images without compiling or executing")
    parser.add_argument("--allow-invalid-crc", action="store_true", help="Permit deliberately patched DFU checksums; record mismatches")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind address; default: all IPv4 interfaces")
    parser.add_argument("--port", type=int, default=9555, help="HTTP port; 0 chooses a free port")
    parser.add_argument("--no-browser", action="store_true", help="Print the local UI URL without opening a browser")
    result = parser.parse_args(argv)
    if result.firmware is None:
        result.firmware = (ROOT / "firmware/9575" if result.model == "9575" else
                           Path.home() / "Documents/Projects/rev-firmware/firmware")
    if not 1 <= result.steps <= 100000000:
        parser.error("--steps must be between 1 and 100000000")
    if not 0 <= result.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    return result


def main(argv=None) -> int:
    args = arguments(argv)
    try:
        firmware = load_firmware(args.firmware.expanduser(), args.image, args.allow_invalid_crc, args.model)
        if args.inspect:
            print(json.dumps([item.describe() for item in firmware], indent=2))
            return 0
        executable = build_engine()
        with Session(executable, firmware, strict_hardware=args.strict_hardware,
                     modem_image=args.modem_image) as session:
            if args.initialize_ui:
                session.control("initialize_ui")
            if args.headless:
                remaining = args.steps
                while remaining:
                    amount = min(remaining, 50000 if args.initialize_ui else 1000000)
                    session.control("step", amount)
                    remaining -= amount
                state = session.state()
                state.pop("asset")
                if state.get("lcd"):
                    state["lcd"].pop("pixels", None)
                    state["lcd"].pop("known", None)
                print(json.dumps(state, indent=2))
                return 2 if any(cpu.get("halt") or cpu.get("milestones", {}).get("panic") is not None
                                for cpu in state["processors"]) else 0
            session.start()
            with Server((args.host, args.port), session, ROOT / "ui", args.allow_invalid_crc) as server:
                url = f"http://{server.authority}/"
                print(f"{session.profile.name} firmware lab: {url}", flush=True)
                print(f"Listening on {args.host}:{server.server_port}", flush=True)
                print("Firmware-derived hardware model. Press Ctrl+C to stop.", flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, FirmwareError, EngineError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"iridium: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
