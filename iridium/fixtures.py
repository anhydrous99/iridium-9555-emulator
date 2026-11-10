"""Explicit synthetic peripherals, connected only through external serial pins."""

from datetime import datetime, timezone
import math
import struct

from .engine import EngineError
from .sim_phonebook_card import PhonebookSIM
from .sim_service_center_card import ServiceCenterSIM


class SyntheticSIM(ServiceCenterSIM):
    """Two writable ADN/SMS records and one SMS service-center record."""

    version = "synthetic-training-storage-v1"

    def __init__(self):
        super().__init__()
        self.adn_write_memory_failure = False

    def _begin_write(self, header):
        if self.selected == 0x6F3A:
            return PhonebookSIM._begin_write(self, header)
        return super()._begin_write(header)


class SIMPeer:
    def __init__(self, modem, card):
        self.modem, self.card = modem, card
        modem.request("uart_pins", port=3, value=1, mask=1)

    def exchange(self):
        pins = self.modem.request("uart_pins", port=3)
        self.card.controls(pins["inputs"], pins["outputs"])
        offered = list(self.card.pending[:255]) if self.card.ready else []
        response = self.modem.request("uart_io", port=3, rx=offered)
        accepted = response["accepted"]
        if response["dropped"] or type(accepted) is not int or not 0 <= accepted <= len(offered):
            raise EngineError("Synthetic SIM serial transport overflow or invalid acknowledgement")
        self.card.accepted(accepted)
        try:
            self.card.feed(response["values"])
        except AssertionError as error:
            raise EngineError(f"Synthetic SIM protocol: {error}") from error
        # Keep the diagnostic trace bounded in an interactive session.
        del self.card.events[:-512]


def ubx(message_class, message_id, payload):
    body = bytes((message_class, message_id)) + len(payload).to_bytes(2, "little") + payload
    a = b = 0
    for value in body:
        a = (a + value) & 255
        b = (b + a) & 255
    return b"\xb5\x62" + body + bytes((a, b))


class GPSPeer:
    """Finite UBX receiver for the original 9575 AVR configuration dialogue."""

    def __init__(self, avr, latitude, longitude, altitude, *, utc=None):
        for name, value, low, high in (("latitude", latitude, -90, 90),
                                       ("longitude", longitude, -180, 180),
                                       ("altitude", altitude, -1000, 100000)):
            if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number from {low} to {high}")
        self.avr = avr
        self.latitude, self.longitude, self.altitude = latitude, longitude, altitude
        self.utc = utc or datetime.now(timezone.utc)
        self.position = ubx(1, 2, struct.pack("<IiiiiII", 123000, round(longitude * 1e7),
                            round(latitude * 1e7), round((altitude + 2) * 1000),
                            round(altitude * 1000), 1000, 1000))
        solution = ubx(1, 6, struct.pack("<IihBBiiiIiiiIHBBI", 123000, 0, 2200, 3, 1,
                       0, 0, 0, 1000, 0, 0, 0, 100, 100, 0, 8, 0))
        d = self.utc
        utc_frame = ubx(1, 0x21, struct.pack("<IIiHBBBBBB", 123000, 1000, 0,
                        d.year, d.month, d.day, d.hour, d.minute, d.second, 7))
        velocity = ubx(1, 0x12, struct.pack("<IiiiIIiII", 123000, 0, 0, 0, 0, 0, 0, 100, 100))
        error = f"GPGST,{d:%H%M%S}.00,1.2,1.0,1.0,0.0,1.0,1.0,1.5"
        checksum = 0
        for value in error.encode("ascii"):
            checksum ^= value
        self.fix = self.position + solution + utc_frame + velocity + f"${error}*{checksum:02X}\r\n".encode("ascii")
        self.powered = False
        self.reset()

    def reset(self):
        self.pending = bytearray(self.position)
        self.buffer = bytearray()
        self.configurations = self.delivered = 0
        self.last_steps = self.avr.state.get("steps", 0)

    def exchange(self, *, avr_reset=False):
        pins = self.avr.request("pin_state")["pins"]
        enabled = len(pins) > 8 and bool(pins[8] & 0x80)
        if avr_reset or not enabled:
            self.reset()
            self.powered = False
            # Bytes emitted with the receiver off belong to the old power epoch.
            self.avr.request("uart_io", port=0)
            return
        if not self.powered:
            self.reset()
            self.powered = True
        response = self.avr.request("uart_io", port=0, rx=list(self.pending[:255]))
        accepted = response["accepted"]
        if response["dropped"] or type(accepted) is not int or not 0 <= accepted <= min(255, len(self.pending)):
            raise EngineError("Synthetic GPS serial transport overflow or invalid acknowledgement")
        del self.pending[:accepted]
        self.delivered += accepted
        self.buffer.extend(response["values"])
        while len(self.buffer) >= 6:
            if self.buffer[:2] != b"\xb5\x62":
                del self.buffer[0]
                continue
            length = int.from_bytes(self.buffer[4:6], "little")
            if length > 1024:
                del self.buffer[0]
                continue
            if len(self.buffer) < length + 8:
                break
            frame = bytes(self.buffer[:length + 8])
            del self.buffer[:length + 8]
            if frame != ubx(frame[2], frame[3], frame[6:-2]):
                continue
            if frame[2:6] == b"\x06\x01\x03\x00":
                self.pending.extend(ubx(5, 1, frame[2:4]))
                self.configurations += 1
                if self.configurations == 20:
                    self.pending.extend(self.fix)
        steps = self.avr.state.get("steps", 0)
        if steps < self.last_steps:
            self.reset()
        elif steps - self.last_steps >= 1000000 and not self.pending:
            self.pending.extend(self.fix if self.configurations >= 20 else self.position)
            self.last_steps = steps
        if len(self.pending) > 4096:
            raise EngineError("Synthetic GPS serial backlog exceeded 4096 bytes")

    def state(self):
        return {"enabled": True, "latitude": self.latitude, "longitude": self.longitude,
                "altitude": self.altitude, "utc": self.utc.isoformat(), "synthetic": True,
                "powered": self.powered, "configurations": self.configurations, "delivered": self.delivered}
