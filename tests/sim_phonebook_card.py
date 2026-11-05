"""Finite external ADN storage for the original serial phonebook contract.

Only EF_ADN6F3A UPDATE RECORD is writable: two opaque32-byte records, matching
StorageSIM's original-consumed geometry. Original9A5AC→A20E8→A3E34 builds ADN;
28CDC sends DC and B462C waits for its procedure ACK before sending the body.
This card does not implement AT commands, GUI editing, authentication or RF.
"""

from sim_language_card import StorageSIM
from sim_message_card import MessageSIM


EMPTY_ADN = b"\xFF" * 32


class PhonebookSIM(MessageSIM):
    version = "synthetic-writable-adn-sim-v1"

    def __init__(self, *, adn_records=None, adn_write_memory_failure=False):
        # Reuse MessageSIM's fragmented T=0 transport and reset handling, but
        # declare only StorageSIM's files. In particular there is no EF_SMSS.
        StorageSIM.__init__(self)
        self._write = None
        self.adn_write_memory_failure = adn_write_memory_failure
        rows = (EMPTY_ADN, EMPTY_ADN) if adn_records is None else tuple(adn_records)
        if len(rows) != 2 or any(not isinstance(row, (bytes, bytearray)) or len(row) != 32
                                 for row in rows):
            raise ValueError("This finite card has exactly two32-byte ADN records")
        self.records[0x6F3A] = tuple(bytes(row) for row in rows)

    def _begin_write(self, header):
        cla, ins, record, mode, length = header
        if cla != 0xA0:
            self.queue(b"\x6E\x00", "unsupported-class")
        elif self.metadata[self.selected][6] != 4:
            self.queue(b"\x94\x00", "no-elementary-file")
        elif self.selected != 0x6F3A or ins != 0xDC:
            self.queue(b"\x6D\x00", "unsupported-write")
        elif mode != 4:
            self.queue(b"\x94\x08", "record-structure")
        elif not 1 <= record <= 2:
            self.queue(b"\x94\x02", "record-range")
        elif length != 32:
            self.queue(b"\x67\x00", "record-length")
        elif self.adn_write_memory_failure:
            self.queue(b"\x92\x40", "adn-write-memory-failure")
        else:
            self.queue(b"\xDC", "update-record-procedure")
            self._write = (ins, self.selected, record, length)
