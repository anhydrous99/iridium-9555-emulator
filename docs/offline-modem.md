# Offline training modem

Offline training uses `OfflineModem` as a finite serial peer on the AVR's modem
UART (9555 USART0; 9575 USART3). The original BC5 and AVR still execute and draw
the LCD. TRX/DSP execution, RF, subscriber authentication and voice audio are
not provided. Firmware research mode retains the original processor link.

The peer exchanges DPL frames, validates XOR and ETX, honors physical ACK/NAK,
preserves partially accepted UART data, and follows the original modem power
output. It never writes guest RAM, changes a guest callback, or advances DSP
queue consumers. Unrecognized AT commands return `ERROR` and appear in the
bounded `unsupported_commands` diagnostic list.

## Evidence and scope

The transport follows the existing [board evidence](hardware-evidence.md),
[SIM storage contracts](sim-device-contract.md) and
[phonebook startup analysis](phonebook-startup.md). A read-only capture of
pinned HT25003 BC5/AVR and DB24002 TRX execution confirmed the startup envelope
`04 04 00 03 00 00 03 03`, followed by the AT-channel `+ANTST:1` notification.
AT commands use DPL channel 4 and a four-byte inner header. Original responses
use type 7 command echoes, type 6 intermediate lines, type 2 terminal results and
type 4 unsolicited lines, with alternating bit 7 sequence values. The peer
keeps those wire conventions, with explicitly simulated outcomes.

Original startup requests observed in that capture include `ATI3`, `ATI7`,
`CPBR`, `CPBS`, `CLVL`, `CMEE`, `CREG`, `CIER`, `CAR`, `CPMS`, `CNMI`, `CMGL`,
`CAPPV`, `-MSSTM`, `CICCID`, `CPIN`, `CLCK` and `CVMI`. `CRDBG=0` really returned
`ERROR`; the training peer does too. The version responses are compatibility
values expected by this firmware, not a claim that the TRX is executing.

Synthetic SIM storage contains 64 PDU SMS slots, two phonebook slots numbered
101 and 102 (ASCII names up to 16 characters), and an editable SMS service
center. The parent Session owns its mutable storage so board restart can preserve it. Clearing the experiment or
changing handset profiles starts a fresh store. SMS payloads use the GSM default
alphabet or UCS-2 and a fixed demonstration timestamp; multipart reception is
not implemented. Unknown card operations and invalid indices fail explicitly.

`notify_scenario()` publishes changes in registration, signal and call state.
Handset call transitions use original seven-field `+XCSI` notifications,
formatted by TRX `0xC7600` and consumed by BC5 `0x77B94 -> 0x7BB30`.
The dialing report must precede the active report so the original UI binds
its pending call to the reported index. Incoming calls stage two ringing
reports around caller ID; BC5 `0x7BE96` opens the incoming UI on the second
report. Answering binds that ringing object directly to the active index.
Stable voice notifications keep the transport AT-ready (mode 1); call state
is carried by `+XCSI`. BC5 `0x8ECFE` does not dispatch ordinary AT commands
in transport mode 8. Voice success uses `OK`; `CONNECT` denotes a data call. Iridium's [MAN0009 v5, section 5.176](https://www.asiasatellite.co/mwdownloads/download/link/id/36)
documents the first five fields; the pinned firmware additionally carries two
metadata fields. The peer reports voice type 0 and local AT ownership 1;
original BC5 `0x7C614` uses ownership 0 for the separate DPL-peripheral UI.
`validate_incoming_sms(number, text)` allows the caller to validate before
mutating scenario history; `incoming_sms(number, text)` stores the PDU and emits
`+CMTI`. AT message reads, writes and deletes operate on this training store.
These are simulated delivery/storage outcomes, not satellite messages.

Firmware-free framing, partial I/O, corruption, unsupported requests, storage,
SIM absence and SMS encoding tests are in `tests/test_offline_modem.py`.
Factory handset regressions must separately establish the displayed result;
unit command responses alone do not establish a complete handset journey.

Training network time starts at **2026-11-09 00:00:00 UTC** and advances only
with the scenario clock. Before registration, `-MSSTM` reports no network
service. The original BC5 retries an unavailable clock after six seconds of
handset time (`0xAF900` / `0xAFA78`); acquiring time can therefore remain visible
briefly after registration. Afterward the peer returns the documented 90ms
frame counter using the Era 3 epoch, **2025-02-14 18:14:17 UTC**. This epoch is recorded in the
[manufacturer's re-epoch technical bulletin](https://metocean.com/important-technical-bulletin-from-metocean-iridium-re-epoch/);
the supplied HL25003 release notes confirm support for the January 2026
change. `network_time` explicitly labels the origin, epoch and current counter
as simulated. It does not synchronize with the host's wall clock.
