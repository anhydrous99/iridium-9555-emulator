"""Finite SMSP extension of the synthetic message card, without identity/RF.

TS51.011 10.5.6 defines a linear-fixed Y+28-byte SMSP record. This card
declares Y=4, one record, and explicit SCA/PID/DCS/validity parameters.
"""

from .sim_language_card import directory_metadata
from .sim_message_card import MessageSIM


# Four alpha bytes, indicator E1 (only destination absent), PID/DCS/VP zero.
# The inert test address +12345 is TON91 with low-nibble-first BCD and F filler.
INITIAL_SMSP = b"SMSC\xE1" + b"\xFF" * 12 + bytes.fromhex("04 91 21 43 F5") + b"\xFF" * 7 + b"\x00" * 3


class ServiceCenterSIM(MessageSIM):
    version = "synthetic-writable-service-center-sim-v1"

    def __init__(self, *, smsp_write_memory_failure=False):
        super().__init__()
        self.smsp_write_memory_failure = smsp_write_memory_failure
        self.metadata[0x7F10] = directory_metadata(0x7F10, 2, 0, 4)
        self.contents[0x6F38] = b"\xCC\x00\xC0"  # Service12 allocated/activated.
        self.metadata[0x6F38] = bytes.fromhex("00 00 00 03 6F 38 04 00 14 F0 44 01 02 00 00")
        self.parents[0x6F42] = 0x7F10
        self.metadata[0x6F42] = bytes.fromhex("00 00 00 20 6F 42 04 00 11 F0 44 01 02 01 20")
        self.records[0x6F42] = (INITIAL_SMSP,)

    def _begin_write(self, header):
        cla, ins, record, mode, length = header
        if self.selected != 0x6F42 or ins != 0xDC:
            return super()._begin_write(header)
        if cla != 0xA0:
            self.queue(b"\x6E\x00", "unsupported-class")
        elif mode != 4:
            self.queue(b"\x94\x08", "record-structure")
        elif record != 1:
            self.queue(b"\x94\x02", "record-range")
        elif length != 32:
            self.queue(b"\x67\x00", "record-length")
        elif self.smsp_write_memory_failure:
            self.queue(b"\x92\x40", "smsp-write-memory-failure")
        else:
            self.queue(b"\xDC", "update-record-procedure")
            self._write = (ins, self.selected, record, length)
