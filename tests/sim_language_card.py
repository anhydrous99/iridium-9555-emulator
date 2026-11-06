"""Finite synthetic, read-only TS51.011 cards for original UART3 contracts.

LanguageSIM declares MF3F00/DF7F20/EF6F05 and two language preferences.
StorageSIM adds the service table and empty TELECOM ADN/SMS records.
Neither supplies identity, authentication, file writes or network service.
"""


def directory_metadata(file_id, kind, directories, files):
    # TS51.011 section9.2.1: B1 declares CHV1 disabled,1.8V and clock-stop support.
    return bytes((0, 0, 0, 0, file_id >> 8, file_id & 255, kind, 0, 0, 0, 0, 0,
                  9, 0xB1, directories, files, 4, 0, 0x83, 0x8A, 0x83, 0x8A))


class LanguageSIM:
    version = "synthetic-language-sim-v1"

    def __init__(self, languages=b"\x01\x04", *, memory_failure=False):
        if len(languages) != 2:
            raise ValueError("This finite card contains exactly two language bytes")
        self.languages = bytes(languages)
        self.memory_failure = memory_failure
        self.metadata = {
            0x3F00: directory_metadata(0x3F00, 1, 1, 0),
            0x7F20: directory_metadata(0x7F20, 2, 0, 1),
            # READ ALW; UPDATE CHV1; valid transparent EF; two data bytes.
            0x6F05: bytes((0, 0, 0, 2, 0x6F, 0x05, 4, 0, 1, 0xF0, 0x44, 1, 2, 0, 0)),
        }
        self.parents = {0x7F20: 0x3F00, 0x6F05: 0x7F20}
        self.contents = {0x6F05: self.languages}
        self.records = {}
        self.ready = False
        self.released = False
        self.atr_due = False
        self.pending = bytearray()
        self.buffer = bytearray()
        self.selecting = False
        self.selected = self.directory = 0x3F00
        self.events = []

    def controls(self, inputs, outputs):
        released = bool(inputs & 1) and outputs & 0x30 == 0x30
        if not released:
            self.pending.clear()
            self.buffer.clear()
            self.selecting = False
            self.selected = self.directory = 0x3F00
            self.atr_due = False
        elif not self.released:
            self.atr_due = True
        self.released = released
        self.ready = released and bool(outputs & 4)
        # Original B462C stops/restarts bit04 without resetting card selection.
        if self.ready and self.atr_due:
            self.queue(b"\x3B\x00", "reset-atr")
            self.atr_due = False

    def queue(self, data, kind):
        if self.pending:
            raise AssertionError("Card response would overwrite an unaccepted suffix")
        self.pending.extend(data)
        self.events.append({"kind": kind, "bytes": list(data)})

    def accepted(self, count):
        if not 0 <= count <= len(self.pending):
            raise ValueError("Invalid accepted-byte count")
        del self.pending[:count]

    def feed(self, data):
        if data and not self.released:
            raise AssertionError("SIM command arrived before the observed reset release")
        self.buffer.extend(data)
        while self.buffer:
            if self.selecting:
                if len(self.buffer) < 2:
                    return
                file_id = int.from_bytes(self.buffer[:2], "big")
                del self.buffer[:2]
                self.selecting = False
                parent = self.parents.get(file_id)
                allowed = file_id == 0x3F00 or parent is not None and (
                    parent == self.directory or parent == 0x3F00)
                if not allowed:
                    self.queue(b"\x94\x04", "file-not-found")
                else:
                    self.selected = file_id
                    if self.metadata[file_id][6] != 4:
                        self.directory = file_id
                    self.queue(bytes((0x9F, len(self.metadata[file_id]))), "selected")
                continue
            if len(self.buffer) < 5:
                return
            header = bytes(self.buffer[:5])
            del self.buffer[:5]
            self.events.append({"kind": "header", "bytes": list(header),
                                "selected": self.selected})
            cla, ins, p1, p2, p3 = header
            if cla != 0xA0:
                self.queue(b"\x6E\x00", "unsupported-class")
            elif ins == 0xA4:
                if p1 or p2:
                    self.queue(b"\x6B\x00", "select-parameters")
                elif p3 != 2:
                    self.queue(b"\x67\x00", "select-length")
                else:
                    self.selecting = True
                    self.queue(b"\xA4", "select-procedure")
            elif ins == 0xC0:
                metadata = self.metadata[self.selected]
                length = p3 or 256
                if p1 or p2:
                    self.queue(b"\x6B\x00", "metadata-parameters")
                elif length > len(metadata):
                    self.queue(b"\x67\x00", "metadata-length")
                else:
                    self.queue(b"\xC0" + metadata[:length] + b"\x90\x00", "metadata")
            elif ins == 0xB0:
                offset, length = (p1 << 8) | p2, p3 or 256
                if self.metadata[self.selected][6] != 4:
                    self.queue(b"\x94\x00", "no-elementary-file")
                elif self.selected not in self.contents:
                    self.queue(b"\x94\x08", "read-structure")
                elif p1 & 0x80 or offset + length > len(self.contents[self.selected]):
                    self.queue(b"\x94\x02", "read-range")
                elif self.memory_failure:
                    self.queue(b"\x92\x40", "read-memory-failure")
                else:
                    self.queue(b"\xB0" + self.contents[self.selected][offset:offset + length] + b"\x90\x00",
                               "read-language-data" if self.selected == 0x6F05 else "read-transparent-data")
            elif ins == 0xB2:
                records = self.records.get(self.selected)
                if self.metadata[self.selected][6] != 4:
                    self.queue(b"\x94\x00", "no-elementary-file")
                elif records is None or p2 != 4:
                    self.queue(b"\x94\x08", "record-structure")
                elif not 1 <= p1 <= len(records):
                    self.queue(b"\x94\x02", "record-range")
                elif (p3 or 256) != len(records[p1 - 1]):
                    self.queue(b"\x67\x00", "record-length")
                else:
                    self.queue(b"\xB2" + records[p1 - 1] + b"\x90\x00", "read-record")
            else:
                self.queue(b"\x6D\x00", "unsupported-instruction")


