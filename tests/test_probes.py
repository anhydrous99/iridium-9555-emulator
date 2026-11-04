"""Machine-code regressions for public board probes and native fault recovery."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from iridium.engine import Engine, EngineError
from iridium.firmware import parse_firmware
from iridium.session import Session


EXECUTABLE = Path(__file__).resolve().parents[1] / "zig-out/bin/iridium-core"


def operand(op, value):
    return [(((value + 0x80) >> 8) & 255) << 8, ((value & 255) << 8) | op]


def images(model, *, receive=True, valid_handle=True):
    bc5_size, avr_size = (0x310FBA, 8678) if model == "9555" else (0x36BB22, 14296)
    data = bytearray(bc5_size)
    data[:2] = b"\xe0\0"
    words = []
    for address, value in ((0x62, 0x8000), (0x61, 0x8010),
                           (0xFE93 if receive else 0xFE94, int(valid_handle)),
                           (0xFDBE, 1), (0xFDBF, 0x440),
                           (0xFDC3, int(receive)), (0xFDC1, 1)):
        words.extend(operand(0x14, value) + operand(0x25, address))
    words.append(0xE2)
    code = b"".join(word.to_bytes(2, "little") for word in words)
    data[0x100:0x100 + len(code)] = code
    avr = b"".join(word.to_bytes(2, "little") for word in (0xE400, 0x9300, 0x4C, 0xCFFF))
    return [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
            parse_firmware(avr.ljust(avr_size, b"\xff"), "avr.bin", "avr", model=model)]


@unittest.skipUnless(EXECUTABLE.is_file(), "Build the native executor first")
class ProbeTests(unittest.TestCase):
    def test_default_continuation_uses_the_native_remaining_peripheral_budget(self):
        for model in ("9555", "9575"):
            for limit in (15, 1014):
                for explicit in (False, True):
                    with self.subTest(model=model, limit=limit, explicit=explicit), Session(EXECUTABLE, images(model)) as session:
                        session.control("step", 16)
                        for address, values in ((0xA002, [0x100, 0]), (0xA100, [8])):
                            session.probe("bc5", "write", {"address": address, "values": values})
                        first = session.engines["bc5"].request("call", entry=0x100, steps=limit)
                        self.assertEqual(first["last_call"]["steps"], 14)
                        self.assertTrue(first["last_call"]["pending"])
                        before = session.engines["avr"].state["steps"]
                        arguments = {"steps": limit - 14} if explicit else {}
                        if limit == 15:
                            with self.assertRaisesRegex(EngineError, "Peripheral wait exceeded"):
                                session.probe("bc5", "call_resume", arguments)
                            call = session.engines["bc5"].state["last_call"]
                            self.assertTrue(call["pending"])
                            self.assertEqual(call["steps"], 14)
                            self.assertEqual(call["remaining_steps"], 1)
                            self.assertEqual(session.engines["avr"].state["steps"] - before, 1)
                        else:
                            result = session.probe("bc5", "call_resume", arguments)
                            self.assertTrue(result["last_call"]["returned"])
                            self.assertEqual(result["last_call"]["steps"], 15)
                            self.assertEqual(result["last_call"]["remaining_steps"], limit - 15)
                            self.assertEqual(session.engines["avr"].state["steps"] - before, 129)

    def test_public_step_partition_preserves_spi_payload_and_instruction_totals(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            words = []
            for address, value in ((0x62, 0x8000), (0x61, 0x8010), (0xFE94, 1),
                                   (0xFDBE, 1), (0xFDBF, 0x440), (0xFDC3, 0), (0xFDC1, 6)):
                words += operand(0x14, value) + operand(0x25, address)
            words.append(0x00E0)
            receiver = [0xE0A0, 0xE0B2, 0xE400, 0x9300, 0x4C, 0x9110, 0x4D,
                        0xFF17, 0xCFFC, 0x9120, 0x4E, 0x932D, 0xCFF8]
            firmware = [parse_firmware(b"".join(w.to_bytes(2, "little") for w in words).ljust(len(bc5.data), b"\0"),
                                       "bc5.bin", "bc5", model=model),
                        parse_firmware(b"".join(w.to_bytes(2, "little") for w in receiver).ljust(len(avr.data), b"\xff"),
                                       "avr.bin", "avr", model=model)]
            for partition in (1, 3, 127, 128, 4096):
                with self.subTest(model=model, partition=partition), Session(EXECUTABLE, firmware) as session:
                    for address, values in ((0xA002, [0x100, 0]), (0xA100, [8]),
                                             (0xA200, [0x2211, 0x4433, 0x6655])):
                        session.probe("bc5", "write", {"address": address, "values": values})
                    remaining = 1024
                    while remaining:
                        steps = min(partition, remaining)
                        session.control("step", steps)
                        remaining -= steps
                    self.assertEqual(session.probe("avr", "read", {"address": 0x200, "count": 6})["values"],
                                     [17, 34, 51, 68, 85, 102])
                    self.assertEqual([worker.state["steps"] for worker in session.engines.values()], [1024, 1024])
                    self.assertEqual(session.spi_link.transferred, 6)
                    self.assertFalse(session.spi_link.pending)

    def test_explicit_step_advances_live_auxiliaries_when_primary_is_already_halted(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            data[0x100:0x102] = b"\xe0\0"
            receiver = [0] * 5000 + [0xE52A, 0xCFFF]  # r18=0x5A after more than one board quantum
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                        parse_firmware(b"".join(word.to_bytes(2, "little") for word in receiver).ljust(
                            0x4000 if model == "9555" else 0x20000, b"\xff"), "avr.bin", "avr", model=model)]
            for image, size in (("trx", 0x260760), ("ptt", 0xA7BF8)):
                firmware.append(parse_firmware(b"\x10\x80\0\0\x01\0\0\0".ljust(size, b"\xff"),
                                               image + ".bin", image, model=model))
            for modem in ("none", "trx", "ptt"):
                with self.subTest(model=model, modem=modem), Session(EXECUTABLE, firmware, modem_image=modem) as session:
                    primary = session.engines["bc5"]
                    stopped = primary.request("call", entry=0x100, steps=1)
                    self.assertEqual(stopped["halt"], "probe-did-not-return")
                    before = {image: worker.state["steps"] for image, worker in session.engines.items()}
                    session.control("step", 9000)
                    self.assertEqual(primary.state["steps"], before["bc5"])
                    self.assertEqual(primary.state["halt"], stopped["halt"])
                    self.assertEqual(session.engines["avr"].state["steps"] - before["avr"], 9000)
                    self.assertEqual(session.engines["avr"].state["registers"][18], 0x5A)
                    for image in ("trx", "ptt"):
                        self.assertEqual(session.engines[image].state["steps"] - before[image],
                                         9000 if modem in ("none", image) else 0)

    def test_ordinary_steps_stop_on_new_halts_even_after_an_existing_halt_or_reset(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            for scenario in ("live", "bc5_halted", "avr_reset"):
                data = bytearray(bc5.data)
                data[0x100:0x102] = b"\xe0\0"
                if scenario == "avr_reset":
                    words = []
                    for address, value in ((0x61, 0x8000), (0x62, 0), (0x62, 0x8000)):
                        words += operand(0x14, value) + operand(0x25, address)
                    words.append(0x00E0)
                    data[:len(words) * 2] = b"".join(word.to_bytes(2, "little") for word in words)
                firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                            parse_firmware(b"\xff\xff".ljust(len(avr.data), b"\xff"), "avr.bin", "avr", model=model)]
                with self.subTest(model=model, scenario=scenario), Session(EXECUTABLE, firmware) as session:
                    primary, auxiliary = session.engines["bc5"], session.engines["avr"]
                    if scenario == "bc5_halted":
                        primary.request("call", entry=0x100, steps=1)
                    elif scenario == "avr_reset":
                        self.assertIsNotNone(auxiliary.request("run", steps=1)["halt"])
                    before = primary.state["steps"]
                    session.control("step", 9000)
                    self.assertIsNotNone(auxiliary.state["halt"])
                    self.assertEqual(primary.state["steps"] - before, 0 if scenario == "bc5_halted" else 4096)
                    self.assertEqual(session.spi_link.resets, int(scenario == "avr_reset"))

    def test_spi_bytes_are_consumed_between_clocks_on_every_board_execution_path(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            for operation in ("call", "call_resume", "idle", "step"):
                for count in (2, 3, 6, 35):
                    data = bytearray(bc5.data)
                    words = []
                    for address, value in ((0x62, 0x8000), (0x61, 0x8010), (0xFE94, 1),
                                           (0xFDBE, 1), (0xFDBF, 0x440), (0xFDC3, 0), (0xFDC1, count)):
                        words.extend(operand(0x14, value) + operand(0x25, address))
                    if operation == "idle":
                        words += operand(0x15, 0xFE95) + [0xFEF0]  # Wait for DMA before entering idle.
                        words += operand(0xE0, 0xB774 // 2 - len(words) - 1)
                        data[0xB774:0xB776] = b"\xe0\0"
                    else:
                        words.append(0x00E0 if operation == "step" else 0x00E2)
                    entry = 0 if operation in ("idle", "step") else 0x100
                    data[entry:entry + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
                    # Poll SPIF, read SPDR and append each completed byte through X.
                    receiver = [0xE0A0, 0xE0B2, 0xE400, 0x9300, 0x4C, 0x9110, 0x4D,
                                0xFF17, 0xCFFC, 0x9120, 0x4E, 0x932D, 0xCFF8]
                    firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                                parse_firmware(b"".join(w.to_bytes(2, "little") for w in receiver).ljust(len(avr.data), b"\xff"),
                                               "avr.bin", "avr", model=model)]
                    with self.subTest(model=model, operation=operation, count=count), Session(EXECUTABLE, firmware) as session:
                        payload = bytes((0x11 * (i + 1)) & 255 for i in range(count))
                        packed = payload + bytes(count % 2)
                        values = [int.from_bytes(packed[i:i + 2], "little") for i in range(0, len(packed), 2)]
                        for address, value in ((0xA002, [0x100, 0]), (0xA100, [8]), (0xA200, values)):
                            session.probe("bc5", "write", {"address": address, "values": value})
                        if operation in ("call", "call_resume"):
                            session.control("step", 100)
                        worker = session.engines["avr"]
                        clocks = []
                        request = worker.request
                        def record(op, **arguments):
                            response = request(op, **arguments)
                            if op == "spi" and response.get("value") is not None:
                                clocks.append(worker.state["steps"])
                            return response
                        with patch.object(worker, "request", record):
                            if operation == "idle":
                                session.control("step", 32)
                                session._idle(session.engines["bc5"])
                                self.assertTrue(session.engines["bc5"].state["at_idle"])
                            elif operation == "step":
                                session.control("step", 20000)
                            else:
                                budget = 1000 if count <= 6 else 20000
                                if operation == "call_resume":
                                    first = session.engines["bc5"].request("call", entry=entry, steps=budget, quantum=1)
                                    self.assertTrue(first["last_call"]["pending"])
                                    result = session.probe("bc5", "call_resume", {"steps": budget - 1})
                                else:
                                    result = session.probe("bc5", "call", {"entry": entry, "steps": budget})
                                self.assertTrue(result["last_call"]["returned"])
                        worker.request("run", steps=128)
                        self.assertEqual(session.probe("avr", "read", {"address": 0x200, "count": count})["values"], list(payload))
                        self.assertEqual(len(clocks), count)
                        self.assertTrue(all(b - a >= 128 for a, b in zip(clocks, clocks[1:])), clocks)
                        self.assertFalse(session.spi_link.pending)

    def test_ordinary_steps_apply_reset_before_avr_execution_regardless_of_load_order(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            words = operand(0x14, 0x8000) + operand(0x25, 0x61) + [0x00E0]
            data[:len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            words = operand(0x14, 0x8000) + operand(0x25, 0x62) + [0x00E2]
            data[0x200:0x200 + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            # POR starts a write; EXTRF skips it and only reads the retained EEPROM.
            receiver = [0x9100, 0x54, 0xFD01, 0xC006, 0xE50A, 0x9300, 0x40,
                        0x9AFA, 0x9AF9, 0xCFFF, 0x9AF8, 0x9120, 0x40, 0xCFFF]
            primary = parse_firmware(bytes(data), "bc5.bin", "bc5", model=model)
            auxiliary = parse_firmware(b"".join(w.to_bytes(2, "little") for w in receiver).ljust(len(avr.data), b"\xff"),
                                       "avr.bin", "avr", model=model)
            for modem in ("none", "trx", "ptt"):
                for avr_first in (False, True):
                    for quantum in (1, 20):
                        firmware = [auxiliary, primary] if avr_first else [primary, auxiliary]
                        if modem != "none":
                            size = 0x260760 if modem == "trx" else 0xA7BF8
                            firmware.append(parse_firmware(b"\x10\x80\0\0\x01\0\0\0".ljust(size, b"\xff"),
                                                           modem + ".bin", modem, model=model))
                        with self.subTest(model=model, modem=modem, avr_first=avr_first, quantum=quantum), Session(EXECUTABLE, firmware, modem_image=modem) as session:
                            for _ in range(20 // quantum):
                                session.control("step", quantum)
                            self.assertTrue(session.spi_link.hold_reset)
                            session.control("step", 30000)
                            self.assertEqual(session.engines["avr"].state["steps"], 0)
                            self.assertTrue(session.probe("bc5", "call", {"entry": 0x200, "steps": 100})["last_call"]["returned"])
                            session.control("step", 20)
                            self.assertFalse(session.spi_link.hold_reset)
                            self.assertEqual(session.engines["avr"].state["registers"][18], 0xFF)

    def test_idle_applies_reset_from_its_final_short_chunk(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            start, idle = 0xB750, 0xB774
            data[:4] = b"".join(w.to_bytes(2, "little") for w in operand(0xE0, start // 2 - 1))
            words = []
            for address, value in ((0x62, 0x8000), (0x61, 0x8000), (0x62, 0)):
                words.extend(operand(0x14, value) + operand(0x25, address))
            words += [0x0114] * ((idle - start) // 2 - len(words))
            data[start:idle] = b"".join(w.to_bytes(2, "little") for w in words)
            data[idle:idle + 2] = b"\xe0\0"
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model), avr]
            with self.subTest(model=model), Session(EXECUTABLE, firmware) as session:
                session._idle(session.engines["bc5"])
                self.assertTrue(session.engines["bc5"].state["at_idle"])
                self.assertTrue(session.spi_link.hold_reset)
                self.assertEqual(session.engines["avr"].state["steps"], 0)

    def test_one_step_continuations_clock_only_their_executed_instructions(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            data[0x100:0x106] = b"\x14\x01\x14\x02\xe2\0"
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model), avr]
            with self.subTest(model=model), Session(EXECUTABLE, firmware) as session:
                primary = session.engines["bc5"]
                first = primary.request("call", entry=0x100, steps=100, quantum=1)
                self.assertTrue(first["last_call"]["pending"])
                for pending, elapsed in ((True, 1), (False, 1)):
                    before = session.engines["avr"].state["steps"]
                    result = session.probe("bc5", "call_resume", {"steps": 1})
                    self.assertEqual(result["last_call"]["pending"], pending)
                    self.assertEqual(session.engines["avr"].state["steps"] - before, elapsed)
                self.assertTrue(result["last_call"]["returned"])
                self.assertEqual(result["last_call"]["steps"], 3)

    def test_serial_wait_exhausts_peripheral_budget_before_executing_more_probe_code(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model, receive=False)
            silent = parse_firmware(b"\xff\xcf".ljust(len(avr.data), b"\xff"), "avr.bin", "avr", model=model)
            with self.subTest(model=model), Session(EXECUTABLE, [bc5, silent]) as session:
                for address, values in ((0xA002, [0x100, 0]), (0xA100, [8]), (0xA200, [65])):
                    session.probe("bc5", "write", {"address": address, "values": values})
                worker = session.engines["avr"]
                with patch.object(worker, "request", wraps=worker.request) as requests:
                    with self.assertRaisesRegex(EngineError, "Peripheral wait exceeded"):
                        session.probe("bc5", "call", {"entry": 0x100, "steps": 20})
                    amounts = [call.kwargs["steps"] for call in requests.call_args_list
                               if call.args[0] == "run"]
                self.assertEqual(sum(amounts), 20)
                state = session.engines["bc5"].request("state")
                self.assertTrue(state["last_call"]["pending"])
                self.assertTrue(state["serial_waiting"])
                self.assertLess(state["last_call"]["steps"], 20)
                self.assertIsNone(state["halt"])

    def test_terminal_probes_apply_reset_before_peripheral_execution(self):
        # Before EXTRF, AVR writes EEPROM; after EXTRF, it only reads it into r18.
        receiver = [0x9100, 0x54, 0xFD01, 0xC006, 0xE50A, 0x9300, 0x40,
                    0x9AFA, 0x9AF9, 0xCFFF, 0x9AF8, 0x9120, 0x40, 0xCFFF]
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            for entry, setup in ((0x100, ((0x62, 0x8000), (0x61, 0x8000), (0x62, 0))),
                                 (0x200, ((0x62, 0x8000),))):
                words = []
                for address, value in setup:
                    words.extend(operand(0x14, value) + operand(0x25, address))
                words.append(0x00E2)
                data[entry:entry + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                        parse_firmware(b"".join(w.to_bytes(2, "little") for w in receiver).ljust(len(avr.data), b"\xff"),
                                       "avr.bin", "avr", model=model)]
            for modem in ("none", "trx", "ptt"):
                loaded = list(firmware)
                if modem != "none":
                    size = 0x260760 if modem == "trx" else 0xA7BF8
                    loaded.append(parse_firmware(b"\x10\x80\0\0\x01\0\0\0".ljust(size, b"\xff"),
                                                 modem + ".bin", modem, model=model))
                for operation in ("call", "call_resume"):
                    with self.subTest(model=model, modem=modem, operation=operation), Session(EXECUTABLE, loaded, modem_image=modem) as session:
                        if operation == "call_resume":
                            first = session.engines["bc5"].request("call", entry=0x100, steps=100, quantum=1)
                            self.assertTrue(first["last_call"]["pending"])
                            result = session.probe("bc5", operation, {"steps": 99})
                        else:
                            result = session.probe("bc5", operation, {"entry": 0x100, "steps": 100})
                        self.assertTrue(result["last_call"]["returned"])
                        self.assertTrue(session.spi_link.hold_reset)
                        self.assertEqual(session.engines["avr"].state["steps"], 0)
                        session.control("step", 30100)
                        self.assertEqual(session.engines["avr"].state["steps"], 0)
                        session.probe("bc5", "call", {"entry": 0x200, "steps": 100})
                        self.assertFalse(session.spi_link.hold_reset)
                        session.control("step", 100)
                        self.assertEqual(session.engines["avr"].state["registers"][18], 0xFF)

    def test_yielding_reset_probes_discard_modem_backlog_and_keep_later_traffic(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            for image, size in (("trx", 0x260760), ("ptt", 0xA7BF8)):
                for operation, later in (("call", False), ("call_resume", False), ("call", True)):
                    data = bytearray(bc5.data)
                    words = []
                    for address, value in ((0x62, 0x8000), (0x61, 0x8000), (0x62, 0), (0x62, 0x8000)):
                        words.extend(operand(0x14, value) + operand(0x25, address))
                    words += [0x0114] * 5000 + [0x00E2]
                    data[0x100:0x100 + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
                    # Cold startup sleeps with reception disabled; EXTRF enables USART0.
                    receiver = [0x9100, 0x54, 0xFF01, 0xC00A, 0xE100, 0x9300, 0xC1,
                                0x9110, 0xC0, 0xFF17, 0xCFFC, 0x9120, 0xC6, 0xCFFF,
                                0xE005, 0x9300, 0x53, 0x9588, 0xCFFE]
                    sender = [0x01000000] * (1200 if later else 0)
                    sender += [0x03200000, 0x82106200, 0x84102051, 0xC4206000, 0x10800000, 0x01000000]
                    firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                                parse_firmware(b"".join(w.to_bytes(2, "little") for w in receiver).ljust(len(avr.data), b"\xff"),
                                               "avr.bin", "avr", model=model),
                                parse_firmware(b"".join(w.to_bytes(4, "big") for w in sender).ljust(size, b"\xff"),
                                               image + ".bin", image, model=model)]
                    with self.subTest(model=model, image=image, operation=operation, later=later), Session(EXECUTABLE, firmware, modem_image=image) as session:
                        session.control("step", 128)
                        self.assertEqual(session.modem_link.state()["pending"], [0, 0 if later else 1])
                        if operation == "call_resume":
                            first = session.engines["bc5"].request("call", entry=0x100, steps=10000, quantum=1)
                            self.assertTrue(first["last_call"]["pending"])
                            result = session.probe("bc5", "call_resume", {"steps": 9999})
                        else:
                            result = session.probe("bc5", "call", {"entry": 0x100, "steps": 10000})
                        self.assertTrue(result["last_call"]["returned"])
                        session.control("step", 256)
                        self.assertEqual(session.engines["avr"].state["registers"][18], 81 if later else 0)
                        self.assertEqual(session.spi_link.resets, 1)
                        self.assertIsNone(session.engines["avr"].state["halt"])

    def test_flash_programming_advances_while_reset_blocks_avr_execution(self):
        for model, size, boot in (("9555", 0x4000, 0x3800), ("9575", 0x20000, 0x1E000)):
            bc5 = images(model)[0]
            data = bytearray(bc5.data)
            for entry, setup in ((0x100, ((0x62, 0x8000), (0x61, 0x8000), (0x62, 0))),
                                 (0x200, ((0x62, 0x8000),))):
                words = []
                for address, value in setup:
                    words.extend(operand(0x14, value) + operand(0x25, address))
                words.append(0x00E2)
                data[entry:entry + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            # Yield enough board quanta to exceed the programming interval.
            words = [0x0114] * 13000 + [0x00E2]
            data[0x300:0x300 + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            words = [0x0114] * 4000 + [0x00E2]
            data[0x20000:0x20000 + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            # Program 0xA55A at byte 0x100; after EXTRF park before issuing more SPM.
            words = [0x9110, 0x54, 0xFD11, 0xCFFF, 0xE0E0, 0xE0F1,
                     0xE50A, 0x2E00, 0xEA05, 0x2E10, 0xE001, 0x9300, 0x57, 0x95E8,
                     0xE005, 0x9300, 0x57, 0x95E8, 0x9130, 0x57, 0xCFFD]
            avr = bytearray(b"\xff" * size)
            avr[boot:boot + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                        parse_firmware(bytes(avr), "avr.bin", "avr", model=model)]
            for service in ("step", "probe", "short-probes", "short-resumes"):
                with self.subTest(model=model, service=service), Session(EXECUTABLE, firmware) as session:
                    session.probe("avr", "fuses", {"low": 0x77, "high": 0x98, "extended": 0xFE, "lock": 0xFF})
                    session.control("reset")
                    session.control("step", 30)
                    self.assertEqual(session.engines["avr"].state["registers"][19], 0x45)
                    self.assertTrue(session.probe("bc5", "call", {"entry": 0x100, "steps": 100})["last_call"]["returned"])
                    session.control("step", 1)
                    self.assertTrue(session.spi_link.hold_reset)
                    before = session.engines["avr"].state
                    self.assertEqual(session.probe("avr", "program_read", {"address": 0x100, "count": 2})["values"], [255, 255])
                    worker = session.engines["avr"]
                    with patch.object(worker, "request", wraps=worker.request) as requests:
                        if service == "step":
                            session.control("step", 100000)
                            clocked = 100000
                        elif service == "probe":
                            result = session.probe("bc5", "call", {"entry": 0x300, "steps": 100000, "quantum": 100000000})
                            self.assertTrue(result["last_call"]["returned"])
                            clocked = result["last_call"]["steps"]
                        else:
                            clocked = 0
                            for _ in range(4):
                                arguments = {"entry": 0x20000, "steps": 10000}
                                if service == "short-resumes":
                                    first = session.engines["bc5"].request("call", **arguments, quantum=1)
                                    result = session.probe("bc5", "call_resume", {"steps": 10000})
                                    clocked += result["last_call"]["steps"] - first["last_call"]["steps"]
                                else:
                                    result = session.probe("bc5", "call", arguments)
                                    clocked += result["last_call"]["steps"]
                                self.assertTrue(result["last_call"]["returned"])
                        amounts = [call.kwargs["cycles"] for call in requests.call_args_list
                                   if call.args[0] == "reset_clock"]
                        self.assertEqual(sum(amounts), clocked)
                        self.assertTrue(all(0 < amount <= 4096 for amount in amounts))
                    after = session.engines["avr"].state
                    self.assertEqual((after["steps"], after["cycles"], after["registers"]),
                                     (before["steps"], before["cycles"], before["registers"]))
                    self.assertTrue(session.spi_link.hold_reset)
                    self.assertEqual(session.probe("avr", "program_read", {"address": 0x100, "count": 2})["values"], [90, 165])
                    self.assertTrue(session.probe("bc5", "call", {"entry": 0x200, "steps": 100})["last_call"]["returned"])
                    session.control("step", 1)  # Observe reset release before scheduling AVR again.
                    self.assertFalse(session.spi_link.hold_reset)
                    session.control("step", 100)
                    self.assertGreater(session.engines["avr"].state["steps"], before["steps"])

    def test_reset_and_avr_replacement_baseline_old_reset_pulses(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            words = []
            for address, value in ((0x61, 0x8000), (0x62, 0x8000)):
                words.extend(operand(0x14, value) + operand(0x25, address))
            words.append(0x00E2)
            data[0x100:0x100 + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                        parse_firmware(b"\x00\x91\x54\0\xfd\xcf".ljust(len(avr.data), b"\xff"), "avr.bin", "avr", model=model)]
            for operation in ("reset", "replace"):
                with self.subTest(model=model, operation=operation), Session(EXECUTABLE, firmware) as session:
                    session.control("step", 1)
                    self.assertTrue(session.probe("bc5", "call", {"entry": 0x100, "steps": 100})["last_call"]["returned"])
                    session.control("step", 2)
                    self.assertEqual(session.spi_link.resets, 1)
                    if operation == "reset":
                        session.control("reset")
                    else:
                        session.load(firmware[1])
                    session.control("step", 10000)
                    state = session.engines["avr"].state
                    self.assertEqual(state["registers"][16], 1)
                    self.assertEqual(state["steps"], 10000)
                    self.assertEqual(session.spi_link.resets, 0)
                    self.assertTrue(session.probe("bc5", "call", {"entry": 0x100, "steps": 100})["last_call"]["returned"])
                    session.control("step", 2)
                    self.assertEqual(session.spi_link.resets, 1)
                    session.control("step", 1)
                    self.assertEqual(session.engines["avr"].state["registers"][16], 3)

    def test_continuation_services_gpio_readiness_within_original_budget(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            data = bytearray(bc5.data)
            words = operand(0x15, 0xFFC2) + operand(0xC4, 0x1000) + [0xFCF4, 0x00E2]
            data[0x100:0x100 + len(words) * 2] = b"".join(w.to_bytes(2, "little") for w in words)
            ddr, port, value = (0x24, 0x25, 1) if model == "9555" else (0x21, 0x22, 0x80)
            words = [0xE000 | ((value & 0xF0) << 4) | (value & 15), 0x9300, ddr, 0x9300, port, 0xCFFF]
            firmware = [parse_firmware(bytes(data), "bc5.bin", "bc5", model=model),
                        parse_firmware(b"".join(w.to_bytes(2, "little") for w in words).ljust(len(avr.data), b"\xff"),
                                       "avr.bin", "avr", model=model)]
            with self.subTest(model=model), Session(EXECUTABLE, firmware) as session:
                session.spi_link.exchange()
                first = session.engines["bc5"].request("call", entry=0x100, steps=10000, quantum=1)
                self.assertTrue(first["last_call"]["pending"])
                self.assertFalse(first["serial_waiting"])
                before = [worker.state["steps"] for worker in session.engines.values()]
                for arguments in ({"steps": 100000001}, {"steps": 0}, {"steps": True},
                                  {"steps": "bad"}, {"steps": 9999, "quantum": 0},
                                  {"steps": 9999, "quantum": 100000001}):
                    with self.assertRaises(EngineError):
                        session.probe("bc5", "call_resume", arguments)
                    self.assertEqual([worker.state["steps"] for worker in session.engines.values()], before)
                resumed = session.probe("bc5", "call_resume", {"steps": 9999})
                self.assertTrue(resumed["last_call"]["returned"])
                self.assertLessEqual(resumed["last_call"]["steps"], 10000)
                self.assertGreater(session.engines["avr"].state["steps"], 0)

    def test_dma_does_not_deliver_next_byte_after_chip_select_is_released(self):
        for model in ("9555", "9575"):
            for selected in (True, False):
                bc5, avr = images(model)
                words = []
                setup = [(0x62, 0x8000), (0x61, 0x8010), (0xFE94, 1), (0xFDBE, 1),
                         (0xFDBF, 0x440), (0xFDC0, 0), (0xFDC3, 0), (0xFDC1, 2),
                         (0x62, 0x8000 if selected else 0x8010)]
                for address, value in setup:
                    words.extend(operand(0x14, value) + operand(0x25, address))
                words.append(0x00E0)
                firmware = [parse_firmware(b"".join(w.to_bytes(2, "little") for w in words).ljust(len(bc5.data), b"\0"),
                                           "bc5.bin", "bc5", model=model)]
                words = [0xE400, 0x9300, 0x4C, 0x9110, 0x4E, 0xCFFD]
                firmware.append(parse_firmware(b"".join(w.to_bytes(2, "little") for w in words).ljust(len(avr.data), b"\xff"),
                                               "avr.bin", "avr", model=model))
                with self.subTest(model=model, selected=selected), Session(EXECUTABLE, firmware) as session:
                    for address, values in ((0xA002, [0x100, 0]), (0xA100, [8]), (0xA200, [0x2211])):
                        session.probe("bc5", "write", {"address": address, "values": values})
                    session.control("step", 16)
                    self.assertEqual(session.spi_link.transferred, 1)
                    session.control("step", 2)
                    session.control("step", 2)
                    self.assertEqual(session.spi_link.transferred, 1)
                    session.control("step", 128)
                    session.control("step", 16)  # Let the receiver consume a selected second byte.
                    self.assertEqual(session.spi_link.transferred, 2 if selected else 1)
                    self.assertEqual(session.engines["avr"].state["registers"][17], 0x22 if selected else 0x11)
                    self.assertIsNone(session.engines["avr"].state["halt"])

    def test_held_input_does_not_block_replacement_of_its_dead_worker(self):
        for model in ("9555", "9575"):
            for image, key in (("bc5", "1"), ("avr", "power")):
                firmware = images(model)
                with self.subTest(model=model, image=image), Session(EXECUTABLE, firmware) as session:
                    session.key(key, True, client_id="tab-a", sequence=1, epoch=session.key_epoch)
                    old = session.engines[image]
                    old._process.kill()
                    old._process.wait()
                    session.load(next(item for item in firmware if item.image == image))
                    self.assertIsNot(session.engines[image], old)
                    self.assertEqual(session.keys, set())

    def test_standalone_cpu_probe_can_resume_without_a_serial_peer(self):
        for model in ("9555", "9575"):
            bc5 = images(model)[0]
            data = bytearray(bc5.data)
            data[0x100:0x106] = b"\x14\x01\x14\x02\xe2\0"
            firmware = parse_firmware(bytes(data), "bc5.bin", "bc5", model=model)
            with self.subTest(model=model), Session(EXECUTABLE, [firmware]) as session:
                first = session.probe("bc5", "call", {"entry": 0x100, "steps": 100, "quantum": 1})
                self.assertTrue(first["last_call"]["pending"])
                second = session.probe("bc5", "call_resume", {"steps": 1})
                self.assertTrue(second["last_call"]["pending"])
                self.assertEqual(second["last_call"]["steps"], 2)
                returned = session.probe("bc5", "call_resume", {"steps": 1})
                self.assertTrue(returned["last_call"]["returned"])
                self.assertEqual(returned["last_call"]["al"], 2)
                self.assertEqual(returned["last_call"]["steps"], 3)

    def test_public_call_and_continuation_service_spi_without_exceeding_instruction_budget(self):
        for model in ("9555", "9575"):
            with self.subTest(model=model), Session(EXECUTABLE, images(model)) as session:
                session.control("step", 16)
                for address, values in ((0xA002, [0x100, 0]), (0xA100, [8])):
                    session.probe("bc5", "write", {"address": address, "values": values})
                result = session.probe("bc5", "call", {"entry": 0x100, "steps": 1000})
                self.assertTrue(result["last_call"]["returned"])
                self.assertEqual(result["last_call"]["steps"], 15)
                self.assertGreater(session.state()["spi_link"]["transferred"], 0)
                primary = session.engines["bc5"]
                paused = primary.request("call", entry=0x100, steps=1000, quantum=1)
                self.assertTrue(paused["last_call"]["pending"])
                chunk = session.probe("bc5", "call_resume", {"steps": 1})
                self.assertTrue(chunk["last_call"]["pending"])
                self.assertEqual(chunk["last_call"]["steps"], 2)
                result = session.probe("bc5", "call_resume", {"steps": 1000})
                self.assertTrue(result["last_call"]["returned"])
                self.assertEqual(result["last_call"]["steps"], 15)
                before = [worker.state["steps"] for worker in session.engines.values()]
                for arguments in ({}, {"entry": 0x100, "steps": "bad"},
                                  {"entry": 0x100, "steps": True},
                                  {"entry": 0x100, "steps": -1},
                                  {"entry": 0x100, "quantum": 0},
                                  {"entry": 0x100, "quantum": 100000001}):
                    with self.assertRaises(EngineError):
                        session.probe("bc5", "call", arguments)
                    self.assertEqual([worker.state["steps"] for worker in session.engines.values()], before)

    def test_serial_mmu_fault_finishes_probe_and_restores_paused_cpu_and_stack(self):
        for model in ("9555", "9575"):
            for receive in (False, True):
                with self.subTest(model=model, receive=receive), tempfile.TemporaryDirectory() as temporary:
                    firmware = images(model, receive=receive, valid_handle=False)[0]
                    path = Path(temporary) / "bc5.bin"
                    path.write_bytes(firmware.data)
                    with Engine(EXECUTABLE, "bc5", path, model=model) as engine:
                        engine.request("hardware", serial_peer=True)
                        engine.request("write", address=0xFCC0, values=[0xBEEF])
                        saved = engine.request("state")["registers"]
                        pending = engine.request("call", entry=0x100, stack=[0x1234], steps=100)
                        self.assertTrue(pending["last_call"]["pending"])
                        if receive:
                            byte = engine.request("serial")
                            fault = engine.request("serial", received=65, sequence=byte["sequence"])
                        else:
                            fault = engine.request("serial")
                        self.assertIn("mmu:InvalidHandle", fault["halt"])
                        self.assertFalse(fault["last_call"]["pending"])
                        self.assertFalse(fault["last_call"]["returned"])
                        self.assertIsNotNone(fault["last_call"]["stopped"])
                        self.assertEqual(fault["last_call"]["steps"], pending["last_call"]["steps"])
                        self.assertEqual(fault["registers"], saved)
                        self.assertEqual(engine.request("read", address=0xFCC0)["values"], [0xBEEF])
                        with self.assertRaisesRegex(EngineError, "NoPendingCall"):
                            engine.request("call_resume")
                        with self.assertRaisesRegex(EngineError, "MachineHalted"):
                            engine.request("call", entry=0x100)

    def test_failed_reset_clears_surviving_contacts_before_recovery(self):
        for model in ("9555", "9575"):
            bc5, avr = images(model)
            with self.subTest(model=model), Session(EXECUTABLE, [avr, bc5]) as session:
                session.key("1", True, client_id="tab-a", sequence=1, epoch=session.key_epoch)
                primary = session.engines["bc5"]
                self.assertEqual(primary.request("state")["gpio"]["key_contacts"], 32)
                process = session.engines["avr"]._process
                process.kill()
                process.wait()
                with self.assertRaises(EngineError):
                    session.control("reset")
                self.assertEqual(primary.request("state")["gpio"]["key_contacts"], 0)
                session.load(avr)
                session.key("1", False, client_id="tab-a", sequence=2, epoch=session.key_epoch)
                self.assertEqual(primary.request("state")["gpio"]["key_contacts"], 0)
                self.assertEqual(session.keys, set())


if __name__ == "__main__":
    unittest.main()
