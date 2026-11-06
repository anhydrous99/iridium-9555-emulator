"""Original serial CPBS/CPBR/CPBW through physical DPL and finite ADN storage.

The host sends commands/packetACKs, never AT results. The card permits only two
opaque32-byte ADN records. HandsetGUI SIM editing is not claimed.
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
from sim_phonebook_card import EMPTY_ADN, PhonebookSIM
from test_factory_sim_service_center_contract import _ServiceCenterWire


TOTAL_STEPS = 240_000_000
ADG_ADN = b"Adg" + b"\xFF" * 15 + bytes.fromhex("04 91 21 43 F5") + b"\xFF" * 9
B_ADN = b"B" + b"\xFF" * 17 + bytes.fromhex("02 81 76") + b"\xFF" * 11


class _ADNWire(_ServiceCenterWire):
    def __init__(self, test, engine, card, evidence):
        super().__init__(test, engine, card, evidence)
        self.expected_writes = []

    def snapshot(self, label):
        value = {"label": label, "steps": self.engine.state["steps"],
                 "initialized": self.read(0x400AA9F8, 4), "used": self.read(0x400AA9FC),
                 "capacity": self.read(0x400AA9FE), "alpha_length": self.read(0x400ABEFA),
                 "read_inflight": self.read(0x400ABEFC, 4),
                 "pins": self.engine.request("uart_pins", port=3),
                 "card_records": [list(row) for row in self.card.records[0x6F3A]]}
        self.evidence["snapshots"].append(value)
        return value

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
            expected = [0xDC] if key == "ack" else ([0x92, 0x40] if item["rejected"] else [0x90, 0])
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
                    test.assertEqual(self.active["phase"], "body", "Original data must wait for procedureACK")
                    self.active["body"].append(value)
                previous = card.records[0x6F3A]
                start = len(card.events)
                card.feed(bytes((value,)))
                for event in card.events[start:]:
                    if event["kind"] == "header" and event["bytes"][1] in (0xDC, 0xD6, 0x32):
                        test.assertEqual(event["selected"], 0x6F3A)
                        test.assertEqual(event["bytes"][1], 0xDC)
                        test.assertTrue(self.expected_writes, "Unexpected original card write")
                        test.assertIsNone(self.active)
                        record, body = self.expected_writes.pop(0)
                        test.assertEqual(event["bytes"], [0xA0, 0xDC, record, 4, 32])
                        self.active = {"header_at": state["steps"], "header": event["bytes"],
                                       "record": record, "expected_body": list(body),
                                       "rejected": bool(card.adn_write_memory_failure),
                                       "body": [], "ack": [], "status": [],
                                       "phase": "status" if card.adn_write_memory_failure else "ack"}
                        self.evidence["transactions"].append(self.active)
                if self.active is not None and self.active["body"]:
                    item = self.active
                    if len(item["body"]) < 32:
                        test.assertEqual(card.records[0x6F3A], previous)
                    else:
                        test.assertEqual(item["body"], item["expected_body"])
                        expected = list(previous)
                        expected[item["record"] - 1] = bytes(item["expected_body"])
                        test.assertEqual(card.records[0x6F3A], tuple(expected))
                        item["committed_at"] = state["steps"]
                        item["phase"] = "status"
        offered = bytes(self.outgoing)
        wire = engine.request("uart_io", port=1, rx=list(offered))
        test.assertEqual(wire["dropped"], 0)
        test.assertTrue(0 <= wire["accepted"] <= len(offered))
        del self.outgoing[:wire["accepted"]]
        if offered or wire["values"]:
            self.evidence["dpl_wire"].append({"steps": state["steps"], "offered": list(offered), **wire})
        self.receive_dpl(wire["values"])

    def exchange(self, payload, *, expect_error=False):
        self.wait(lambda: not self.incoming and not self.outgoing, 2_000_000, "DPL packets did not drain")
        frame = bytes((4, len(payload) + 4, self.sequence | 1, 3, 0, len(payload))) + payload
        frame += bytes((reduce(xor, frame, 0), 3))
        self.sequence ^= 0x80
        start = len(self.evidence["frames"])
        item = {"request": list(payload), "packet": list(frame), "started_at_steps": self.engine.state["steps"],
                "expect_error": expect_error}
        self.evidence["exchanges"].append(item)
        self.outgoing.extend(frame)

        def complete():
            item["response"] = "".join(row.get("text", "") for row in self.evidence["frames"][start:])
            return bool(re.search(r"\r\n(?:OK|ERROR)\r\n|\+(?:CME|CMS) ERROR:\s*\d+\r\n", item["response"]))

        self.wait(complete, 20_000_000, "Original phonebook request produced no terminal result")
        item["finished_at_steps"] = self.engine.state["steps"]
        if expect_error:
            self.test.assertNotIn("\r\nOK\r\n", item["response"])
            self.test.assertRegex(item["response"], r"\r\nERROR\r\n|\+CME ERROR:\s*\d+\r\n")
        else:
            self.test.assertIn("\r\nOK\r\n", item["response"])
            self.test.assertNotIn("ERROR", item["response"])
        print(f"{self.test.model}: {payload!r} => {item['response']!r} at{item['finished_at_steps']}", flush=True)
        return item["response"]


class SharedSIMPhonebookWriteChecks:
    def run_phonebook(self, *, reject_edit):
        require_factory_host()
        firmware = next(image for image in factory_firmware(self.model, self.firmware_directory, modem=True)
                        if image.image == "trx")
        sources = ("test_factory_sim_phonebook_write_contract.py", "sim_phonebook_card.py",
                   "test_sim_phonebook_card.py", "test_factory_sim_service_center_contract.py")
        hashes = {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in sources}
        card = PhonebookSIM()
        before_records, before_contents = dict(card.records), dict(card.contents)
        evidence = {"firmware": firmware.describe(), "card_version": card.version,
                    "reject_edit": reject_edit, "budget": TOTAL_STEPS,
                    "scope": "Original reset, UART1DPL phonebook requests/packetACKs and UART3 finiteADNcard; no GUI, ATresults, guestwrites/calls, identity/authentication or RF",
                    "source_sha256_before": hashes, "frames": [], "controls": [], "card_wire": [],
                    "dpl_wire": [], "transactions": [], "snapshots": [], "exchanges": [],
                    "unpowered_card_tx": []}
        engine = link = None
        pid = None
        try:
            with tempfile.TemporaryDirectory(prefix="iridium-sim-phonebook-write-") as temporary:
                path = Path(temporary) / "trx.bin"
                path.write_bytes(firmware.data)
                with Engine(EXECUTABLE, "trx", path, model=self.model) as engine:
                    pid = engine._process.pid
                    evidence["worker_pid"] = pid
                    evidence["executable_sha256"] = sha256(Path("/proc", str(pid), "exe").read_bytes()).hexdigest()
                    self.assertEqual(evidence["executable_sha256"], sha256(EXECUTABLE.read_bytes()).hexdigest())
                    link = _ADNWire(self, engine, card, evidence)
                    while engine.state["steps"] < 60_000_000:
                        link.step(min(1024 if engine.state["steps"] < 8_000_000 else 100000,
                                      60_000_000 - engine.state["steps"]))
                    self.assertFalse(card.events)
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    ready = lambda: link.read(0x400AA9F8, 4) == [0, 0, 0, 1]
                    link.wait(ready, 65_000_000, "Original ADN consumer did not initialize")
                    initial = link.snapshot("initial-ready")
                    self.assertEqual(initial["capacity"], [2])
                    self.assertEqual(initial["used"], [0])
                    self.assertEqual(initial["alpha_length"], [18])
                    self.assertEqual(initial["read_inflight"], [0, 0, 0, 0])
                    link.exchange(b"AT+CMEE=1\r")
                    link.exchange(b'AT+CPBS="SM"\r')
                    self.assertIn('+CPBS:"SM",000,002', link.exchange(b"AT+CPBS?\r"))
                    # Original SM uses the unified index after the100local slots.
                    self.assertIn("+CPBR:(101-102)", link.exchange(b"AT+CPBR=?\r"))
                    self.assertIn("+CPBW:(101-102)", link.exchange(b"AT+CPBW=?\r"))

                    def update(command, body, *, rejected=False):
                        start = len(evidence["transactions"])
                        card.adn_write_memory_failure = rejected
                        link.expected_writes.append((1, body))
                        response = link.exchange(command, expect_error=rejected)
                        link.wait(lambda: len(evidence["transactions"]) == start + 1 and link.drained(),
                                  10_000_000, "Original ADN transaction did not finish")
                        self.assertFalse(link.expected_writes)
                        transaction = evidence["transactions"][-1]
                        self.assertEqual(transaction["phase"], "complete")
                        if rejected:
                            self.assertEqual(transaction["ack"], [])
                            self.assertEqual(transaction["body"], [])
                            self.assertEqual(transaction["status"], [0x92, 0x40])
                            self.assertNotIn("committed_at", transaction)
                        else:
                            self.assertEqual(transaction["ack"], [0xDC])
                            self.assertEqual(transaction["body"], list(body))
                            self.assertEqual(transaction["status"], [0x90, 0])
                            self.assertLessEqual(transaction["ack_accepted_at"], transaction["committed_at"])
                        return response

                    def read_entry(number, ton, name):
                        response = link.exchange(b"AT+CPBR=101\r")
                        self.assertIn(f'+CPBR:101,"{number}",{ton:03d},"{name}"', response)
                        self.assertEqual(response.count("+CPBR:"), 1)

                    update(b'AT+CPBW=101,"+12345",145,"Adg"\r', ADG_ADN)
                    self.assertEqual(card.records[0x6F3A], (ADG_ADN, EMPTY_ADN))
                    read_entry("+12345", 145, "Adg")
                    self.assertIn('+CPBS:"SM",001,002', link.exchange(b"AT+CPBS?\r"))
                    update(b'AT+CPBW=101,"67",129,"B"\r', B_ADN, rejected=reject_edit)
                    expected = ADG_ADN if reject_edit else B_ADN
                    self.assertEqual(card.records[0x6F3A], (expected, EMPTY_ADN))
                    read_entry("+12345" if reject_edit else "67", 145 if reject_edit else 129,
                               "Adg" if reject_edit else "B")
                    link.wait(link.drained, 2_000_000, "Phonebook readback did not drain")
                    link.snapshot("before-removal")
                    engine.request("uart_pins", port=3, value=0, mask=1)
                    removed = engine.state["steps"]
                    link.wait(lambda: engine.state["steps"] - removed >= 5_000_000 and
                              engine.request("uart_pins", port=3)["outputs"] == 0x40 and
                              link.read(0x400B4D24, 2) == [0, 0] and
                              link.read(0x70003234, 4) == [0, 0, 0, 0] and link.drained(),
                              20_000_000, "Original card absence/reset/debounce did not settle")
                    link.snapshot("removed-and-settled")
                    start = len(card.events)
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    def rebuilt():
                        selected = None
                        count = 0
                        for event in card.events[start:]:
                            if event["kind"] == "header":
                                selected = event["selected"]
                            elif event["kind"] == "read-record" and selected == 0x6F3A:
                                count += 1
                        return ready() and count >= 2 and link.drained()

                    link.wait(rebuilt, 70_000_000, "Original ADN consumer did not reread both records after reinsertion")
                    link.snapshot("reinserted-ready")
                    reads = []
                    header = None
                    for event in card.events[start:]:
                        if event["kind"] == "header":
                            header = event
                        elif event["kind"] == "read-record" and header is not None and header["selected"] == 0x6F3A:
                            reads.append({"header": header["bytes"], "response": event["bytes"]})
                    self.assertEqual(reads, [
                        {"header": [0xA0, 0xB2, 1, 4, 32], "response": [0xB2, *expected, 0x90, 0]},
                        {"header": [0xA0, 0xB2, 2, 4, 32], "response": [0xB2, *EMPTY_ADN, 0x90, 0]},
                    ])
                    link.exchange(b'AT+CPBS="SM"\r')
                    read_entry("+12345" if reject_edit else "67", 145 if reject_edit else 129,
                               "Adg" if reject_edit else "B")
                    if reject_edit:
                        update(b'AT+CPBW=101,"67",129,"B"\r', B_ADN)
                        expected = B_ADN
                        read_entry("67", 129, "B")
                        self.assertIn('+CPBS:"SM",001,002', link.exchange(b"AT+CPBS?\r"))
                    else:
                        update(b"AT+CPBW=101\r", EMPTY_ADN)
                        expected = EMPTY_ADN
                        response = link.exchange(b"AT+CPBR=101,102\r")
                        self.assertNotIn("+CPBR:", response)
                        self.assertIn('+CPBS:"SM",000,002', link.exchange(b"AT+CPBS?\r"))
                    link.wait(link.drained, 2_000_000, "Final phonebook packets did not drain")
                    link.snapshot("final")
                    self.assertEqual(card.records, {**before_records, 0x6F3A: (expected, EMPTY_ADN)})
                    self.assertEqual(card.contents, before_contents)
                    self.assertEqual(len(evidence["transactions"]), 3)
        finally:
            evidence.update({"events": card.events, "final_state": engine.state if engine else None,
                             "final_adn": [list(row) for row in card.records[0x6F3A]],
                             "pending_card": list(card.pending), "partial_card_command": list(card.buffer),
                             "select_payload_pending": card.selecting,
                             "pending_dpl": list(link.outgoing) if link else [],
                             "partial_dpl_frame": list(link.incoming) if link else [],
                             "worker_closed": pid is None or not Path("/proc", str(pid)).exists(),
                             "source_sha256_after": {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                                     for name in sources}})
            directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (self.id() + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")
            self.assertTrue(evidence["worker_closed"])
            self.assertEqual(evidence["source_sha256_after"], hashes)

    def test_original_cpbw_create_edit_delete_and_fresh_cpbr_after_reinsertion(self):
        self.run_phonebook(reject_edit=False)

    def test_original_cpbw_rejected_adn_write_preserves_card_and_cpbr_then_recovers(self):
        self.run_phonebook(reject_edit=True)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555SIMPhonebookWriteContractTests(SharedSIMPhonebookWriteChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575SIMPhonebookWriteContractTests(SharedSIMPhonebookWriteChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")
