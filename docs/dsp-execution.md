# Factory DSP execution evidence

The supplied TRX firmware contains initial programs and data for both DSPs. The original SPARC code copies and verifies them, then issues entry/start strobes. The emulator currently stores their memory and control registers without executing DSP instructions. This is the observed boundary behind the two full-modem Phone Lock failures: background modem burst-search commands fill a ring whose DSP consumer never advances.

This investigation used shipped bytes, the original SPARC listing, and read-only runtime traces. It did not modify guest memory, redirect execution, advance consumers in the host, or suppress the original fatal check. No DSP execution or Phone Lock success is claimed.

## Identity and instruction-set boundary

The telephony segment `trx_seg1_0x10000.bin` has 2,492,256 bytes and SHA-256 `4f7939844993b28cae3031fa3da1b5bdb5c9546045cae1e0f6e42dd2d591e54b`. It is identical in the examined 9555 and 9575 packages. The DSP-fatal string at original RAM address `0x70064EE0` names Sapphyre.

Cambridge Consultants describes Sapphyre as a configurable VLIW family with independently selected processing modules and data paths. Its assembler and simulator understand each selected design; the export tool can produce program ROM, initial RAM, symbols, and memory sizes. These are configuration-dependent inputs, rather than evidence of a single standard opcode map. See the developer's [Sapphyre overview, pages 2, 6, 9–11](https://cdn2.hubspot.net/hubfs/218152/Cambridge%20Consultants%20-%20Sapphyre%20Overview.pdf).

The developer's [2017 architecture presentation, pages 10–12](https://nmi.org.uk/wp-content/uploads/2017/09/5_CC_Sapphyre-P-009-v1.0.pdf) shows a simulator opened on `modem.aof` and module definitions such as `alu_t1.mdf` and `ioregisters_t1`. Its displayed assembly includes `seq.nop`, `ram.read`, and `ram.write`. A [first-person engineering résumé](https://robertmaye.co.uk/assets/pdf/resume.pdf) also describes Iridium work using proprietary Sapphyre. These support the Sapphyre-family identification; they do not identify the exact configuration or opcode fields of this older handset build.

Both supplied program images have a repeating four-host-word structure, consistent with 128-bit VLIW bundles. For example, the first modem groups, in original big-endian host-word order, are:

```text
0000: 00000000 30000000 00000005 00000000
0001: 00010000 30000001 00000005 00000000
0002: 00020000 30000000 00000005 00000000
0003: 00030000 30000000 00000005 00000000
0004: 0003021b 00040007 00000000 00000000
```

The grouping is an observation, not a decoded ISA. Instruction width, lane order inside a DSP instruction, sequencer encodings, routing fields, module set, arithmetic widths, and pipeline timing remain unverified. No matching DSP core, `.aof`, `.mdf`, RTL, assembler, or decoder was found in the examined local repositories, downloads, or installed tools. Existing native execution cores are XAP2, AVR, and SPARC. The translated upstream DSP/OSAL Zig files call original SPARC addresses; they do not implement a DSP CPU.

## Supplied executable blobs

All counts below are hexadecimal 32-bit host words. Sources are original execution addresses; raw offsets are offsets within the relevant segment file, excluding its load base. Each source is immediately preceded by a four-byte pointer to itself. The loader copies raw words without decompression.

| Image | DSP/window | Source | Raw offset | Words | Host destination |
|---|---|---|---|---|---|
| TRX | audio data | `70064F6C` | `23E110` | `569` | `D0000000` |
| TRX | audio program | `70066514` | `23F6B8` | `1000` | `C0000000` |
| TRX | modem data | `7006AEAC` | `244050` | `1D39` | `B0000000` |
| TRX | modem program | `70072394` | `24B538` | `4000` | `A0000000` |
| PTT | audio data | `004491F4` | `491F4` | `7C7` | `D0000000` |
| PTT | audio program | `0044B114` | `4B114` | `1000` | `C0000000` |
| PTT | modem data | `0045653C` | `5653C` | `170A` | `B0000000` |
| PTT | modem program | `0045C168` | `5C168` | `4000` | `A0000000` |

The telephony RAM shadow maps raw offset `0x1D921C` to RAM `0x70000078`. Thus a source address `a` is at raw offset `0x1D921C + a - 0x70000078`. PTT sources above are in its flash segment, loaded at `0x400000`.

