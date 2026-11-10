"""Finite, explicitly simulated modem at the original AVR DPL UART boundary.

This is a training peer, not TRX/DSP execution, authentication, RF or voice.
It never changes guest memory or processor execution. See docs/offline-modem.md.
"""

from collections import deque
from datetime import datetime, timezone, timedelta
from functools import reduce
from operator import xor
import re

from .engine import EngineError


class OfflineModem:
    quantum = 4096
    capacity = 64
    network_epoch = datetime(2025, 2, 14, 18, 14, 17, tzinfo=timezone.utc)
    training_origin = datetime(2026, 11, 9, tzinfo=timezone.utc)

    def __init__(self, avr, satellite, *, avr_port=0, power_pin=None, sim_present=True, storage=None):
        self.avr, self.satellite = avr, satellite
        self.endpoints = ((avr, avr_port),)
        self.avr_port, self.power_pin = avr_port, power_pin
        self.image = "offline-training"
        self.powered = power_pin is None
        self.power_resets = 0
        snapshot = avr.request("pin_state") if power_pin is not None else {}
        self.power_rises = snapshot.get("modem_power_rises", 0)
        self.error = None
        self.delivered = [0, 0]
        self.commands = deque(maxlen=100)
        self.unsupported = deque(maxlen=20)
        self.other_frames = deque(maxlen=20)
        self.sim_present = bool(sim_present)
        self.storage = {} if storage is None else storage
        self.messages = self.storage.setdefault("messages", {})
        self.phonebook = self.storage.setdefault("phonebook", {})
        self.storage.setdefault("service_center", "+881662900005")
        self._message_id = 0
        self._reset_transport()
        if self.powered:
            self._bootstrap()

    def _reset_transport(self):
        self._incoming, self._wire = bytearray(), bytearray()
        self._frames, self._controls = deque(), bytearray()
        self._awaiting = None
        self._sequence = 0
        self._last_request = None
        self._sent_at = 0
        self._retries = 0
        self._data_entry = None
        self._data = bytearray()
        self._scenario = None
        self._creg = 0
        self._cnmi = False
        self._volume = 7

    @staticmethod
    def frame(payload):
        if not 1 <= len(payload) <= 256:
            raise ValueError("DPL payload must contain 1 to 256 bytes")
        result = bytes((4, len(payload) & 255)) + payload
        return result + bytes((reduce(xor, result, 0), 3))

    def _packet(self, text, kind, *, mode=None):
        if mode is None:
            mode = 1
        data = text.encode("ascii") if isinstance(text, str) else bytes(text)
        for offset in range(0, max(1, len(data)), 240):
            part = data[offset:offset + 240]
            last = offset + 240 >= len(data)
            flag = kind if last else 6
            payload = bytes((self._sequence | flag, 0x63, mode, len(part))) + part
            self._sequence ^= 0x80
            self._frames.append(self.frame(payload))
        if len(self._frames) > 256:
            raise EngineError("Offline modem response backlog exceeded 256 packets")

    def _bootstrap(self):
        # Original TRX emits this empty AT channel envelope at startup.
        self._frames.append(self.frame(bytes((0, 3, 0, 0))))
        self._sequence = 0x80
        self._packet("\r\n+ANTST:1\r\n", 4)

    def _result(self, text="", terminal="OK", *, intermediate_mode=None):
        if text:
            self._packet("\r\n" + text + "\r\n", 6, mode=intermediate_mode)
        self._packet("\r\n" + terminal + "\r\n", 2)

    def _unsolicited(self, text):
        self._packet("\r\n" + text + "\r\n", 4)

    def _registration(self):
        service = self.satellite
        return 1 if service.registered and service.available else (2 if service.state().get("registering") else 0)

    def _network_counter(self):
        elapsed_ms = int((self.training_origin - self.network_epoch).total_seconds() * 1000)
        return ((elapsed_ms + self.satellite.time_ms) // 90) & 0xFFFFFFFF

    def notify_scenario(self):
        """Call after Satellite changes; exchange also detects delayed registration."""
        service = self.satellite
        current = (self._registration(), service.signal if service.available else 0,
                   service.call_state, service.number)
        previous = self._scenario
        self._scenario = current
        if not self.powered:
            return
        if previous is None or current[:2] != previous[:2]:
            if self._creg:
                self._unsolicited(f"+CREG:{current[0]:03d}")
            self._unsolicited(f"+CIEV:0,{current[1]}")
            self._unsolicited(f"+CIEV:1,{int(current[0] == 1)}")
        if previous is not None and current[2:] != previous[2:]:
            if current[2] == "ringing":
                self._unsolicited("+XCSI=3,2,0,255,255,0,1")
                self._unsolicited("RING")
                self._unsolicited(f'+CLIP:"{current[3]}",{145 if current[3].startswith("+") else 129}')
                # BC5 stages caller ID on the first report; the next opens the ringer.
                self._unsolicited("+XCSI=3,2,0,255,255,0,1")
            elif current[2] == "active":
                self._unsolicited("+XCSI=1,4,0,0,255,0,1")
            elif previous[2] != "idle":
                self._unsolicited("+XCSI=16,15,0,0,255,0,1")
                self._unsolicited("NO CARRIER")
                self._unsolicited("+XCSI=0,0,0,255,255,0,0")
        # Incoming SMS is explicitly inserted through incoming_sms(), avoiding
        # duplicate ingestion when Satellite's bounded history rolls over.

    def incoming_sms(self, number, text):
        """Store one synthetic SMS and notify the original handset via +CMTI."""
        pdu = self.validate_incoming_sms(number, text)
        index = next(i for i in range(1, self.capacity + 1) if i not in self.messages)
        self.messages[index] = (0, pdu)
        if self.powered and self._cnmi:
            self._unsolicited(f'+CMTI:"SM",{index:03d}')
        return index

    def validate_incoming_sms(self, number, text):
        if not self.sim_present:
            raise ValueError("Insert the training SIM before receiving messages")
        if len(self.messages) >= self.capacity:
            raise ValueError("Training SIM message storage is full")
        return self.sms_pdu(number, text)

    @staticmethod
    def sms_pdu(number, text):
        """Single SMS-DELIVER PDU, GSM default alphabet or UCS-2, fixed demo date."""
        from .satellite import Satellite
        number = Satellite._number(number)
        if not isinstance(text, str) or not 1 <= len(text) <= 160:
            raise ValueError("SMS text must contain 1 to 160 characters")
        alphabet = ('@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ '
                    '!"#¤%&\'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§'
                    '¿abcdefghijklmnopqrstuvwxyzäöñüà')
        if all(char in alphabet and char != '\x1b' for char in text):
            values = [alphabet.index(char) for char in text]
            packed = sum(value << (7 * i) for i, value in enumerate(values))
            body = packed.to_bytes((len(values) * 7 + 7) // 8, "little")
            dcs, length = 0, len(values)
        else:
            body = text.encode("utf-16-be")
            if len(body) > 140:
                raise ValueError("A Unicode training SMS must fit in 70 UTF-16 code units")
            dcs, length = 8, len(body)
        digits = number.lstrip("+")
        padded = digits + ("F" if len(digits) % 2 else "")
        address = bytes(int(padded[i + 1] + padded[i], 16) for i in range(0, len(padded), 2))
        return bytes((0, 4, len(digits), 145 if number.startswith("+") else 129)) + address + bytes((0, dcs)) + bytes.fromhex("62119000000000") + bytes((length,)) + body

    @staticmethod
    def _pdu_length(pdu):
        return len(pdu) - 1 - pdu[0]

    def _command(self, raw):
        try:
            command = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            self._result(terminal="ERROR")
            return
        self._packet(raw, 7)  # Original AT echo identifies the pending command.
        self.commands.append(command)
        upper = command.upper()
        simple = {"AT", "ATE0", "ATE1", "AT+CMEE=1", "AT+CAR=2",
                  'AT+CPBS="SM"', "AT+CMGF=0", "AT+CSDT=0", "AT+CSDT=1"}
        sim_command = any(upper.startswith(prefix) for prefix in ("AT+CPB", "AT+CPIN", "AT+CICCID", "AT+CMG", "AT+CPMS", "AT+CNMI", "AT+CSCA"))
        if sim_command and not self.sim_present:
            self._result(terminal="+CMS ERROR:310" if upper.startswith(("AT+CMG", "AT+CPMS", "AT+CNMI", "AT+CSCA")) else "+CME ERROR:010")
        elif upper in simple:
            self._result()
        elif upper == "ATI3":
            # Version compatibility only; state/UI always identify the training peer.
            self._result("DB24002")
        elif upper == "ATI7":
            self._result("BOOT0fa0/H2ARevA/00/RAW00")
        elif re.fullmatch(r'AT\+CAPPV="[A-Z0-9_]+","[A-Z0-9]+","[A-Z0-9]+"', upper):
            self._result()
        elif upper in ("AT+CPBR=?", "AT+CPBW=?"):
            self._result("+CPBW:(101-102)" if upper == "AT+CPBW=?" else "+CPBR:(101-102)")
        elif upper == "AT+CPBS?":
            self._result(f'+CPBS:"SM",{len(self.phonebook):03d},002')
        elif re.fullmatch(r'AT\+CPBR=\d+(?:,\d+)?', upper):
            indices = [int(value) for value in upper.split("=")[1].split(",")]
            start, end = indices[0], indices[-1]
            if not 101 <= start <= end <= 102:
                self._result(terminal="+CME ERROR:021")
            else:
                self._result("\r\n".join(f'+CPBR:{index:03d},"{number}",{ton:03d},"{name}"'
                             for index, (number, ton, name) in sorted(self.phonebook.items()) if start <= index <= end))
        elif upper.startswith("AT+CPBW="):
            match = re.fullmatch(r'AT\+CPBW=(101|102)(?:,"(\+?\d{1,20})",(129|145),"([^"\r\n]{0,16})")?', command, re.I)
            if not match:
                self._result(terminal="+CME ERROR:021")
            else:
                index = int(match[1])
                if match[2] is None:
                    self.phonebook.pop(index, None)
                else:
                    self.phonebook[index] = (match[2], int(match[3]), match[4])
                self._result()
        elif upper in ("AT+CPIN?", "AT+CICCID+CPIN?"):
            self._result(("00000000000000000000\r\n" if "CICCID" in upper else "") + "+CPIN:READY")
        elif upper == "AT+CLCK=?":
            self._result('+CLCK:("CS")')
        elif upper in ('AT+CLCK="FD",2', 'AT+CLCK="SC",2'):
            self._result("+CLCK:0")
        elif upper == "AT+CVMI":
            self._result("+CVMI:0")
        elif upper == "AT+CREG?":
            self._result(f"+CREG:{self._creg:03d},{self._registration():03d}")
        elif upper in ("AT+CREG=0", "AT+CREG=1", "AT+CREG=2"):
            self._creg = int(upper[-1]); self._result()
        elif re.fullmatch(r'AT\+CIER=[01],[01],[01](?:,[01])?', upper):
            self._result()
        elif upper == "AT+CSQ":
            self._result(f"+CSQ:{self.satellite.signal if self.satellite.available else 0}")
        elif upper == "AT+COPS=1":
            try:
                self.satellite.register()
                self._result()
            except ValueError:
                self._result(terminal="+CME ERROR:030")
        elif upper == "AT-MSSTM":
            value = f"{self._network_counter():x}" if self._registration() == 1 else "no network service"
            self._result("-MSSTM: " + value)
        elif upper == "AT+CLVL?":
            self._result(f"+CLVL:{self._volume}")
        elif re.fullmatch(r'AT\+CLVL=[0-7]', upper):
            self._volume = int(upper[-1]); self._result()
        elif upper in ('AT+CPMS="SM"', "AT+CPMS?"):
            used = len(self.messages)
            fields = f'{used:03d},{self.capacity:03d}'
            if upper.endswith("?"):
                fields = '"SM",' + fields
            self._result("+CPMS:" + ",".join((fields,) * 3))
        elif upper in ("AT+CNMI=2,1,0,0,0", "AT+CNMI=2,1,0,1,0"):
            self._cnmi = True; self._result()
        elif upper == "AT+CSCA?":
            self._result(f'+CSCA:"{self.storage["service_center"]}",145')
        elif re.fullmatch(r'AT\+CSCA="\+?\d{1,20}"(?:,145)?', upper):
            self.storage["service_center"] = command.split('"')[1]
            self._result()
        elif re.fullmatch(r'AT\+CMGL=[0-4]', upper):
            status = int(upper[-1])
            rows = [f"+CMGL:{index:03d},{kind:03d},,{self._pdu_length(pdu):03d}\r\n{pdu.hex().upper()}"
                    for index, (kind, pdu) in sorted(self.messages.items()) if status == 4 or status == kind]
            self._result("\r\n".join(rows))
        elif re.fullmatch(r'AT\+CMGR=\d+', upper):
            index = int(upper.split("=")[1])
            if index not in self.messages:
                self._result(terminal="+CMS ERROR:321")
            else:
                kind, pdu = self.messages[index]
                self._result(f'+CMGR:{kind:03d},"",{self._pdu_length(pdu):03d}\r\n{pdu.hex().upper()}')
                if kind == 0:
                    self.messages[index] = (1, pdu)
        elif re.fullmatch(r'AT\+CMGD=\d+', upper):
            index = int(upper.split("=")[1])
            if self.messages.pop(index, None) is None:
                self._result(terminal="+CMS ERROR:321")
            else:
                self._result()
        elif re.fullmatch(r'AT\+CMG[SW]=\d+(?:,[0-3])?', upper):
            self._data_entry = upper
            self._data.clear()
            self._packet("\r\n> ", 7, mode=6)
        elif upper == "AT+WANTST":
            self._result()
            self._unsolicited("+ANTST:1")
        elif re.fullmatch(r'AT\+CHLD=(?:0|1[0-9]?)', upper):
            if upper in ("AT+CHLD=1", "AT+CHLD=10") or (upper == "AT+CHLD=0" and self.satellite.call_state == "ringing"):
                self.satellite.hangup()
            self._result()
            if self.satellite.call_state == "idle":
                self._unsolicited("+XCSI=0,0,0,255,255,0,0")
        elif re.fullmatch(r'ATD\+?\d+;', upper):
            if self.satellite.call_state != "idle":
                self._result(terminal="BUSY")
            else:
                self._packet(b"", 0, mode=5)
                self._packet("\r\n+XCSI=16,1,0,0,255,0,1\r\n", 4, mode=5)
                if self._registration() != 1:
                    self._result(terminal="NO CARRIER")
                    self._unsolicited("+XCSI=0,0,0,255,255,0,0")
                else:
                    self.satellite.number = command[3:-1]
                    self.satellite.call_state = "active"
                    self._result()
        elif upper in ("ATH", "ATH0", "AT+CHUP"):
            self.satellite.hangup(); self._result()
        elif upper == "ATA":
            self._packet(b"", 0, mode=5)
            try:
                self.satellite.answer(); self._result()
            except ValueError:
                self._result(terminal="NO CARRIER")
        elif re.fullmatch(r'AT-MSVTS=[0-9A-D*#]', upper) and self.satellite.call_state == "active":
            self._result()
        else:
            self.unsupported.append(command)
            self._result(terminal="ERROR")
        self.notify_scenario()

    def _body(self, data):
        if self._data_entry is None:
            self._result(terminal="ERROR")
            return
        self._data.extend(data)
        if len(self._data) > 1024:
            self._data_entry = None; self._data.clear()
            self._result(terminal="+CMS ERROR:305")
            return
        if 27 in self._data:
            self._data_entry = None; self._data.clear(); self._result()
            return
        if 26 not in self._data:
            return
        command, self._data_entry = self._data_entry, None
        raw = bytes(self._data).split(b"\x1a", 1)[0]
        self._data.clear()
        try:
            pdu = bytes.fromhex(raw.decode("ascii"))
            length = int(command.split("=")[1].split(",")[0])
            if not pdu or self._pdu_length(pdu) != length or len(pdu) > 176:
                raise ValueError("Invalid PDU")
        except (UnicodeDecodeError, ValueError):
            self._result(terminal="+CMS ERROR:304"); return
        if command.startswith("AT+CMGW"):
            if len(self.messages) >= self.capacity:
                self._result(terminal="+CMS ERROR:322"); return
            index = next(i for i in range(1, self.capacity + 1) if i not in self.messages)
            kind = int(command.split(",")[1]) if "," in command else 2
            self.messages[index] = (kind, pdu)
            self._result(f"+CMGW:{index:03d}", intermediate_mode=6)
        elif self._registration() != 1:
            self._result(terminal="+CMS ERROR:331")
        else:
            self._message_id = (self._message_id + 1) % 256
            self._result(f"+CMGS:{self._message_id:03d}", intermediate_mode=6)

    def _receive(self, values):
        self._incoming.extend(values)
        while self._incoming:
            if self._incoming[0] in (6, 21):
                control = self._incoming.pop(0)
                if control == 6:
                    self._awaiting = None; self._retries = 0
                elif self._awaiting is not None:
                    self._retry()
                continue
            if len(self._incoming) < 2:
                break
            size = (self._incoming[1] or 256) + 4
            if len(self._incoming) < size:
                break
            frame = bytes(self._incoming[:size]); del self._incoming[:size]
            if frame[-1] != 3 or reduce(xor, frame[:-2], 0) != frame[-2]:
                self._controls.append(21); continue
            self._controls.append(6)
            if frame == self._last_request:
                continue
            self._last_request = frame
            payload = frame[2:-2]
            if frame[0] != 4 or len(payload) < 4 or payload[3] != len(payload) - 4:
                self.other_frames.append(frame[:32].hex())
                continue
            kind = payload[0] & 127
            if kind == 1:
                self._command(payload[4:])
            elif kind == 6:
                self._body(payload[4:])
            else:
                self.other_frames.append(frame[:32].hex())

    def _retry(self):
        self._retries += 1
        if self._retries > 3:
            raise EngineError("Offline modem DPL response was not acknowledged; restart the handset")
        self._wire = bytearray(self._awaiting)
        self._sent_at = self.avr.state.get("steps", 0)

    def exchange(self, *, avr_reset=False):
        if self.error:
            raise EngineError(self.error)
        try:
            if self.power_pin is not None:
                snapshot = self.avr.request("pin_state")
                port, bit = self.power_pin
                rises = snapshot["modem_power_rises"]
                enabled = bool(snapshot["pins"][port] & (1 << bit)) and not avr_reset
                if enabled and (not self.powered or rises != self.power_rises):
                    self.power_resets += 1
                    self._reset_transport(); self._bootstrap()
                if self.powered and not enabled:
                    self.satellite.hangup()
                self.power_rises = rises
                self.powered = enabled
            arguments = {"modem_link": True} if self.power_pin is not None else {}
            wire = self.avr.request("uart_io", port=self.avr_port, **arguments)
            if wire["dropped"]:
                raise EngineError("UART capture overflow on offline modem link")
            if not self.powered or avr_reset:
                self._reset_transport()
                return
            self.delivered[0] += len(wire["values"])
            self._receive(wire["values"])
            self.notify_scenario()
            steps = self.avr.state.get("steps", 0)
            if self._awaiting is not None and not self._wire and steps - self._sent_at > 2000000:
                self._retry()
            if not self._wire:
                if self._controls:
                    self._wire.extend(self._controls); self._controls.clear()
                elif self._awaiting is None and self._frames:
                    self._awaiting = self._frames.popleft()
                    self._wire.extend(self._awaiting)
                    self._sent_at = steps
            if self._wire:
                offered = bytes(self._wire[:255])
                response = self.avr.request("uart_io", port=self.avr_port, rx=list(offered), tx_limit=0)
                count = response["accepted"]
                if type(count) is not int or not 0 <= count <= len(offered):
                    raise EngineError("Invalid UART acknowledgement from offline modem link")
                del self._wire[:count]
                self.delivered[1] += count
        except EngineError as error:
            self.error = str(error)
            raise

    def state(self):
        return {"connected": True, "modem": self.image, "simulation": True,
                "mode": "offline training", "powered": self.powered,
                "avr_port": self.avr_port, "power_managed": self.power_pin is not None,
                "power_resets": self.power_resets, "quantum_instructions": self.quantum,
                "avr_to_modem": self.delivered[0], "modem_to_avr": self.delivered[1],
                "pending": [len(self._incoming), len(self._wire)],
                "queued_packets": len(self._frames), "messages_stored": len(self.messages),
                "sim_present": self.sim_present, "phonebook_used": len(self.phonebook),
                "unsupported_commands": list(self.unsupported), "other_frames": list(self.other_frames), "error": self.error,
                "network_time": {"simulation": True, "available": self._registration() == 1,
                                 "epoch_utc": self.network_epoch.isoformat(),
                                 "origin_utc": self.training_origin.isoformat(),
                                 "utc": (self.network_epoch + timedelta(milliseconds=self._network_counter() * 90)).isoformat(),
                                 "counter": self._network_counter(), "tick_ms": 90},
                "limitations": ["Synthetic service and SIM storage", "No RF or authentication", "No voice audio"]}
