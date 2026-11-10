"""Bounded ST7541 three-wire command decoder, not a display UI replacement.

Reference: Sitronix ST7541 v1.9 (2007-09-03), pages 1, 20, 32-50.
Coordinates default to controller outputs SEG0..SEG127 and COM0..COM127.
The handset profile places SEG0 at the right edge of its panel. Contrast is an
uncalibrated register ratio; PWM brightness and electrical timing are not modeled.
Unknown DDRAM stays marked unknown until firmware writes both pixel planes.
"""


class ST7541:
    WIDTH = HEIGHT = 128

    def __init__(self, *, segment_zero_on_right: bool = False):
        self.segment_zero_on_right = segment_zero_on_right
        self.ram = bytearray(4096)
        self.written = bytearray(4096)
        self.page = self.column = self.start_line = 0
        self.display_on = self.reverse = self.entire_on = False
        self.adc_reverse = self.com_reverse = self.sleeping = False
        self.parameters = {}
        self.palette = [0] * 8
        self.pending = None
        self.remaining = 0
        self.saved_column = None
        self.error = None
        self.version = self.data_bytes = 0
        self._state_cache = None

    def feed(self, data: bytes) -> None:
        """Consume a stream fragment, preserving incomplete commands/data runs.

        Unsupported operations latch an error and raise ValueError. Continuing
        after a framing failure would turn command bytes into invented pixels.
        """
        if self.error:
            raise ValueError(self.error)
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("LCD input must be bytes")
        if data:
            self.version += 1
            self._state_cache = None
        for value in data:
            if self.remaining:
                address = self.page * 256 + self.column
                self.ram[address] = value
                self.written[address] = 1
                self.column = (self.column + 1) & 255
                self.remaining -= 1
                self.data_bytes += 1
            elif self.pending is not None:
                command = self.pending
                self.pending = None
                self._parameter(command, value)
            else:
                self._command(value)

    def _fail(self, message):
        self.error = message
        raise ValueError(message)

    def _command(self, command):
        if command <= 0x0F:
            self.column = (self.column & 0xE0) | (command << 1)
        elif 0x10 <= command <= 0x17:
            self.column = (self.column & 0x1E) | ((command & 7) << 5)
        elif 0xB0 <= command <= 0xBF:
            self.page = command & 15
        elif (command in (0x38, 0x81, 0xE8, 0xF3, 0xF7)
              or 0x40 <= command <= 0x4F or 0x88 <= command <= 0x8F):
            self.pending = command
        elif command in (0xAE, 0xAF):
            self.display_on = bool(command & 1)
        elif command in (0xA0, 0xA1):
            self.adc_reverse = bool(command & 1)
        elif 0xC0 <= command <= 0xCF:
            self.com_reverse = bool(command & 8)
        elif command in (0xA6, 0xA7):
            self.reverse = bool(command & 1)
        elif command in (0xA4, 0xA5):
            self.entire_on = bool(command & 1)
        elif command in (0xA8, 0xA9, 0xE1):
            self.sleeping = command == 0xA9
        elif command == 0xA3:
            self._fail("ST7541 icon row is outside the supported 128-row panel")
        elif command == 0xE0:
            self.saved_column = self.column
        elif command == 0xEE:
            if self.saved_column is None:
                self._fail("ST7541 read-modify-write release without a saved address")
            self.column = self.saved_column
            self.saved_column = None
        elif command == 0xE2:
            # Software reset preserves DDRAM, output direction and display state
            # (datasheet reset table, page 32); it differs from a power-on reset.
            self.page = self.column = self.start_line = 0
            self.remaining = 0
            self.saved_column = None
            self.palette = [0] * 8
            self.parameters.update({0x20: 0, 0x81: 32, 0x90: 0})
        elif (0x20 <= command <= 0x2F or 0x50 <= command <= 0x57
              or 0x64 <= command <= 0x67 or 0x90 <= command <= 0x97
              or command in (0xA2, 0xAB, 0xE3, 0xE4)):
            # Defined analog/timing controls do not change logical DDRAM pixels.
            self.parameters[command] = None
        else:
            self._fail(f"Unsupported ST7541 command 0x{command:02X}")

    def _parameter(self, command, value):
        if command == 0xE8:
            self.remaining = value + 1
        elif 0x40 <= command <= 0x43:
            self.start_line = value & 127
        elif 0x44 <= command <= 0x47:
            if value & 127:
                self._fail("ST7541 nonzero initial COM is not supported")
        elif 0x48 <= command <= 0x4B:
            if 16 <= value <= 127:
                self._fail("ST7541 partial display duty is not supported")
            # Values outside 16..128 have no operation (datasheet page 43).
        elif 0x88 <= command <= 0x8F:
            self.palette[command - 0x88] = value
        elif command in (0xF3, 0xF7):
            expected = 0x0D if command == 0xF3 else 0x1A
            if value != expected:
                self._fail(f"Unsupported ST7541 high-power setting {command:02X} {value:02X}")
        elif command == 0x38 and value & 9:
            self._fail(f"Invalid ST7541 mode setting 0x{value:02X}")
        self.parameters[command] = value

    def state(self) -> dict:
        # Reuse the projection between stream fragments; callers own their snapshots.
        if self._state_cache is None:
            self._state_cache = self._render_state()
        return {**self._state_cache, "pixels": self._state_cache["pixels"].copy(),
                "known": self._state_cache["known"].copy(),
                "palette": self._state_cache["palette"].copy()}

    def _render_state(self) -> dict:
        """Return nominal 2-bit output pixels and their evidence mask.

        Pixel codes are white/light/dark/black (0..3), not measured luminance.
        Unknown pixels have placeholder value zero and known=False. Consumers
        must preserve that distinction instead of claiming an initialized LCD.
        """
        visible = self.display_on and not self.sleeping
        pixels = [3 if visible and self.entire_on else 0] * (self.WIDTH * self.HEIGHT)
        known = [not visible or self.entire_on] * len(pixels)
        if visible and not self.entire_on:
            mirrored = self.segment_zero_on_right != self.adc_reverse
            for y in range(self.HEIGHT):
                com = 127 - y if self.com_reverse else y
                row = (com + self.start_line) & 127
                page = (row // 8) * 256
                bit = row & 7
                for x in range(self.WIDTH):
                    index = y * 128 + x
                    column = 127 - x if mirrored else x
                    address = page + column * 2
                    valid = self.written[address] and self.written[address + 1]
                    known[index] = bool(valid)
                    if valid:
                        value = (((self.ram[address] >> bit) & 1) << 1
                                 | ((self.ram[address + 1] >> bit) & 1))
                        pixels[index] = 3 - value if self.reverse else value
        return {
            "width": self.WIDTH, "height": self.HEIGHT, "pixels": pixels,
            "display_on": visible, "error": self.error, "version": self.version,
            "live": True, "known": known, "known_pixels": sum(known),
            "written_bytes": sum(self.written), "data_bytes": self.data_bytes,
            "adc_reverse": self.adc_reverse, "com_reverse": self.com_reverse,
            "segment_zero_on_right": self.segment_zero_on_right,
            "coordinates": "SEG127 left, COM0 top" if self.segment_zero_on_right else "SEG0 left, COM0 top",
            "palette": list(self.palette),
            # EV5..EV0 are the 64 contrast steps (datasheet pages 26-27, 40).
            # This ratio is UI feedback, not a calibrated optical contrast model.
            "contrast_ratio": (self.parameters.get(0x81, 32) & 63) / 63,
            "contrast_approximate": True,
        }