SHA-256 of the extracted TRX windows:

```text
audio-data     8111d028822e2a0b8298c9f4ee64c033b90889af7667dba67364e5eb380d7fb4
audio-program  70019481fc13a4f53aad387296e6b9e6860f18fe69dd5df52c346f2e0d967649
modem-data     2228439c2659e7069b411cd603fe685fe205f345a94d0d04305d095e06423116
modem-program  ce40b4a2164e00e2778237cf81328663a2919b7c02a473069dc41db59d84407c
```

Original TRX `0x70044584` first clears the complete program/data apertures: modem program 64 KiB, modem data 32 KiB, audio program 16 KiB, and audio data 8 KiB. `0x700443EC` then selects DSP 0/audio or 1/modem, writes its HPI `+0x2C = 1`, and loads the initial images through `0x700443B8`. Its copy loop is `0x70044344`; its compare loop is `0x70044378`. PTT equivalents are `0x4383E0`, `0x438230`, `0x4381FC`, `0x438188`, and `0x4381BC`.

## Original reset, entry, and wake sequence

HPI base `0x80000C00` belongs to audio; `0x80000D00` belongs to modem. The authoritative TRX assembly is `0x70044238–0x700442EC`, called by `0x7004449C` after both images verify. The decompiled C omits earlier writes and the `+0x14` pulses, so its final assignments alone are insufficient.

The exact initial sequence is:

1. Both HPI `+0x24 = 0`, then `+0x04 = 1`, then `+0x2C = 1`.
2. Both `+0x00 = 0`, then `+0x2C = 0`.
3. Modem `+0x20 = 0`, `+0x14 = 1`, `+0x14 = 0`.
4. Audio `+0x20 = 0`, `+0x14 = 1`, `+0x14 = 0`.
5. Both `+0x04 = 0`, then `+0x24 = 1`.
6. Modem `+0x00 = 1`, then audio `+0x00 = 1`.

The entry arguments come from `0x700823A0`/`0x7006A520`, both zero; the enable arguments at `0x7008239C`/`0x7006A51C` are one. Treat `+0x20` and its `+0x14` pulse as the observed entry-loading contract. Names such as reset, clock enable, or interrupt enable for the other fields are inferred; their complete electrical semantics are not established by these stores.

There is additional wake behavior: original `0x70044788` prints that it is forcing the selected DSP to sleep and writes HPI `+0x04 = 1`. Audio helpers such as `0x700862D8` and `0x70086540` post work in shared RAM, wait for a completion field, and repeatedly pulse `0x80000C00` from one to zero when `D0000068` is zero. Therefore `+0x00` cannot be modeled solely as a persistent CPU-enable boolean. For example, `0x70086540` posts command 5 at halfword address `D0000E26` and waits for it to clear before reading the result. DSP execution must supply that completion.

A bounded run from the native TRX reset vector observed both initial loads and the complete sequence above by instruction 3,301,376, with no halt and no dropped trace events. All four runtime copy hashes equal the static hashes above. No host initialization call or forced program counter was used. This rules out absent blob loading or an unexecuted SPARC startup call as the immediate blocker. PTT blob extraction was checked statically; a PTT DSP-start runtime trace was not taken.

## Shared-memory and interrupt contract

TRX rings contain host-visible 32-bit cells. Control pointers use their low 16 bits and are DSP word indices: host address = window base + pointer × 4. A queue header swaps its two halfwords at the host boundary: host structure `{opcode:u16, length:u16}` becomes a shared word `(length << 16) | opcode`; payload words are copied unchanged. Original encoders/decoders are modem `0x70048414`/`0x700483D4` and audio `0x70045D08`/`0x70045CC8`.

| Ring | Producer | Consumer | Base index | Slots × words | Producer owner |
|---|---|---|---|---|---|
| Modem commands | `B0006CE0` | `B0006CE4` | `1B3A` | 5 × 6 | SPARC |
| Modem responses | `B0006D60` | `B0006D64` | `1B5A` | 10 × 6 | DSP |
| Audio commands | `D0000BC8` | `D0000BCC` | `2F4` | 5 × 5 | SPARC |
| Audio responses | `D0000C34` | `D0000C38` | `30F` | 20 × 5 | DSP |

