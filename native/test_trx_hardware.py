#!/usr/bin/env python3
"""Execute original TRX/PTT UART and timer drivers when firmware is supplied."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = [(name, os.environ.get(name)) for name in
            ("IRIDIUM_TEST_FIRMWARE", "IRIDIUM_TEST_9575_FIRMWARE")]


@unittest.skipUnless(any(path for _, path in FIRMWARE), "Set a firmware environment variable for original modem driver checks")
class OriginalModemHardware(unittest.TestCase):
    def test_original_uart_timer_isr_and_watchdog_drivers(self):
        with tempfile.TemporaryDirectory(prefix="iridium-trx-test-") as directory:
            executable = str(Path(directory) / "trx-hardware-probe")
            result = subprocess.run([
                "zig", "build-exe", "-O", "ReleaseSafe", f"-femit-bin={executable}",
                "--dep", "common", "--dep", "sparc", "--dep", "trx",
                "-Mroot=native/trx_hardware_probe.zig", "-Mcommon=native/vendor/common/root.zig",
                "--dep", "common", "-Msparc=native/vendor/emu/sparc/root.zig",
                "--dep", "common", "--dep", "sparc", "-Mtrx=native/vendor/soc/trx/root.zig",
            ], cwd=ROOT, text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            for variable, path in FIRMWARE:
                if path:
                    with self.subTest(firmware=variable):
                        result = subprocess.run([executable, str(Path(path).resolve())], cwd=ROOT,
                                                text=True, capture_output=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn("p1: original UART drain", result.stderr)
                        self.assertIn("p2: original UART drain", result.stderr)


if __name__ == "__main__":
    unittest.main()
