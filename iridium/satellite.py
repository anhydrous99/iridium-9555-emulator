"""Deterministic, offline service scenario model.

This models service outcomes, not the Iridium RF waveform, authentication, DSP,
or satellite constellation. It is intentionally separate from CPU execution
until the board's modem transport is established from hardware evidence.
"""

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Satellite:
    visible: bool = True
    signal: int = 5
    latency_ms: int = 800
    registered: bool = False
    call_state: str = "idle"
    number: str = ""
    time_ms: int = 0
    messages: deque = field(default_factory=lambda: deque(maxlen=100))
    _registration_due: int | None = None

    @property
    def available(self) -> bool:
        return self.visible and self.signal > 0

    def configure(self, *, visible=None, signal=None, latency_ms=None) -> None:
        if visible is not None and type(visible) is not bool:
            raise ValueError("visible must be a boolean")
        for value, name, low, high in ((signal, "signal", 0, 5),
                                      (latency_ms, "latency_ms", 0, 60000)):
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f"{name} must be an integer from {low} to {high}")
        if visible is not None:
            self.visible = visible
        if signal is not None:
            self.signal = signal
        if latency_ms is not None:
            self.latency_ms = latency_ms
        if not self.available:
            self.registered = False
            self._registration_due = None
            self.call_state = "idle"
            self.number = ""

    def advance(self, milliseconds: int) -> None:
        if type(milliseconds) is not int or milliseconds < 0:
            raise ValueError("Time must advance by a nonnegative integer")
        self.time_ms += milliseconds
        if self._registration_due is not None and self.time_ms >= self._registration_due:
            self.registered = self.available
            self._registration_due = None

    def register(self) -> None:
        if not self.available:
            raise ValueError("No satellite visibility or signal")
        self.registered = False
        self._registration_due = self.time_ms + self.latency_ms
        self.advance(0)

    def incoming_call(self, number: str) -> None:
        self._require_service()
        if self.call_state != "idle":
            raise ValueError("A call is already in progress")
        self.number = self._number(number)
        self.call_state = "ringing"

    def answer(self) -> None:
        self._require_service()
        if self.call_state != "ringing":
            raise ValueError("There is no incoming call to answer")
        self.call_state = "active"

    def hangup(self) -> None:
        self.call_state = "idle"
        self.number = ""

    def incoming_sms(self, number: str, text: str) -> None:
        self._require_service()
        number = self._number(number)
        if not isinstance(text, str) or not 1 <= len(text) <= 160:
            raise ValueError("SMS text must contain 1 to 160 characters")
        self.messages.append({"number": number, "text": text, "time_ms": self.time_ms})

    def _require_service(self) -> None:
        if not self.registered or not self.available:
            raise ValueError("Register the simulated terminal first")

    @staticmethod
    def _number(number: str) -> str:
        if not isinstance(number, str) or not 1 <= len(number) <= 24:
            raise ValueError("A phone number is required (maximum 24 characters)")
        digits = number[1:] if number.startswith("+") else number
        if not digits or any(char not in "0123456789" for char in digits):
            raise ValueError("Phone number must contain digits and an optional +")
        return number

    def state(self) -> dict:
        return {"visible": self.visible, "signal": self.signal, "latency_ms": self.latency_ms,
                "registered": self.registered, "registering": self._registration_due is not None,
                "call_state": self.call_state, "number": self.number, "time_ms": self.time_ms,
                "messages": list(self.messages), "firmware_connected": False,
                "mode": "offline service scenario"}
