from pathlib import Path
from itertools import product
import unittest

from iridium.board import ModemLink
from iridium.engine import EngineError
from iridium.firmware import parse_firmware
from iridium.session import Session
from test_session import FakeEngine


class Endpoint:
    def __init__(self, transmit=(), capacity=255):
        self.transmit = list(transmit)
        self.receive = []
        self.capacity = capacity
        self.dropped = 0
        self.ports = []

    def request(self, op, *, port, rx=(), tx_limit=255):
        self.ports.append(port)
        accepted = min(len(rx), self.capacity)
        self.receive.extend(rx[:accepted])
        values = self.transmit[:tx_limit]
        del self.transmit[:tx_limit]
        return {"accepted": accepted, "values": values, "dropped": self.dropped}


class ModemLinkTests(unittest.TestCase):
    def test_held_avr_reset_discards_new_input_and_the_existing_receive_backlog(self):
        avr, modem = Endpoint(capacity=0), Endpoint([81])
        link = ModemLink(avr, modem, "trx")
        link.exchange()
        self.assertEqual(link.state()["pending"], [0, 1])
        modem.transmit = [82]
        link.exchange(avr_reset=True)
        self.assertEqual(link.state()["pending"], [0, 0])
        avr.capacity = 255
        link.exchange()
        self.assertEqual(avr.receive, [])
        modem.transmit = [83]
        link.exchange()
        self.assertEqual(avr.receive, [83])
        self.assertEqual(link.state()["modem_to_avr"], 1)

    def test_bidirectional_bytes_survive_partial_acceptance_in_order(self):
        avr, modem = Endpoint([1, 2, 3], capacity=1), Endpoint([4, 5], capacity=2)
        link = ModemLink(avr, modem, "trx")
        link.exchange()
        self.assertEqual(modem.receive, [1, 2])
        self.assertEqual(avr.receive, [4])
        self.assertEqual(link.state()["pending"], [1, 1])
        link.exchange()
        self.assertEqual(modem.receive, [1, 2, 3])
        self.assertEqual(avr.receive, [4, 5])
        self.assertEqual(link.state()["pending"], [0, 0])
        self.assertEqual(link.state()["avr_to_modem"], 3)
        self.assertEqual(link.state()["modem_to_avr"], 2)
        self.assertEqual(set(avr.ports), {0})
        self.assertEqual(set(modem.ports), {1})

    def test_capture_loss_is_latched_and_stops_further_delivery(self):
        avr, modem = Endpoint([1]), Endpoint()
        avr.dropped = 1
        link = ModemLink(avr, modem, "trx")
        with self.assertRaisesRegex(EngineError, "overflow"):
            link.exchange()
        avr.dropped = 0
        with self.assertRaisesRegex(EngineError, "overflow"):
            link.exchange()
        self.assertEqual(modem.receive, [])
        self.assertIsNotNone(link.state()["error"])

    def test_unconsumed_link_bytes_have_a_hard_bound(self):
        avr, modem = Endpoint(capacity=0), Endpoint(capacity=0)
        link = ModemLink(avr, modem, "trx")
        for _ in range(16):
            avr.transmit = [42] * 255
            link.exchange()
        avr.transmit = [42] * 255
        with self.assertRaisesRegex(EngineError, "backlog"):
            link.exchange()

    def test_session_runs_only_selected_modem_and_rebuilds_link_after_reset(self):
        class ConnectedEngine(FakeEngine):
            def request(self, op, **arguments):
                if op == "uart_io":
                    self.calls.append((op, arguments))
                    return {"accepted": len(arguments.get("rx", [])), "values": [], "dropped": 0}
                return super().request(op, **arguments)

        images = [parse_firmware(bytes(size), name, image)
                  for size, name, image in ((8678, "avr.bin", "avr"),
                                             (0x260760, "trx.bin", "trx"),
                                             (0xA7BF8, "ptt.bin", "ptt"))]
        with Session(Path("unused"), images, ConnectedEngine) as session:
            old_link = session.modem_link
            session.control("step", 9000)
            self.assertEqual(session.engines["avr"].state["steps"], 9000)
            self.assertEqual(session.engines["trx"].state["steps"], 9000)
            self.assertEqual(session.engines["ptt"].state["steps"], 0)
            self.assertEqual([args["steps"] for op, args in session.engines["avr"].calls if op == "run"],
                             [4096, 4096, 808])
            session.control("reset")
            self.assertIsNot(session.modem_link, old_link)
            self.assertEqual(session.state()["processor_link"]["pending"], [0, 0])


