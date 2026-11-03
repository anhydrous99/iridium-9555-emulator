# 9575 Extreme control evidence

Observed on 2026-11-02 using the downloaded HL25003 BC5 payload, SHA-256
`21b9f28484bc1be0a5dc5cce78444e50b265b0b025ee40ed1d332830f7e90da1`.
Addresses below are image byte offsets unless explicitly called data words.
Static instructions were decoded with the supplied upstream
`re/tools/isa/xap.py`; runtime observations execute those instructions in the
native worker. REA's advertised raw CPU families do not include XAP2, so its
native disassembler was not substituted for this established decoder.

The [Iridium-authored H3UG1301 user manual](https://www.tracplus.com/hubfs/Iridium-Extreme-Users-Manual.pdf?hsLang=en),
printed pages 14–15 and 171, documents two-way navigation, a right-side location
convenience key, and a dedicated SOS button under a top cover. The browser
depiction follows those controls. This does not establish electrical wiring.

## Software input boundary

`0x67F04(AL=raw_key, AH=phase)` accepts phase 1 for press and 4 for release,
allocates an event through `0x67F88`, and dispatches via `0x67FEA`. In HL25003
the callback lives at data words `0xF70E:0xF70F`; experimental initialization
installs `[4, 0x0A55]`, identifying handler `0x71492`. The pending count is
`0xF70D`. This differs from HT25003's `0xF6FB:0xF6FC` callback and `0x713AE`
handler even though the software input entry address is unchanged.

The handler stores the current raw key at data word `0xF756` on phases 1–3
and clears it on release (instructions `0x714B4..0x714CA`). The corresponding
HT25003 word is `0xF743`.

Widget normalizer `0x79CC8` transforms the event's key field before diagnostic
screens consume it. Calling this original routine with a scratch event
`[2, raw_key, 1]` independently reproduced every mapping below, with no halt.

| Control | Raw software key | Normalized widget key |
| --- | --- | --- |
| Digits 0–9 | `0x64..0x6D` | `0xD2..0xDB` |
| Star / hash | `0x79` / `0x78` | `0xD0` / `0xCF` |
| Up / down | `0x82` / `0x83` | `0xCA` / `0xCB` |
| Left / right soft key | `0x96` / `0x97` | `0xC8` / `0xCE` |
| Green / red | `0x8D` / `0x8C` | `0xC9` / `0x8C` |
| Volume up / down | `0xA0` / `0xA1` | `0xCC` / `0xCD` |
| Convenience / location | `0xAA` | `0xAA` |
| SOS | `0xAB` | `0xAB` |

The normalizer's digit path at `0x79DEA..0x79E08` adds `0x6E` to raw digits;
its switch handles the listed navigation keys. Other widget normalizers can
apply different contextual mappings. Injection belongs at the raw boundary,
not at the normalized diagnostic codes.

The built-in keypad test independently identifies convenience and SOS:

- Test state 21 displays string `0x1295` at `0x7E670` and accepts `0xAA` at
  `0x7EBC4`. The string identifies the convenience key.
- State 22 displays string `0x132D` at `0x7E680` and accepts `0xAB` at
  `0x7EBD4`. The string identifies the emergency key.
- HL25003 English strings are TLV records in filesystem file 45. Their IDs
  follow the established `0x1000 + string_index` format.
- HT25003's same convenience prompt is loaded at `0x7E1F2`, and the diagnostic
  accepts `0xAA` at `0x7E6EC`. An original HT25003 home-screen press/release of
  `0xAA` left the home screen running without a halt or display error. The
  initial convenience action can be inactive. **`0xAA` must not be labeled
  as the physical power button on either model.** A power-switch event path
  remains unresolved; recording that control must not claim firmware delivery.

## Executed location and SOS behavior

Each experiment initialized only the original BC5 image, ran 600 batches of
200,000 instructions to reach home, and injected press then release at safe
scheduler boundaries. Unless stated otherwise, each key was followed by ten
batches of 200,000 instructions. All captures had complete LCD pixels, no
capture errors, and no native halt.

1. Raw `0xAA` opens the original GPS-enable prompt. Left soft key selects Yes,
   opening Current Location with blank latitude, longitude, and altitude and
   an updating fix status. A further 20 million instructions retained that
   screen. No GPS fix was fabricated. Right soft key returns home.
2. Raw `0xAB` opens the firmware's 20-second emergency countdown even after
   immediate release. A further 20 million instructions changes the visible
   countdown to 19. Right soft key cancels and restores the original home.
3. The SOS branch is explicit at `0x714F0`: key `0xAB` with phase 1, outside
   the diagnostic screen, calls `0x83246`. The countdown initializer
   `0x832FA` writes 20 at `0x83340`, then schedules an original callback at
   a 1,000,000-microsecond interval. Callback `0x83570` decrements the count
   and reschedules through `0x769A`. Its zero path requests emergency mode
   through `0xB9078`. This is the original firmware timer, not a host countdown.

The input routine's separate hold timer produces phase 2 after its initial
1,000,000-microsecond timeout and phase 3 repeats at 500,000 microseconds.
These modeled firmware intervals do not establish physical handset timing.

The following SHA-256 values cover row-major 0–3 LCD pixel bytes at
`pixels[first_row * 128:last_row * 128]` (last row excluded). Screens were
visually inspected before recording the hashes. Top status icons are excluded.

| Original screen | Rows | SHA-256 |
| --- | --- | --- |
| GPS-enable prompt | 16–97 | `6ed573ae1d790186ce9343c295755529ba4ff6609978ff34771dbe1451522873` |
| Current Location awaiting a fix | 16–97 | `7593b7dc3794469f02bc612ae5e85d4c1909d7c76cc770e120d99fdbcb624210` |
| SOS countdown, 20 seconds | 16–97 | `48d9b42fd91ff4b93045fad54c36b5949977577dbe08f77b71da362645e703e6` |
| SOS countdown, 19 seconds | 16–97 | `0eef6286acc766efe7f851379d64b092dbc230f5961ae5375eb3e16fca1c8a8c` |
| SOS Cancel caption | 113–128 | `4263e2ad1e0712a13794af33292caf52752f0cf8ab65f020a9c665186f946859` |
| Home after cancellation | 16–97 | `136fc5caa2e78f17fc657c7f202213b03618b5f0e2222b33211328451e32e4d1` |
| Home Menu / Help captions after cancellation | 113–128 | `b27866e4b66c4276d7f13b5b830b672ddf8f348dab67e38c8df5326a58de66d9` |

These observations establish original location menus and the cancellable SOS
countdown. They do not establish GPS receiver emulation, a fix, completed
emergency messaging, calling, or a coupled modem/satellite transport.
