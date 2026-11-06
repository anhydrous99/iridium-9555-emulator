"""External UART3 card peer; the HTTP test alone clocks the CPUs."""

from hashlib import sha256
from pathlib import Path
import threading

from iridium.engine import Engine
from sim_language_card import StorageSIM


class FactorySIMPeer:
    def __init__(self, testcase, handset, *, card=None):
        self.test = testcase
        self.engine = handset.session.engines["trx"]
        self.card = StorageSIM() if card is None else card
        self.request_method = Engine.request
        self.stop = threading.Event()
        self.errors = []
        self.wire = []
        self.controls = []
        self.workers = {
            image: {"pid": engine._process.pid,
                    "executable_sha256": sha256(Path(
                        f"/proc/{engine._process.pid}/exe").read_bytes()).hexdigest()}
            for image, engine in handset.session.engines.items()
        }
        # Physical card presence precedes initialize_ui and original modem reset.
        pins = self.engine.request("uart_pins", port=3, value=1, mask=1)
        testcase.assertEqual(pins["inputs"] & 1, 1)
        self.thread = threading.Thread(target=self._service, name="factory-sim")
        self.thread.start()

    def _service(self):
        try:
            previous = None
            while not self.stop.is_set():
                # These are the existing locked transport methods. Never touch
                # UART1/DPL, replace an Engine method, or run/step a processor.
                pins = self.engine.request("uart_pins", port=3)
                values = (pins["inputs"], pins["outputs"])
                if values != previous:
                    self.controls.append({"steps": self.engine.state["steps"],
                                          "inputs": values[0], "outputs": values[1]})
                    previous = values
                self.card.controls(*values)
                offered = bytes(self.card.pending) if self.card.ready else b""
                wire = self.engine.request("uart_io", port=3, rx=list(offered))
                if wire["dropped"]:
                    raise AssertionError(f"Original SIM UART lost bytes: {wire}")
                self.card.accepted(wire["accepted"])
                if offered or wire["values"]:
                    self.wire.append({"steps": self.engine.state["steps"],
                                      "offered": list(offered),
                                      "accepted": wire["accepted"], "tx": wire["values"]})
                self.card.feed(wire["values"])
                self.stop.wait(.001)
        except BaseException as error:
            self.errors.append(repr(error))

    def check(self):
        self.test.assertEqual(self.errors, [])
        self.test.assertTrue(self.thread.is_alive())
        self.test.assertIs(Engine.request, self.request_method)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        self.test.assertFalse(self.thread.is_alive(), "External SIM peer did not stop")
        self.test.assertEqual(self.errors, [])
        self.test.assertIs(Engine.request, self.request_method)

    def evidence(self):
        return {"card_version": self.card.version,
                "scope": "Finite synthetic card files declared below; no identity, authentication or service",
                "metadata": {hex(k): list(v) for k, v in self.card.metadata.items()},
                "contents": {hex(k): list(v) for k, v in self.card.contents.items()},
                "records": {hex(k): [list(v) for v in rows]
                            for k, rows in self.card.records.items()},
                "controls": self.controls, "wire": self.wire, "card_events": self.card.events,
                "errors": self.errors, "thread_closed": not self.thread.is_alive(),
                "workers": self.workers,
                "engine_request_method_unchanged": Engine.request is self.request_method}
