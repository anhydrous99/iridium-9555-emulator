#!/usr/bin/env python3
"""Acquire the verified HL25003 release without running its Windows installer."""

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile


URL = "https://www.e-sat.fr/wp-content/uploads/HL25003_upgrade_installer_Iridium-Extreme.zip"
PACKAGE_SHA256 = "26e0ee5e95def77b176cb5ee774c98eaceadb2e8e699f09be7f7f93db41455c8"
UPGRADER_SHA256 = "49d808e59cdda826e17f8023e00fc43e90b56976030b74eb2a0a368b0223f80f"
PACKAGE_DIRECTORY = "HL25003_upgrade_installer_Iridium Extreme/"
INSTALLER = "Iridium Extreme Software Upgrade HL25003 Installer.exe"
UPGRADER = "pf/Iridium/Extreme/Upgrade_Tool/Iridium Extreme Software Upgrade HL25003.exe"
RELEASE_NOTES = "IRDM-1023-SRN-001 v5.2 - Iridium Extreme Software Release Note HL25003.pdf"
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
# Resource offsets are valid only for the exact hash-checked updater above.
RESOURCES = {"main.dfu": (0x3201F0, 0x36BF16),
             "loader.dfu": (0x68C108, 0x146242),
             "h2g.hex": (0x7D234C, 0x9D23)}
PAYLOAD_HASHES = {
    "main.dfu": "1ef3927985520a53b8c44df9fbd742c79e101ea62b5636182d130b82fbea2ff4",
    "loader.dfu": "62f63a0bc123ef74158ecdc3dfe9d2d42ea20abefc74308a5e101a26b75f9c15",
    "bc5_main.bin": "21b9f28484bc1be0a5dc5cce78444e50b265b0b025ee40ed1d332830f7e90da1",
    "avr.bin": "8b2e5df7b59d04f526facfeb422939ef09d5df11603da0f7ad207262fd30ddc2",
    "trx_seg1_0x10000.bin": "4f7939844993b28cae3031fa3da1b5bdb5c9546045cae1e0f6e42dd2d591e54b",
    "trx_seg2.bin": "1a4f78525e9b474946b21c4aba287dbd7e076c72acb534a0b0a7439daefb28ca",
}


def check_hash(data: bytes, expected: str, name: str) -> None:
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"{name}: SHA-256 differs from the verified HL25003 release")


def decode_avr_hex(text: str) -> bytes:
    """Decode the contiguous, zero-based AVR Intel HEX image used by this release."""
    output = bytearray()
    ended = False
    for line in text.splitlines():
        if ended or not line.startswith(":"):
            raise ValueError("Invalid AVR HEX record or data after EOF")
        record = bytes.fromhex(line[1:])
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise ValueError("Invalid AVR HEX length/checksum")
        address, kind = int.from_bytes(record[1:3], "big"), record[3]
        if kind == 1 and record[0] == 0 and address == 0:
            ended = True
        elif kind == 0 and address == len(output) and len(output) + record[0] <= 32768:
            output.extend(record[4:-1])
        else:
            raise ValueError("Unsupported AVR HEX layout")
    if not ended or not output:
        raise ValueError("AVR HEX requires data and an EOF record")
    return bytes(output)


def extract_payloads(upgrader: bytes) -> dict[str, bytes]:
    check_hash(upgrader, UPGRADER_SHA256, "Windows updater")
    files = {name: upgrader[offset:offset + length]
             for name, (offset, length) in RESOURCES.items()}
    files["bc5_main.bin"] = files["main.dfu"][0x3E0:-20]
    files["avr.bin"] = decode_avr_hex(files["h2g.hex"].decode("ascii"))
    offset = 0x12EE8
    for name, address, size in [("trx_seg1_0x10000.bin", 0x10000, 0x260760),
                                ("trx_seg2.bin", 0x400000, 0xA7BF8)]:
        if struct.unpack_from(">II", upgrader, offset) != (address, size):
            raise ValueError("Unexpected transceiver record")
        offset += 8
        files[name] = upgrader[offset:offset + size]
        offset += size
    if upgrader[offset:offset + 16] != b"\0" * 8 + b"DB24002\0":
        raise ValueError("Unexpected transceiver terminator/version")
    for name, expected in PAYLOAD_HASHES.items():
        check_hash(files[name], expected, name)
    return files


def write_outputs(output: Path, files: dict[str, bytes]) -> None:
    # Never replace a user's patched firmware, even when other outputs are missing.
    for name, data in files.items():
        path = output / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite different existing file: {path}")
    output.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = output / name
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("firmware/9575"))
    parser.add_argument("--archive", type=Path, help="Use an already downloaded HL25003 ZIP")
    parser.add_argument("--innoextract", default="innoextract", help="Path to innoextract (1.9 tested)")
    args = parser.parse_args()
    extractor = shutil.which(args.innoextract)
    if extractor is None:
        parser.error("innoextract is required to unpack the installer; install it or pass --innoextract")
    try:
        archive = args.archive or args.output / "HL25003_upgrade_installer.zip"
        if archive.exists():
            with archive.open("rb") as source:
                package = source.read(MAX_PACKAGE_BYTES + 1)
        elif args.archive:
            raise ValueError(f"Archive not found: {archive}")
        else:
            with urlopen(URL, timeout=60) as source:
                package = source.read(MAX_PACKAGE_BYTES + 1)
        check_hash(package, PACKAGE_SHA256, "Firmware ZIP")
        with tempfile.TemporaryDirectory(prefix="iridium-9575-extract-") as temporary:
            root = Path(temporary)
            with ZipFile(io.BytesIO(package)) as zipped:
                installer = root / INSTALLER
                installer.write_bytes(zipped.read(PACKAGE_DIRECTORY + INSTALLER))
                release_notes = zipped.read(PACKAGE_DIRECTORY + RELEASE_NOTES)
            subprocess.run([extractor, "--silent", "--extract", "--output-dir", str(root),
                            str(installer)], check=True, timeout=120)
            files = extract_payloads((root / UPGRADER).read_bytes())
        files["release-notes.pdf"] = release_notes
        manifest = {"model": "9575", "firmware_version": "HL25003", "verified_on": "2026-11-02",
                    "listing_url": "https://ifp.iridium.com/resources/?fwp_sort=last_updated",
                    "download_url": URL, "package_sha256": PACKAGE_SHA256,
                    "upgrader_sha256": UPGRADER_SHA256,
                    "files": {name: {"size": len(data), "sha256": sha256(data).hexdigest()}
                              for name, data in files.items()}}
        files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
        files["HL25003_upgrade_installer.zip"] = package
        write_outputs(args.output, files)
        print(f"HL25003 firmware verified and extracted to {args.output.resolve()}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Firmware acquisition failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