Initial producer and consumer equal each ring's base. Command enqueue routines are `0x70044B5C`/`0x70044A60`; they reserve one empty slot. Modem enqueue publishes its producer after writing the payload and does not issue a separate HPI wake store in that routine. Modem response drain `0x70044948` decodes each message, calls `0x7005F6C8`, and publishes the consumer. Audio drain `0x70044834` forwards decoded messages to the original queue interface and publishes its consumer.

Original `0x7004449C` registers audio IRQ source 8 at CPU level 5 with callback `0x70044720`, and modem source 9 at level 6 with `0x7004470C`. The callbacks activate HISR 1/audio and HISR 0/modem through `0x700490D8`; their entry functions are `0x70044834` and `0x70044948`. The precise DSP-side I/O bit that raises each source, and edge/level acknowledgement behavior, still require the configured core/I/O definition or hardware evidence. The current native interrupt selector supplies timers, UARTs, and RF alarm events, but no DSP source 8/9 event.

In the captured factory failure, the SPARC read modem producer `1B52` and consumer `1B3A`. The next slot wrapped to the unchanged consumer, so original `0x70044B5C` rejected a fifth request, passed fatal `FFFF` to `0x700448EC`, and deliberately rebooted through `0x7004A090`. Saved request header `00040005` identifies opcode 4 / length 5 in the host structure; its builder `0x7005F5C4` and schema string identify `MSG_PAYLOAD_BURST_SEARCH_CMD`. The Sapphyre fatal-status cell `B0006CDC` remained zero in the preceding captured polls. This is a modem command-consumption failure, independent of Phone Lock PIN validation or the audio queue.

The 9575 Reset-to-Defaults contact/note retention journey also reaches this
previously traced reboot signature: TRX step `311574149`, PC `7004A0C8`, saved
`i7=70044934`. Its saved name, number and note assertions passed before TRX
halted while the user returned home. That case remains enabled and failing;
shortening the journey or suppressing its final health check would not fix DSP
execution. Its final state is recorded with the factory expansion artifacts.

## Genuine implementation path and evidence files

The next required artifact is the handset's Sapphyre configuration: its object/core definition and module definitions, generated RTL, or an instruction reference and matching assembly/encoded examples. A generic Sapphyre family description does not give the bit fields. A useful original toolchain export would include the symbol map, program image, initial RAM image, module/routing configuration, and external I/O definition for both cores. These are the specific missing inputs; selecting TI, CEVA, Motorola, or Kalimba instructions by resemblance is unjustified.

Once encoding is established, a genuine implementation needs parallel instruction evaluation from pre-cycle state, defined arithmetic and pipeline rules, shared program/data memory with the existing host byte lanes, the observed HPI entry/sleep/wake strobes, and DSP I/O driving original IRQ sources 8/9. The first useful regression is reset-to-initial idle using the untouched extracted programs, followed by an actual factory command through SPARC enqueue, DSP instruction-level consumption, response publication, and original HISR drain. RF input or audio samples should enter through the defined external I/O boundary. A host routine that only updates a queue pointer cannot establish this behavior.

Local research artifacts are under `/tmp/iridium-dsp-execution/`:

- `extract.py`, `extract.log`, and `manifest.json`: all eight original blobs, pointer/range/identity checks, initial ring assertions, hashes, and runtime/static copy comparisons. Program `*-lanes.tsv` files show raw four-word groups without invented opcodes.
- `capture_boot.py`, `boot-trace.json`, and `boot-trace.log`: bounded original TRX reset execution, the observed HPI writes, no-drop assertion, and runtime images reconstructed from actual loader writes. Run `python3 /tmp/iridium-dsp-execution/capture_boot.py`, then `python3 /tmp/iridium-dsp-execution/extract.py` in this workspace.
- `sapphyre-overview.pdf`, `sapphyre-2017.pdf`, their text extractions, and `sapphyre-simulator.png`: the primary architecture references examined.

The earlier fatal capture is `/tmp/iridium-dsp-fatal-evidence.md`, with live stack/MMIO records in `/tmp/iridium-dsp-fatal-live.json` and `/tmp/iridium-dsp-fatal-events.json`. Temporary artifacts are local diagnostics, not durable repository fixtures. Only this evidence document was added during the DSP execution investigation; production and test sources were unchanged.
