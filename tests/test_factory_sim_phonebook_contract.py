"""Original TRX consumes empty/populated ADN records into its phonebook cache.

The finite external card is read-only. Natural UART3 execution and original
consumer state establish initialization, without GUI contact editing, writes,
subscriber authentication, AT requests or RF service.
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
SST_POINTER_ENTRY = 0x70002270 + 7 * 4
PHONEBOOK_INITIALIZED = 0x400AA9F8  # Original 918CC stores the big-endian word 1.
SIM_USED = 0x400AA9FC
SIM_CAPACITY = 0x400AA9FE  # Original 918DC(...,1); geometry from 92708.
ALPHA_LENGTH = 0x400ABEFA
READ_INFLIGHT = 0x400ABEFC
ADN_METADATA = bytes.fromhex("00 00 00 40 6F 3A 04 00 11 F0 22 01 02 01 20")
EMPTY_ADN = b"\xFF" * 32
# TS51.011 10.5.1: alpha18, length4, international TON/NPI91, BCD12345,
# seven unused number bytes, then absent capability/extension identifiers.
ADG_ADN = b"Adg" + b"\xFF" * 15 + bytes.fromhex("04 91 21 43 F5") + b"\xFF" * 9
FIRST_SIM_INDEX = 101  # Original local capacity is100; ADN record1 follows it.
NAME_INDEX = 0x400AACED + FIRST_SIM_INDEX * 16
NUMBER_INDEX = 0x400AA9FD + FIRST_SIM_INDEX * 3


class SharedSIMPhonebookChecks:
    def run_adn_card(self, *, populated):
        require_factory_host()
        firmware = next(image for image in factory_firmware(
            self.model, self.firmware_directory, modem=True) if image.image == "trx")
        card = StorageSIM()
        records = (ADG_ADN if populated else EMPTY_ADN, EMPTY_ADN)
        card.records[0x6F3A] = records  # External read-only card data only.
        self.assertEqual(card.contents[0x6F38], b"\xCC\x00")
        self.assertEqual(card.metadata[0x6F3A], ADN_METADATA)
        self.assertEqual(tuple(map(len, records)), (32, 32))
        evidence = {
            "firmware": firmware.describe(), "card_version": card.version,
            "populated": populated,
            "service_table": [0xCC, 0], "adn_metadata": list(ADN_METADATA),
            "adn_records": [list(record) for record in card.records[0x6F3A]],
            "scope": "Natural original TRX reset, external read-only UART3 card and original ADN consumer/cache; no guest writes/calls, GUI editing, AT, authentication or RF service",
            "budget": {"absent_boot": BOOT_STEPS, "total": TOTAL_STEPS},
            "wire": [], "snapshots": [],
        }
        with tempfile.TemporaryDirectory(prefix="iridium-sim-adn-") as temporary:
            path = Path(temporary) / "trx.bin"
            path.write_bytes(firmware.data)
            with Engine(EXECUTABLE, "trx", path, model=self.model) as engine:
                evidence["worker_pid"] = engine._process.pid
                evidence["executable_sha256"] = sha256(
                    Path("/proc", str(engine._process.pid), "exe").read_bytes()).hexdigest()
                sst_pointer = None
                previous_snapshot = None

                def read(address, count):
                    return engine.request("read", address=address, count=count)["values"]

                def snapshot():
                    return {"sst": read(sst_pointer, 6),
                            "initialized": read(PHONEBOOK_INITIALIZED, 4),
                            "sim_capacity": read(SIM_CAPACITY, 1),
                            "sim_used": read(SIM_USED, 1),
                            "alpha_length": read(ALPHA_LENGTH, 1),
                            "read_inflight": read(READ_INFLIGHT, 4),
                            "name_index": read(NAME_INDEX, 16),
                            "number_index": read(NUMBER_INDEX, 3),
                            "name_sort_index": read(0x400ABDF0, 4),
                            "number_sort_index": read(0x400ABCF0, 4)}

                def step(steps=100000):
                    state = engine.request("run", steps=steps)
                    self.assertIsNone(state["halt"])
                    self.assertIsNone(state["last_call"], "Execute naturally from original reset")
                    self.assertEqual(state["uart_tx_dropped"], [0, 0, 0, 0])
                    pins = engine.request("uart_pins", port=3)
                    card.controls(pins["inputs"], pins["outputs"])
                    for port in range(3):
                        self.assertEqual(engine.request("uart_io", port=port)["dropped"], 0)
                    offered = bytes(card.pending) if card.ready else b""
                    wire = engine.request("uart_io", port=3, rx=list(offered))
                    self.assertEqual(wire["dropped"], 0)
                    self.assertGreaterEqual(wire["accepted"], 0)
                    self.assertLessEqual(wire["accepted"], len(offered))
                    card.accepted(wire["accepted"])  # Retain every unaccepted suffix.
                    if offered or wire["values"]:
                        evidence["wire"].append({"steps": state["steps"],
                                                 "offered": list(offered),
                                                 "accepted": wire["accepted"],
                                                 "tx": wire["values"]})
                    card.feed(wire["values"])
                    return state

                try:
                    while engine.state["steps"] < BOOT_STEPS:
                        step(min(1024 if engine.state["steps"] < 8_000_000 else 100000,
                                 BOOT_STEPS - engine.state["steps"]))
                    self.assertFalse(card.events, "Absent card supplies no ATR or file bytes")
                    sst_pointer = int.from_bytes(bytes(read(SST_POINTER_ENTRY, 4)), "big")
                    self.assertTrue(0x40000000 <= sst_pointer <= 0x400C3E10 - 6)
                    initial = snapshot()
                    self.assertEqual(initial["sst"], [0, 5, 0, 0, 255, 255])
                    self.assertEqual(initial["initialized"], [0, 0, 0, 0])
                    # 91824's default maximum is not consumed card geometry.
                    self.assertEqual(initial["sim_capacity"], [155])
                    self.assertEqual(initial["sim_used"], [0])
                    self.assertEqual(initial["alpha_length"], [0])
                    self.assertEqual(read(0x400AA9FF, 1), [100])
                    self.assertEqual(initial["name_index"], [0] * 16)
                    evidence["initial_snapshot"] = initial
                    before = engine.state["steps"]
                    engine.request("uart_pins", port=3, value=1, mask=1)
                    self.assertEqual(engine.request("state")["steps"], before)
                    geometry_before_completion = False
                    while engine.state["steps"] < TOTAL_STEPS:
                        state = step(min(100000, TOTAL_STEPS - engine.state["steps"]))
                        current = snapshot()
                        if current != previous_snapshot:
                            evidence["snapshots"].append({"steps": state["steps"], **current})
                            previous_snapshot = current
                        if (current["sim_capacity"] == [2] and current["alpha_length"] == [18]
                                and current["initialized"] == [0, 0, 0, 0]):
                            geometry_before_completion = True
                        if (current["initialized"] == [0, 0, 0, 1]
                                and current["sim_capacity"] == [2]
                                and current["alpha_length"] == [18]):
                            break
                    self.assertTrue(geometry_before_completion,
                                    "Original metadata must update geometry before record completion")
                    self.assertEqual(current["sst"], [0, 0, 1, 2, 0xCC, 0])
                    self.assertEqual(current["sim_capacity"], [2])
                    self.assertEqual(current["alpha_length"], [18])
                    self.assertEqual(current["sim_used"], [int(populated)])
                    self.assertEqual(current["initialized"], [0, 0, 0, 1])
                    self.assertEqual(current["read_inflight"], [0, 0, 0, 0])
                    headers = [event for event in card.events if event["kind"] == "header"]
                    self.assertIn({"kind": "header", "bytes": [0xA0, 0xB0, 0, 0, 2],
                                   "selected": 0x6F38}, headers)
                    adn_headers = [event["bytes"] for event in headers if event["selected"] == 0x6F3A]
                    self.assertIn([0xA0, 0xC0, 0, 0, 15], adn_headers)
                    self.assertIn({"kind": "metadata", "bytes": [0xC0, *ADN_METADATA, 0x90, 0]},
                                  card.events)
                    self.assertEqual([header for header in adn_headers if header[1] == 0xB2],
                                     [[0xA0, 0xB2, 1, 4, 32], [0xA0, 0xB2, 2, 4, 32]])
                    record_responses = []
                    active_header = None
                    for event in card.events:
                        if event["kind"] == "header":
                            active_header = event
                        elif event["kind"] == "read-record" and active_header["selected"] == 0x6F3A:
                            record_responses.append(event["bytes"])
                    self.assertEqual(record_responses,
                                     [[0xB2, *record, 0x90, 0] for record in records])
                    if populated:
                        # Original93540→92498/9240C/92340 stores the name and
                        # number search index at logical slot100+SIM record1.
                        # This compact number index strips the international
                        # prefix; it is not full-number or GUI readback.
                        self.assertEqual(current["name_index"], list(b"Adg" + b"\x00" * 13))
                        self.assertEqual(current["number_index"], [0x21, 0x43, 0xF5])
                        self.assertEqual(current["name_sort_index"], [101, 0, 0, 0])
                        self.assertEqual(current["number_sort_index"], [101, 0, 0, 0])
                    self.assertFalse(card.pending)
                finally:
                    evidence.update({"events": card.events, "final_state": engine.request("state"),
                                     "sst_pointer": sst_pointer,
                                     "final_snapshot": snapshot() if sst_pointer is not None else None,
                                     "unaccepted_card_bytes": list(card.pending),
                                     "partial_original_command": list(card.buffer)})
                    directory = Path(os.environ.get("IRIDIUM_E2E_ARTIFACTS", "test-artifacts/factory-peripheral"))
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / (self.id() + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")

    def test_original_adn_metadata_and_two_empty_records_initialize_phonebook_consumer(self):
        self.run_adn_card(populated=False)

    def test_original_populated_adn_record_updates_used_count_name_and_number_index(self):
        self.run_adn_card(populated=True)


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory9555 SIM ADN consumer contract")
class Factory9555SIMPhonebookContractTests(SharedSIMPhonebookChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory9575 SIM ADN consumer contract")
class Factory9575SIMPhonebookContractTests(SharedSIMPhonebookChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
