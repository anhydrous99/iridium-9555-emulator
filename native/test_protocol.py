"""Native protocol regressions; synthetic guest snippets require no proprietary firmware.

Run: python3 native/test_protocol.py
Original-image checks: IRIDIUM_TEST_FIRMWARE=/path/to/firmware python3 native/test_protocol.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = Path(os.environ.get("IRIDIUM_CORE", ROOT / "zig-out/bin/iridium-core"))
ORIGINALS = os.environ.get("IRIDIUM_TEST_FIRMWARE")


def exchange(image: str, firmware: bytes, commands: list[dict | str]) -> list[dict]:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "test.bin"
        path.write_bytes(firmware)
        result = subprocess.run(
            [str(ENGINE), "--image", image, "--firmware", str(path)],
            input="".join((command if isinstance(command, str) else json.dumps(command)) + "\n" for command in commands),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return [json.loads(line) for line in result.stdout.splitlines()]


def avr_loop() -> bytes:
    # RJMP -1 at reset, followed by erased program flash. The loader accepts this same-layout patch.
    return b"\xff\xcf" + b"\xff" * (8678 - 2)


class ProtocolTests(unittest.TestCase):
    def test_avr_watchdog_request_stops_execution_until_reset(self):
        # Enable WDE, then keep reading MCUSR without servicing the watchdog.
        words = (0xE008, 0x9300, 0x0060, 0x9110, 0x0054, 0xCFFD)
        firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(8678, b"\xff")
        states = exchange("avr", firmware, [
            {"op": "run", "steps": 100000}, {"op": "run", "steps": 100},
            {"op": "reset"}, {"op": "run", "steps": 10},
        ])
        self.assertEqual(states[1]["halt"], "firmware-reset-requested")
        self.assertLess(states[1]["steps"], 100000)
        self.assertEqual(states[2]["steps"], states[1]["steps"])
        self.assertEqual(states[2]["halt"], states[1]["halt"])
        self.assertEqual(states[3]["steps"], 0)
        self.assertIsNone(states[3]["halt"])
        self.assertEqual(states[4]["steps"], 10)
        self.assertIsNone(states[4]["halt"])

    def test_uart_output_reports_loss_per_port_and_reset_clears_it(self):
        for port in (0, 1):
            with self.subTest(port=port):
                # Enable TX, poll UDRE, and transmit exactly 300 'A' bytes.
                base = 0xC0 + port * 8
                words = (0xE008, 0x9300, base + 1, 0xE401, 0xE28C, 0xE091,
                         0x9110, base, 0xFF15, 0xCFFC, 0x9300, base + 6,
                         0x9701, 0xF7C1, 0xCFFF)
                firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(8678, b"\xff")
                states = exchange("avr", firmware, [
                    {"op": "run", "steps": 500000},
                    *({"op": "uart_tx", "port": port} for _ in range(256)),
                    {"op": "state"}, {"op": "reset"}, {"op": "uart_tx", "port": port},
                ])
                expected = [0, 0]
                expected[port] = 45
                self.assertIsNone(states[1]["halt"])
                self.assertEqual(states[1]["registers"][24:26], [0, 0])
                self.assertEqual(states[1]["uart_tx_dropped"], expected)
                self.assertEqual([reply["value"] for reply in states[2:258]], [65] * 255 + [None])
                self.assertTrue(all(reply["dropped"] == 45 for reply in states[2:258]))
                self.assertEqual(states[258]["uart_tx_dropped"], expected)
                self.assertEqual(states[259]["uart_tx_dropped"], [0, 0])
                self.assertEqual(states[260], {"value": None, "dropped": 0})

    def test_multiple_commands_preserve_state_and_eof_terminates(self):
        states = exchange("avr", avr_loop(), [
            {"op": "run", "steps": 10}, {"op": "run", "steps": 20}, {"op": "state"},
            {"op": "reset"}, {"op": "run", "steps": 1},
        ])
        self.assertEqual([s["steps"] for s in states], [0, 10, 30, 30, 0, 1])
        self.assertTrue(all(s["pc"] == 0 and s["halt"] is None for s in states))

    def test_bad_json_does_not_desynchronize_protocol(self):
        states = exchange("avr", avr_loop(), ["{", {"op": "state"}])
        self.assertEqual(len(states), 3)
        self.assertFalse(states[1]["fatal"])
        self.assertEqual(states[2]["steps"], 0)

    def test_ram_write_is_atomic_and_rom_is_protected(self):
        states = exchange("avr", avr_loop(), [
            {"op": "write", "address": 0x100, "values": [12, 34]},
            {"op": "write", "address": 0x100, "values": [56, -1]},
            {"op": "read", "address": 0x100, "count": 2},
            {"op": "write", "address": 0, "values": [0]},
        ])
        self.assertEqual(states[2]["error"], "BadMemoryValue")
        self.assertEqual(states[3]["values"], [12, 34])
        self.assertEqual(states[4]["error"], "RamWriteRequired")

    def test_bounds_are_checked_before_execution(self):
        states = exchange("avr", avr_loop(), [
            {"op": "run", "steps": 10_000_001},
            {"op": "read", "address": 0xFFFFFFFF, "count": 2},
            {"op": "run", "steps": -1}, {"op": "state"},
        ])
        self.assertEqual([s["error"] for s in states[1:4]], ["StepLimit", "BadMemoryRange", "IntegerOutOfRange"])
        self.assertEqual(states[-1]["steps"], 0)

    def test_patched_opcode_changes_execution_and_fault_is_sticky(self):
        patched = b"\xff\xff" + avr_loop()[2:]
        states = exchange("avr", patched, [{"op": "run", "steps": 10}, {"op": "run", "steps": 100}])
        self.assertIn("invalid", states[1]["halt"])
        self.assertEqual(states[1]["steps"], states[2]["steps"])

    def test_bc5_call_executes_original_bytes_and_restores_cpu(self):
        # A same-layout synthetic image with a small function: ld AL,#7; rts.
        firmware = bytearray(0x310FBA)
        firmware[0:2] = (0x0004).to_bytes(2, "little")  # brk if reset executes
        firmware[0x100:0x104] = (0x0714).to_bytes(2, "little") + (0x00E2).to_bytes(2, "little")
        states = exchange("bc5", firmware, [{"op": "call", "entry": 0x100, "steps": 10}, {"op": "run", "steps": 1}])
        self.assertTrue(states[1]["last_call"]["returned"])
        self.assertEqual(states[1]["last_call"]["al"], 7)
        self.assertEqual(states[1]["pc"], states[0]["pc"])
        self.assertEqual(states[1]["registers"], states[0]["registers"])
        self.assertIn("brk", states[2]["halt"])

    def test_bc5_warm_reset_retains_ram_while_fresh_reset_clears_it(self):
        firmware = bytearray(0x310FBA)
        firmware[0:2] = (0x0004).to_bytes(2, "little")
        states = exchange("bc5", firmware, [
            {"op": "write", "address": 0xFCE0, "values": [0x94A1, 0x1234]},
            {"op": "run", "steps": 1}, {"op": "warm_reset"},
            {"op": "read", "address": 0xFCE0, "count": 2},
            {"op": "reset"}, {"op": "read", "address": 0xFCE0, "count": 2},
        ])
        self.assertIn("brk", states[2]["halt"])
        self.assertEqual(states[3]["pc"], 0)
        self.assertEqual(states[3]["steps"], 0)
        self.assertIsNone(states[3]["halt"])
        self.assertEqual(states[4]["values"], [0x94A1, 0x1234])
        self.assertEqual(states[6]["values"], [0, 0])
        other = exchange("avr", avr_loop(), [{"op": "warm_reset"}, {"op": "state"}])
        self.assertEqual(other[1]["error"], "Bc5Only")
        self.assertEqual(other[2]["steps"], 0)

    def test_bc5_call_stack_arguments_do_not_overwrite_paused_stack(self):
        firmware = bytearray(0x310FBA)
        # ld AL,@(0,Y); rts: returns the first stack argument.
        firmware[0x100:0x104] = b"\x17\x00\xe2\x00"
        states = exchange("bc5", firmware, [
            {"op": "write", "address": 0xFCC0, "values": [0xBEEF]},
            {"op": "call", "entry": 0x100, "stack": [0x1234], "steps": 10},
            {"op": "read", "address": 0xFCC0, "count": 1},
        ])
        self.assertEqual(states[2]["last_call"]["al"], 0x1234)
        self.assertEqual(states[3]["values"], [0xBEEF])

    def test_reset_wait_requires_an_armed_watchdog(self):
        firmware = bytearray(0x310FBA)
        firmware[0x184F0:0x184F2] = b"\xe0\x00"  # Original reset-wait address.
        # ld AL,#1; st AL,@0x76; st AL,@0xFF91; rts.
        firmware[0x100:0x108] = b"\x14\x01\x25\x76\x25\x91\xe2\x00"
        states = exchange("bc5", firmware, [
            {"op": "call", "entry": 0x184F0, "steps": 10},
            {"op": "reset"},
            {"op": "call", "entry": 0x100, "steps": 10},
            {"op": "call", "entry": 0x184F0, "steps": 10},
        ])
        self.assertEqual(states[1]["halt"], "probe-did-not-return")
        self.assertTrue(states[3]["last_call"]["returned"])
        self.assertEqual(states[4]["halt"], "firmware-reset-requested")
        self.assertEqual(states[4]["last_call"]["pc"], 0x184F0)
        self.assertEqual(states[4]["last_call"]["steps"], 0)

    def test_bc5_nonreturning_probe_stops_until_reset(self):
        firmware = bytearray(0x310FBA)
        firmware[0x100:0x102] = b"\xe0\x00"  # bra to the same program word
        states = exchange("bc5", firmware, [
            {"op": "call", "entry": 0x100, "steps": 10},
            {"op": "run", "steps": 100}, {"op": "reset"},
        ])
        self.assertFalse(states[1]["last_call"]["returned"])
        stopped = states[1]["last_call"]["stopped"]
        self.assertEqual(stopped["stack_address"], 0xFCC0)
        self.assertEqual(stopped["registers"][3], 0xFCC0)
        self.assertEqual(stopped["stack_count"], 64)
        self.assertEqual(len(stopped["stack_words"]), 64)
        self.assertEqual(states[1]["halt"], "probe-did-not-return")
        self.assertEqual(states[2]["steps"], states[1]["steps"])
        self.assertIsNone(states[3]["halt"])


@unittest.skipUnless(ORIGINALS, "Set IRIDIUM_TEST_FIRMWARE for original firmware integration checks")
class OriginalFirmwareTests(unittest.TestCase):
    def test_original_factory_defaults_survive_warm_reset_and_pass_startup_gate(self):
        firmware = (Path(ORIGINALS) / "bc5_main.bin").read_bytes()
        states = exchange("bc5", firmware, [
            {"op": "idle"},
            {"op": "call", "entry": 0x6365E, "steps": 10_000_000},
            {"op": "call", "entry": 0x8CC8C, "steps": 10_000_000},
            {"op": "warm_reset"},
            # Application initialization after retained factory settings exceeds one run budget.
            {"op": "idle"}, {"op": "idle"},
            {"op": "call", "entry": 0x3AF72, "steps": 100_000},
            {"op": "call", "entry": 0xBB06A, "steps": 100_000},
            {"op": "reset"}, {"op": "idle"},
            {"op": "call", "entry": 0x3AF72, "steps": 100_000},
            {"op": "call", "entry": 0xBB06A, "steps": 100_000},
        ])
        self.assertEqual(states[3]["halt"], "firmware-reset-requested")
        self.assertEqual(states[3]["last_call"]["pc"], 0x184F0)
        self.assertTrue(states[6]["at_idle"])
        for state in states[4:9]:
            self.assertIsNone(state["halt"])
            self.assertIsNone(state["milestones"]["panic"])
            self.assertIsNone(state["model_error"])
        self.assertEqual([state["last_call"]["al"] for state in states[7:9]], [1, 1])
        self.assertEqual([state["last_call"]["al"] for state in states[11:13]], [0, 0])

    def test_explicit_original_display_initialization_emits_known_command_stream(self):
        firmware = (Path(ORIGINALS) / "bc5_main.bin").read_bytes()
        states = exchange("bc5", firmware, [
            {"op": "idle", "steps": 10_000_000},
            {"op": "call", "entry": 0x6365E, "steps": 10_000_000},
        ])
        boot, probe = states[-2:]
        self.assertEqual(boot["lcd_bytes"], [])  # Natural boot has not initialized the display.
        self.assertTrue(boot["at_idle"])
        self.assertEqual(boot["pc"], 0xB774)
        self.assertTrue(probe["last_call"]["returned"])
        self.assertIsNone(probe["halt"])
        self.assertIsNone(probe["milestones"]["panic"])
        self.assertIsNone(probe["model_error"])
        self.assertEqual(probe["lcd_bytes"], list(bytes.fromhex(
            "38 00 A1 C0 44 00 AB 27 81 27 57 48 80 64 "
            "2C 67 2E 2F 4C 0F F7 1A F3 0D "
            "88 00 89 00 8A AA 8B AA 8C 77 8D 77 8E FF 8F FF 93 A6 AF"
        )))

    def test_idle_advances_before_stopping_at_safe_scheduler_boundary(self):
        firmware = (Path(ORIGINALS) / "bc5_main.bin").read_bytes()
        states = exchange("bc5", firmware, [{"op": "idle"}, {"op": "idle"}])
        self.assertTrue(states[1]["at_idle"])
        self.assertTrue(states[2]["at_idle"])
        self.assertGreater(states[2]["steps"], states[1]["steps"])

    def test_explicit_ui_startup_delivers_original_key_event_and_display_bytes(self):
        firmware = (Path(ORIGINALS) / "bc5_main.bin").read_bytes()
        states = exchange("bc5", firmware, [
            {"op": "idle"},
            {"op": "call", "entry": 0x6365E, "steps": 10_000_000},
            {"op": "call", "entry": 0x8CC5E, "steps": 10_000_000},
            {"op": "idle"},
            {"op": "call", "entry": 0x67F04, "al": 0x96, "ah": 1, "steps": 1_000_000},
            {"op": "idle"},
            {"op": "read", "address": 0xF743, "count": 1},
            {"op": "run", "steps": 2_000_000},
        ])
        self.assertEqual(states[-2]["values"], [0x96])
        display = states[-1]
        self.assertIsNone(display["halt"])
        self.assertIsNone(display["model_error"])
        self.assertGreater(len(display["lcd_bytes"]), 4096)
        self.assertEqual(display["lcd_dropped"], 0)
        self.assertEqual(set(display["lcd_bytes"][:3]), {0xB0, 0x10, 0})
        self.assertEqual(display["lcd_bytes"][3:5], [0xE8, 0x7F])

    def test_bc5_original_and_crc_stripped_reach_same_idle(self):
        original = (Path(ORIGINALS) / "bc5_main.bin").read_bytes()
        states = [exchange("bc5", data, [{"op": "run", "steps": 7_000_000}])[-1] for data in (original, original[:-4])]
        for state in states:
            self.assertTrue(state["milestones"]["main"])
            self.assertTrue(state["milestones"]["scheduler"])
            self.assertTrue(state["milestones"]["idle"])
            self.assertIsNone(state["halt"])
            self.assertIsNone(state["milestones"]["panic"])
        self.assertEqual(states[0], states[1])

    def test_original_avr_reaches_main_and_event_loop(self):
        firmware = (Path(ORIGINALS) / "avr.bin").read_bytes()
        state = exchange("avr", firmware, [{"op": "run", "steps": 100_000}])[-1]
        self.assertTrue(state["milestones"]["main"])
        self.assertTrue(state["milestones"]["idle"])
        self.assertIsNone(state["halt"])

    def test_both_original_sparc_images_reach_task_handoff(self):
        for image, filename in [("trx", "trx_seg1_0x10000.bin"), ("ptt", "trx_seg2.bin")]:
            with self.subTest(image=image):
                firmware = (Path(ORIGINALS) / filename).read_bytes()
                state = exchange(image, firmware, [{"op": "run", "steps": 10_000_000}])[-1]
                self.assertTrue(state["milestones"]["main"])
                self.assertTrue(state["milestones"]["scheduler"])
                self.assertIsNone(state["halt"])


if __name__ == "__main__":
    unittest.main()
