"""Original TRX serial SMS storage, separate from HTTP/local GUI drafts.

An external UART1 DPL host sends requests and physical ACKs only. Original TRX
executes from reset and reads/writes the finite external UART3 MessageSIM.
No guest calls/writes, AT response substitution, subscriber identity or RF.
"""

from functools import reduce
from hashlib import sha256
import json
import os
from operator import xor
from pathlib import Path
import re
import tempfile
import unittest

from factory_handset import EXECUTABLE, factory_firmware, require_factory_host
from iridium.engine import Engine
from sim_message_card import MessageSIM


BOOT_STEPS = 60_000_000
TOTAL_STEPS = 240_000_000
EMPTY = b"\x00" + b"\xFF" * 175
PDU = b"00010005912143F500000331D90C"
# Original86588 normalizes an unsent submit record to status07 and TP-MRFF.
STORED = bytes.fromhex("07 00 01 FF 05 91 21 43 F5 00 00 03 31 D9 0C") + b"\xFF" * 161
READBACK_PDU = "0001FF05912143F500000331D90C"


class SharedSIMSMSWriteChecks:
    def run_sms_store(self, *, memory_failure):
        require_factory_host()
        firmware = next(image for image in factory_firmware(
            self.model, self.firmware_directory, modem=True) if image.image == "trx")
        card = MessageSIM(sms_write_memory_failure=memory_failure)
        source = Path(__file__)
        source_before = sha256(source.read_bytes()).hexdigest()
        evidence = {
            "firmware": firmware.describe(), "sms_write_memory_failure": memory_failure,
            "scope": "Natural original TRX reset, external DPL request/ACK host and finite writable SIM; serial/card persistence only, no HTTP/GUI, identity, authentication or RF service",
            "budget": {"absent_boot": BOOT_STEPS, "total": TOTAL_STEPS},
            "source_sha256_before": source_before, "dpl_wire": [], "frames": [],
            "card_wire": [], "controls": [], "transactions": [], "exchanges": [],
            "card_records_initial": [list(row) for row in card.records[0x6F3C]],
            "smss_initial": list(card.contents[0x6F43]), "snapshots": [],
            "unpowered_card_tx": [],
        }
        incoming = bytearray()
        outgoing = bytearray()
        sequence = 0
        active_write = None
        previous_pins = None
        engine = None
        pid = None

        def read(address, count):
            return engine.request("read", address=address, count=count)["values"]

        def snapshot(label):
            values = {"steps": engine.state["steps"], "label": label,
                      "capacity": read(0x400AA2D6, 1), "flags": read(0x400AA2D3, 1),
                      "controller": read(0x400AA30C, 4)}
            evidence["snapshots"].append(values)
            return values

        def receive_dpl(data):
            incoming.extend(data)
            while incoming:
                if incoming[0] in (6, 21):
                    control = incoming.pop(0)
                    evidence["frames"].append({"steps": engine.state["steps"], "control": control})
                    self.assertEqual(control, 6, "Original DPL must acknowledge legitimate requests")
                    continue
                self.assertTrue(incoming[0] == 4 or 0x81 <= incoming[0] <= 0x87)
                if len(incoming) < 2:
                    return
                length = incoming[1] + 4
                self.assertTrue(7 <= length <= 258)
                if len(incoming) < length:
                    return
                frame = bytes(incoming[:length])
                del incoming[:length]
                self.assertEqual(frame[-1], 3)
                self.assertEqual(reduce(xor, frame[:-2], 0), frame[-2])
                text = frame[6:-2].decode("ascii", errors="backslashreplace") if frame[0] == 4 else ""
                if frame[0] == 4:
                    self.assertEqual(frame[5], len(frame) - 8)
                evidence["frames"].append({"steps": engine.state["steps"],
                                           "bytes": list(frame), "text": text})
                outgoing.append(6)  # Physical packet ACK, never an AT result.

        def step(count=100000):
            nonlocal active_write, previous_pins
            self.assertLess(engine.state["steps"], TOTAL_STEPS)
            state = engine.request("run", steps=min(count, TOTAL_STEPS - engine.state["steps"]))
            self.assertIsNone(state["halt"])
            self.assertIsNone(state["last_call"], "Original execution must start at reset")
            self.assertIsNone(state["model_error"])
            self.assertIsNone(state["milestones"]["panic"])
            self.assertEqual(state["uart_tx_dropped"], [0, 0, 0, 0])
            pins = engine.request("uart_pins", port=3)
            pair = (pins["inputs"], pins["outputs"])
            if pair != previous_pins:
                evidence["controls"].append({"steps": state["steps"], **pins})
                previous_pins = pair
            card.controls(*pair)
            for port in (0, 2):
                self.assertEqual(engine.request("uart_io", port=port)["dropped"], 0)
            offered = bytes(card.pending) if card.ready else b""
            wire = engine.request("uart_io", port=3, rx=list(offered))
            self.assertEqual(wire["dropped"], 0)
            self.assertTrue(0 <= wire["accepted"] <= len(offered))
            accepted = offered[:wire["accepted"]]
            card.accepted(wire["accepted"])
            if active_write is not None and accepted == b"\xDC":
                active_write["ack_accepted_at"] = state["steps"]
            if active_write is not None and accepted == b"\x92\x40":
                active_write["status_accepted_at"] = state["steps"]
                active_write["status"] = [0x92, 0x40]
                active_write = None
            elif active_write is not None and accepted == b"\x90\x00":
                active_write["status_accepted_at"] = state["steps"]
                active_write["status"] = [0x90, 0]
                active_write = None
            if offered or wire["values"]:
                evidence["card_wire"].append({"steps": state["steps"], "offered": list(offered), **wire})
            if not card.released:
                if wire["values"]:
                    evidence["unpowered_card_tx"].append({"steps": state["steps"], "bytes": wire["values"]})
            else:
                # Preserve actual captured TX; byte-sized delivery exposes any premature commit.
                for value in wire["values"]:
                    if active_write is not None:
                        self.assertIn("ack_accepted_at", active_write)
                        active_write["body"].append(value)
                    previous_records = card.records[0x6F3C]
                    event_start = len(card.events)
                    card.feed(bytes((value,)))
                    for event in card.events[event_start:]:
                        if (event["kind"] == "header" and event["selected"] == 0x6F3C
                                and event["bytes"][1] == 0xDC):
                            self.assertIsNone(active_write)
                            self.assertEqual(event["bytes"], [0xA0, 0xDC, 1, 4, 176])
                            active_write = {"header_at": state["steps"], "header": event["bytes"], "body": []}
                            evidence["transactions"].append(active_write)
                    if active_write is not None and active_write["body"]:
                        if len(active_write["body"]) < 176:
                            self.assertEqual(card.records[0x6F3C], previous_records)
                        else:
                            self.assertEqual(len(active_write["body"]), 176)
                            self.assertEqual(bytes(active_write["body"]), STORED)
                            self.assertEqual(card.records[0x6F3C], (STORED, EMPTY))
                            active_write["committed_at"] = state["steps"]
            offered = bytes(outgoing)
            wire = engine.request("uart_io", port=1, rx=list(offered))
            self.assertEqual(wire["dropped"], 0)
            self.assertTrue(0 <= wire["accepted"] <= len(offered))
            del outgoing[:wire["accepted"]]
            if offered or wire["values"]:
                evidence["dpl_wire"].append({"steps": state["steps"], "offered": list(offered), **wire})
            receive_dpl(wire["values"])
            return state

        def wait_until(predicate, budget, message):
            deadline = min(TOTAL_STEPS, engine.state["steps"] + budget)
            while not predicate():
                self.assertLess(engine.state["steps"], deadline, message)
                step(min(100000, deadline - engine.state["steps"]))

        def drained():
            return not outgoing and not incoming and not card.pending and not card.buffer and not card.selecting

        def exchange(payload, *, data_entry=False, prompt=False, error=False):
            nonlocal sequence
            wait_until(lambda: not outgoing and not incoming, 2_000_000, "DPL packet/ACK did not drain")
            flag = sequence | (6 if data_entry else 1)
            frame = bytes((4, len(payload) + 4, flag, 3, 0, len(payload))) + payload
            frame += bytes((reduce(xor, frame, 0), 3))
            sequence ^= 0x80
            start = len(evidence["frames"])
            item = {"request": list(payload), "packet": list(frame), "started_at_steps": engine.state["steps"]}
            evidence["exchanges"].append(item)
            outgoing.extend(frame)

            def complete():
                text = "".join(row.get("text", "") for row in evidence["frames"][start:])
                item["response"] = text
                return bool(re.search(r"\r\n(?:OK|ERROR)\r\n|\+CMS ERROR:\d+\r\n", text)) or prompt and "\r\n> " in text

            wait_until(complete, 20_000_000, "Original request did not reach its terminal response/prompt")
            item["finished_at_steps"] = engine.state["steps"]
            text = item["response"]
            if prompt:
                self.assertIn("\r\n> ", text)
            elif error:
                # 9240 ->28104 result5 ->8342C false ->85730/A5850(1) ->C7A6C=142h.
                self.assertIn("\r\n+CMS ERROR:322\r\n", text)
                self.assertNotIn("+CMGW:", text)
                self.assertNotIn("\r\nOK\r\n", text)
            else:
                self.assertIn("\r\nOK\r\n", text)
                self.assertNotIn("+CMS ERROR:", text)
                self.assertNotIn("\r\nERROR\r\n", text)
            return text

        def ready():
            return read(0x400AA30C, 4) == [0, 0, 0, 1]

        def sms_reads(events):
            records = []
            header = None
            for event in events:
                if event["kind"] == "header":
                    header = event
                elif event["kind"] == "read-record" and header["selected"] == 0x6F3C:
                    records.append({"header": header["bytes"], "response": event["bytes"]})
            return records

        try:
            with tempfile.TemporaryDirectory(prefix="iridium-sim-sms-write-") as temporary:
                path = Path(temporary) / "trx.bin"
                path.write_bytes(firmware.data)
                with Engine(EXECUTABLE, "trx", path, model=self.model) as engine:
                    pid = engine._process.pid
                    evidence["worker_pid"] = pid
                    evidence["executable_sha256"] = sha256(Path("/proc", str(pid), "exe").read_bytes()).hexdigest()
                    self.assertEqual(evidence["executable_sha256"], sha256(EXECUTABLE.read_bytes()).hexdigest())
                    while engine.state["steps"] < BOOT_STEPS:
                        step(min(1024 if engine.state["steps"] < 8_000_000 else 100000,
                                 BOOT_STEPS - engine.state["steps"]))
                    self.assertFalse(card.events)
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    wait_until(ready, 60_000_000, "Original SMS consumer did not initialize")
                    initial = snapshot("initial-ready")
                    self.assertEqual(initial["capacity"], [2])
                    self.assertEqual(initial["flags"], [3])
                    self.assertEqual(sms_reads(card.events), [
                        {"header": [0xA0, 0xB2, record, 4, 176], "response": [0xB2, *EMPTY, 0x90, 0]}
                        for record in (1, 2)])
                    self.assertIn("+CPMS:000,002,000,002,000,002", exchange(b'AT+CPMS="SM"\r'))
                    exchange(b"AT+CMGF=0\r")
                    exchange(b"AT+CMGW=13,2\r", prompt=True)
                    response = exchange(PDU + b"\x1A", data_entry=True, error=memory_failure)
                    wait_until(drained, 2_000_000, "Completed storage response did not drain")
                    self.assertEqual(len(evidence["transactions"]), 1)
                    transaction = evidence["transactions"][0]
                    if memory_failure:
                        self.assertEqual(transaction["body"], [])
                        self.assertNotIn("ack_accepted_at", transaction)
                        self.assertEqual(transaction["status"], [0x92, 0x40])
                        self.assertEqual(card.records[0x6F3C], (EMPTY, EMPTY))
                        self.assertFalse(any(row["kind"] == "update-record-procedure" for row in card.events))
                    else:
                        self.assertIn("\r\n+CMGW:001\r\n", response)
                        self.assertEqual(transaction["status"], [0x90, 0])
                        self.assertEqual(bytes(transaction["body"]), STORED)
                        self.assertLessEqual(transaction["ack_accepted_at"], transaction["committed_at"])
                        self.assertEqual(card.records[0x6F3C], (STORED, EMPTY))
                        engine.request("uart_pins", port=3, value=0, mask=1)
                        removed_at = engine.state["steps"]

                        def removed():
                            return (engine.state["steps"] - removed_at >= 5_000_000
                                    and engine.request("uart_pins", port=3)["outputs"] == 0x40
                                    and read(0x400B4D24, 2) == [0, 0]
                                    and read(0x70003234, 4) == [0, 0, 0, 0] and drained())

                        wait_until(removed, 20_000_000, "Natural removal/reset/debounce did not settle")
                        absent = snapshot("removed-and-settled")
                        self.assertEqual(absent["controller"], [0, 0, 0, 0])
                        self.assertEqual(absent["capacity"], [0])
                        self.assertEqual(absent["flags"], [0])
                        event_start = len(card.events)
                        engine.request("uart_pins", port=3, value=1, mask=1)
                        wait_until(ready, 70_000_000, "Natural reinsertion did not rebuild the SMS consumer")
                        snapshot("reinserted-ready")
                        self.assertEqual(sms_reads(card.events[event_start:]), [
                            {"header": [0xA0, 0xB2, 1, 4, 176], "response": [0xB2, *STORED, 0x90, 0]},
                            {"header": [0xA0, 0xB2, 2, 4, 176], "response": [0xB2, *EMPTY, 0x90, 0]}])
                        cmgr_start = len(card.events)
                        text = exchange(b"AT+CMGR=1\r")
                        self.assertIn("\r\n+CMGR:002,", text)
                        self.assertIn("\r\n" + READBACK_PDU + "\r\n", text)
                        # The original quoted alpha field is retained, not claimed correct.
                        self.assertIn({"header": [0xA0, 0xB2, 1, 4, 176],
                                       "response": [0xB2, *STORED, 0x90, 0]}, sms_reads(card.events[cmgr_start:]))
                        wait_until(drained, 2_000_000, "Original CMGR response did not drain")
                        self.assertEqual(card.records[0x6F3C], (STORED, EMPTY))
                    snapshot("final")
        finally:
            evidence.update({"events": card.events, "final_state": engine.state if engine is not None else None,
                             "card_records_final": [list(row) for row in card.records[0x6F3C]],
                             "smss_final": list(card.contents[0x6F43]),
                             "pending_card": list(card.pending), "partial_card_command": list(card.buffer),
                             "select_payload_pending": card.selecting, "pending_dpl": list(outgoing),
                             "partial_dpl_frame": list(incoming), "worker_closed": pid is None or not Path("/proc", str(pid)).exists(),
                             "source_sha256_after": sha256(source.read_bytes()).hexdigest()})
            directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (self.id() + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")
            self.assertEqual(evidence["source_sha256_after"], source_before)

    def test_original_cmgw_commits_sms_card_and_cmgr_reads_it_after_natural_reinsertion(self):
        self.run_sms_store(memory_failure=False)

    def test_original_cmgw_card_memory_failure_returns_cms322_without_committing_sms(self):
        self.run_sms_store(memory_failure=True)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 serial SMS storage contracts")
class Factory9555SIMSMSWriteContractTests(SharedSIMSMSWriteChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 serial SMS storage contracts")
class Factory9575SIMSMSWriteContractTests(SharedSIMSMSWriteChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
