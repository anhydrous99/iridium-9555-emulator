"""Machine-code regressions for public board probes and native fault recovery."""
from pathlib import Path
import tempfile
import unittest

from iridium.engine import Engine, EngineError
from iridium.firmware import parse_firmware
from iridium.session import Session


EXECUTABLE = Path(__file__).resolve().parents[1] / "zig-out/bin/iridium-core"


def images(model, *, receive=True, valid_handle=True):
    def operand(op, value):
        return [(((value + 0x80) >> 8) & 255) << 8, ((value & 255) << 8) | op]

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
                self.assertTrue(returned["last_call"]["pending"])
                self.assertEqual(returned["last_call"]["steps"], 3)
                done = session.probe("bc5", "call_resume", {"steps": 1})
                self.assertTrue(done["last_call"]["returned"])
                self.assertEqual(done["last_call"]["al"], 2)
                self.assertEqual(done["last_call"]["steps"], 3)

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
                                  {"entry": 0x100, "quantum": 0}):
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
