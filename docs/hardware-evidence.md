# Hardware evidence and emulation limits

The source artifact for these observations is HT25003 `bc5_main.bin`, SHA-256
`8ff911b30bb57d77e0eb9c46054a2d8b26f4889feb00b94a64963effba28705d`.
Addresses of BC5 functions are image **byte offsets**; data addresses are
16-bit **word addresses**. The runtime program address is `byte_offset / 2 + 0x800C`.
Evidence paths below are relative to the supplied `rev-firmware` repository.

## Execution and input boundaries

Original instructions establish these boundaries; physical pin timing has not
been measured:

| Boundary | Original-firmware behavior |
| --- | --- |
| `0x67F04(AL=key, AH=transition)` | Starts the repeat timer for transition 1, cancels it for transition 4, then creates an input event. |
| `0x67F88(AL=key, AH=transition)` | Allocates three words using `0x1C9BC`, writes `{2, key, transition}`, and passes the allocation to `0x67FBE`. |
| `0x67FBE(AL=event)` | Increments pending count at data `0xF6FA`; schedules zero-delay callback `0x67FEA` through `0x769A`. |
| `0x67FEA` | Calls the registered handler at data `0xF6FB:0xF6FC`, or frees the event if that pointer is zero; decrements the pending count. |
| `0x7133C(0, 0)` | Selects default handler `0x713AE` and registers it through `0x67E52`. This alone does not initialize all UI state. |
| `0x713AE(AL=event)` | Handles type 2 events, updates last key at data `0xF743`, and dispatches to the existing UI. Owns/frees the event. |
| `0x71476(AL=row, AH=column)` | Converts a 5×5 matrix index into the firmware's key code. |

These were checked using `re/tools/isa/xap.py` on the original binary. The
decompiled C is a navigation aid; it has known missing arguments and incorrect
prototypes.

The key codes below occur in the matrix lookup. Their labels are supported by
the debug-character conversion at `0x9BE20`; they are not measured electrical
matrix wiring:

| Control | Code |
| --- | --- |
| Digits 0 through 9 | `0x64` through `0x6D` |
| Star, hash | `0x79`, `0x78` |
| Up, down | `0x82`, `0x83` |
| Left soft key, right soft key | `0x96`, `0x97` |
| Send, end | `0x8D`, `0x8C` |
| Volume up, volume down | `0xA0`, `0xA1` |
| Power | `0xAA` |

The handset has a two-way navigation rocker, separate soft keys, and a side
convenience key. A distinct four-way rocker or center OK key should not be
invented. The convenience key's code is not established here. The shared
firmware also targets other handset variants.

### Dynamic observation on the existing core

On 2026-11-02 an isolated Zig probe loaded the original binary using
`zig/soc/bc5/Soc` and the existing device models. Cold reset reached the first
scheduler idle call at `0xB774` after **6,442,383 instructions**. The registered
key callback `0xF6FB:0xF6FC` remained **zero**.

The probe invoked original `0x67F04` with power press `(0xAA, 1)`, ran two million
instructions, invoked release `(0xAA, 4)`, and ran another two million. Both
injected calls returned. Original `0x67FEA` dispatched twice and freed the events;
the pending count returned to zero. There were **zero calls to UI handler
`0x713AE` and zero calls to LCD sender `0x68E48`** during those intervals.

This proves execution of the input-event path under the model, not an operating
handset. A visible key event in a host log cannot establish that a firmware menu
responded. Reaching the kernel idle loop is also insufficient evidence of a
completed handset boot.

An additional diagnostic directly invoked application initialization `0x6365E`
after that kernel idle point. This is an out-of-band diagnostic, not an observed
hardware boot sequence. Before the MMU model below was added, original calls
reached `0x63704`, then graphics init `0x68518`, which invoked original panic id 1
because `0x68B88` could not allocate the display buffer.

With the bounded MMU model, original `0x6365E` returns after approximately
5.1 million instructions and emits the 43-byte LCD initialization stream. The
native worker's `call` operation saves/restores CPU registers and the call's
stack area, preserving changes to firmware globals and device state. Calls are
made at the scheduler idle entry `0xB774`; arbitrary interrupted tasks are not
established as safe call sites. This is a software integration boundary, not
electrical keypad injection or a complete hardware power-on model.

### Application startup and persistent storage

Calling only `0x6365E` and `0x8CC5E` schedules the boot animation but omits the
full application initialization at `0x8CC8C`. That incomplete sequence explains
the earlier stable logo and the absence of working menus. The original task 11
at `0x3ADB8` first calls `0x3AF72`, which reads persistent-store keys 1 and
`0x25C`, derives three words, and compares them. Only a successful check leads
to `0x39BBC` and `0x6365E`.

