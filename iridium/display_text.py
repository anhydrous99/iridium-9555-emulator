"""Read visible text by matching the firmware's own monochrome font bitmaps.

This is a bounded accessibility aid, not knowledge of the guest's UI state.
Only ASCII/Latin-1 text is transcribed; other glyphs and graphics are marked.
"""

from dataclasses import dataclass, replace

from .assets import AssetError, BC5Assets


UNKNOWN = "[unreadable]"


@dataclass(frozen=True)
class _Glyph:
    text: str
    columns: tuple
    bearing: int
    advance: int
    ink: int


class _Font:
    def __init__(self, data):
        if len(data) < 21 or data[:4] != b"\xf0B\x01\x01":
            raise AssetError("Unsupported text font")
        count = int.from_bytes(data[4:6], "big")
        width, self.height = data[6:8]
        metrics, bitmap, table = (int.from_bytes(data[a:a + 4], "big") for a in (8, 12, 16))
        name_end = 21 + data[20]
        if data[21:name_end] not in (b"ASCII-1", b"Dialling"):
            raise AssetError("Not a text font")
        stride = width * ((self.height + 7) // 8)
        if (not 0 < count <= 16384 or not 0 < width <= 32 or not 0 < self.height <= 32
                or not name_end <= metrics <= name_end + 1
                or table != metrics + count * 2 or bitmap != table + count * 2
                or bitmap + count * stride != len(data)):
            raise AssetError("Invalid text font dimensions or offsets")
        self.first = {}
        shapes = {}
        self.space = 4
        previous = -1
        for i in range(count):
            code = int.from_bytes(data[table + 2 * i:table + 2 * i + 2], "big")
            if code <= previous:
                raise AssetError("Unordered text font character table")
            previous = code
            advance = data[metrics + 2 * i]
            if not 0 < advance <= width:
                raise AssetError("Invalid text font advance")
            if code == 32:
                self.space = advance
            raw = data[bitmap + i * stride:bitmap + (i + 1) * stride]
            columns = [sum(raw[page * width + x] << (page * 8)
                           for page in range((self.height + 7) // 8)) & ((1 << self.height) - 1)
                       for x in range(width)]
            occupied = [x for x, column in enumerate(columns) if column]
            if not occupied:
                continue
            left, right = occupied[0], occupied[-1] + 1
            if right > advance:
                raise AssetError("Text font has overlapping glyphs")
            text = chr(code) if 32 < code < 127 or 160 < code <= 255 else UNKNOWN
            glyph = _Glyph(text, tuple(columns[left:right]), left, advance,
                           sum(column.bit_count() for column in columns))
            shapes[glyph.columns] = text if shapes.get(glyph.columns, text) == text else UNKNOWN
            self.first.setdefault(glyph.columns[0], []).append(glyph)
        for glyphs in self.first.values():
            glyphs[:] = [replace(glyph, text=shapes[glyph.columns]) for glyph in glyphs]
            glyphs.sort(key=lambda glyph: glyph.ink, reverse=True)


class DisplayText:
    """Extract a fresh, caller-owned accessibility snapshot from an LCD state."""

    def __init__(self, firmware):
        self.fonts = []
        self._last_frame = self._last_result = None
        try:
            assets = BC5Assets(firmware.data, firmware.profile)
            for file_id in assets.files:
                data = assets.file_bytes(file_id)
                if data[:4] == b"\xf0B\x01\x01":
                    try:
                        self.fonts.append(_Font(data))
                    except AssetError:
                        pass
        except AssetError:
            pass

    def read(self, lcd):
        """Return {lines: [{text, selected}], status, complete} from live pixels.

        Unknown output, unsupported glyphs, and graphics never become guessed
        application labels. Cached matching depends on pixels and evidence,
        rather than the stream version (which also changes for analog controls).
        """
        pixels, known = lcd.get("pixels", ()), lcd.get("known", ())
        frame = (lcd.get("display_on"), lcd.get("width"), lcd.get("height"),
                 bytes(pixels), bytes(known), lcd.get("error"))
        if frame != self._last_frame:
            self._last_result = self._read(lcd, pixels, known)
            self._last_frame = frame
        return {**self._last_result, "lines": [dict(line) for line in self._last_result["lines"]]}

    def _read(self, lcd, pixels, known):
        if not lcd.get("display_on"):
            return {"lines": [], "status": "Display off", "complete": True}
        if (lcd.get("width") != 128 or lcd.get("height") != 128 or len(pixels) != 16384
                or len(known) != 16384 or not self.fonts):
            return {"lines": [], "status": "Display text unavailable", "complete": False}
        rows = [[pixels[y * 128 + x] == 3 for x in range(128)] for y in range(128)]
        inverted = [False] * 128
        # Selection rectangles may end before a scrollbar. Require a broad
        # solid edge and sustained vertical sides; thin title rules do not qualify.
        start = 0
        while start < 128:
            left = 0
            matched = False
            while left < 128:
                if not rows[start][left]:
                    left += 1
                    continue
                right = left
                while right < 128 and rows[start][right]:
                    right += 1
                end = start
                edge = 0 if rows[start][0] else left
                if right - left >= 64:
                    while (end < 128 and rows[end][edge] and rows[end][right - 1]
                           and (edge == 0 or not rows[end][edge - 1])
                           and (right == 128 or not rows[end][right])):
                        end += 1
                # An outlined edit field has the same edges but a light interior.
                dark = sum(sum(row[edge:right]) for row in rows[start:end])
                if end - start >= 10 and dark >= (end - start) * (right - edge) / 2:
                    for y in range(start, end):
                        rows[y][edge:right] = [not value for value in rows[y][edge:right]]
                        inverted[y] = True
                    start = end
                    matched = True
                    break
                left = right
            if not matched:
                start += 1
        for y, row in enumerate(rows):
            if not inverted[y]:
                # Rules are longer than text glyph strokes, including title rules.
                x = 0
                while x < 128:
                    end = x
                    while end < 128 and row[end]:
                        end += 1
                    if end - x >= 24 or (end - x >= 16 and (x == 0 or end == 128)):
                        row[x:end] = [False] * (end - x)
                    x = max(x + 1, end)
        columns = [sum(int(rows[y][x]) << y for y in range(128)) for x in range(128)]
        invalid = [sum(int(not known[y * 128 + x] or pixels[y * 128 + x] not in (0, 3)) << y
                       for y in range(128)) for x in range(128)]
        candidates = []
        for font in self.fonts:
            mask = (1 << font.height) - 1
            for top in range(129 - font.height):
                strip = [(column >> top) & mask for column in columns]
                bad = [(column >> top) & mask for column in invalid]
                tokens, score, x = [], 0, 0
                while x < 128:
                    if not strip[x]:
                        x += 1
                        continue
                    match = None
                    for glyph in font.first.get(strip[x], ()):
                        end = x + len(glyph.columns)
                        if (end <= 128 and tuple(strip[x:end]) == glyph.columns
                                and (end == 128 or not strip[end]) and not any(bad[x:end])):
                            match = glyph
                            break
                    if match:
                        tokens.append((x, x + len(match.columns), match))
                        score += match.ink
                        x += len(match.columns)
                    else:
                        end = x + 1
                        while end < 128 and strip[end]:
                            end += 1
                        tokens.append((x, end, None))
                        x = end
                if score:
                    candidates.append((score, top, font, tokens))
        occupied, lines = set(), []
        for score, top, font, tokens in sorted(candidates, key=lambda candidate: -candidate[0]):
            band = set(range(top, top + font.height))
            if occupied & band:
                continue
            occupied.update(band)
            text, previous_end = "", None
            for left, right, glyph in tokens:
                value = glyph.text if glyph else UNKNOWN
                origin = left - glyph.bearing if glyph else left
                if text and previous_end is not None and origin - previous_end >= font.space - 1:
                    text += " "
                if value != UNKNOWN or not text.rstrip().endswith(UNKNOWN):
                    text += value
                previous_end = origin + glyph.advance if glyph else right + 1
            lines.append((top, {"text": text.strip(), "selected": sum(inverted[y] for y in band) > font.height / 2}))
        # Keep wholly unrecognized text/graphics explicit, including unsupported locales.
        unknown_rows = [y for y in range(128) if y not in occupied and any(rows[y])]
        for y in unknown_rows:
            if y - 1 not in unknown_rows:
                lines.append((y, {"text": UNKNOWN, "selected": inverted[y]}))
        ordered = [line for _, line in sorted(lines, key=lambda item: item[0])]
        lines = []
        for line in ordered:
            if line["text"] != UNKNOWN or not lines or line != lines[-1]:
                lines.append(line)
        complete = all(known) and not any(invalid) and not lcd.get("error") and all(UNKNOWN not in line["text"] for line in lines)
        return {"lines": lines, "complete": complete,
                "status": "Visible text" if complete else "Partial text; unreadable content may include symbols, graphics or unsupported characters"}