class ExecutingModemLinkTests(unittest.TestCase):
    def test_modem_traffic_during_reset_is_lost_but_later_bytes_arrive(self):
        executable = Path(__file__).resolve().parents[1] / "zig-out/bin/iridium-core"
        if not executable.is_file():
            self.skipTest("Build the native executor first")

        def operand(op, value):
            return [(((value + 0x80) >> 8) & 255) << 8, ((value & 255) << 8) | op]

        # BC5 either holds PIO15 across quanta or pulses it within a single quantum.
        primary = operand(0x14, 0x8000) + operand(0x25, 0x61)
        primary += operand(0x14, 0) + operand(0x25, 0x62)
        release = operand(0x14, 0x8000) + operand(0x25, 0x62) + [0x00E0]
        # AVR enables USART0, polls RXC and reads a received byte into r18.
        receiver = [0xE100, 0x9300, 0xC1, 0x9110, 0xC0, 0xFF17, 0xCFFC, 0x9120, 0xC6, 0xCFFF]
        # SPARC writes Q to UART1 and loops.
        sender = [0x03200000, 0x82106200, 0x84102051, 0xC4206000, 0x10800000, 0x01000000]
        for model, bsz, asz in (("9555", 0x310FBA, 8678), ("9575", 0x36BB22, 14296)):
            for image, size in (("trx", 0x260760), ("ptt", 0xA7BF8)):
                for timing, held in product(("during", "after", "silent"), (False, True)):
                    program = primary + [0] * (600 if held else 0) + release
                    modem = sender if timing == "during" else [0x01000000] * 1200 + sender if timing == "after" else sender[-2:]
                    firmware = [parse_firmware(b"".join(w.to_bytes(2, "little") for w in program).ljust(bsz, b"\0"),
                                               "bc5.bin", "bc5", model=model),
                                parse_firmware(b"".join(w.to_bytes(2, "little") for w in receiver).ljust(asz, b"\xff"),
                                               "avr.bin", "avr", model=model),
                                parse_firmware(b"".join(w.to_bytes(4, "big") for w in modem).ljust(size, b"\xff"),
                                               image + ".bin", image, model=model)]
                    with self.subTest(model=model, image=image, timing=timing, held=held), Session(executable, firmware, modem_image=image) as session:
                        session.control("step", 128)
                        self.assertEqual(session.spi_link.hold_reset, held)
                        self.assertEqual(session.engines["avr"].state["steps"], 0 if held else 128)
                        for _ in range(5):
                            session.control("step", 128)
                        session.control("step", 2048)
                        session.control("step", 128)
                        self.assertFalse(session.spi_link.hold_reset)
                        # A pulse completed before auxiliary execution; immediate output is post-release.
                        received = timing == "after" or (timing == "during" and not held)
                        self.assertEqual(session.engines["avr"].state["registers"][18], 81 if received else 0)
                        self.assertIsNone(session.engines["avr"].state["halt"])

    def test_guest_machine_code_exchanges_bytes_across_native_processors(self):
        executable = Path(__file__).resolve().parents[1] / "zig-out/bin/iridium-core"
        if not executable.is_file():
            self.skipTest("Build the native executor first")

        def fmt3(op, op3, rd, rs1, immediate):
            return (op << 30) | (rd << 25) | (op3 << 19) | (rs1 << 14) | 0x2000 | immediate

        # AVR transmits 'A', then waits for and reads one reply into r18.
        avr_words = (0xE108, 0x9300, 0xC1, 0xE401, 0x9300, 0xC6,
                     0x9110, 0xC0, 0xFF17, 0xCFFC, 0x9120, 0xC6, 0xCFFF)
        # SPARC polls physical UART200, stores the byte in SDRAM and transmits byte+1.
        sparc_words = (0x03200000, fmt3(2, 2, 1, 1, 0x200),
                       fmt3(3, 0, 2, 1, 4), fmt3(2, 0x11, 0, 2, 0x80),
                       0x12BFFFFE, 0x01000000, fmt3(3, 0, 2, 1, 0), 0x07100000,
                       fmt3(3, 4, 2, 3, 0), fmt3(2, 0, 2, 2, 1),
                       fmt3(3, 4, 2, 1, 0), 0x10800000, 0x01000000)
        modem = b"".join(word.to_bytes(4, "big") for word in sparc_words).ljust(0x260760, b"\xff")
        for model, size in (("9555", 8678), ("9575", 14296)):
            with self.subTest(model=model):
                avr = b"".join(word.to_bytes(2, "little") for word in avr_words).ljust(size, b"\xff")
                images = [parse_firmware(avr, "avr.bin", "avr", model=model),
                          parse_firmware(modem, "trx.bin", "trx", model=model)]
                with Session(executable, images) as session:
                    session.control("step", 16384)
                    result = session.probe("trx", "read", {"address": 0x40000000, "count": 4})
                    self.assertEqual(result["values"], [0, 0, 0, 65])
                    self.assertEqual(session.engines["avr"].state["registers"][18], 66)
                    link = session.state()["processor_link"]
                    self.assertEqual((link["avr_to_modem"], link["modem_to_avr"]), (1, 1))
                    self.assertIsNone(link["error"])