On a fresh simulated handset, original `0x8CC8C` finds no factory marker through
`0xBB06A` and invokes `0xBAC86`. The latter writes the original defaults, including
the required keys, then writes the marker through `0xBB148` and requests a reset
through `0x6F5C0(1)`. Original `0x184D2` arms/kicks the watchdog and waits at
`0x184F0`. The worker reports `firmware-reset-requested` at that original wait;
it does not guess a watchdog duration. `warm_reset` preserves flash and RAM while
resetting the CPU and devices. Retained RAM also permits original reset code to
inspect persistent-store retention records around `0xFCE0` before normal RAM
initialization.

The previous flash profile combined ID `0x0001:0x22CB`, no CFI response, and
uniform erase sectors. Original ID lookup at `0x16C94` selected a fallback
geometry which placed both persistent-store banks (`0x2000..0x2FFF` and
`0x3000..0x3FFF`, physical word addresses) in one erase sector. Instrumented
original boot wrote the first bank header, then erased that same sector while
initializing the second bank. Subsequent default writes therefore lacked a valid
header and were discarded after reset. Preserving the backing array alone could
not repair this.

The replacement profile is explicitly **`inferred-am29lv320db-compatible`**:
ID `0x0001:0x22F9`, 4 MiB, eight 8 KiB bottom sectors and sixty-three 64 KiB
sectors. Its CFI query and erase boundaries agree with the
[AMD Am29LV320D datasheet](https://www.insidegadgets.com/wp-content/uploads/2012/12/AM29LV320D.pdf),
publication 23579, revision C+6, tables 4 and 9–14. The actual handset part has
not been identified. Original CFI parser `0x1A870` discovers this geometry; the
model supplies neither persistent-store records nor patched instructions.
Programming/erase complete immediately; protection and erase suspension are
not modeled.

The verified experimental startup sequence is:

1. Run cold reset to scheduler idle, then call original `0x6365E` if its graphics
   allocation at data `0xF719` is absent.
2. Call original `0x8CC8C`. With empty persistent storage this performs the full
   factory-default path and reaches the original reset request.
3. Perform `warm_reset`, then run to idle again. With the defaults retained,
   original `0x3AF72` succeeds and the original task invokes `0x6365E` itself.
   Do not duplicate that initialization.
4. Call original `0x8CC8C` again, then `0x8CC5E`, and let the original scheduler
   advance the animation and home screen.

On the tested image, cold idle took 6,491,511 instructions. The first `0x8CC8C`
requested reset after 7,185,233 instructions; warm boot reached idle after
11,686,197, emitted 43 LCD bytes naturally, and left `data[0xF719] = 0xCE10`.
Both original checks `0x3AF72` and `0xBB06A` then returned 1. These checks and
factory writes ran as original instructions.

Two startup boundaries remain explicit. `0x6365E` eventually calls
`0x8C518 → 0x8CC2A → 0x8CF3A`, which registers board-identification ADC callback
`0x8CF70`; that callback would select a board variant and invoke `0x8CC8C`.
ADC completion is not modeled. After warm boot, an additional 30 million
instructions left the UI callback unset and produced no further LCD writes.
The power state machine registers `0x8CC5E` as its UI-start callback; its physical
power event is also not modeled. Explicit calls at these two boundaries are
therefore an experimental application bootstrap, not a claim of complete natural
boot. Calling `0x8CC5E` directly does not advance the original power state from
1 through `0x10` and `0x20`; complete power-state behavior and every navigation
path remain unverified. No link-ready callback such as `0x8CA1E` is injected.

### Measured original UI and key response

After the complete sequence above and 150 million scheduler instructions, with
no keys injected, original LCD writes show the Iridium home screen with
**Searching for Iridium...**, **Acquiring time...**, and **Menu / Help** soft-key
labels. The remaining logo belongs to this searching screen; it does not mean
the animation is still running. All controller RAM bytes were initialized by
original writes. The run had no native fault, MMU error, or lost capture bytes.

An original left-soft-key press and release through
`0x67F04(AL=0x96, AH=1)` and `0x67F04(AL=0x96, AH=4)`, followed by two million
scheduler instructions, opens the actual firmware menu: My Phonebook, SIM
Phonebook, Messages, Voicemail, Data Modem, and Call History. Down, Select, and
Back navigate into SIM Phonebook and return through original UI handlers. This
establishes working home/menu interaction at the software key boundary, not all
menus, handset registration, or satellite connectivity. The animation advances
without keys and must not be presented as evidence of a key response.

## Buffer MMU model

The original allocation request `0x39ED6(&data[0xF719], 4096)` successfully
selected class `0x8C` through `0x3A144`, allocated ordinary RAM for the descriptor
and page table, and obtained handle 4 through `0xF63C`. It then failed the free
page check at `0xFC62`: `0xFA5A` returns `max(0, signed(data[0xF102] - MMIO[0xFFCF]))`.
The old latch model supplied `0` at `0xFFCF`; the end pointer at `0xF102` was
`0xA15A`, so the signed calculation returned zero free pages.

The new `native/mmu.zig` models actual independent buffers and page allocation;
it does not replace the allocation routine or force its result. These structural
facts are established by instructions and initialized memory:

| Property | Evidence |
| --- | --- |
| Physical shared RAM is `0x5500` bytes at word address `0xA000` | `0x3000` calls `0xF58C(0x5500, 0x5A)`; the reset RAM region ends at `0xCA80`. |
| Page size is 128 bytes, hence 64 data words | `0x249CA` returns shift 7; `0xF58C` uses this to build the free page list. |
| 90 handle slots, descriptor at `0xA000 + 2*handle` | `0xF58C` initializes the table; `0xF63C` finds and fills an unused descriptor. |
| Descriptor bits 15..13 encode `log2(page-table words)` | `0xF63C`, `0xF758`, and `0xF77E`. Each word contains two page ids. |
| Descriptor low 13 bits locate the page table relative to `0xA000` | `0xF77E`; multiply the offset by two when `0xFF97` bit 11 is set. |
| Next descriptor word supplies a byte offset; capacity is `128 * 2^(size+1)` bytes | `0xF882` and `0xF8C8`. |
| Even page id is the low byte of the table word, odd page id is the high byte | Explicit branches in `0xF77E`, `0xF7FE..0xF828`. |
| CPU byte windows begin at `0x4000` and `0x6000`, selected by `0x6E` and `0x6F` | `0xF83E`, `0xF856`, `0xF872`, `0xF87C`. |
| Free-list start is written to `0x70`, end stored at `0xF102` | `0xF58C`; observed list starts `0xA0B6`, ends `0xA15A`, and contains page ids 6 through 169. |
| Returning a page writes its id to `0x71` | `0xFAE0`. Trimming a live buffer first writes its page-table byte index to `0xFD05` (`0xF77E`). |

The model exposes the assumption name **`inferred-bc5-buffer-mmu`**. The following
hardware details remain hypotheses: `0xFFCF` as the current allocation cursor;
lazy allocation on writes; low-byte-first placement within physical RAM words;
returning pages through a stack at that cursor; and clearing the pending
`0xFD05` page-table entry on the following free command. The instruction sequences
constrain these choices but do not independently prove the hardware behavior.

Unallocated reads, invalid selectors/descriptors, malformed or exhausted free
lists, and inconsistent frees fail explicitly. In particular, returning a
constant amount of free memory would conceal the defect while leaving every
buffer aliased; the model instead assigns and preserves real per-buffer pages.
Focused tests cover independent handles, shared window views, page boundaries,
offset wrapping, release/reuse, bounds, malformed state, and exhaustion.

## Display boundary

The original controller initialization is `0x63396`, reached via veneer
`0x6114C`. Its sender is **`0x68E48(AL=word-buffer, AH=count)`**, taking the low
byte of each word. `0x68F24` sends data in chunks of at most 128 bytes, preceding
each chunk with the command pair `E8, count-1`; observing the common sender
therefore captures command and data traffic in order. The serial busy wait at
`0x39354` polls data `0xFE95` bit 0. The existing generic BC5 model does not
implement this serial engine or its buffer-transfer completion.

`zig/soc/bc5/tests.zig` contains a known-answer test of `0x63396`: 43 bytes in
batches of 14, 2, 1, 7, 19, with waits of 200, 200, 10, 200, 10 ms. This test
intercepts the sender, delays, and bus locks. It proves the init routine's output
under those substitutions, not actual power-on display behavior.

`iridium/lcd.py` implements a bounded three-wire decoder from the manufacturer
[Sitronix ST7541 v1.9 datasheet](https://www.displayfuture.com/Display/datasheet/controller/ST7541.pdf)
(2007-09-03), pages 1, 20, and 32–50. `E8` precedes a count-minus-one byte and
1–256 data bytes. Two successive bytes address one column; the even byte is the
high gray bitplane and bit zero addresses the page's first row. Column bytes
wrap within a page. Command fragments persist across capture batches.

The decoder handles addressing, output directions, scrolling, display/reverse/
entire-display states, sleep and software reset. Known analog configuration
commands are recorded without claiming calibrated luminance or electrical
timing. Unknown commands, the icon row, partial display duty, and nonzero initial
COM fail explicitly. Pixels whose two planes have not been written retain a
separate `known` mask: power-on DDRAM is undefined. The generic decoder defaults
to **SEG0 at left, COM0 at top**. The handset profile places **SEG127 at left**:
the original `A1` command then renders the same readable logo as its firmware
resource. The previous SEG0-left presentation mirrored the text, matching the
reported display defect. This panel mapping is inferred from the original asset
and visible text, not an electrical pin measurement. Firmware ADC direction
changes still reverse the panel image; the mapping applies equally to pixels
and their known mask. Resource previews retain their own bitmap coordinates.

Native observation reads the sender's word buffer through the inferred MMU
when appropriate, while allowing the original sender instructions to execute.
Its 65,536-byte capture buffer reports lost bytes explicitly; a decoder must
stop after any loss. This observes the software driver's intended output,
not an electrically validated serial transfer. No single contiguous physical
framebuffer address is established. In particular, **`0xA0F8E` is a Unicode
mirror lookup, not the display driver**.

## Original resources

`re/tools/bc5-data/bc5img.py` and `bitmaps_dump.py` establish:

- Constant-data window begins at image byte `0x3096BE`.
- Data words `0x2BD6:0x2BD7` hold the filesystem directory address; subtract
  `0x800C` and multiply by two to obtain its image byte offset.
- There are 140 five-word slots: file id, address high/low, size high/low.
  The supplied image has 47 used files.
- Bitmap words begin `{3, width, height, frame_count}`, followed by page-major
  frames: `ceil(height/8) * width` words each. Low/high bytes are two bitplanes;
  bit zero is the top pixel of a page. Gray-plane significance is not verified.
- File 19 is a **128×128, 98-frame** original animation. Its pixels are
  monochrome. Displaying this asset independently is a resource preview, not a
  screen captured from running firmware.
- Stream-oriented files emit the high byte of each stored word first.

`iridium/assets.py` validates the pointers, lengths, ids, and bitmap dimensions
before decoding. Its synthetic tests exercise page layout, both planes, frame
selection, odd stream lengths, malformed files, and PNG output. Parsing the
supplied image recovered the 47 files and the animation dimensions above.

## Other established devices and missing behavior

From `re/maps/bc5-arch.md`, with model code in `zig/soc/bc5/soc.zig`:

- Clock: data `0xFFB4:0xFFB5`, high/low. The existing deterministic model uses
  one microsecond per eight instructions; this is not a measured CPU rate.
- Compare A: `0x41:0x42`, period `0x48:0x49`; compare B: `0x43:0x44`;
  compare C: `0x4C`. Enable bits 1/2/3 are in `0xFF94`.
- Interrupt global enable: `0xFF95` bit 1. Source: `0xFFC3`. End of interrupt:
  write `(0xFFC4 | 0x800)` to `0x67`. The hardware entry-frame layout remains
  a documented XAP hypothesis.
- Flash page: data `0x8000..0x8FFF`, selected by register `0x73`. The model lays
  image word zero at physical word `0x1800C`.
- Chip revision: boot requires `0xFF7D >= 0x5011`; the model supplies `0x5011`.
- Most other BC5 registers are latches. General UART, USB, audio, and keypad
  peripherals are not complete hardware models.

From `re/maps/avr-full.md` and `zig/soc/avr/devices.zig`:

- The AVR is an ATmega164P SPI-slave I/O expander, 1-Wire master, and DPL router.
  Its firmware does **not** scan the keypad matrix.
- DPL frames are `channel, length, payload, XOR checksum, 0x03`; length zero
  means 256 bytes. ACK=`0x06`, NAK=`0x15`. The AVR forwards the checksum without
  validating it; host endpoint validation must not be mistaken for AVR behavior.
- Channel 7 is Trxctrl; channels 4/5/7/0x87 route between SPI and USART0.
  The association of USART0 with the transceiver is strongly inferred from
  routing, not established by a board capture.
- Existing device APIs are `uartPush`, `uartPop`, `spiTransfer`, `setPinsIn`, and
  `owConnect`. SPI replies are pipelined and need CPU time between transfers.

From `re/maps/trx-arch.md` and `zig/soc/trx/devices.zig`:

- The supplied SPARC telephony image starts at `0x10000`. The boot block
  `0x000000..0x00FFFF` is **not shipped**. An application-entry boot bypasses it.
- The modem and audio DSPs use HPI blocks `0x80000C00`/`0x80000D00`, with shared
  memory windows around `0xA0000000..0xD0000000`; existing models provide memory
  and latches, not DSP execution.
- L1 RF/frame sequencer block is `0x80001000`; TDMA counter is `0x80000A10`.
  RF, satellite acquisition, provisioning, network authentication, voice codec,
  and complete satellite protocol behavior are not established by these stubs.

A deterministic local satellite scenario model can exercise an explicitly
defined interface. It cannot be described as full satellite/modem emulation
until that interface is connected to executing firmware and its behavior is
validated.
