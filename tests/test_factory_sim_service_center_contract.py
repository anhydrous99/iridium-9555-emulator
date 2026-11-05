"""Original TRX service-center persistence through real external UARTs.

The DPL host sends requests/packet ACKs, never AT responses. The finite card
stores one SMSP record. Setter OK is deliberately not treated as card commit.
No HTTP/GUI, identity, authentication, registration or transmission is claimed.
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

from factory_handset import EXECUTABLE, factory_firmware
from iridium.engine import Engine
from sim_service_center_card import INITIAL_SMSP, ServiceCenterSIM


TOTAL_STEPS = 240_000_000
SAVED_SMSP = b"SMSC\xE1" + b"\xFF" * 12 + bytes.fromhex("04 91 76 98 F0") + b"\xFF" * 7 + b"\x00" * 3


class _ServiceCenterWire:
    """Lossless physical DPL/card peer; all guest execution starts at reset."""

    def __init__(self, test, engine, card, evidence):
        self.test, self.engine, self.card, self.evidence = test, engine, card, evidence
        self.incoming, self.outgoing = bytearray(), bytearray()
        self.sequence = 0
        self.active = None
        self.previous_pins = None

    def read(self, address, count=1):
        return self.engine.request("read", address=address, count=count)["values"]

    def snapshot(self, label):
        value = {"label": label, "steps": self.engine.state["steps"],
                 "capacity": self.read(0x400AA2D6), "controller": self.read(0x400AA30C, 4),
                 "smsp_indicator": self.read(0x400A94EC), "alpha_length": self.read(0x400A94ED),
                 "service_center": self.read(0x400A94D0, 12),
                 "pins": self.engine.request("uart_pins", port=3)}
        self.evidence["snapshots"].append(value)
        return value

    def receive_dpl(self, values):
        self.incoming.extend(values)
        while self.incoming:
            if self.incoming[0] in (6, 21):
                value = self.incoming.pop(0)
                self.test.assertEqual(value, 6)
                self.evidence["frames"].append({"steps": self.engine.state["steps"], "control": value})
                continue
            self.test.assertTrue(self.incoming[0] == 4 or 0x81 <= self.incoming[0] <= 0x87)
            if len(self.incoming) < 2:
                return
            length = self.incoming[1] + 4
            self.test.assertTrue(7 <= length <= 258)
            if len(self.incoming) < length:
                return
            frame = bytes(self.incoming[:length])
            del self.incoming[:length]
            self.test.assertEqual(frame[-1], 3)
            self.test.assertEqual(reduce(xor, frame[:-2], 0), frame[-2])
            text = frame[6:-2].decode("ascii", errors="backslashreplace") if frame[0] == 4 else ""
            if frame[0] == 4:
                self.test.assertEqual(frame[5], len(frame) - 8)
            self.evidence["frames"].append({"steps": self.engine.state["steps"],
                                            "bytes": list(frame), "text": text})
            self.outgoing.append(6)  # Actual packet ACK, not an AT result.

    def step(self, count=100000):
        test, card, engine = self.test, self.card, self.engine
        test.assertLess(engine.state["steps"], TOTAL_STEPS)
        state = engine.request("run", steps=min(count, TOTAL_STEPS - engine.state["steps"]))
        for key in ("halt", "last_call", "model_error"):
            test.assertIsNone(state[key])
        test.assertIsNone(state["milestones"]["panic"])
        test.assertEqual(state["uart_tx_dropped"], [0, 0, 0, 0])
        pins = engine.request("uart_pins", port=3)
        pair = (pins["inputs"], pins["outputs"])
        if pair != self.previous_pins:
            self.evidence["controls"].append({"steps": state["steps"], **pins})
            self.previous_pins = pair
        card.controls(*pair)
        for port in (0, 2):
            test.assertEqual(engine.request("uart_io", port=port)["dropped"], 0)
        offered = bytes(card.pending) if card.ready else b""
        wire = engine.request("uart_io", port=3, rx=list(offered))
        test.assertEqual(wire["dropped"], 0)
        test.assertTrue(0 <= wire["accepted"] <= len(offered))
        accepted = offered[:wire["accepted"]]
        card.accepted(wire["accepted"])
        if self.active is not None and accepted:
            item = self.active
            key = "ack" if item["phase"] == "ack" else "status"
            item[key].extend(accepted)
            expected = [0xDC] if key == "ack" else ([0x92, 0x40] if card.smsp_write_memory_failure else [0x90, 0])
            test.assertEqual(item[key], expected[:len(item[key])])
            if item[key] == expected:
                item[key + "_accepted_at"] = state["steps"]
                if key == "ack":
                    item["phase"] = "body"
                else:
                    item["phase"] = "complete"
                    self.active = None
        if offered or wire["values"]:
            self.evidence["card_wire"].append({"steps": state["steps"], "offered": list(offered), **wire})
        if not card.released:
            if wire["values"]:
                self.evidence["unpowered_card_tx"].append({"steps": state["steps"], "bytes": wire["values"]})
        else:
            for value in wire["values"]:
                if self.active is not None:
                    test.assertEqual(self.active["phase"], "body", "Card must acknowledge before original data TX")
                    self.active["body"].append(value)
                previous = card.records[0x6F42]
                start = len(card.events)
                card.feed(bytes((value,)))
                for event in card.events[start:]:
                    if event["kind"] == "header" and event["selected"] == 0x6F42 and event["bytes"][1] == 0xDC:
                        test.assertIsNone(self.active)
                        test.assertEqual(event["bytes"], [0xA0, 0xDC, 1, 4, 32])
                        self.active = {"header_at": state["steps"], "header": event["bytes"],
                                       "body": [], "ack": [], "status": [],
                                       "phase": "status" if card.smsp_write_memory_failure else "ack"}
                        self.evidence["transactions"].append(self.active)
                if self.active is not None and self.active["body"]:
                    if len(self.active["body"]) < 32:
                        test.assertEqual(card.records[0x6F42], previous)
                    else:
                        test.assertEqual(bytes(self.active["body"]), SAVED_SMSP)
                        test.assertEqual(card.records[0x6F42], (SAVED_SMSP,))
                        self.active["committed_at"] = state["steps"]
                        self.active["phase"] = "status"
        offered = bytes(self.outgoing)
        wire = engine.request("uart_io", port=1, rx=list(offered))
        test.assertEqual(wire["dropped"], 0)
        test.assertTrue(0 <= wire["accepted"] <= len(offered))
        del self.outgoing[:wire["accepted"]]
        if offered or wire["values"]:
            self.evidence["dpl_wire"].append({"steps": state["steps"], "offered": list(offered), **wire})
        self.receive_dpl(wire["values"])

    def wait(self, predicate, budget, message):
        deadline = min(TOTAL_STEPS, self.engine.state["steps"] + budget)
        while not predicate():
            self.test.assertLess(self.engine.state["steps"], deadline, message)
            self.step(min(100000, deadline - self.engine.state["steps"]))

    def drained(self):
        return not (self.incoming or self.outgoing or self.card.pending or self.card.buffer or self.card.selecting or self.active)

    def exchange(self, payload):
        self.wait(lambda: not self.incoming and not self.outgoing, 2_000_000, "DPL packets did not drain")
        frame = bytes((4, len(payload) + 4, self.sequence | 1, 3, 0, len(payload))) + payload
        frame += bytes((reduce(xor, frame, 0), 3))
        self.sequence ^= 0x80
        start = len(self.evidence["frames"])
        item = {"request": list(payload), "packet": list(frame), "started_at_steps": self.engine.state["steps"]}
        self.evidence["exchanges"].append(item)
        self.outgoing.extend(frame)

        def complete():
            item["response"] = "".join(row.get("text", "") for row in self.evidence["frames"][start:])
            return bool(re.search(r"\r\n(?:OK|ERROR)\r\n|\+CMS ERROR:\d+\r\n", item["response"]))

        self.wait(complete, 20_000_000, "Original AT request did not produce a terminal response")
        item["finished_at_steps"] = self.engine.state["steps"]
        self.test.assertIn("\r\nOK\r\n", item["response"])
        self.test.assertNotIn("ERROR", item["response"])
        print(f"{self.test.model}: {payload!r} => {item['response']!r} at{item['finished_at_steps']}", flush=True)
        return item["response"]


class SharedSIMServiceCenterChecks:
    def run_service_center(self, *, memory_failure):
        firmware = next(image for image in factory_firmware(self.model, self.firmware_directory, modem=True) if image.image == "trx")
        sources = ("test_factory_sim_service_center_contract.py", "sim_service_center_card.py", "test_sim_service_center_card.py")
        hashes = {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources}
        card = ServiceCenterSIM(smsp_write_memory_failure=memory_failure)
        before_records, before_contents = dict(card.records), dict(card.contents)
        evidence = {"firmware": firmware.describe(), "smsp_write_memory_failure": memory_failure,
                    "scope": "Original reset/UART1 DPL CSCA and UART3 SMSP persistence; no HTTP/GUI, subscriber identity, authentication or RF",
                    "budget": {"absent_boot": 60000000, "total": TOTAL_STEPS}, "source_sha256_before": hashes,
                    "frames": [], "controls": [], "card_wire": [], "dpl_wire": [], "transactions": [],
                    "snapshots": [], "exchanges": [], "unpowered_card_tx": [], "initial_smsp": list(INITIAL_SMSP)}
        engine = link = None
        pid = None
        try:
            with tempfile.TemporaryDirectory(prefix="iridium-service-center-") as temporary:
                path = Path(temporary) / "trx.bin"
                path.write_bytes(firmware.data)
                with Engine(EXECUTABLE, "trx", path, model=self.model) as engine:
                    pid = engine._process.pid
                    evidence["worker_pid"] = pid
                    evidence["executable_sha256"] = sha256(Path("/proc", str(pid), "exe").read_bytes()).hexdigest()
                    self.assertEqual(evidence["executable_sha256"], sha256(EXECUTABLE.read_bytes()).hexdigest())
                    link = _ServiceCenterWire(self, engine, card, evidence)
                    while engine.state["steps"] < 60_000_000:
                        link.step(min(1024 if engine.state["steps"] < 8_000_000 else 100000, 60_000_000 - engine.state["steps"]))
                    self.assertFalse(card.events)
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    ready = lambda: link.read(0x400AA30C, 4) == [0, 0, 0, 1]
                    link.wait(ready, 60_000_000, "Original SMS consumer did not initialize")
                    self.assertEqual(link.snapshot("initial-ready")["service_center"], list(INITIAL_SMSP[17:29]))
                    self.assertEqual(link.read(0x400A94EC), [0xE1])
                    self.assertEqual(link.read(0x400A94ED), [4])
                    self.assertIn('+CSCA:"12345",145', link.exchange(b"AT+CSCA?\r"))
                    # Original85A14 sends OK before the asynchronous card completion.
                    link.exchange(b'AT+CSCA="+67890",145\r')
                    link.wait(lambda: len(evidence["transactions"]) == 1 and link.drained(), 10_000_000, "Original SMSP update did not complete")
                    transaction, = evidence["transactions"]
                    self.assertEqual(transaction["phase"], "complete")
                    if memory_failure:
                        self.assertEqual(transaction["body"], [])
                        self.assertEqual(transaction["ack"], [])
                        self.assertEqual(transaction["status"], [0x92, 0x40])
                        self.assertNotIn("committed_at", transaction)
                        expected = INITIAL_SMSP
                    else:
                        self.assertEqual(transaction["ack"], [0xDC])
                        self.assertEqual(transaction["status"], [0x90, 0])
                        self.assertEqual(bytes(transaction["body"]), SAVED_SMSP)
                        self.assertLessEqual(transaction["ack_accepted_at"], transaction["committed_at"])
                        expected = SAVED_SMSP
                    self.assertEqual(card.records[0x6F42], (expected,))
                    # Even a failed physical write leaves the early cache changed.
                    self.assertIn('+CSCA:"67890",145', link.exchange(b"AT+CSCA?\r"))
                    link.wait(link.drained, 2_000_000, "Cached query did not drain")
                    link.snapshot("after-write-before-removal")
                    engine.request("uart_pins", port=3, value=0, mask=1)
                    removed_at = engine.state["steps"]
                    link.wait(lambda: engine.state["steps"] - removed_at >= 5_000_000 and
                              engine.request("uart_pins", port=3)["outputs"] == 0x40 and
                              link.read(0x400B4D24, 2) == [0, 0] and link.read(0x70003234, 4) == [0, 0, 0, 0] and link.drained(),
                              20_000_000, "Natural absence/reset/debounce did not settle")
                    self.assertEqual(link.snapshot("removed-and-settled")["controller"], [0, 0, 0, 0])
                    start = len(card.events)
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    link.wait(ready, 70_000_000, "Natural reinsertion did not rebuild the consumer")
                    self.assertEqual(link.snapshot("reinserted-ready")["service_center"], list(expected[17:29]))
                    reads, metadata = [], []
                    header = None
                    for event in card.events[start:]:
                        if event["kind"] == "header":
                            header = event
                        elif header is not None and header["selected"] == 0x6F42:
                            if event["kind"] == "read-record":
                                reads.append({"header": header["bytes"], "response": event["bytes"]})
                            elif event["kind"] == "metadata":
                                metadata.append(event["bytes"])
                    self.assertEqual(reads, [{"header": [0xA0, 0xB2, 1, 4, 32], "response": [0xB2, *expected, 0x90, 0]}])
                    self.assertIn([0xC0, *card.metadata[0x6F42], 0x90, 0], metadata)
                    number = "12345" if memory_failure else "67890"
                    self.assertIn('+CSCA:"' + number + '",145', link.exchange(b"AT+CSCA?\r"))
                    link.wait(link.drained, 2_000_000, "Fresh service-center query did not drain")
                    link.snapshot("final")
                    self.assertEqual(card.records, {**before_records, 0x6F42: (expected,)})
                    self.assertEqual(card.contents, before_contents)
                    writes = [e for e in card.events if e["kind"] == "header" and e["bytes"][1] in (0xD6, 0xDC, 0x32)]
                    self.assertEqual(writes, [{"kind": "header", "bytes": [0xA0, 0xDC, 1, 4, 32], "selected": 0x6F42}])
        finally:
            evidence.update({"events": card.events, "final_state": engine.state if engine else None,
                             "final_smsp": list(card.records[0x6F42][0]), "pending_card": list(card.pending),
                             "partial_card_command": list(card.buffer), "select_payload_pending": card.selecting,
                             "pending_dpl": list(link.outgoing) if link else [], "partial_dpl_frame": list(link.incoming) if link else [],
                             "worker_closed": pid is None or not Path("/proc", str(pid)).exists(),
                             "source_sha256_after": {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources}})
            directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (self.id() + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")
            self.assertTrue(evidence["worker_closed"])
            self.assertEqual(evidence["source_sha256_after"], hashes)

    def test_original_csca_commits_smsp_and_fresh_query_retains_number_after_reinsertion(self):
        self.run_service_center(memory_failure=False)

    def test_original_csca_failed_smsp_write_preserves_card_and_fresh_query_after_reinsertion(self):
        self.run_service_center(memory_failure=True)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "Set IRIDIUM_TEST_FIRMWARE for original9555 service-center contracts")
class Factory9555SIMServiceCenterContractTests(SharedSIMServiceCenterChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "Set IRIDIUM_TEST_9575_FIRMWARE for original9575 service-center contracts")
class Factory9575SIMServiceCenterContractTests(SharedSIMServiceCenterChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
