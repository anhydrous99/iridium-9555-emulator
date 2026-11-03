"""Read original BC5 filesystem assets; these are not live display output.

The HT25003 layout is documented in rev-firmware/re/maps/bc5-data.md and
re/tools/bc5-data/{bc5img,bitmaps_dump}.py. Addresses here are image byte offsets.
"""

from dataclasses import dataclass
import struct
from types import MappingProxyType
from typing import Mapping
import zlib

from .profiles import PROFILES, HandsetProfile


class AssetError(ValueError):
    """The firmware does not contain a valid supported asset."""


@dataclass(frozen=True)
class FirmwareFile:
    file_id: int
    offset: int
    size: int


@dataclass(frozen=True)
class Bitmap:
    width: int
    height: int
    pixels: bytes
    frame_count: int

    def to_png(self) -> bytes:
        """Return one 8-bit grayscale PNG using the inferred plane ordering."""
        shades = bytes((255, 170, 85, 0))
        rows = b"".join(
            b"\0" + bytes(shades[p] for p in self.pixels[y * self.width:(y + 1) * self.width])
            for y in range(self.height)
        )

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 0, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class BC5Assets:
    """Validated filesystem view of an HT25003 ``bc5_main.bin`` payload.

    This layout is a build-specific profile. A firmware modification that moves
    the constant window needs a new profile, not a guessed directory location.
    """

    WINDOW_OFFSET = 0x3096BE
    DIRECTORY_POINTER = 0x2BD6
    DIRECTORY_SLOTS = 140
    ADDRESS_BIAS = 0x800C
    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    MAX_FRAME_PIXELS = 16 * 1024 * 1024

    def __init__(self, image: bytes, profile: HandsetProfile = PROFILES["9555"]):
        if len(image) > self.MAX_IMAGE_BYTES or len(image) % 2:
            raise AssetError("BC5 payload must be an even number of bytes, at most 8 MiB")
        self._image = bytes(image)
        self.WINDOW_OFFSET = profile.code_bytes
        self.DIRECTORY_POINTER = profile.directory_pointer
        self.DIRECTORY_SLOTS = profile.directory_slots
        pointer = self.WINDOW_OFFSET + 2 * self.DIRECTORY_POINTER
        if pointer + 4 > len(image):
            raise AssetError(f"BC5 payload is too short for the {profile.version} filesystem pointer")
        high, low = struct.unpack_from("<HH", image, pointer)
        directory = (((high << 16) | low) - self.ADDRESS_BIAS) * 2
        directory_end = directory + self.DIRECTORY_SLOTS * 10
        if directory < 0 or directory_end > min(len(image), self.WINDOW_OFFSET):
            raise AssetError("Filesystem directory points outside the firmware resource region")

        files = {}
        for slot in range(self.DIRECTORY_SLOTS):
            file_id, high, low, size_high, size_low = struct.unpack_from("<5H", image, directory + slot * 10)
            if file_id == 0xFFFF:
                if any((high, low, size_high, size_low)):
                    raise AssetError(f"Unused filesystem slot {slot} contains data")
                continue
            if not 1 <= file_id <= self.DIRECTORY_SLOTS or file_id in files:
                raise AssetError(f"Invalid or duplicate filesystem id {file_id}")
            offset = (((high << 16) | low) - self.ADDRESS_BIAS) * 2
            size = (size_high << 16) | size_low
            if offset < directory_end or offset + size + (size & 1) > self.WINDOW_OFFSET:
                raise AssetError(f"Filesystem entry {file_id} points outside the resource region")
            files[file_id] = FirmwareFile(file_id, offset, size)
        self.files: Mapping[int, FirmwareFile] = MappingProxyType(files)

    def file_bytes(self, file_id: int) -> bytes:
        """Read the byte-stream API ordering: high byte of each stored word first."""
        entry = self._entry(file_id)
        raw = self._image[entry.offset:entry.offset + entry.size + (entry.size & 1)]
        result = bytearray(len(raw))
        result[0::2], result[1::2] = raw[1::2], raw[0::2]
        return bytes(result[:entry.size])

    def bitmap(self, file_id: int, frame: int = 0) -> Bitmap:
        """Decode one page-major 2bpp frame into row-major values 0..3.

        Each word holds eight vertical pixels, low byte plane 0 and high byte
        plane 1. Gray-plane significance is inferred; monochrome is unambiguous.
        """
        entry = self._entry(file_id)
        if entry.size < 8:
            raise AssetError(f"Filesystem entry {file_id} has no bitmap header")
        kind, width, height, count = struct.unpack_from("<4H", self._image, entry.offset)
        if kind != 3 or not width or not height or not count:
            raise AssetError(f"Filesystem entry {file_id} is not a supported bitmap")
        pages = (height + 7) // 8
        frame_words = pages * width
        if entry.size != 8 + 2 * frame_words * count:
            raise AssetError(f"Bitmap {file_id} size does not match its dimensions")
        if width * height > self.MAX_FRAME_PIXELS:
            raise AssetError("Bitmap frame exceeds the decoded pixel limit")
        if not isinstance(frame, int) or not 0 <= frame < count:
            raise AssetError(f"Bitmap frame must be between 0 and {count - 1}")
        start = entry.offset + 8 + 2 * frame * frame_words
        pixels = bytearray(width * height)
        for page in range(pages):
            for x in range(width):
                word = struct.unpack_from("<H", self._image, start + 2 * (page * width + x))[0]
                for bit in range(min(8, height - page * 8)):
                    pixels[(page * 8 + bit) * width + x] = ((word >> bit) & 1) | (((word >> (8 + bit)) & 1) << 1)
        return Bitmap(width, height, bytes(pixels), count)

    def _entry(self, file_id: int) -> FirmwareFile:
        try:
            return self.files[file_id]
        except KeyError:
            raise AssetError(f"No filesystem entry {file_id}") from None
