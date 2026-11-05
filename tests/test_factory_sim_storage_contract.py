"""Original TRX initializes empty SIM SMS storage only when SST enables it.

These are natural-reset peripheral contracts with an external, read-only T=0
card. They establish local metadata/record consumption and controller state,
without a subscriber identity, AT request, stored message or network service.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from factory_handset import EXECUTABLE, factory_firmware, require_factory_host
from iridium.engine import Engine
from sim_language_card import StorageSIM


BOOT_STEPS = 60_000_000
TOTAL_STEPS = 120_000_000
SST_POINTER_ENTRY = 0x70002270 + 7 * 4  # Original F107 cache, shared TRX image.
SMS_CAPACITY = 0x400AA2D6
SMS_FLAGS = 0x400AA2D3
SMS_CONTROLLER = 0x400AA30C
SMS_METADATA = bytes.fromhex("00 00 01 60 6F 3C 04 00 11 F0 44 01 02 01 B0")


class SharedSIMStorageChecks:
    def run_storage_card(self, *, sms_available):
        require_factory_host()
        firmware = next(image for image in factory_firmware(
            self.model, self.firmware_directory, modem=True) if image.image == "trx")
        card = StorageSIM(sms_available=sms_available)
        service_table = b"\xCC\x00" if sms_available else b"\x0C\x00"
        self.assertEqual(card.contents[0x6F38], service_table)
        self.assertEqual(card.metadata[0x6F3C], SMS_METADATA)
        self.assertEqual(card.records[0x6F3C], (b"\x00" + b"\xFF" * 175,) * 2)
        self.assertEqual(card.records[0x6F3A], (b"\xFF" * 32,) * 2)
        evidence = {
            "firmware": firmware.describe(), "card_version": card.version,
            "sms_available": sms_available, "service_table": list(service_table),
            "declared_metadata": {hex(k): list(v) for k, v in card.metadata.items()},
            "declared_records": {hex(k): [list(v) for v in records]
                                 for k, records in card.records.items()},
            "scope": "Natural original TRX reset, external UART3 card and read-only storage/cache observations; no guest writes/calls, AT, identity, message delivery or RF service",
            "budget": {"absent_boot": BOOT_STEPS, "total": TOTAL_STEPS},
            "wire": [], "commands": [], "select_requests": [], "snapshots": [],
        }
        with tempfile.TemporaryDirectory(prefix="iridium-sim-storage-") as temporary:
            path = Path(temporary) / "trx.bin"
            path.write_bytes(firmware.data)
            with Engine(EXECUTABLE, "trx", path, model=self.model) as engine:
                evidence["worker_pid"] = engine._process.pid
                evidence["executable_sha256"] = sha256(
                    Path("/proc", str(engine._process.pid), "exe").read_bytes()).hexdigest()
                command_bytes = bytearray()
                selecting = False
                pointer = None
                previous_snapshot = None

                def read(address, count):
                    return engine.request("read", address=address, count=count)["values"]

                def snapshot():
                    return {"sst": read(pointer, 6),
                            "sms_capacity": read(SMS_CAPACITY, 1),
                            "sms_flags": read(SMS_FLAGS, 1),
                            "sms_controller": read(SMS_CONTROLLER, 4)}

                def observe_commands(data, steps):
                    # Reassemble original TX independently of the card's parser.
                    # SELECT has a two-byte outgoing payload after its procedure
                    # ACK; the other observed commands only return card data.
                    nonlocal selecting
                    command_bytes.extend(data)
                    while len(command_bytes) >= (2 if selecting else 5):
                        length = 2 if selecting else 5
                        chunk = bytes(command_bytes[:length])
                        del command_bytes[:length]
                        if selecting:
                            evidence["select_requests"].append({
                                "steps": steps, "file": int.from_bytes(chunk, "big"),
                                "bytes": list(chunk)})
                            selecting = False
                        else:
                            evidence["commands"].append({"steps": steps, "bytes": list(chunk)})
                            self.assertEqual(chunk[0], 0xA0)
                            self.assertIn(chunk[1], (0xA4, 0xC0, 0xB0, 0xB2),
                                          "This finite contract expects only SELECT and read commands")
                            if chunk[1] == 0xA4:
                                self.assertEqual(chunk[2:], b"\x00\x00\x02")
                                selecting = True

                def step(steps=100000):
                    state = engine.request("run", steps=steps)
                    self.assertIsNone(state["halt"])
                    self.assertIsNone(state["last_call"], "Execute naturally from original reset")
                    self.assertEqual(state["uart_tx_dropped"], [0, 0, 0, 0])
                    pins = engine.request("uart_pins", port=3)
                    card.controls(pins["inputs"], pins["outputs"])
                    for port in range(3):
                        other = engine.request("uart_io", port=port)
                        self.assertEqual(other["dropped"], 0)
                    offered = bytes(card.pending) if card.ready else b""
                    wire = engine.request("uart_io", port=3, rx=list(offered))
                    self.assertEqual(wire["dropped"], 0)
                    self.assertGreaterEqual(wire["accepted"], 0)
                    self.assertLessEqual(wire["accepted"], len(offered))
                    card.accepted(wire["accepted"])  # Preserve every unaccepted suffix.
                    if offered or wire["values"]:
                        evidence["wire"].append({"steps": state["steps"],
                                                 "offered": list(offered),
                                                 "accepted": wire["accepted"],
                                                 "tx": wire["values"]})
                    observe_commands(wire["values"], state["steps"])
                    card.feed(wire["values"])
                    return state

                try:
                    while engine.state["steps"] < BOOT_STEPS:
                        step(min(1024 if engine.state["steps"] < 8_000_000 else 100000,
                                 BOOT_STEPS - engine.state["steps"]))
                    self.assertFalse(card.events, "Absent card must not supply ATR or data")
                    self.assertFalse(evidence["commands"])
                    pointer = int.from_bytes(bytes(read(SST_POINTER_ENTRY, 4)), "big")
                    self.assertTrue(0x40000000 <= pointer <= 0x400C3E10 - 6)
                    self.assertEqual(read(pointer, 6), [0, 5, 0, 0, 255, 255])
                    self.assertEqual(read(SMS_CAPACITY, 1), [0])
                    self.assertEqual(read(SMS_CONTROLLER, 4), [0, 0, 0, 0])
                    before = engine.state["steps"]
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    self.assertEqual(engine.request("state")["steps"], before)
                    expected_sst = [0, 0, 1, 2, *service_table]
                    sst_consumed = False
                    while engine.state["steps"] < TOTAL_STEPS:
                        state = step(min(100000, TOTAL_STEPS - engine.state["steps"]))
                        current = snapshot()
                        if current != previous_snapshot:
                            evidence["snapshots"].append({"steps": state["steps"], **current})
                            previous_snapshot = current
                        if current["sst"] == expected_sst:
                            sst_consumed = True
                        if not sms_available:
                            self.assertEqual(current["sms_capacity"], [0])
                            self.assertEqual(current["sms_controller"], [0, 0, 0, 0])
                        elif (sst_consumed and current["sms_capacity"] == [2]
                              and current["sms_flags"] == [3]
                              and current["sms_controller"] == [0, 0, 0, 1]):
                            break
                    self.assertTrue(sst_consumed, "Original F107 must consume the advertised SST")
                    self.assertEqual(read(pointer, 6), expected_sst)
                    headers = [event for event in card.events if event["kind"] == "header"]
                    self.assertIn({"kind": "header", "bytes": [0xA0, 0xB0, 0, 0, 2],
                                   "selected": 0x6F38}, headers)
                    self.assertIn({"kind": "read-transparent-data",
                                   "bytes": [0xB0, *service_table, 0x90, 0]}, card.events)
                    sms_headers = [event["bytes"] for event in headers if event["selected"] == 0x6F3C]
                    if sms_available:
                        self.assertEqual(read(SMS_CAPACITY, 1), [2])
                        self.assertEqual(read(SMS_FLAGS, 1), [3])
                        self.assertEqual(read(SMS_CONTROLLER, 4), [0, 0, 0, 1])
                        self.assertIn(0x6F3C, [item["file"] for item in evidence["select_requests"]])
                        self.assertIn([0xA0, 0xC0, 0, 0, 15], sms_headers)
                        self.assertIn({"kind": "metadata", "bytes": [0xC0, *SMS_METADATA, 0x90, 0]},
                                      card.events)
                        self.assertEqual([header for header in sms_headers if header[1] == 0xB2],
                                         [[0xA0, 0xB2, 1, 4, 176], [0xA0, 0xB2, 2, 4, 176]])
                        record_responses = []
                        active_header = None
                        for event in card.events:
                            if event["kind"] == "header":
                                active_header = event
                            elif event["kind"] == "read-record" and active_header["selected"] == 0x6F3C:
                                record_responses.append(event["bytes"])
                        self.assertEqual(record_responses,
                                         [[0xB2, 0, *([255] * 175), 0x90, 0]] * 2)
                    else:
                        self.assertEqual(engine.state["steps"], TOTAL_STEPS)
                        self.assertNotIn(0x6F3C, [item["file"] for item in evidence["select_requests"]])
                        self.assertFalse(sms_headers)
                finally:
                    evidence.update({"events": card.events, "final_state": engine.request("state"),
                                     "sst_pointer": pointer,
                                     "final_snapshot": snapshot() if pointer is not None else None,
                                     "unaccepted_card_bytes": list(card.pending),
                                     "partial_original_command": list(command_bytes),
                                     "select_payload_pending": selecting})
                    directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / (self.id() + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")

    def test_original_sms_metadata_and_two_empty_records_initialize_storage_controller(self):
        self.run_storage_card(sms_available=True)

    def test_original_service_table_without_sms_prevents_sms_selection_and_initialization(self):
        self.run_storage_card(sms_available=False)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 SIM storage contracts")
class Factory9555SIMStorageContractTests(SharedSIMStorageChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 SIM storage contracts")
class Factory9575SIMStorageContractTests(SharedSIMStorageChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
