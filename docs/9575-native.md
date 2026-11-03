# HL25003 native execution evidence

This records the initial HL25003 integration. Later IRQ/register-bank, ADC,
keypad, serial-link and AVR peripheral implementations are documented in
[current inferred hardware](inferred-hardware.md); the missing-device list
below describes the earlier baseline.

The 9575 Extreme profile executes the downloaded HL25003 instructions. Source
identities and acquisition are recorded in [9575-firmware.md](9575-firmware.md).
The native worker accepts `--model 9575`; the default remains `9555`.
Model selection is checked against each processor's payload length before loading.
It does not prove that a same-sized modified image retains the supported layout.

## BC5 application

The CSR headers give `0x363E4A` code/resource bytes and `0x7CD8` constant-data bytes.
The mapped constant window uses image word base `0x363E4A / 2` and ends before
word address `0x3E6C`. The final instruction at image byte `0xFEF94` is `rts`;
`0xFEF96` starts erased padding before the resource region. Instruction fetches
are bounded to `0x000000..0x0FEF95`, plus the existing executable RAM mapping.
No resource data is presented as executable code.

The corrected XAP decoder from the supplied `rev-firmware/re/tools/isa/xap.py`
was used to compare the original binaries. Byte offsets below are **image byte
offsets**, while RAM addresses are **16-bit word addresses**.

| Boundary | HT25003 / 9555 | HL25003 / 9575 |
| --- | --- | --- |
| Main / scheduler / idle | `0x5748` / `0xB5E0` / `0xB774` | Same |
| Panic / armed-watchdog reset wait | `0x70A0` / `0x184F0` | Same |
| LCD sender | `0x68E48` | Same |
| Graphics initialization | `0x6365E` | Same |
| Graphics allocation pointer | RAM `0xF719` | RAM `0xF72C` |
| Application setup | `0x8CC8C` | `0x93788` |
| Application start | `0x8CC5E` | `0x9375A` |
| Key transition routine | `0x67F04` | Same |
| Installed key callback pointer | RAM `0xF6FB:0xF6FC` | RAM `0xF70E:0xF70F` |
| Default key handler | `0x713AE` | `0x71492` |
| Key matrix mapper | `0x71476` | `0x715CC` |
| Probe stack / stack guard | `0xFCC0` / `0xF960` | Same |

The firmware's new key callback `[4, 0x0A55]` converts to handler byte `0x71492`
using `(far_pointer - 0x800C) * 2`.

A direct native run reached cold idle after 6,491,511 instructions. Original
graphics initialization returned after 5,065,898 instructions and produced the
43-byte controller initialization stream. Application setup wrote factory
defaults and reached the watchdog reset wait. The retained warm reset reached
idle after 11,686,895 instructions. Repeating setup returned after 6,861,290
instructions, then application start returned after 1,194,730 instructions and
installed the callback above. These numbers describe this interpreter/profile,
not hardware timing.

The board-identification callback moved from `0x8CF70` to `0x93A84`. It classifies
an ADC sample into **board revisions**, including `GRev`, rather than selecting a
handset model directly. The emulator does not invent an ADC voltage or force this
callback to claim a physical 9575 board. Experimental application initialization
still enters the established software boundaries explicitly.

## AVR helper

The Extreme AVR image is **14,296 bytes**, unlike the 9555's 8,678-byte image.
Its reset vector enters byte `0x19A`; original startup sets SP to `0x21FF`, copies
266 initialized bytes from flash `0x36CE` into SRAM `0x200..0x309`, and clears BSS
`0x30A..0x90B`. Main is `0x105C`; its final call enters the event loop at `0xB0A`,
whose repeated flag/timer sweep starts at `0xB1E`. Both milestones are reached
within a 100,000-instruction regression.

The 57-vector table, SRAM map, and use of USART2/3 match the
[ATmega640/1280 family datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega640-1280-1281-2560-2561-Datasheet-DS40002211A.pdf).
The upgrade executable's supported-device table names ATmega640 and ATmega1280
with signatures `1E:96:08` and `1E:97:03`; it does not identify the fitted chip.
The profile therefore reports **`inferred-atmega640-1280-family`**. It uses a
1280-compatible 16-bit word PC and two-byte return addresses; behavior beyond
this small upgrade image's address range has not been validated against a
physical handset. It does not assume a 2560's three-byte return-address stack.

The profile supplies SRAM `0x200..0x21FF`, the larger I/O range, four independent
USARTs at `0xC0`, `0xC8`, `0xD0`, `0x130`, GPIO A–H/J/K/L, 4 KiB EEPROM, PRR1
serial clock gating, and the family interrupt numbers for the supported
peripherals. Existing timer0/1/2, SPI, watchdog and ADC models are reused with
those interrupt numbers. USART queues retain separate loss counters. `pins`
accepts indices 0–10 in A,B,C,D,E,F,G,H,J,K,L order; `uart_rx`/`uart_tx` accept
ports 0–3. The 9555 remains limited to four GPIO ports and two USARTs.

Additional timers3–5, external interrupt inputs, TWI, full ADC mux/gain behavior,
physical battery/GPS/serial wiring, and analog timing remain incomplete. Unknown
registers follow the existing explicit open-bus hypothesis. The AVR and BC5 run
in separate workers; successful AVR startup does not connect them into a board.
The existing 1-Wire device is not automatically connected to the Extreme.

## Modem and validation

The extracted telephony and PTT payloads are byte-identical to the existing
HT25003 payloads, so their existing SPARC profiles are reused. The missing boot
block, DSP/RF execution, network authentication, SIM and call audio limitations
remain as documented in [hardware-evidence.md](hardware-evidence.md).

`zig build test -j2` includes independent checks of high AVR program addresses,
LPM, four serial channels and interrupt vectors, PRR1 gating, extended GPIO,
interrupt acknowledgement and EEPROM addressing. `native/test_protocol.py`
checks profile-specific memory bounds and code/resource separation using
synthetic payloads. With `IRIDIUM_TEST_9575_FIRMWARE=firmware/9575`, it also runs
original HL25003 setup/reset/callback and AVR startup tests. A reset-opcode
mutation must halt rather than report the original startup milestones.
