"""Validate firmware containers without ever modifying the supplied images.

Layouts come from rev-firmware/re/tools/bc5-data/bcfw_dump.py and
re/maps/{bc5-arch,trx-arch,avr-full}.md. Raw images have no usable container
checksum; their SHA-256 identifies exactly which experiment was executed.
"""

from dataclasses import dataclass
from functools import cached_property
from hashlib import sha256
from pathlib import Path
import struct
import zlib


MAX_IMAGE_BYTES = 8 * 1024 * 1024
BC5_CODE_BYTES = 0x3096BE
BC5_DATA_BYTES = 0x78FC
BC5_PAYLOAD_BYTES = BC5_CODE_BYTES + BC5_DATA_BYTES
RAW_FILES = {"bc5": "bc5_main.bin", "avr": "avr.bin",
             "trx": "trx_seg1_0x10000.bin", "ptt": "trx_seg2.bin"}
PROFILE_BYTES = {"avr": 8678, "trx": 0x260760, "ptt": 0xA7BF8}


class FirmwareError(ValueError):
    """The image cannot safely be interpreted with the supported board profile."""


@dataclass(frozen=True)
class Firmware:
    image: str
    name: str
    data: bytes
    sha256: str
    format: str
    warnings: tuple[str, ...] = ()

    @cached_property
    def payload_sha256(self) -> str:
        return sha256(self.data).hexdigest()

    def describe(self) -> dict:
        return {"image": self.image, "name": self.name, "sha256": self.sha256,
                "payload_sha256": self.payload_sha256, "format": self.format,
                "size": len(self.data), "warnings": list(self.warnings)}


def _crc(data: bytes) -> int:
    return zlib.crc32(data) ^ 0xFFFFFFFF


def _dfu(data: bytes, allow_invalid_crc: bool) -> tuple[bytes, tuple[str, ...]]:
    if len(data) < 40:
        raise FirmwareError("Truncated CSR DFU header")
    magic, version, length, header_size = struct.unpack_from("<8sHIH", data)
    if magic != b"CSR-dfu2" or version != 2 or length != len(data) - 16:
        raise FirmwareError("Invalid CSR-dfu2 version or length")
    if header_size < 16 or header_size + 24 > len(data) - 20:
        raise FirmwareError("CSR firmware header extends outside the file")
    magic, checksum, code_field, data_field, reserved = struct.unpack_from(
        "<8s4I", data, header_size)
    if magic != b"CSRbcfw1" or reserved != 0:
        raise FirmwareError("Unsupported CSRbcfw1 header")
    if code_field != BC5_CODE_BYTES + 4 or data_field != BC5_DATA_BYTES + 0x10000:
        raise FirmwareError("Firmware layout differs from the supported HT25003 BC5 profile")
    start = header_size + 24
    end = start + BC5_PAYLOAD_BYTES
    if end + 20 != len(data):
        raise FirmwareError("CSR code/data lengths do not match the container")
    _, product, vendor, dfu_version, signature, suffix_size, suffix_crc = struct.unpack_from(
        "<HHHH3sBI", data, end + 4)
    if (product, vendor, signature, suffix_size) != (0xA555, 0x1EDD, b"UFD", 16):
        raise FirmwareError("DFU suffix is not an Iridium 9555 image")
    if dfu_version != 0x100:
        raise FirmwareError("Unsupported USB DFU version")
    failures = []
    checks = [("CSR firmware", _crc(data[header_size + 12:end]), checksum),
              ("DFU file", _crc(data[:end]), struct.unpack_from("<I", data, end)[0]),
              ("USB suffix", _crc(data[:-4]), suffix_crc)]
    for label, actual, expected in checks:
        if actual != expected:
            failures.append(f"{label} CRC mismatch")
    if failures and not allow_invalid_crc:
        raise FirmwareError("; ".join(failures) + "; use --allow-invalid-crc for a deliberate patch")
    return data[start:end], tuple(failures)


def parse_firmware(data: bytes, name: str, image: str | None = None,
                   allow_invalid_crc: bool = False) -> Firmware:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise FirmwareError("Firmware must contain 1 byte to 8 MiB")
    warnings: tuple[str, ...] = ()
    payload = data
    kind = "raw"
    if data.startswith(b"CSR-dfu2"):
        if image not in (None, "bc5"):
            raise FirmwareError("CSR DFU contains BC5 firmware, not the selected processor")
        payload, warnings = _dfu(data, allow_invalid_crc)
        image, kind = "bc5", "CSR-dfu2"
    else:
        if image is None:
            image = next((key for key, filename in RAW_FILES.items() if filename == name), None)
        if image is None and len(data) in (BC5_PAYLOAD_BYTES, BC5_PAYLOAD_BYTES + 4):
            image = "bc5"
        if image is None:
            image = next((key for key, size in PROFILE_BYTES.items() if len(data) == size), None)
        if image == "bc5":
            if len(data) not in (BC5_PAYLOAD_BYTES, BC5_PAYLOAD_BYTES + 4):
                raise FirmwareError("Raw BC5 image has the wrong length for HT25003")
            payload = data[:BC5_PAYLOAD_BYTES]
            warnings = ("Raw image: container CRC unavailable; identity tracked by SHA-256",)
        elif image in PROFILE_BYTES:
            expected = PROFILE_BYTES[image]
            if len(data) != expected:
                raise FirmwareError(f"{image} image must contain {expected} bytes for the HT25003 profile")
        else:
            raise FirmwareError("Unknown image: supply main.dfu, bc5_main.bin, or --image avr|trx|ptt")
    return Firmware(image, name, payload, sha256(data).hexdigest(), kind, warnings)


def load_firmware(path: Path, image: str | None = None,
                  allow_invalid_crc: bool = False) -> list[Firmware]:
    if path.is_dir():
        if image:
            return load_firmware(path / RAW_FILES[image], image, allow_invalid_crc)
        # Prefer the checked container; explicitly pass a .bin to run a raw patch.
        bc5 = path / "main.dfu"
        if not bc5.exists():
            bc5 = path / RAW_FILES["bc5"]
        result = load_firmware(bc5, "bc5", allow_invalid_crc)
        for processor in ("avr", "trx", "ptt"):
            candidate = path / RAW_FILES[processor]
            if candidate.exists():
                result.extend(load_firmware(candidate, processor, allow_invalid_crc))
        return result
    with path.open("rb") as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    return [parse_firmware(data, path.name, image, allow_invalid_crc)]
