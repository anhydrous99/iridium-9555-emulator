"""Firmware-inferred AVR USART0 ↔ modem logical UART1 wiring.

The AVR routes DPL channel 7 on USART0; the modem DPL initializer selects
logical UART1. Instruction quanta are deterministic, not a measured clock ratio.
"""

from .engine import EngineError


class ModemLink:
    quantum = 4096

    def __init__(self, avr, modem, image):
        self.endpoints = ((avr, 0), (modem, 1))
        self.image = image
        self.pending = [bytearray(), bytearray()]
        self.delivered = [0, 0]
        self.error = None

    def exchange(self, *, avr_reset=False):
        if self.error:
            raise EngineError(self.error)
        try:
            for direction, (source, port) in enumerate(self.endpoints):
                response = source.request("uart_io", port=port)
                if direction == 1 and avr_reset:
                    self.pending[direction].clear()
                else:
                    self.pending[direction].extend(response["values"])
                if response["dropped"]:
                    raise EngineError("UART capture overflow on the processor link; reset before continuing")
                if len(self.pending[direction]) > 4096:
                    raise EngineError("Processor link backlog exceeded 4096 bytes; reset before continuing")
            for direction, pending in enumerate(self.pending):
                if not pending:
                    continue
                target, port = self.endpoints[1 - direction]
                data = list(pending[:255])
                response = target.request("uart_io", port=port, rx=data, tx_limit=0)
                accepted = response["accepted"]
                if type(accepted) is not int or not 0 <= accepted <= len(data):
                    raise EngineError("Invalid UART acknowledgement from processor link")
                del pending[:accepted]
                self.delivered[direction] += accepted
        except EngineError as error:
            self.error = str(error)
            raise

    def state(self):
        return {"connected": True, "modem": self.image,
                "assumption": "inferred-avr-usart0-modem-uart1",
                "quantum_instructions": self.quantum,
                "avr_to_modem": self.delivered[0], "modem_to_avr": self.delivered[1],
                "pending": [len(data) for data in self.pending], "error": self.error}


class SpiLink:
    """BC5 serial DMA ↔ AVR slave; replies wait for the next instruction quantum."""

    def __init__(self, bc5, avr, model, *, reset_count=0):
        if model not in ("9555", "9575"):
            raise ValueError("Unknown handset model for BC5/AVR SPI link")
        if type(reset_count) is not int or reset_count < 0:
            raise EngineError("Invalid BC5 reset counter")
        self.bc5, self.avr, self.model = bc5, avr, model
        self.hold_reset = False
        self.pending = False
        self.transferred = self.resets = self.stale = self.undriven = 0
        self.reset_count = reset_count
        self.error = None
        self._byte = self._reply = None

    @property
    def quantum(self):
        return 128 if self.pending else 4096

    @staticmethod
    def _number(value, maximum):
        return type(value) is int and 0 <= value <= maximum

    def exchange(self):
        if self.error:
            raise EngineError(self.error)
        try:
            acknowledgement = self._reply is not None
            arguments = ({"received": self._reply, "sequence": self._byte[1]}
                         if acknowledgement else {})
            response = self.bc5.request("serial", **arguments)
            if not isinstance(response, dict):
                raise EngineError("Invalid serial response on BC5/AVR SPI link")
            value, sequence = response.get("value"), response.get("sequence")
            active, remaining = response.get("active"), response.get("remaining")
            gpio = response.get("gpio")
            if ("value" not in response or (value is not None and not self._number(value, 255))
                    or not self._number(sequence, 0xFFFFFFFF) or type(active) is not bool
                    or type(remaining) is not int or remaining < 0
                    or not isinstance(gpio, dict)
                    or not self._number(gpio.get("output"), 0xFFFFFFFF)
                    or not self._number(gpio.get("direction"), 0xFFFFFFFF)
                    or type(gpio.get("reset_count")) is not int or gpio["reset_count"] < self.reset_count
                    or ((value is not None or remaining) and not active)):
                raise EngineError("Invalid serial response on BC5/AVR SPI link")

            held = bool(gpio["direction"] & 0x8000 and not gpio["output"] & 0x8000)
            reset = gpio["reset_count"] != self.reset_count or (held and not self.hold_reset)
            if reset:
                self.avr.request("warm_reset")
                self.resets += 1
            self.reset_count, self.hold_reset = gpio["reset_count"], held

            if self._byte is not None:
                if reset or (not acknowledgement and (not active or sequence != self._byte[1])):
                    self.stale += 1
                    self._byte = self._reply = None
                elif acknowledgement:
                    self._byte = self._reply = None
                elif value is not None:
                    raise EngineError("Native serial controller reissued an outstanding SPI byte")
            if value is not None:
                self._byte = value, sequence

            snapshot = self.avr.request("pin_state")
            pins = snapshot.get("pins") if isinstance(snapshot, dict) else None
            if (not isinstance(pins, list) or len(pins) < 3
                    or any(not self._number(pin, 255) for pin in pins)):
                raise EngineError("Invalid AVR pins on BC5/AVR SPI link")
            # Original SPI ISRs toggle PB0/PA7; irq_set drives PA3/PC2.
            handshake = pins[1] & 1 if self.model == "9555" else pins[0] & 0x80
            attention = pins[0] & 8 if self.model == "9555" else pins[2] & 4
            self.bc5.request("pins", mask=0x5000,
                             value=(0x1000 if handshake else 0) | (0x4000 if attention else 0))

            selected = bool(gpio["direction"] & 0x10 and not gpio["output"] & 0x10)
            if self._byte is not None and self._reply is None and not held and selected:
                reply = self.avr.request("spi", value=self._byte[0])
                if not isinstance(reply, dict) or "value" not in reply:
                    raise EngineError("Invalid AVR response on BC5/AVR SPI link")
                reply = reply["value"]
                if reply is None:
                    self.undriven += 1
                elif self._number(reply, 255):
                    self._reply = reply
                    self.transferred += 1
                else:
                    raise EngineError("Invalid AVR response on BC5/AVR SPI link")
            self.pending = active or self._byte is not None
        except EngineError as error:
            self.error = str(error)
            raise

    def state(self):
        return {"connected": True, "model": self.model,
                "assumption": "inferred-bc5-serial-avr-spi",
                "quantum_instructions": self.quantum, "transferred": self.transferred,
                "pending": self.pending, "hold_reset": self.hold_reset,
                "reset_count": self.reset_count, "resets": self.resets,
                "stale": self.stale, "undriven": self.undriven, "error": self.error}
