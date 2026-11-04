# Native firmware worker

`iridium-core` executes original machine instructions using the vendored XAP2, AVR and SPARC interpreters. It contains no firmware or translated handset application code. See [PROVENANCE.md](PROVENANCE.md) for origin and fidelity qualifications.

Build with Zig 0.17.0: `zig build -j2`. Run one image in each process:

```
zig-out/bin/iridium-core --image bc5 --firmware /path/to/bc5_main.bin
zig-out/bin/iridium-core --model 9575 --image bc5 --firmware firmware/9575/bc5_main.bin
```

Images are `bc5`, `avr`, `trx` and `ptt`. The default model `9555` accepts the HT25003 layout; `--model 9575` selects HL25003. Inputs are raw payload files, including same-layout patches. BC5 accepts 0x310FBA firmware bytes for HT25003 or 0x36BB22 for HL25003, optionally with four trailing container-CRC bytes. The CRC is excluded from the mapped constant window. The Python host handles containers and hashes. Image length must match the selected model; the worker does not infer layout changes in same-sized patches.

HL25003 uses its own BC5 constant window and executable extent, plus an inferred
ATmega1280-compatible profile: SRAM 0x200–0x21FF, four USARTs, extended GPIO,
timers 0–5 and 4 KiB EEPROM. AVR accepts upgrade payloads or complete flash images
(16 KiB 9555,128 KiB 9575). The exact fitted part is unverified. Both modem images
are byte-identical across these releases. Current contracts and original-driver
evidence are in [inferred hardware](../docs/inferred-hardware.md).

The worker emits an initial JSON state, then one response for each newline-delimited JSON request. EOF exits. Request errors are `{ "error": "...", "fatal": false }`; loading and stream errors use `fatal: true` and exit code 2. An interpreter trap is a non-null `halt` in the state. It stays stopped until reset.

| Request | Response / effect |
|---|---|
| `{"op":"run","steps":100000}` | Advance at most 10,000,000 interpreter steps; return state. AVR steps can include IRQ entry or idle cycles. |
| `{"op":"idle","steps":10000000}` | BC5 only: execute at least one step, then stop at the known scheduler idle boundary 0xB774. Check `at_idle` before a debugger injection; budget exhaustion can return `at_idle:false`. |
| `{"op":"state"}` | Return state without advancing guest time. |
| `{"op":"reset"}` | Reset CPU/RAM/devices and discard guest changes to flash/EEPROM. Reload the original input in memory. |
| `{"op":"warm_reset"}` | BC5/AVR: reset CPU/devices while retaining programmed flash and RAM; AVR also retains EEPROM, fuses and external fixtures, and records an external reset in MCUSR. Guest startup initializes its own memory. |
| `{"op":"reset_clock","cycles":4096}` | AVR only: advance pending flash/EEPROM programming while the board holds reset. Execute no instructions and leave other peripheral clocks stopped. Accept 1–10,000,000 cycles. |
| `{"op":"read","address":40960,"count":16}` | Return `{address,unit_bits,values}` from raw backing memory, without side effects. BC5 units are 16-bit words; AVR/SPARC units are bytes. Device and CPU register state is not reflected in this raw-memory view. |
| `{"op":"write","address":40960,"values":[123]}` | Debugger RAM/scratch write. Validate all values/ranges first; ROM, MMIO and CPU aliases are rejected. Return state. |
| `{"op":"call","entry":476,"al":40960,"ah":123,"stack":[1],"steps":10000}` | BC5-only explicit debugger function probe at a byte address. Execute the original routine with AL/AH/stack arguments. Return state with `last_call`. |
| `{"op":"pins","port":0,"value":255}` | AVR external input levels: 9555 ports 0–3 (A–D), 9575 ports 0–10 (A,B,C,D,E,F,G,H,J,K,L). Return state. |
| `{"op":"uart_rx","port":0,"value":65}` | Queue one AVR UART input byte: 9555 ports 0–1, 9575 ports 0–3. Return state, or `UartFull`. |
| `{"op":"uart_tx","port":0}` | Pop a transmitted AVR byte on a model-supported port; return `{value: byte_or_null, dropped: cumulative_lost_bytes}`. |
| `{"op":"spi","value":0}` | Clock one AVR slave transfer; return `{value: byte_or_null}`. |

Additional operations include strict `hardware` mode, bounded `trace`, BC5
electrical `key`/`pins`, coupled `serial`, AVR `pin_state`/`adc`/`comparator`/
`async_clock`/`twi`/`fuses`/`program_read`, SPARC external `irq`, and batched
`uart_io` on AVR or modem ports. See the [protocol examples](../docs/inferred-hardware.md).
`hardware.enabled` selects the BC5 IRQ/bank/ADC model and performs a warm reset
when changed; normal execution enables it by default.
Probe stack placement reserves the interrupt frame and all supplied arguments.
Serial MMU faults end suspended probes and restore their saved CPU/stack;
`last_call.stopped` retains the failing function's state.

