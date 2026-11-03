# Iridium 9575 Extreme firmware evidence

## Release and acquisition

On 2026-11-02, the latest ordinary Extreme release found in
[Iridium's resource listing](https://ifp.iridium.com/resources/?fwp_sort=last_updated)
was **HL25003**, dated January 13, 2026. The separately listed **HP25003** belongs
to Extreme PTT, not this handset profile. Iridium's release note is
IRDM-1023-SRN-001 v5.2, dated December 19, 2025.

The manufacturer portal returned HTTP 403 to direct download requests. The
Iridium-authored package was acquired from the public
[E-SAT distributor mirror](https://www.e-sat.fr/wp-content/uploads/HL25003_upgrade_installer_Iridium-Extreme.zip),
also linked from its [download page](https://www.e-sat.fr/en/downloads/).
This is a mirror download, not a claim that the bytes came directly from
Iridium's server. The recorded hashes identify this inspected copy; no
manufacturer-published checksum or Authenticode trust verification was found.

The downloaded ZIP, extracted payloads, release notes and `manifest.json` are
under `firmware/9575/`, which is ignored by Git. No Windows program was executed.
The ZIP was inventoried with REA; Inno Setup 5.5.7 data was unpacked with
`innoextract` 1.9. Firmware was read from resources and a data segment in the
extracted updater. The source ZIP and installer remain unchanged.

To reproduce, install `innoextract` on the host and run:

```sh
python3 tools/download_firmware.py
# Or reuse the previously downloaded, hash-checked ZIP:
python3 tools/download_firmware.py --archive /path/to/HL25003_upgrade_installer.zip
```

`--output` chooses the output directory, and `--innoextract` chooses the extractor
executable. The script pins this verified release, bounds downloads, checks the
ZIP and extracted updater hashes before using offsets, and verifies every
executable payload hash. It refuses to replace different existing files,
including locally patched firmware. Future releases require fresh inspection
and updated constants; the script does not silently download a different build.

## Byte identity

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Download ZIP | 14,579,424 | `26e0ee5e95def77b176cb5ee774c98eaceadb2e8e699f09be7f7f93db41455c8` |
| Windows installer | 14,190,064 | `b73355ff8d824f97ece2d620801be6c78ec63de0f807f678e9b9b0edd805f86f` |
| Extracted Windows updater | 9,214,976 | `49d808e59cdda826e17f8023e00fc43e90b56976030b74eb2a0a368b0223f80f` |
| `main.dfu` | 3,587,862 | `1ef3927985520a53b8c44df9fbd742c79e101ea62b5636182d130b82fbea2ff4` |
| `bc5_main.bin` | 3,586,850 | `21b9f28484bc1be0a5dc5cce78444e50b265b0b025ee40ed1d332830f7e90da1` |
| `loader.dfu` | 1,335,874 | `62f63a0bc123ef74158ecdc3dfe9d2d42ea20abefc74308a5e101a26b75f9c15` |
| `avr.bin` | 14,296 | `8b2e5df7b59d04f526facfeb422939ef09d5df11603da0f7ad207262fd30ddc2` |
| `trx_seg1_0x10000.bin` | 2,492,256 | `4f7939844993b28cae3031fa3da1b5bdb5c9546045cae1e0f6e42dd2d591e54b` |
| `trx_seg2.bin` | 687,096 | `1a4f78525e9b474946b21c4aba287dbd7e076c72acb534a0b0a7439daefb28ca` |

The updater's `DFUFILE/DFUFILEH2G` PE resource starts at file offset `0x3201F0`
with length `0x36BF16`; `DFUFILE/DFUFILELOADER` starts at `0x68C108` with length
`0x146242`. `HEXFILE/HEXFILEH2G` at `0x7D234C`, length `0x9D23`, contains the
AVR Intel HEX records. Record checksums and contiguous addresses were checked
before producing `avr.bin`.

The main container uses CSR-dfu2 v2 and CSRbcfw1 headers, with firmware beginning
at `0x3E0`. Code length is `0x363E4A`; constant data length is `0x7CD8`. The raw
payload excludes both the trailing four-byte file CRC and the USB suffix. USB
VID/PID is `1EDD:9575`, DFU version `0x0100`. All three CRCs match:
CSR firmware `AED9EA81`, DFU file `645D4087`, USB suffix `C3D099E4`.

The transceiver record stream at updater file offset `0x12EE8` contains a
`0x260760`-byte block loaded at `0x10000` and a `0xA7BF8`-byte block loaded at
`0x400000`, followed by a zero terminator and `DB24002`. These two blocks are
byte-for-byte identical to the existing HT25003 telephony/PTT payloads.
This does not add the absent modem boot block or establish hardware equivalence.

BC5 and AVR are different from HT25003. Sharing transceiver bytes or seeing
multiple product names in strings does not justify using 9555 application
addresses or board settings for the Extreme.

## AVR evidence

The Extreme AVR startup sets SP to `0x21FF`, uses SRAM beginning at `0x0200`,
and has 57 interrupt vectors. This fits the ATmega640/1280 family rather than
the existing ATmega164P model. The updater has a generic device table with
ATmega164P, ATmega324P, ATmega644P, ATmega640 and ATmega1280 entries; the
ATmega1280 signature `1E 97 03` occurs at updater file offset `0x31FB50`.
ATmega2560 is absent from that table. These observations constrain a compatible
emulator profile, but do not uniquely identify the physical AVR part.

## Handset behavior to preserve

The [manufacturer's product page](https://www.iridium.com/products/iridium-extreme-satellite-phone)
identifies GPS, location messaging, SBD and a programmable SOS button as Extreme
features. The [October 2021 manufacturer manual](https://www.e-sat.fr/wp-content/uploads/UM_Iridium-Extreme_User-Manual_Oct-2021.pdf),
printed pages 161–177, describes Setup → Location Options: GPS settings,
portal registration, emergency settings, automatic location messages, position
format and current position. GPS defaults off; SOS enables it. GPS update modes
are one-time, real-time, five minutes and ten minutes. The side convenience
key also changes text-entry modes and has configurable shortcuts.

The [HL25003 release note](https://www.e-sat.fr/wp-content/uploads/IRDM-1023-SRN-001-v5.2-Iridium-Extreme-Software-Release-Note-HL25003.pdf)
supersedes older manual behavior in several places: IERCC replaces GEOS;
selecting IERCC requires a five-digit registration PIN. An unconfigured SOS
uses 112 for voice, and sends no SMS without an SMS recipient. The release
also handles the January 2026 network time epoch and restricts direct Internet
dial-up. GPS/IERCC labels alone do not demonstrate that the executing firmware
receives GPS measurements, places calls or transmits messages.

## Verification boundary

Acquisition tests cover Intel HEX record/checksum validation, rejection of an
unrecognized updater, and preservation of a user's existing files. The complete
extraction was rerun against the downloaded archive and verified every listed
payload hash. Package inspection and checksums establish byte identity and
container consistency, not full device emulation. Runtime support and remaining
hardware gaps must be assessed separately against actual firmware execution.
