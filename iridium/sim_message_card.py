"""Finite external TS51.011 SMS storage; no identity, authentication or network.

StorageSIM's reads remain unchanged. This card adds only EF_SMS UPDATE RECORD
and its associated two-byte EF_SMSS UPDATE BINARY (TS51.011 sections10.5.3/7).
Original TRX8203C/28CDC issue DC; B462C waits for its procedure ACK before data.
"""

from .sim_language_card import StorageSIM, directory_metadata


class MessageSIM(StorageSIM):
    version = "synthetic-writable-message-sim-v1"

    def __init__(self, *, sms_available=True, sms_write_memory_failure=False):
        super().__init__(sms_available=sms_available)
        self.sms_write_memory_failure = sms_write_memory_failure
        self.metadata[0x7F10] = directory_metadata(0x7F10, 2, 0, 3)
        self.parents[0x6F43] = 0x7F10
        self.metadata[0x6F43] = bytes.fromhex(
            "00 00 00 02 6F 43 04 00 11 F0 44 01 02 00 00")
        # TS51.011 10.5.7: byte2 bit1=available, reserved bits2..8=1 -> FF.
        # Byte1 is a synthetic counter seed0; original6E394 loads both unchanged.
        self.contents[0x6F43] = b"\x00\xFF"
        self._write = None

    def controls(self, inputs, outputs):
        if not (inputs & 1 and outputs & 0x30 == 0x30):
            self._write = None
        super().controls(inputs, outputs)

    def feed(self, data):
        if data and not self.released:
            raise AssertionError("SIM command arrived before the observed reset release")
        for value in data:
            if self.pending:
                raise AssertionError("SIM command arrived before the card response was accepted")
            if self._write is not None:
                self.buffer.append(value)
                ins, file_id, position, length = self._write
                if len(self.buffer) == length:
                    body = bytes(self.buffer)
                    if ins == 0xDC:
                        records = list(self.records[file_id])
                        records[position - 1] = body
                        self.records[file_id] = tuple(records)
                    else:
                        previous = self.contents[file_id]
                        self.contents[file_id] = (
                            previous[:position] + body + previous[position + length:])
                    self.buffer.clear()
                    self._write = None
                    self.queue(b"\x90\x00", "updated-record" if ins == 0xDC else "updated-binary")
            elif (not self.selecting and len(self.buffer) == 4
                  and self.buffer[1] in (0xDC, 0xD6)):
                header = bytes(self.buffer) + bytes((value,))
                self.buffer.clear()
                self.events.append({"kind": "header", "bytes": list(header),
                                    "selected": self.selected})
                self._begin_write(header)
            else:
                # Delegate every read, SELECT and other command to the pinned peer.
                super().feed(bytes((value,)))

    def _begin_write(self, header):
        cla, ins, p1, p2, p3 = header
        length = p3 or 256
        if cla != 0xA0:
            self.queue(b"\x6E\x00", "unsupported-class")
        elif self.metadata[self.selected][6] != 4:
            self.queue(b"\x94\x00", "no-elementary-file")
        elif self.metadata[self.selected][13] != (1 if ins == 0xDC else 0):
            self.queue(b"\x94\x08", "write-structure")
        elif self.selected != (0x6F3C if ins == 0xDC else 0x6F43):
            self.queue(b"\x6D\x00", "unsupported-write")
        elif ins == 0xDC and p2 != 4:
            self.queue(b"\x94\x08", "record-structure")
        elif ins == 0xDC and not 1 <= p1 <= 2:
            self.queue(b"\x94\x02", "record-range")
        elif ins == 0xDC and length != 176:
            self.queue(b"\x67\x00", "record-length")
        elif ins == 0xD6 and (p1 & 0x80 or (p1 << 8 | p2) + length > 2):
            self.queue(b"\x94\x02", "write-range")
        elif ins == 0xDC and self.sms_write_memory_failure:
            self.queue(b"\x92\x40", "sms-write-memory-failure")
        else:
            self.queue(bytes((ins,)), "update-record-procedure" if ins == 0xDC else "update-binary-procedure")
            self._write = (ins, self.selected, p1 if ins == 0xDC else p1 << 8 | p2, length)