class StorageSIM(LanguageSIM):
    """Declared empty ADN/SMS geometry, with an independently gated service table."""

    version = "synthetic-readonly-storage-sim-v1"

    def __init__(self, *, sms_available=True):
        super().__init__()
        self.metadata[0x3F00] = directory_metadata(0x3F00, 1, 2, 0)
        self.metadata[0x7F20] = directory_metadata(0x7F20, 2, 0, 2)
        self.metadata[0x7F10] = directory_metadata(0x7F10, 2, 0, 2)
        self.parents.update({0x7F10: 0x3F00, 0x6F38: 0x7F20,
                             0x6F3A: 0x7F10, 0x6F3C: 0x7F10})
        # SST service2=ADN, service4=SMS; each has allocated/activated bits.
        self.contents[0x6F38] = b"\xCC\x00" if sms_available else b"\x0C\x00"
        self.metadata[0x6F38] = bytes((0, 0, 0, 2, 0x6F, 0x38, 4, 0, 0x14, 0xF0, 0x44, 1, 2, 0, 0))
        self.metadata[0x6F3A] = bytes((0, 0, 0, 64, 0x6F, 0x3A, 4, 0, 0x11, 0xF0, 0x22, 1, 2, 1, 32))
        self.metadata[0x6F3C] = bytes((0, 0, 1, 96, 0x6F, 0x3C, 4, 0, 0x11, 0xF0, 0x44, 1, 2, 1, 176))
        self.records = {0x6F3A: (b"\xFF" * 32,) * 2,
                        0x6F3C: (b"\x00" + b"\xFF" * 175,) * 2}
