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
EXTREME = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


def exchange(image: str, firmware: bytes, commands: list[dict | str], model: str = "9555") -> list[dict]:
    expanded, responses = [], []
    for command in commands:
        # Full IRQ startup can exceed one native request's 10m instruction limit.
        expanded.extend([{"op": "idle"}] * 3 if isinstance(command, dict) and command.get("op") == "boot_idle"
                        else [command])
        responses.append(len(expanded))
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "test.bin"
        path.write_bytes(firmware)
        result = subprocess.run(
            [str(ENGINE), "--image", image, "--firmware", str(path), "--model", model],
            input="".join((command if isinstance(command, str) else json.dumps(command)) + "\n" for command in expanded),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        states = [json.loads(line) for line in result.stdout.splitlines()]
        return [states[0], *(states[index] for index in responses)]


def avr_loop() -> bytes:
    # RJMP -1 at reset, followed by erased program flash. The loader accepts this same-layout patch.
    return b"\xff\xcf" + b"\xff" * (8678 - 2)


class ProtocolTests(unittest.TestCase):
    def test_link_snapshots_match_live_device_queries_after_execution_and_reset(self):
        for model, size in (("9555", 8678), ("9575", 14296)):
            code = b"\xff\xcf" + b"\xff" * (size - 2)
            states = exchange("avr", code, [
                {"op": "pins", "port": 0, "value": 0xA5},
                {"op": "run", "steps": 1000}, {"op": "pin_state"},
                {"op": "uart_io", "port": 0},
                {"op": "warm_reset"}, {"op": "pin_state"},
            ], model=model)
            for state_index, pins_index in ((2, 3), (5, 6)):
                self.assertEqual(states[state_index]["_links"]["pins"], states[pins_index]["pins"])
                self.assertEqual(states[state_index]["_links"]["inputs"], states[pins_index]["inputs"])
            self.assertTrue(states[2]["_links"]["uart_empty"][0])
            self.assertEqual(states[4], {"accepted": 0, "values": [], "dropped": 0})
        states = exchange("bc5", bytes(0x310FBA), [
            {"op": "pins", "mask": 0x5000, "value": 0x4000}, {"op": "serial"},
            {"op": "warm_reset"}, {"op": "serial"},
        ])
        self.assertEqual(states[1]["_links"]["serial"], states[2])
        self.assertEqual(states[3]["_links"]["serial"], states[4])

    def test_sim_pin_protocol_rejects_wrong_images_and_invalid_arguments_without_mutation(self):
        for image, size in (("ptt", 0xA7BF8), ("bc5", 0x310FBA), ("avr", 0x4000)):
            with self.subTest(image=image):
                state = exchange(image, bytes(size), [{"op": "uart_pins", "port": 3, "value": 1}])[-1]
                self.assertEqual(state["error"], "TrxOnly")
        invalid = (
            ({"port": True}, "ExpectedInteger"),
            ({"port": 4}, "IntegerOutOfRange"),
            ({"port": -1}, "IntegerOutOfRange"),
            ({"value": True}, "ExpectedInteger"),
            ({"value": 65536}, "IntegerOutOfRange"),
            ({"value": 2}, "BadPinMask"),
            ({"mask": True}, "ExpectedInteger"),
            ({"mask": 65536}, "IntegerOutOfRange"),
            ({"mask": -1}, "IntegerOutOfRange"),
        )
        commands = [{"op": "uart_pins", "port": 3, "value": 0x101}]
        for arguments, _ in invalid:
            commands.extend([{"op": "uart_pins", "port": 3, "value": 0, **arguments},
                             {"op": "uart_pins", "port": 3}])
        commands.append({"op": "state"})
        states = exchange("trx", bytes(0x260760), commands)
        for index, (_, error) in enumerate(invalid):
            with self.subTest(index=index):
                self.assertEqual(states[2 + index * 2]["error"], error)
                self.assertEqual(states[3 + index * 2]["inputs"], 0x101)
        self.assertEqual(states[-1]["steps"], 0)

    def test_sim_inputs_validate_atomically_and_survive_only_warm_modem_reset(self):
        base = 0x80001600
        words = (0x05000000 | (base >> 10), 0x8410A000 | (base & 0x3FF),
                 0x821020FF, 0xC220A010, 0xC600A010, 0x10800000, 0x01000000)
        code = b"".join(word.to_bytes(4, "big") for word in words).ljust(0x260760, b"\xff")
        states = exchange("trx", code, [
            {"op": "uart_pins", "port": 3},
            {"op": "uart_pins", "port": 3, "value": 0x101},
            {"op": "uart_pins", "port": 3, "value": 0, "mask": 2},
            {"op": "uart_pins", "port": 3, "value": -1},
            {"op": "uart_pins", "port": 2, "value": 0},
            {"op": "uart_pins", "port": 3, "mask": 1},
            {"op": "uart_pins", "port": 3},
            {"op": "state"}, {"op": "run", "steps": 5},
            {"op": "uart_pins", "port": 3},
            {"op": "warm_reset"}, {"op": "uart_pins", "port": 3},
            {"op": "run", "steps": 5},
            {"op": "uart_pins", "port": 3, "value": 0, "mask": 0x100},
            {"op": "reset"}, {"op": "uart_pins", "port": 3},
        ])
        self.assertEqual(states[1]["pins"], 0)
        for index in (2, 7, 12):
            self.assertEqual(states[index]["inputs"], 0x101)
        self.assertEqual(states[3]["error"], "BadPinMask")
        self.assertEqual(states[4]["error"], "IntegerOutOfRange")
        self.assertEqual(states[5]["error"], "BadPort")
        self.assertEqual(states[6]["error"], "MissingField")
        self.assertEqual(states[8]["steps"], 0)
        self.assertEqual(states[9]["registers"][3], 0x1FF)
        self.assertEqual(states[10]["outputs"], 0xFE)
        self.assertEqual(states[12]["outputs"], 0)
        self.assertEqual(states[13]["registers"][3], 0x1FF)
        self.assertEqual(states[14]["inputs"], 1)
        self.assertEqual(states[14]["outputs"], 0xFE)
        self.assertEqual(states[16]["pins"], 0)

    def test_9575_reset_releases_power_and_sos_but_warm_reset_preserves_held_sos(self):
        firmware = b"\xff\xcf" + b"\xff" * (14296 - 2)
        states = exchange("avr", firmware, [
            {"op": "pin_state"}, {"op": "pins", "port": 9, "value": 0},
            {"op": "warm_reset"}, {"op": "pin_state"},
            {"op": "reset"}, {"op": "pin_state"},
        ], model="9575")
        for index in (1, 6):
            self.assertNotEqual(states[index]["inputs"][8] & 8, 0, "PJ3 Power must be released")
            self.assertNotEqual(states[index]["inputs"][9] & 1, 0, "PK0 SOS must be released")
        self.assertEqual(states[4]["inputs"][9] & 1, 0, "Warm reset must preserve a held external input")

    def test_twi_stop_rejects_a_power_reduced_slave_without_losing_its_transaction(self):
        for model, size in (("9555", 0x4000), ("9575", 0x20000)):
            for reduced in (False, True):
                with self.subTest(model=model, reduced=reduced):
                    words = []

                    def put(address, value):
                        words.extend([0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, address])

                    for address, value in ((0xBA, 0x50), (0xBC, 0x45),
                                           (0xBC, 0xC5), (0x64, 0x80 if reduced else 0)):
                        put(address, value)
                    words += [0x9110, 0xB9, 0x9120, 0xBC]
                    put(0x64, 0)
                    words += [0x9130, 0xB9, 0x9140, 0xBC, 0xCFFF]
                    firmware = b"".join(w.to_bytes(2, "little") for w in words).ljust(size, b"\xff")
                    states = exchange("avr", firmware, [
                        {"op": "hardware", "strict": True}, {"op": "run", "steps": 4},
                        {"op": "twi", "action": "address", "address": 0x28, "read": False},
                        {"op": "run", "steps": 4}, {"op": "twi", "action": "stop"},
                        {"op": "run", "steps": 2}, {"op": "run", "steps": 2},
                        {"op": "twi", "action": "stop"}, {"op": "run", "steps": 2},
                    ], model=model)
                    self.assertTrue(states[3]["accepted"])
                    self.assertEqual(states[5]["accepted"], not reduced)
                    self.assertEqual(states[6]["registers"][17:19], [0xF8, 0x45] if reduced else [0xA0, 0xC5])
                    self.assertEqual(states[8]["accepted"], reduced)
                    self.assertEqual(states[9]["registers"][19:21], [0xA0, 0xC5])
                    self.assertIsNone(states[9]["halt"])
                    self.assertIsNone(states[9]["model_error"])

    def test_flash_page_programming_completes_across_external_reset(self):
        # On EXTRF, boot code parks before it can issue another SPM operation.
        words = (0x9110, 0x54, 0xFD11, 0xCFFF, 0xE0E0, 0xE0F1,
                 0xE50A, 0x2E00, 0xEA05, 0x2E10,
                 0xE001, 0x9300, 0x57, 0x95E8,
                 0xE005, 0x9300, 0x57, 0x95E8, 0x9130, 0x57, 0xCFFD)
        for model, size, boot in (("9555", 0x4000, 0x3800), ("9575", 0x20000, 0x1E000)):
            firmware = bytearray(b"\xff" * size)
            code = b"".join(w.to_bytes(2, "little") for w in words)
            firmware[boot:boot + len(code)] = code
            for reset in ("none", "pulse", "held"):
                with self.subTest(model=model, reset=reset):
                    commands = [{"op": "fuses", "low": 0x77, "high": 0x98, "extended": 0xFE, "lock": 0xFF},
                                {"op": "reset"}, {"op": "run", "steps": 30}]
                    if reset != "none":
                        commands.append({"op": "warm_reset"})
                    commands.append({"op": "reset_clock", "cycles": 12000} if reset == "held"
                                    else {"op": "run", "steps": 12000})
                    commands.append({"op": "program_read", "address": 0x100, "count": 2})
                    states = exchange("avr", firmware, commands, model=model)
                    self.assertEqual(states[3]["registers"][19], 0x45)
                    self.assertIsNone(states[-2]["halt"])
                    self.assertEqual(states[-1]["values"], [0x5A, 0xA5])
                    if reset == "held":
                        for key in ("pc", "program_pc", "registers", "cycles", "steps", "halt"):
                            self.assertEqual(states[-3][key], states[-2][key], key)

    def test_reset_clock_validates_inputs_before_advancing_and_preserves_stops(self):
        for model, size in (("9555", 8678), ("9575", 14296)):
            bad = [{"op": "reset_clock", **args} for args in ({}, {"cycles": 0}, {"cycles": -1},
                   {"cycles": 10000001}, {"cycles": True}, {"cycles": "1"})]
            states = exchange("avr", b"\x08\x90".ljust(size, b"\xff"),
                              [{"op": "run", "steps": 1}, *bad,
                               {"op": "reset_clock", "cycles": 10000000}, {"op": "state"}], model=model)
            self.assertIsNotNone(states[1]["halt"])
            for state in states[2:2 + len(bad)]:
                self.assertIn("error", state)
                self.assertFalse(state["fatal"])
            for state in states[-2:]:
                for key in ("pc", "program_pc", "registers", "cycles", "steps", "halt"):
                    self.assertEqual(state[key], states[1][key], key)
        states = exchange("bc5", b"\xe0\0".ljust(0x310FBA, b"\0"), [{"op": "reset_clock", "cycles": 1}])
        self.assertEqual(states[-1]["error"], "AvrOnly")

    def test_164p_invalid_flash_buffer_is_diagnostic_and_explicit_clear_recovers(self):
        for model, size, boot in (("9555", 0x4000, 0x3800), ("9575", 0x20000, 0x1E000)):
            for clear_buffer in (False, True):
                with self.subTest(model=model, clear_buffer=clear_buffer):
                    words = [0xE0E0, 0xE0F1, 0xE50A, 0x2E00, 0xEA05, 0x2E10]

                    def put(address, value):
                        words.extend([0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, address])

                    def spm(command):
                        put(0x57, command)
                        words.append(0x95E8)

                    spm(1)
                    for address, value in ((0x40, 0x77), (0x3F, 4), (0x3F, 2)):
                        put(address, value)
                    words.extend([0x9120, 0x3F, 0xFD21, 0xCFFC])  # Wait for EEPE to clear.
                    put(0x3F, 1)
                    words.extend([0x9150, 0x40])  # EEPROM readback into r21.
                    if clear_buffer:
                        spm(0x11)
                        spm(1)
                    spm(5)
                    words.append(0xCFFF)
                    firmware = bytearray(b"\xff" * size)
                    code = b"".join(w.to_bytes(2, "little") for w in words)
                    firmware[boot:boot + len(code)] = code
                    states = exchange("avr", firmware, [
                        {"op": "fuses", "low": 0x77, "high": 0x98, "extended": 0xFE, "lock": 0xFF},
                        {"op": "reset"}, {"op": "run", "steps": 15000},
                        {"op": "program_read", "address": 0x100, "count": 2},
                    ], model=model)
                    self.assertEqual(states[-2]["registers"][21], 0x77)
                    if model == "9555" and not clear_buffer:
                        self.assertIn("undefined_spm_buffer", states[-2]["halt"])
                        self.assertEqual(states[-1]["values"], [0xFF, 0xFF])
                    else:
                        self.assertIsNone(states[-2]["halt"])
                        self.assertEqual(states[-1]["values"], [0x5A, 0xA5])

    def test_avr_external_reset_preserves_fixtures_without_inventing_timer_edges(self):
        # Read the reset cause, clear sticky flags, enable rising-edge T0 and poll count/ACO.
        words = (0x9110, 0x54, 0xE000, 0x9300, 0x54, 0xE007, 0x9300, 0x45,
                 0x9120, 0x46, 0x9130, 0x50, 0xCFFB)
        for model, size, port, high in (("9555", 8678, 1, 1), ("9575", 14296, 3, 0x80)):
            with self.subTest(model=model):
                firmware = b"".join(w.to_bytes(2, "little") for w in words).ljust(size, b"\xff")
                states = exchange("avr", firmware, [
                    {"op": "pins", "port": port, "value": high},
                    {"op": "comparator", "positive": 900, "negative": 100, "bandgap": 300},
                    {"op": "run", "steps": 20}, {"op": "warm_reset"},
                    {"op": "run", "steps": 20},
                ], model=model)
                for index, cause in ((3, 1), (5, 2)):
                    self.assertEqual(states[index]["registers"][17], cause)
                    self.assertEqual(states[index]["registers"][18], 0)
                    self.assertEqual(states[index]["registers"][19] & 0x20, 0x20)
                    self.assertIsNone(states[index]["halt"])

    def test_complete_avr_flash_and_boot_fuses_use_model_specific_bounds(self):
        for model, size, boot in (("9555", 0x4000, 0x1C00), ("9575", 0x20000, 0xF000)):
            with self.subTest(model=model):
                firmware = bytearray(b"\xff" * size)
                firmware[:2] = b"\xff\xcf"
                firmware[-2:] = b"\x12\x34"
                states = exchange("avr", firmware, [
                    {"op": "program_read", "address": size - 2, "count": 2},
                    {"op": "program_read", "address": size, "count": 1},
                    {"op": "fuses", "low": 0x77, "high": 0x98, "extended": 0xFE, "lock": 0xFF},
                    {"op": "reset"}, {"op": "fuses"},
                    {"op": "fuses", "low": 0x77}, {"op": "fuses"},
                ], model=model)
                self.assertEqual(states[1]["values"], [0x12, 0x34])
                self.assertEqual(states[2]["error"], "BadMemoryRange")
                self.assertEqual(states[3]["boot_start"], boot)
                self.assertEqual(states[3]["reset_vector"], boot)
                self.assertEqual(states[4]["program_pc"], boot)
                self.assertEqual(states[5]["fuses"]["high"], 0x98)
                self.assertEqual(states[6]["error"], "MissingField")
                self.assertEqual(states[7], states[5])

    def test_strict_bc5_rejects_latch_access_and_survives_reset(self):
        for model, size in (("9555", 0x310FBA), ("9575", 0x36BB22)):
            with self.subTest(model=model):
                firmware = bytearray(size)
                # ld AL,#1; st AL,@0xFF91; rts.
                firmware[0x100:0x106] = b"\x14\x01\x25\x91\xe2\x00"
                states = exchange("bc5", firmware, [
                    {"op": "hardware", "strict": True},
                    {"op": "call", "entry": 0x100, "steps": 10},
                    {"op": "hardware", "strict": False},
                    {"op": "run", "steps": 10}, {"op": "reset"},
                    {"op": "trace", "enabled": True},
                    {"op": "call", "entry": 0x100, "steps": 10}, {"op": "trace"},
                    {"op": "hardware", "strict": True}, {"op": "reset"},
                ], model=model)
                self.assertEqual(states[2]["model_error"], {
                    "address": 0xFF91, "operation": "write", "reason": "UnmodeledRegister"})
                self.assertEqual(states[4]["steps"], states[2]["steps"])
                self.assertTrue(states[7]["last_call"]["returned"])
                self.assertEqual(states[8]["accesses"], [
                    {"addr": 0xFF91, "bits": 16, "write": True, "value": 1}])
                self.assertTrue(states[10]["hardware_strict"])
                self.assertIsNone(states[10]["model_error"])

    def test_strict_avr_rejects_open_bus_and_protocol_errors_are_atomic(self):
        firmware = b"".join(word.to_bytes(2, "little") for word in (0x9100, 0xF0, 0xCFFF))
        for model, size in (("9555", 8678), ("9575", 14296)):
            with self.subTest(model=model):
                states = exchange("avr", firmware.ljust(size, b"\xff"), [
                    {"op": "hardware", "strict": "yes"},
                    {"op": "hardware", "strict": True},
                    {"op": "run", "steps": 10}, {"op": "reset"},
                    {"op": "run", "steps": 10},
                ], model=model)
                self.assertEqual(states[1]["error"], "ExpectedBoolean")
                self.assertEqual(states[3]["model_error"], {
                    "address": 0xF0, "operation": "read", "reason": "UnmodeledRegister"})
                self.assertTrue(states[4]["hardware_strict"])
                self.assertEqual(states[5]["model_error"], states[3]["model_error"])

    def test_trace_is_ordered_bounded_and_reports_capture_loss(self):
        # Read PINB repeatedly. Every iteration has one MMIO read.
        words = (0x9100, 0x23, 0xCFFD)
        firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(8678, b"\xff")
        states = exchange("avr", firmware, [
            {"op": "trace", "enabled": True}, {"op": "pins", "port": 1, "value": 0xA5},
            {"op": "run", "steps": 10000}, {"op": "trace"}, {"op": "trace"},
            {"op": "reset"}, {"op": "trace"},
        ])
        trace = states[4]
        self.assertEqual(len(trace["accesses"]), 4096)
        self.assertEqual(trace["dropped"], 5000 - 4096)
        self.assertTrue(all(access == {"addr": 0x23, "bits": 8, "write": False, "value": 0xA5}
                            for access in trace["accesses"]))
        self.assertEqual(states[5]["accesses"], [])
        self.assertEqual(states[5]["dropped"], trace["dropped"])
        self.assertEqual(states[7], {"enabled": True, "accesses": [], "dropped": 0})

    def test_trace_toggle_applies_to_pending_call_without_refilling_fuel(self):
        for model, size in (("9555", 0x310FBA), ("9575", 0x36BB22)):
            firmware = bytearray(size)
            # ld AL,#1; st AL,@0xFF91; rts.
            firmware[0x100:0x106] = b"\x14\x01\x25\x91\xe2\x00"
            for enabled in (False, True):
                with self.subTest(model=model, enabled=enabled):
                    states = exchange("bc5", firmware, [
                        {"op": "trace", "enabled": not enabled},
                        {"op": "call", "entry": 0x100, "steps": 10, "quantum": 1},
                        {"op": "trace", "enabled": enabled},
                        {"op": "call_resume", "steps": 10}, {"op": "trace"},
                    ], model=model)
                    self.assertTrue(states[2]["last_call"]["pending"])
                    self.assertTrue(states[4]["last_call"]["returned"])
                    self.assertEqual(states[5]["accesses"], [
                        {"addr": 0xFF91, "bits": 16, "write": True, "value": 1}
                    ] if enabled else [])

    def test_adc_stimulus_reaches_guest_conversion_on_both_models(self):
        for model, size, channel in (("9555", 8678, 7), ("9575", 14296, 15)):
            with self.subTest(model=model):
                # Select ADC7/15, start a conversion, wait, then read the result.
                words = (0xE007, 0x9300, 0x7C, 0xE008 if channel == 15 else 0xE000,
                         0x9300, 0x7B, 0xEC00, 0x9300, 0x7A,
                         *(0x0000 for _ in range(100)), 0x9110, 0x78, 0x9120, 0x79, 0xCFFF)
                firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(size, b"\xff")
                states = exchange("avr", firmware, [
                    {"op": "adc", "channel": channel, "value": 0x2AB},
                    {"op": "adc", "channel": channel, "value": 1024},
                    {"op": "run", "steps": 150},
                    {"op": "adc", "channel": channel + 1, "value": 0},
                ], model=model)
                self.assertEqual(states[2]["error"], "IntegerOutOfRange")
                self.assertIsNone(states[3]["halt"])
                self.assertEqual(states[3]["registers"][17:19], [0xAB, 2])
                self.assertIn(states[4]["error"], ("BadChannel", "IntegerOutOfRange"))

    def test_adc_software_requests_share_their_next_prescaled_sample_edge(self):
        for model, size in (("9555", 0x4000), ("9575", 0x20000)):
            for offset in (0, 3):
                with self.subTest(model=model, offset=offset):
                    # ADEN starts at cycle1; normal ADSC requests at420/423 share the next /16 edge.
                    words = [0xEC04, 0x9300, 0x7A] + [0] * (416 + offset)
                    words += [0xED04, 0x9300, 0x7A] + [0] * (23 - offset)
                    words += [0] * 215 + [0x9140, 0x78, 0x9150, 0x79, 0xCFFF]
                    firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(size, b"\xff")
                    states = exchange("avr", firmware, [
                        {"op": "adc", "channel": 0, "value": 400}, {"op": "run", "steps": 443},
                        {"op": "adc", "channel": 0, "value": 800}, {"op": "run", "steps": 217},
                    ], model=model)
                    self.assertEqual(states[2]["cycles"], 445)
                    self.assertEqual(states[4]["cycles"], 664)
                    self.assertIsNone(states[4]["halt"])
                    self.assertEqual(states[4]["registers"][20:22], [0x20, 3])

    def test_adc_auto_trigger_synchronizes_before_sampling(self):
        for model, size, bit in (("9555", 0x4000, 4), ("9575", 0x20000, 1)):
            with self.subTest(model=model):
                words = []

                def put(address, value):
                    words.extend([0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, address])

                put(0x7A, 0xC4)
                words += [0] * 500
                for address, value in ((0x7A, 0x94), (0x7B, 2), (0x7A, 0xA4), (0x69, 3)):
                    put(address, value)
                words += [0] * 253 + [0x9140, 0x78, 0x9150, 0x79, 0xCFFF]
                firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(size, b"\xff")
                states = exchange("avr", firmware, [
                    {"op": "adc", "channel": 0, "value": 400}, {"op": "run", "steps": 510},
                    {"op": "pins", "port": 3, "value": bit}, {"op": "run", "steps": 33},
                    {"op": "adc", "channel": 0, "value": 800}, {"op": "run", "steps": 222},
                ], model=model)
                self.assertEqual(states[4]["cycles"] - states[2]["cycles"], 33)
                self.assertIsNone(states[6]["halt"])
                self.assertEqual(states[6]["registers"][20:22], [0x20, 3])

    def test_comparator_adc_trigger_keeps_all_synchronization_clocks(self):
        for model, size in (("9555", 0x4000), ("9575", 0x20000)):
            for first in (False, True):
                for delta in (-1, 0, 1):
                    with self.subTest(model=model, first=first, delta=delta):
                        words = []

                        def put(address, value):
                            words.extend([0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, address])

                        if not first:
                            put(0x7A, 0xC4)
                            words += [0] * 500
                        for address, value in ((0x7B, 1), (0x50, 3), (0x7A, 0xB4)):
                            put(address, value)
                        words += [0] * 600 + [0x9140, 0x78, 0x9150, 0x79, 0xCFFF]
                        sample = 2 + 3 + (216 if first else 32)
                        change = sample - 1 + delta
                        firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(size, b"\xff")
                        states = exchange("avr", firmware, [
                            {"op": "adc", "channel": 0, "value": 400},
                            {"op": "run", "steps": 6 if first else 508},
                            {"op": "comparator", "positive": 800, "negative": 100},
                            {"op": "run", "steps": change},
                            {"op": "adc", "channel": 0, "value": 800},
                            {"op": "run", "steps": 600 - change + 2},
                        ], model=model)
                        self.assertEqual(states[4]["cycles"] - states[2]["cycles"], change)
                        self.assertIsNone(states[6]["halt"])
                        value = states[6]["registers"][20] | states[6]["registers"][21] << 8
                        self.assertEqual(value, 800 if change < sample else 400)

    def test_timer_output_capture_is_independent_of_instruction_length(self):
        for model, size, direction in (("9555", 0x4000, 0x2A), ("9575", 0x20000, 0x101)):
            for armed in (False, True):
                for noise in (False, True):
                    captures = []
                    for call in (False, True):
                        with self.subTest(model=model, armed=armed, noise=noise, call=call):
                            words = []

                            def put(address, value):
                                words.extend([0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, address])

                            if armed:
                                put(0x7A, 0xA0)
                            for address, value in ((direction, 0x40), (0xB0, 0x10), (0xB4, 3),
                                                   (0x81, 0xC1 if noise else 0x41), (0xB1, 1)):
                                put(address, value)
                            words += [0x940E, len(words) + 2] if call else [0] * 4
                            words += [0] * 4 + [0x9140, 0x86, 0x9150, 0x87, 0xCFFF]
                            firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(size, b"\xff")
                            steps = (21 if call else 24) if armed else (19 if call else 22)
                            state = exchange("avr", firmware, [{"op": "run", "steps": steps}], model=model)[1]
                            self.assertIsNone(state["halt"])
                            self.assertEqual(state["cycles"], 34 if armed else 31)
                            captured = state["registers"][20] | state["registers"][21] << 8
                            self.assertEqual(captured, (11 if noise else 7) if model == "9555" else 0)
                            captures.append(captured)
                    self.assertEqual(len(set(captures)), 1)

    def test_capture_filter_keeps_four_clocks_after_each_edge_source(self):
        for model, size in (("9555", 0x4000), ("9575", 0x20000)):
            for source in ("pin", "comparator", "timer"):
                if model == "9575" and source == "timer":
                    continue  # OC2B and ICP1 share a pin only on the 9555.
                for noise in (False, True):
                    with self.subTest(model=model, source=source, noise=noise):
                        words = []

                        def put(address, value):
                            words.extend([0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, address])

                        put(0x81, 0xC1 if noise else 0x41)
                        if source == "comparator":
                            put(0x50, 4)
                        elif source == "timer":
                            for address, value in ((0x2A, 0x40), (0xB0, 0x10), (0xB4, 3), (0xB1, 1)):
                                put(address, value)
                        setup_steps = len(words) // 3 * 2
                        # STS has already advanced Timer2 by two clocks; comparator output needs two.
                        wait = 3 if source == "pin" else 5
                        words += [0] * wait + [0xB326, 0xB336, 0xCFFF]  # IN r18/r19,TIFR1
                        firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(size, b"\xff")
                        commands = [{"op": "run", "steps": setup_steps}]
                        if source == "pin":
                            commands.append({"op": "pins", "port": 3, "value": 0x40 if model == "9555" else 0x10})
                        elif source == "comparator":
                            commands.append({"op": "comparator", "positive": 900, "negative": 100})
                        commands.append({"op": "run", "steps": wait + 2})
                        state = exchange("avr", firmware, commands, model=model)[-1]
                        self.assertIsNone(state["halt"])
                        self.assertEqual(state["registers"][18] & 0x20, 0 if noise else 0x20)
                        self.assertEqual(state["registers"][19] & 0x20, 0x20)

    def test_capture_filter_ignores_pin_glitches_without_elapsed_clocks(self):
        words = (0xEC01, 0x9300, 0x81, 0, 0, 0, 0, 0xB326, 0, 0, 0xB336, 0xCFFF)
        for model, size, bit in (("9555", 0x4000, 0x40), ("9575", 0x20000, 0x10)):
            firmware = b"".join(w.to_bytes(2, "little") for w in words).ljust(size, b"\xff")
            for glitch in (False, True):
                for end in (False, True):
                    with self.subTest(model=model, glitch=glitch, end=end):
                        commands = [{"op": "run", "steps": 2}, {"op": "pins", "port": 3, "value": bit},
                                    {"op": "run", "steps": 2}]
                        if glitch:
                            commands += [{"op": "pins", "port": 3, "value": 0},
                                         {"op": "pins", "port": 3, "value": bit}]
                        commands += ([{"op": "run", "steps": 2}, {"op": "pins", "port": 3, "value": 0},
                                      {"op": "run", "steps": 4}] if end else [{"op": "run", "steps": 6}])
                        state = exchange("avr", firmware, commands, model=model)[-1]
                        self.assertIsNone(state["halt"])
                        self.assertEqual([r & 0x20 for r in state["registers"][18:20]], [0x20, 0x20])

    def test_sparc_irq_stimulus_is_validated_and_reset_deasserts_it(self):
        firmware = bytes(0x260760)
        states = exchange("trx", firmware, [
            {"op": "irq", "level": 15}, {"op": "irq", "level": 16},
            {"op": "state"}, {"op": "irq", "level": 0},
            {"op": "irq", "level": 7}, {"op": "reset"},
        ])
        self.assertEqual(states[1]["irq_level"], 15)
        self.assertEqual(states[2]["error"], "IntegerOutOfRange")
        self.assertEqual(states[3]["irq_level"], 15)
        self.assertEqual(states[4]["irq_level"], 0)
        self.assertEqual(states[6]["irq_level"], 0)

    def test_modem_warm_reset_preserves_guest_programmed_flash_and_clears_volatile_state(self):
        words = []

        def address(value):
            # sethi/or %g2, then access through that register.
            words.extend([0x05000000 | (value >> 10), 0x8410A000 | (value & 0x3FF)])

        def store(target, value, opcode):
            address(target)
            words.extend([0x03000000 | (value >> 10), 0x82106000 | (value & 0x3FF), opcode])

        address(0x80000300)
        words.append(0xC600A000)  # ld [%g2], %g3: observe the UART RX queue after reset.
        for target, value in ((0xAAA, 0xAA), (0x554, 0x55), (0xAAA, 0xA0), (0x600000, 0x1234)):
            store(target, value, 0xC2B08020)  # stha %g1, [%g2] 1: real flash command interface.
        for target in (0x40000080, 0x70090080):
            store(target, 0xA5, 0xC220A000)  # st %g1, [%g2]: SDRAM and on-chip RAM.
        store(0x80000300, 0x41, 0xC220A000)
        store(0x80000300, 0x42, 0xC220A000)
        words.extend([0x10800000, 0x01000000])  # ba .; nop
        code = b"".join(word.to_bytes(4, "big") for word in words)
        for image, size, entry in (("trx", 0x260760, 0x10000), ("ptt", 0xA7BF8, 0x400000)):
            with self.subTest(image=image):
                states = exchange(image, code.ljust(size, b"\xff"), [
                    {"op": "run", "steps": len(words)},
                    {"op": "read", "address": 0x600000, "count": 2},
                    {"op": "read", "address": 0x40000080, "count": 4},
                    {"op": "read", "address": 0x70090080, "count": 4},
                    {"op": "uart_io", "port": 0, "rx": [0x42], "tx_limit": 1},
                    {"op": "irq", "level": 7}, {"op": "warm_reset"},
                    {"op": "read", "address": 0x600000, "count": 2},
                    {"op": "read", "address": 0x40000080, "count": 4},
                    {"op": "read", "address": 0x70090080, "count": 4},
                    {"op": "uart_io", "port": 0, "tx_limit": 255},
                    {"op": "run", "steps": 3}, {"op": "reset"},
                    {"op": "read", "address": 0x600000, "count": 2},
                    {"op": "read", "address": entry, "count": 4},
                ])
                self.assertIsNone(states[1]["halt"])
                self.assertEqual(states[2]["values"], [0x12, 0x34])
                for index in (3, 4):
                    self.assertEqual(states[index]["values"], [0, 0, 0, 0xA5])
                self.assertEqual(states[5]["accepted"], 1)
                self.assertEqual(states[5]["values"], [0x41])
                self.assertNotIn("error", states[7])
                for key in ("pc", "registers", "steps", "halt", "irq_level"):
                    self.assertEqual(states[7][key], states[0][key], key)
                self.assertEqual(states[7]["pc"], entry)
                self.assertEqual(states[8]["values"], [0x12, 0x34])
                for index in (9, 10):
                    self.assertEqual(states[index]["values"], [0, 0, 0, 0])
                self.assertEqual(states[11]["values"], [])
                self.assertEqual(states[12]["registers"][3], 0, "Warm reset must discard queued UART RX")
                self.assertIsNone(states[12]["halt"])
                self.assertEqual(states[13]["pc"], entry)
                self.assertEqual(states[14]["values"], [0xFF, 0xFF])
                self.assertEqual(states[15]["values"], list(code[:4]))

    def test_uart_batch_validation_precedes_input_and_output_mutation(self):
        # Enable TX, transmit one byte, then wait for its completion.
        words = (0xE008, 0x9300, 0xC1, 0xE401, 0x9300, 0xC6, 0xCFFF)
        firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(8678, b"\xff")
        states = exchange("avr", firmware, [
            {"op": "run", "steps": 1000},
            {"op": "uart_io", "port": 0, "rx": [1, -1]},
            {"op": "uart_io", "port": 0, "rx": [1] * 64},
            {"op": "uart_io", "port": 0},
        ])
        self.assertEqual(states[2]["error"], "IntegerOutOfRange")
        self.assertEqual(states[3], {"accepted": 63, "values": [65], "dropped": 0})
        self.assertEqual(states[4], {"accepted": 0, "values": [], "dropped": 0})

    def test_avr_additional_stimuli_validate_without_advancing_guest_instructions(self):
        states = exchange("avr", avr_loop(), [
            {"op": "comparator", "positive": 900, "negative": 200, "bandgap": 350},
            {"op": "comparator", "positive": 900, "negative": 1024},
            {"op": "async_clock", "ticks": 10},
            {"op": "async_clock", "ticks": 10_000_001},
            {"op": "twi", "action": "address", "address": 128, "read": False},
            {"op": "twi", "action": "reply", "reply": "invented"},
            {"op": "twi", "action": "address", "address": 20, "read": False},
            {"op": "twi", "action": "events"}, {"op": "state"},
        ])
        self.assertEqual(states[2]["error"], "IntegerOutOfRange")
        self.assertEqual(states[4]["error"], "StepLimit")
        self.assertEqual(states[5]["error"], "IntegerOutOfRange")
        self.assertEqual(states[6]["error"], "BadTwiReply")
        self.assertEqual(states[7], {"accepted": False})
        self.assertEqual(states[8], {"events": [], "dropped": 0})
        self.assertEqual(states[9]["steps"], 0)

    def test_extreme_memory_map_and_additional_ports(self):
        firmware = b"\xff\xcf" + b"\xff" * (14296 - 2)
        states = exchange("avr", firmware, [
            {"op": "write", "address": 0x200, "values": [0x56]},
            {"op": "write", "address": 0x21FF, "values": [0xA5]},
            {"op": "read", "address": 0x21FF, "count": 1},
            {"op": "write", "address": 0x130, "values": [1]},
            {"op": "uart_rx", "port": 3, "value": 65},
            {"op": "pins", "port": 10, "value": 32},
            {"op": "pins", "port": 11, "value": 0},
            {"op": "read", "address": 0x2200, "count": 1},
            {"op": "reset"}, {"op": "read", "address": 0x21FF, "count": 1},
        ], model="9575")
        self.assertEqual(states[0]["sp"], 0x21FF)
        self.assertEqual(states[0]["handset"], "9575")
        self.assertEqual(states[0]["uart_tx_dropped"], [0, 0, 0, 0])
        self.assertEqual(states[3]["values"], [0xA5])
        self.assertEqual(states[4]["error"], "RamWriteRequired")
        self.assertNotIn("error", states[5])
        self.assertNotIn("error", states[6])
        self.assertEqual(states[7]["error"], "BadPort")
        self.assertEqual(states[8]["error"], "BadMemoryRange")
        self.assertEqual(states[10]["values"], [0])

    def test_extreme_bc5_constant_window_and_instruction_extent(self):
        firmware = bytearray(0x36BB22)
        firmware[0x363E4A + 0x200:0x363E4A + 0x202] = b"\x34\x12"
        # A function beyond the 9555's code boundary must execute under the HL profile.
        firmware[0xFEF90:0xFEF94] = b"\x14\x07\xe2\x00"
        states = exchange("bc5", firmware, [
            {"op": "read", "address": 0x100, "count": 1},
            {"op": "call", "entry": 0xFEF90, "steps": 10},
            {"op": "call", "entry": 0xFEF96, "steps": 10},
        ], model="9575")
        self.assertEqual(states[1]["values"], [0x1234])
        self.assertTrue(states[2]["last_call"]["returned"])
        self.assertEqual(states[2]["last_call"]["al"], 7)
        self.assertEqual(states[3]["error"], "BadEntry")

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

    def test_uart_txc_writes_preserve_then_clear_completed_transmission(self):
        for port in (0, 1):
            with self.subTest(port=port):
                base = 0xC0 + port * 8
                # Transmit 'A', wait for TXC, then write TXC=0 and TXC=1, saving each status.
                words = (0xE008, 0x9300, base + 1, 0xE401, 0x9300, base + 6,
                         0x9110, base, 0xFF16, 0xCFFC,
                         0xE000, 0x9300, base, 0x9120, base,
                         0xE400, 0x9300, base, 0x9130, base, 0xCFFF)
                firmware = b"".join(word.to_bytes(2, "little") for word in words).ljust(8678, b"\xff")
                states = exchange("avr", firmware, [
                    {"op": "run", "steps": 1000}, {"op": "uart_tx", "port": port},
                ])
                self.assertIsNone(states[1]["halt"])
                self.assertEqual(states[1]["registers"][17:20], [0x60, 0x60, 0x20])
                self.assertEqual(states[2], {"value": 65, "dropped": 0})

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

    def test_bc5_exact_budget_returns_without_a_sentinel_instruction(self):
        for model, size in (("9555", 0x310FBA), ("9575", 0x36BB22)):
            firmware = bytearray(size)
            firmware[:2] = b"\x04\0"
            firmware[0x100:0x104] = b"\x14\x07\xe2\0"  # ld AL,7; rts
            for budget in (1, 2, 3):
                with self.subTest(model=model, budget=budget):
                    states = exchange("bc5", firmware, [{"op": "call", "entry": 0x100, "steps": budget}], model=model)
                    result = states[1]
                    self.assertEqual(result["last_call"]["returned"], budget >= 2)
                    self.assertEqual(result["last_call"]["steps"], min(budget, 2))
                    self.assertEqual(result["registers"], states[0]["registers"])
                    self.assertEqual(result["pc"], states[0]["pc"])
                    if budget >= 2:
                        self.assertIsNone(result["halt"])
                        self.assertEqual(result["last_call"]["al"], 7)
                    else:
                        self.assertEqual(result["halt"], "probe-did-not-return")
            states = exchange("bc5", firmware, [{"op": "call", "entry": 0x100, "steps": 2, "quantum": 1},
                              {"op": "call_resume", "steps": 1}, {"op": "call_resume", "steps": 1}], model=model)
            self.assertTrue(states[1]["last_call"]["pending"])
            self.assertTrue(states[2]["last_call"]["returned"])
            self.assertEqual(states[2]["last_call"]["steps"], 2)
            self.assertIsNone(states[2]["halt"])
            self.assertEqual(states[3]["error"], "NoPendingCall")

    def test_bc5_return_stops_before_a_due_timer_ticks_or_interrupts(self):
        def operand(op, value):
            return [(((value + 128) >> 8) & 255) << 8, ((value & 255) << 8) | op]

        for model, size in (("9555", 0x310FBA), ("9575", 0x36BB22)):
            for interrupts in (False, True):
                firmware = bytearray(size)
                firmware[:2] = b"\x04\0"
                firmware[4:6] = b"\x04\0"  # Trap if a post-return interrupt executes.
                settings = (((0x44, 2), (0xFF94, 4), (0x64, 1), (0xFF95, 2)) if interrupts
                            else ((0x4C, 3), (0xFF94, 8)))
                code = []
                for address, value in settings:
                    code += operand(0x14, value) + operand(0x25, address)
                code += ([0x0006, 0x0107, 0x0205] + [0x0014] * 4 if interrupts else [0x0714] * 19)
                code.append(0x00E2)
                payload = b"".join(word.to_bytes(2, "little") for word in code)
                firmware[0x100:0x100 + len(payload)] = payload
                count = 16 if interrupts else 24
                for budget in (count, count + 1, 100):
                    for quantum in (1, 7, budget):
                        with self.subTest(model=model, interrupts=interrupts, budget=budget, quantum=quantum):
                            commands = [{"op": "call", "entry": 0x100, "steps": budget, "quantum": quantum,
                                         "stack": [0xFFFE, 0xFCC0, 0x10]}]
                            commands += [{"op": "call_resume", "steps": quantum}] * ((count - 1) // quantum)
                            states = exchange("bc5", firmware, commands, model=model)
                            result = states[-1]
                            self.assertTrue(result["last_call"]["returned"])
                            self.assertEqual(result["last_call"]["steps"], count)
                            self.assertIsNone(result["halt"])
                            self.assertEqual(result["gpio"]["irq_pending"], 0)
                            self.assertEqual(result["registers"], states[0]["registers"])

    def test_bc5_modifier_chain_probe_returns_and_reset_still_executes(self):
        firmware = bytearray(0x310FBA)
        firmware[0:2] = (0x0004).to_bytes(2, "little")
        # Repeated 'u' modifiers; lsr #1; rts.
        code = b"\x09\x00" * 299 + b"\xa4\x01\xe2\x00"
        firmware[0x100:0x100 + len(code)] = code
        states = exchange("bc5", firmware, [
            {"op": "call", "entry": 0x100, "al": 0x8000, "steps": 10},
            {"op": "call", "entry": 0x100, "al": 8, "steps": 10},
            {"op": "reset"}, {"op": "run", "steps": 1},
        ])
        for state, result in zip(states[1:3], (0x4000, 4)):
            self.assertTrue(state["last_call"]["returned"])
            self.assertEqual(state["last_call"]["al"], result)
            self.assertEqual(state["last_call"]["steps"], 2)
            self.assertEqual(state["registers"], states[0]["registers"])
            self.assertIsNone(state["halt"])
        self.assertEqual(states[3]["steps"], 0)
        self.assertIn("brk", states[4]["halt"])

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
        other = exchange("avr", avr_loop(), [
            {"op": "write", "address": 0x110, "values": [0xA5]},
            {"op": "run", "steps": 5}, {"op": "warm_reset"},
            {"op": "read", "address": 0x110, "count": 1},
            {"op": "reset"}, {"op": "read", "address": 0x110, "count": 1},
        ])
        self.assertIsNone(other[3]["halt"])
        self.assertEqual(other[3]["steps"], 0)
        self.assertEqual(other[4]["values"], [0xA5])
        self.assertEqual(other[6]["values"], [0])

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
            {"op": "boot_idle"},
            {"op": "call", "entry": 0x6365E, "steps": 10_000_000},
            {"op": "call", "entry": 0x8CC8C, "steps": 10_000_000},
            {"op": "warm_reset"},
            # Application initialization after retained factory settings exceeds one run budget.
            {"op": "boot_idle"}, {"op": "boot_idle"},
            {"op": "call", "entry": 0x3AF72, "steps": 100_000},
            {"op": "call", "entry": 0xBB06A, "steps": 100_000},
            {"op": "reset"}, {"op": "boot_idle"},
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
            {"op": "boot_idle"},
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
        states = exchange("bc5", firmware, [{"op": "boot_idle"}, {"op": "boot_idle"}])
        self.assertTrue(states[1]["at_idle"])
        self.assertTrue(states[2]["at_idle"])
        self.assertGreater(states[2]["steps"], states[1]["steps"])

    def test_hardware_startup_delivers_matrix_events_and_original_display(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from iridium.firmware import load_firmware
        from iridium.session import Session
        images = [item for item in load_firmware(Path(ORIGINALS)) if item.image in ("bc5", "avr")]
        with Session(ENGINE, images) as session:
            session.control("initialize_ui")
            self.assertTrue(session.key("soft_left", True)["delivered"])
            self.assertEqual(session.engines["bc5"].request("read", address=0xF704, count=1)["values"], [0x96])
            self.assertTrue(session.key("soft_left", False)["delivered"])
            state = session.state()
            bc5 = session.engines["bc5"].state
            self.assertIsNone(bc5["halt"])
            self.assertIsNone(bc5["model_error"])
            self.assertEqual(bc5["lcd_dropped"], 0)
            self.assertEqual(state["lcd"]["known_pixels"], 16384)
            self.assertIsNone(state["lcd"]["error"])
            self.assertGreater(state["spi_link"]["transferred"], 0)

    def test_bc5_original_and_crc_stripped_reach_same_idle(self):
        original = (Path(ORIGINALS) / "bc5_main.bin").read_bytes()
        states = [exchange("bc5", data, [{"op": "boot_idle"}])[-1] for data in (original, original[:-4])]
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


@unittest.skipUnless(EXTREME, "Set IRIDIUM_TEST_9575_FIRMWARE for HL25003 integration checks")
class ExtremeFirmwareTests(unittest.TestCase):
    def test_original_extreme_factory_defaults_and_key_handler(self):
        firmware = (Path(EXTREME) / "bc5_main.bin").read_bytes()
        states = exchange("bc5", firmware, [
            {"op": "boot_idle"},
            {"op": "call", "entry": 0x6365E, "steps": 10_000_000},
            {"op": "call", "entry": 0x93788, "steps": 10_000_000},
            {"op": "warm_reset"}, {"op": "boot_idle"}, {"op": "boot_idle"},
            {"op": "call", "entry": 0x93788, "steps": 10_000_000},
            {"op": "call", "entry": 0x9375A, "steps": 10_000_000},
            {"op": "boot_idle"}, {"op": "read", "address": 0xF70E, "count": 2},
        ], model="9575")
        self.assertTrue(states[1]["at_idle"])
        self.assertEqual(len(states[2]["lcd_bytes"]), 43)
        self.assertEqual(states[3]["halt"], "firmware-reset-requested")
        self.assertEqual(states[3]["last_call"]["pc"], 0x184F0)
        self.assertTrue(states[6]["at_idle"])
        self.assertTrue(states[7]["last_call"]["returned"])
        self.assertTrue(states[8]["last_call"]["returned"])
        self.assertEqual(states[10]["values"], [4, 0x0A55])
        for state in states[4:10]:
            self.assertIsNone(state["halt"])
            self.assertIsNone(state["model_error"])

    def test_original_extreme_avr_executes_and_mutation_changes_execution(self):
        firmware = (Path(EXTREME) / "avr.bin").read_bytes()
        state = exchange("avr", firmware, [{"op": "run", "steps": 100_000}], model="9575")[-1]
        self.assertTrue(state["milestones"]["main"])
        self.assertTrue(state["milestones"]["idle"])
        self.assertIsNone(state["halt"])
        self.assertGreater(state["sp"], 0x200)
        altered = exchange("avr", b"\xff\xff" + firmware[2:], [{"op": "run", "steps": 100_000}], model="9575")[-1]
        self.assertIn("invalid", altered["halt"])
        self.assertFalse(altered["milestones"]["main"])


@unittest.skipUnless(ORIGINALS or EXTREME, "Set original firmware directories for BC5 hardware checks")
class OriginalBc5HardwareTests(unittest.TestCase):
    def profiles(self):
        for model, directory, setup, board in (
            ("9555", ORIGINALS, 0x8CC8C, 0xF7B5),
            ("9575", EXTREME, 0x93788, 0xF7D6),
        ):
            if directory:
                yield model, Path(directory), setup, board

    def worker(self, model, directory, image="bc5"):
        # This file also runs directly from native/, outside Python's package search root.
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from iridium.engine import Engine
        engine = Engine(ENGINE, image, directory / ("avr.bin" if image == "avr" else "bc5_main.bin"), model=model)
        self.addCleanup(engine.close)
        return engine

    def reach_idle(self, engine):
        for _ in range(3):
            state = engine.request("idle")
            self.assertIsNone(state["halt"])
            if state["at_idle"]:
                return state
        self.fail("Original BC5 did not reach scheduler idle")

    def return_from_irq(self, engine):
        for _ in range(400):
            state = engine.request("state")
            self.assertIsNone(state["halt"])
            if state["pc"] == 0x12E:
                return engine.request("run", steps=1)
            engine.request("run", steps=1)
        self.fail("Original IRQ wrapper did not reach RTI")

    def test_original_avr_power_selectors_read_the_model_specific_physical_inputs(self):
        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model):
                engine = self.worker(model, directory, "avr")
                engine.request("run", steps=100000)
                signals = ((2, 0, 0x20), (2, 1, 0x22), (3, 4, 0x38)) if model == "9555" else (
                    (8, 3, 0x86), (8, 4, 0x88), (8, 5, 0x8A))
                for selector, (port, bit, reply_selector) in zip((0x20, 0x22, 0x38), signals):
                    for level in (0, 1):
                        engine.request("pins", port=port, value=level << bit)
                        received = []
                        # Execute the original register4 SPI GPIO-read command.
                        for value in (0x80, selector, 0x11, 0, 0, 0, 0):
                            received.append(engine.request("spi", value=value)["value"])
                            self.assertIsNone(engine.request("run", steps=1000)["halt"])
                        self.assertEqual(received[4:], [0x80, reply_selector | level, 0])

    def test_original_irq_wrapper_preserves_register_banks_and_scratch_at_different_depths(self):
        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model):
                engine = self.worker(model, directory)
                engine.request("hardware", enabled=True)
                engine.request("reset")
                self.reach_idle(engine)
                for entry, priority in ((0x6590, 3), (0x65E6, 1)):
                    state = engine.request("call", entry=entry, al=1, ah=priority, steps=10000)
                    self.assertTrue(state["last_call"]["returned"])
                self.reach_idle(engine)
                checked = 0
                for offset in range(24):
                    if offset:
                        engine.request("run", steps=1031 * offset)
                    before = engine.request("state")
                    engine.request("irq", source=1)  # Original IRQ1 handler is a bare RTS.
                    state = engine.request("run", steps=1)
                    if state["pc"] != 8:  # Guest critical sections defer delivery.
                        continue
                    after = self.return_from_irq(engine)
                    self.assertEqual(after["pc"], before["pc"])
                    self.assertEqual(after["registers"], before["registers"])
                    checked += 1
                self.assertGreaterEqual(checked, 5)

    def test_original_nested_irq_restores_outer_handler_and_interrupted_task(self):
        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model):
                engine = self.worker(model, directory)
                engine.request("hardware", enabled=True)
                engine.request("reset")
                self.reach_idle(engine)
                for source, priority in ((0, 2), (1, 3)):
                    engine.request("call", entry=0x6590, al=source, ah=priority, steps=10000)
                    engine.request("call", entry=0x65E6, al=source, ah=1, steps=10000)
                task = self.reach_idle(engine)
                engine.request("irq", source=0)
                for _ in range(100):
                    outer = engine.request("run", steps=1)
                    self.assertIsNone(outer["halt"])
                    if outer["pc"] == 0x66:  # Original wrapper has selected and enabled the user bank.
                        break
                else:
                    self.fail("Outer IRQ did not enable its handler bank")
                engine.request("irq", source=1)
                self.assertEqual(engine.request("run", steps=1)["pc"], 8)
                after = self.return_from_irq(engine)
                self.assertEqual(after["pc"], outer["pc"])
                self.assertEqual(after["registers"], outer["registers"])
                for _ in range(1000):
                    after = engine.request("run", steps=1)
                    self.assertIsNone(after["halt"])
                    if after["pc"] == task["pc"]:
                        break
                else:
                    self.fail("Outer IRQ did not resume the interrupted task")
                self.assertEqual(after["registers"], task["registers"])

    def test_original_warm_boot_completes_adc_board_detection_without_application_probe(self):
        for model, directory, setup, board_address in self.profiles():
            with self.subTest(model=model):
                engine = self.worker(model, directory)
                engine.request("hardware", enabled=False)
                engine.request("reset")
                self.reach_idle(engine)
                engine.request("call", entry=0x6365E, steps=10_000_000)
                provisioned = engine.request("call", entry=setup, steps=10_000_000)
                self.assertEqual(provisioned["halt"], "firmware-reset-requested")
                # Both original callbacks map 8-bit154..168 to GRev; choose an interior test voltage.
                engine.request("adc", channel=0, value=640)
                engine.request("hardware", enabled=True)
                engine.request("warm_reset")
                lcd_bytes = 0
                for _ in range(3):
                    state = engine.request("run", steps=10_000_000)
                    self.assertIsNone(state["halt"])
                    self.assertIsNone(state["model_error"])
                    self.assertIsNone(state["last_call"])
                    lcd_bytes += len(state["lcd_bytes"])
                board = engine.request("read", address=board_address, count=1)["values"][0]
                self.assertGreater(board, 0)
                revision, _, label = engine.request("read", address=board, count=3)["values"]
                self.assertEqual(revision, 11)
                self.assertEqual(engine.request("read", address=label, count=4)["values"], list(map(ord, "GRev")))
                self.assertGreater(lcd_bytes, 43)

    def test_original_irq_wrapper_preserves_short_and_maximum_probe_argument_lists(self):
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from iridium.engine import Engine

        for model, directory, _, _ in self.profiles():
            entry = 0xDC040 if model == "9555" else 0xFEF92
            for count in (3, 32):
                with self.subTest(model=model, count=count), tempfile.TemporaryDirectory() as temporary:
                    data = bytearray((directory / "bc5_main.bin").read_bytes())
                    data[entry:entry + 4] = (((count - 1) << 8) | 0x17).to_bytes(2, "little") + b"\xe2\0"
                    path = Path(temporary) / "probe.bin"
                    path.write_bytes(data)
                    with Engine(ENGINE, "bc5", path, model=model) as engine:
                        self.reach_idle(engine)
                        for target, ah in ((0x6590, 3), (0x65E6, 1)):
                            self.assertTrue(engine.request("call", entry=target, al=1, ah=ah,
                                                           steps=10000)["last_call"]["returned"])
                        arguments = [0x1100 + n for n in range(count)]
                        engine.request("irq", source=1)
                        result = engine.request("call", entry=entry, stack=arguments, steps=10000)
                        self.assertTrue(result["last_call"]["returned"])
                        self.assertEqual(result["last_call"]["al"], arguments[-1])
                        self.assertIsNone(result["halt"])

    def test_original_debugger_ui_initialization_keeps_probe_stack_below_irq_frame(self):
        # Function probes and hardware interrupts must use separate supervisor-stack space.
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from iridium.engine import Engine
        from iridium.firmware import load_firmware
        from iridium.session import Session

        def worker(executable, image, firmware, **arguments):
            engine = Engine(executable, image, firmware, **arguments)
            if image == "bc5":
                engine.request("hardware", enabled=True)
                engine.request("reset")
                engine.request("adc", channel=0, value=640)
            return engine

        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model), Session(
                ENGINE, [image for image in load_firmware(directory) if image.image in ("bc5", "avr")],
                engine_factory=worker, modem_image="none"
            ) as session:
                session.control("initialize_ui")
                self.assertTrue(session.ui_initialized)
                self.assertIsNone(session.engines["bc5"].request("state")["halt"])

    def test_original_matrix_contacts_deliver_press_and_release_through_gpio_irq_and_debounce(self):
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from iridium.firmware import load_firmware
        from iridium.session import Session

        codes = ((0x96, 0x82, 0x97, 0x8D, 0x8C),
                 (0x65, 0x66, 0x67, 0x83, 0x2A),
                 (0x68, 0x69, 0x6A, 0xA1, 0x2B),
                 (0x6B, 0x6C, 0x6D, 0xAA, 0x2C),
                 (0x79, 0x64, 0x78, 0xA0, 0x2D))

        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model), Session(
                ENGINE, [image for image in load_firmware(directory) if image.image in ("bc5", "avr")],
                modem_image="none"
            ) as session:
                session.control("initialize_ui")
                engine = session.engines["bc5"]
                last_key = 0xF756 if model == "9575" else 0xF743
                handler = 0x71492 if model == "9575" else 0x713AE
                expected_callback = (handler // 2 + 0x800C)
                self.assertEqual(engine.request("read", address=session.profile.key_callback, count=2)["values"],
                                 [expected_callback >> 16, expected_callback & 0xFFFF])
                state = engine.request("state")
                self.assertEqual(state["gpio"]["key_rows"], 0x7C0,
                                 "Original initialization must leave the electrical scanner armed")
                probe_before = state["last_call"]
                scanner = 0xF716 if model == "9575" else 0xF703
                for row in codes:
                    for code in row:
                        with self.subTest(model=model, code=hex(code)):
                            try:
                                state = engine.request("key", code=code, pressed=True)
                                self.assertNotEqual(state["gpio"]["key_columns"], 0)
                                self.assertNotEqual(state["gpio"]["irq_pending"] & 0x8000, 0)
                                for _ in range(10):
                                    session.control("step", steps=50000)
                                    state = engine.state
                                    self.assertIsNone(state["halt"])
                                    self.assertIsNone(state["model_error"])
                                    if engine.request("read", address=scanner, count=2)["values"] == [1, code]:
                                        break
                                else:
                                    self.fail(f"Original GPIO IRQ/debounce did not scan key {code:#x}")
                                # The ordinary first soft key also reaches the actual UI callback.
                                # Later keys may select global actions or close the current screen.
                                if code == 0x96:
                                    for _ in range(10):
                                        if engine.request("read", address=last_key, count=1)["values"] == [code]:
                                            break
                                        session.control("step", steps=50000)
                                    else:
                                        self.fail("Original UI callback did not receive the left soft key")
                            finally:
                                state = engine.request("key", code=code, pressed=False)
                                self.assertEqual(state["gpio"]["key_contacts"], 0)
                                for _ in range(10):
                                    session.control("step", steps=50000)
                                    state = engine.state
                                    self.assertIsNone(state["halt"])
                                    self.assertIsNone(state["model_error"])
                                    if engine.request("read", address=scanner, count=1)["values"] == [0]:
                                        break
                                else:
                                    self.fail(f"Original GPIO IRQ/debounce did not release key {code:#x}")
                            if code == 0x96:
                                for _ in range(10):
                                    if engine.request("read", address=last_key, count=1)["values"] == [0]:
                                        break
                                    session.control("step", steps=50000)
                                else:
                                    self.fail("Original UI callback did not release the left soft key")
                            self.assertEqual(state["last_call"], probe_before)

    def test_sos_is_not_a_bc5_matrix_contact_on_either_profile(self):
        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model):
                engine = self.worker(model, directory)
                from iridium.engine import EngineError
                engine.request("key", code=0x96, pressed=True)
                before = engine.request("state")
                for pressed in (True, False):
                    with self.assertRaisesRegex(EngineError, "UnknownKey"):
                        engine.request("key", code=0xAB, pressed=pressed)
                    after = engine.request("state")
                    self.assertEqual(after["steps"], before["steps"])
                    self.assertEqual(after["registers"], before["registers"])
                    self.assertEqual(after["gpio"], before["gpio"])

    def test_original_power_button_is_released_high_and_shutdown_requires_a_low_hold(self):
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from iridium.firmware import load_firmware
        from iridium.session import Session

        for model, directory, _, _ in self.profiles():
            with self.subTest(model=model), Session(
                ENGINE, [image for image in load_firmware(directory) if image.image in ("bc5", "avr")],
                modem_image="none"
            ) as session:
                session.control("initialize_ui")
                bc5, avr = session.engines["bc5"], session.engines["avr"]
                port, bit = session.profile.power_pin
                inputs = avr.request("pin_state")["inputs"][port]
                self.assertNotEqual(inputs & (1 << bit), 0, "Released power button must be high")
                power_pointer = 0xF72F if model == "9575" else 0xF71C
                power = bc5.request("read", address=power_pointer, count=1)["values"][0]
                ui_lock = 0xF74C if model == "9575" else 0xF739
                session.control("step", steps=5_000_000)
                self.assertIsNone(bc5.state["halt"])
                self.assertEqual(bc5.request("read", address=power, count=1)["values"], [3])
                self.assertEqual(bc5.request("read", address=ui_lock, count=1)["values"], [0])
                try:
                    avr.request("pins", port=port, value=inputs & ~(1 << bit))
                    session.control("step", steps=5_000_000)
                    self.assertIsNone(bc5.state["halt"])
                    self.assertIn(bc5.request("read", address=power, count=1)["values"][0], (2, 8))
                    self.assertEqual(bc5.request("read", address=ui_lock, count=1)["values"], [1])
                finally:
                    avr.request("pins", port=port, value=inputs)


if __name__ == "__main__":
    unittest.main()