Memory requests are capped at 4096 units and input lines at 64 KiB. CPU fuel bounds block-copy work and XAP2 instruction-word decoding independently of the instruction count. Access logs are flushed every 1024 steps. SPARC register latches are capped at 65,536 entries. These are host resource limits, reported as stops where relevant.

Watchdog reset requests stop execution with `halt: "firmware-reset-requested"`
until an explicit reset. Each UART output capture holds 255 bytes; overflow
increments its cumulative loss count without changing guest TX status.
`uart_tx_dropped` has two counters for 9555 AVR and four for 9575 AVR or either
modem. Reading capture data preserves the counts; reset clears them.

The state includes `image`, `handset`, `pc`, `program_pc`, `steps`, `at_idle`, `halt`, `registers`, `register_names`, `flags`, `sp`, `cycles`, `milestones`, `unclassified_accesses`, `lcd_bytes`, `lcd_dropped`, `last_call`, `mmu_assumption`, `flash_assumption`, `avr_assumption`, `model_error` and `model`. `pc` uses BC5 registry byte offsets, AVR byte offsets or SPARC virtual addresses; `program_pc` retains each CPU's native addressing. `cycles` is implemented for AVR only. Milestones mark entries at the known profile addresses; they do not certify successful hardware initialization. The BC5 panic entry at 0x70A0 is a diagnostic breakpoint that stops before executing that routine. The known watchdog wait loop at 0x184F0 is reported as `firmware-reset-requested` when its watchdog enable registers match the original reset sequence; the host can then issue `warm_reset` without inventing watchdog timing.

`lcd_bytes` contains completed MMU-backed serial transfers from the LCD pin
configuration. The sender PC is not intercepted. The 65536-byte capture drains
through state responses; `lcd_dropped` reports loss. AVR transfers use the same
serial engine, with FE95 busy until the connected processor clocks and replies.
SPI handshake, attention and reset follow actual guest GPIO behavior.
BC5 state and `serial` expose the lifetime `gpio.reset_count`; recreated links
baseline it before execution. Modem traffic into a held-reset AVR is discarded.
External AVR reset retains active flash and EEPROM programming; both continue
while board reset is held, including during function probes. The 9555 reports
`undefined_spm_buffer` if a page write uses data invalidated by an EEPROM write;
RWWSRE followed by reloading the temporary buffer restores defined behavior.

A function probe chooses an IRQ-safe Y no higher than 0xFCC0, preserving the
35-word separation from the supervisor stack in banked mode. It saves/restores
0xF960–0xFCDF and the paused CPU at final return/failure, retaining global memory,
device and elapsed-time effects. Stack-local returned pointers expire.
`last_call` reports `returned`, `pending`, AL/AH, steps and the probe PC.
Reaching the unmapped ABI return sentinel at depth zero completes a probe even
on its final allowed instruction, without another instruction or peripheral tick.
Coupled Session probes and idle waits synchronize links after every chunk,
including the final response, before servicing peripherals. Board service accounts for the actual
executed instructions; service and extra serial waiting share the request's
instruction-sized peripheral budget. Held reset advances programming only.
Failed probes retain stopped registers and up to 64 stack words. A serial wait
or explicit `quantum` can yield a live probe; `call_resume` accepts the same
per-request quantum and continues within its original cumulative budget and bus
fuel. Ordinary run/idle/write and
a second call are rejected while pending. Reset discards it. Traps, nonreturning
probes and stack-guard changes halt explicitly; this is not a snapshot transaction.

Tests:

```
zig build test -j2
python3 native/test_protocol.py
python3 native/test_trx_hardware.py
IRIDIUM_TEST_FIRMWARE=/path/to/firmware python3 native/test_protocol.py
IRIDIUM_TEST_9575_FIRMWARE=firmware/9575 python3 native/test_protocol.py
```

The inferred buffer MMU is identified in `mmu_assumption`. Invalid handles/pages
stop with `model_error`. Strict mode also rejects unknown-register fallbacks and
unclassified data-bus accesses; exploratory mode retains their latch/open-bus
hypotheses. Original initialization at 0x6365E still produces its 43-byte LCD stream.
Natural warm-boot tests now exercise ADC completion and application setup too.

The flash profile is an inferred Am29LV320DB-compatible 4 MiB device, with JEDEC ID `01:22F9`, CFI query data and matching bottom-sector geometry from [AMD's datasheet](https://www.insidegadgets.com/wp-content/uploads/2012/12/AM29LV320D.pdf). It is not a measured identification of the physical handset. Programming and erase complete immediately; erase suspend and protection changes remain unmodelled. Original firmware discovers its geometry and writes factory settings through normal flash commands. A regression executes the complete original factory-default path, observes the firmware's reset request, warm reboots, and checks that original startup validators accept the retained settings. A fresh reset discards them.

The first two commands require no original firmware. The last adds real-image boot checks and verifies that CRC stripping leaves BC5 execution unchanged. Original-image tests skip when the environment variable is unset. Tests include independent synthetic guest instructions, mutation-sensitive execution, malformed IPC recovery, bounded requests, atomic RAM writes and probe context/stack restoration.
