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

from .profiles import PROFILES, HandsetProfile


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
    model: str = "9555"

    @property
    def profile(self) -> HandsetProfile:
        return PROFILES[self.model]

    @cached_property
    def payload_sha256(self) -> str:
        return sha256(self.data).hexdigest()

    def describe(self) -> dict:
        return {"image": self.image, "name": self.name, "sha256": self.sha256,
                "payload_sha256": self.payload_sha256, "format": self.format,
                "size": len(self.data), "warnings": list(self.warnings),
                "model": self.model, "firmware_version": self.profile.version}


def _crc(data: bytes) -> int:
    return zlib.crc32(data) ^ 0xFFFFFFFF


def _dfu(data: bytes, allow_invalid_crc: bool, model: str | None
         ) -> tuple[bytes, tuple[str, ...], HandsetProfile]:
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
    profile = next((p for p in PROFILES.values()
                    if code_field == p.code_bytes + 4 and data_field == p.data_bytes + 0x10000), None)
    if profile is None:
        raise FirmwareError("Firmware layout differs from the supported BC5 profiles")
    if model is not None and model != profile.model:
        raise FirmwareError(f"Firmware is for {profile.name}, not the selected {model}")
    start = header_size + 24
    end = start + profile.payload_bytes
    if end + 20 != len(data):
        raise FirmwareError("CSR code/data lengths do not match the container")
    _, product, vendor, dfu_version, signature, suffix_size, suffix_crc = struct.unpack_from(
        "<HHHH3sBI", data, end + 4)
    if (product, vendor, signature, suffix_size) != (profile.product, 0x1EDD, b"UFD", 16):
        raise FirmwareError(f"DFU suffix does not match the {profile.name} profile")
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
    return data[start:end], tuple(failures), profile


def parse_firmware(data: bytes, name: str, image: str | None = None,
                   allow_invalid_crc: bool = False, model: str | None = None) -> Firmware:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise FirmwareError("Firmware must contain 1 byte to 8 MiB")
    warnings: tuple[str, ...] = ()
    payload = data
    kind = "raw"
    if model is not None and model not in PROFILES:
        raise FirmwareError("Unknown handset model")
    if data.startswith(b"CSR-dfu2"):
        if image not in (None, "bc5"):
            raise FirmwareError("CSR DFU contains BC5 firmware, not the selected processor")
        payload, warnings, profile = _dfu(data, allow_invalid_crc, model)
        image, kind = "bc5", "CSR-dfu2"
    else:
        if image is None:
            image = next((key for key, filename in RAW_FILES.items() if filename == name), None)
        candidates = [(p, processor) for p in PROFILES.values()
                      if model is None or p.model == model
                      for processor, size in p.image_sizes.items()
                      if (image is None or processor == image) and size > 0
                      and len(data) in ((size, size + 4) if processor == "bc5" else
                                        (size, p.avr_flash_bytes) if processor == "avr" else (size,))]
        if not candidates:
            raise FirmwareError("Unknown image or wrong length for the selected handset/processor profile")
        # Shared auxiliary images retain the original 9555 default; a directory's
        # checked BC5 container or --model resolves their handset context.
        profile, image = candidates[0]
        if image == "bc5":
            payload = data[:profile.payload_bytes]
        warnings = ("Raw image: container CRC unavailable; identity tracked by SHA-256",)
    return Firmware(image, name, payload, sha256(data).hexdigest(), kind, warnings, profile.model)


def load_firmware(path: Path, image: str | None = None,
                  allow_invalid_crc: bool = False, model: str | None = None) -> list[Firmware]:
    if path.is_dir():
        # Prefer the checked container; explicitly pass a .bin to run a raw patch.
        bc5 = path / "main.dfu"
        if not bc5.exists():
            bc5 = path / RAW_FILES["bc5"]
        if image and image != "bc5":
            if model is None and bc5.exists():
                model = load_firmware(bc5, "bc5", allow_invalid_crc)[0].model
            return load_firmware(path / RAW_FILES[image], image, allow_invalid_crc, model)
        result = load_firmware(bc5, "bc5", allow_invalid_crc, model)
        if image == "bc5":
            return result
        model = result[0].model
        for processor in ("avr", "trx", "ptt"):
            candidate = path / RAW_FILES[processor]
            if candidate.exists():
                result.extend(load_firmware(candidate, processor, allow_invalid_crc, model))
        return result
    with path.open("rb") as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    return [parse_firmware(data, path.name, image, allow_invalid_crc, model)]