class ExecutingBoardReloadTests(unittest.TestCase):
    def test_primary_replacement_releases_power_on_the_retained_avr(self):
        executable = Path(__file__).resolve().parents[1] / "zig-out/bin/iridium-core"
        if not executable.is_file():
            self.skipTest("Build the native executor first")
        for model, bc5_size, avr_size in (("9555", 0x310FBA, 8678), ("9575", 0x36BB22, 14296)):
            with self.subTest(model=model):
                bc5 = parse_firmware(b"\xe0\0".ljust(bc5_size, b"\0"), "bc5.bin", "bc5", model=model)
                avr = parse_firmware(b"\xff\xcf".ljust(avr_size, b"\xff"), "avr.bin", "avr", model=model)
                with Session(executable, [bc5, avr]) as session:
                    retained = session.engines["avr"]
                    session._power_input(True)
                    session.keys.add("power")
                    port, bit = session.profile.power_pin
                    self.assertEqual(retained.request("pin_state")["inputs"][port] & (1 << bit), 0)
                    session.load(bc5)
                    self.assertIs(session.engines["avr"], retained)
                    self.assertNotEqual(retained.request("pin_state")["inputs"][port] & (1 << bit), 0)
                    self.assertEqual(session.keys, set())

    def test_avr_replacement_releases_retained_key_contacts_and_cancels_owned_spi_dma(self):
        executable = Path(__file__).resolve().parents[1] / "zig-out/bin/iridium-core"
        if not executable.is_file():
            self.skipTest("Build the native executor first")

        def operand(op, value):
            # XAP prefix and consuming instruction; both operand bytes are signed.
            return [(((value + 0x80) >> 8) & 0xFF) << 8, ((value & 0xFF) << 8) | op]

        words = []
        for address, value in ((0x61, 0x8010), (0x62, 0x8000), (0xFDBE, 1),
                               (0xFDBF, 0x440), (0xFDC3, 1), (0xFDC1, 1)):
            words.extend(operand(0x14, value))  # ld AL,#value
            words.extend(operand(0x25, address))  # st AL,@address
        words.append(0x00E0)  # bra .
        program = b"".join(word.to_bytes(2, "little") for word in words)
        for model, bc5_size, avr_size in (("9555", 0x310FBA, 8678), ("9575", 0x36BB22, 14296)):
            with self.subTest(model=model):
                bc5 = parse_firmware(program.ljust(bc5_size, b"\0"), "bc5.bin", "bc5", model=model)
                avr = parse_firmware(b"\xff\xcf".ljust(avr_size, b"\xff"), "avr.bin", "avr", model=model)
                with Session(executable, [bc5, avr]) as session:
                    self.assertTrue(session.key("1", True)["delivered"])
                    primary, old_avr, old_link = session.engines["bc5"], session.engines["avr"], session.spi_link
                    before = primary.request("state")
                    self.assertNotEqual(before["gpio"]["key_contacts"], 0)
                    self.assertTrue(before["serial_waiting"])
                    self.assertIsNotNone(old_link._byte)
                    generation = session.key_generations["1"]
                    session.ui_initialized = session.lcd_seen = True

                    session.load(avr)

                    after = primary.request("state")
                    self.assertIs(session.engines["bc5"], primary)
                    self.assertIsNone(old_avr._process)
                    self.assertEqual(after["gpio"]["key_contacts"], 0)
                    self.assertFalse(after["serial_waiting"])
                    self.assertFalse(primary.request("serial")["active"])
                    self.assertIsNot(session.spi_link, old_link)
                    self.assertFalse(session.ui_initialized)
                    self.assertFalse(session.lcd_seen)
                    self.assertEqual(session.keys, set())
                    self.assertGreater(session.key_generations["1"], generation)
                    self.assertFalse(session.key("1", False, generation)["delivered"])
                    # Re-execution creates a fresh byte owned by the new bridge.
                    session.control("step", 128)
                    self.assertIsNotNone(session.spi_link._byte)
                    self.assertNotEqual(session.spi_link._byte[1], old_link._byte[1])


if __name__ == "__main__":
    unittest.main()
