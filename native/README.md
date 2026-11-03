# Native firmware worker

`iridium-core` executes original machine instructions using the vendored XAP2, AVR and SPARC interpreters. It contains no firmware or translated handset application code. See [PROVENANCE.md](PROVENANCE.md) for origin and fidelity qualifications.

Build with Zig 0.17.0: `zig build -j2`. Run one image in each process:

```
zig-out/bin/iridium-core --image bc5 --firmware /path/to/bc5_main.bin
```

Images are `bc5`, `avr`, `trx` and `ptt`. Inputs are raw payload files in the HT25003 layout, including same-layout patched files. BC5 accepts 0x310FBA firmware bytes or the extracted 0x310FBE file with its trailing container CRC; that CRC is excluded from the mapped constant window. The Python host handles containers and hashes.

The worker emits an initial JSON state, then one response for each newline-delimited JSON request. EOF exits. Request errors are `{ "error": "...", "fatal": false }`; loading and stream errors use `fatal: true` and exit code 2. An interpreter trap is a non-null `halt` in the state. It stays stopped until reset.

| Request | Response / effect |
|---|---|
| `{"op":"run","steps":100000}` | Advance at most 10,000,000 interpreter steps; return state. AVR steps can include IRQ entry or idle cycles. |
| `{"op":"idle","steps":10000000}` | BC5 only: execute at least one step, then stop at the known scheduler idle boundary 0xB774. Check `at_idle` before a debugger injection; budget exhaustion can return `at_idle:false`. |
| `{"op":"state"}` | Return state without advancing guest time. |
| `{"op":"reset"}` | Reset CPU/RAM/devices and discard guest changes to flash/EEPROM. Reload the original input in memory. |
| `{"op":"warm_reset"}` | BC5 only: reset CPU/device state while retaining RAM and programmed flash. Original reset instructions validate and initialize retained memory. Watchdog timing is not simulated. |
| `{"op":"read","address":40960,"count":16}` | Return `{address,unit_bits,values}` from raw backing memory, without side effects. BC5 units are 16-bit words; AVR/SPARC units are bytes. Device and CPU register state is not reflected in this raw-memory view. |
| `{"op":"write","address":40960,"values":[123]}` | Debugger RAM/scratch write. Validate all values/ranges first; ROM, MMIO and CPU aliases are rejected. Return state. |
| `{"op":"call","entry":476,"al":40960,"ah":123,"stack":[1],"steps":10000}` | BC5-only explicit debugger function probe at a byte address. Execute the original routine with AL/AH/stack arguments. Return state with `last_call`. |
| `{"op":"pins","port":0,"value":255}` | AVR external input levels, ports 0–3. Return state. |
| `{"op":"uart_rx","port":0,"value":65}` | Queue one AVR UART input byte, port 0 or 1. Return state, or `UartFull`. |
| `{"op":"uart_tx","port":0}` | Pop a transmitted AVR byte; return `{value: byte_or_null, dropped: cumulative_lost_bytes}`. |
| `{"op":"spi","value":0}` | Clock one AVR slave transfer; return `{value: byte_or_null}`. |

Memory requests are capped at 4096 units and input lines at 64 KiB. CPU fuel bounds block-copy work and XAP2 instruction-word decoding independently of the instruction count. Access logs are flushed every 1024 steps. SPARC register latches are capped at 65,536 entries. These are host resource limits, reported as stops where relevant.

AVR watchdog reset requests stop execution with `halt: "firmware-reset-requested"` until an explicit `reset`. The host does not perform an automatic watchdog reboot. Each AVR UART output capture holds 255 bytes; additional completed transmissions increment that port's dropped-byte count. State reports both counts as `uart_tx_dropped: [port0, port1]` (`null` for other processors). Reading captured bytes does not clear these counts; `reset` clears them.

The state includes `image`, `pc`, `program_pc`, `steps`, `at_idle`, `halt`, `registers`, `register_names`, `flags`, `sp`, `cycles`, `milestones`, `unclassified_accesses`, `lcd_bytes`, `lcd_dropped`, `last_call`, `mmu_assumption`, `flash_assumption`, `model_error` and `model`. `pc` uses BC5 registry byte offsets, AVR byte offsets or SPARC virtual addresses; `program_pc` retains each CPU's native addressing. `cycles` is implemented for AVR only. Milestones mark entries at the known profile addresses; they do not certify successful hardware initialization. The BC5 panic entry at 0x70A0 is a diagnostic breakpoint that stops before executing that routine. The known watchdog wait loop at 0x184F0 is reported as `firmware-reset-requested` when its watchdog enable registers match the original reset sequence; the host can then issue `warm_reset` without inventing watchdog timing.

`lcd_bytes` contains numeric low bytes observed at the original firmware serial sender 0x68E48; no sender instructions are skipped. This is a software-boundary observation, not proof that a hardware serial transfer completed. The 65,536-byte telemetry buffer is drained by state responses; `lcd_dropped` reports overflow. A missing stream produces no fabricated display.

A function probe temporarily uses Y=0xFCC0, saves/restores the known stack range 0xF960–0xFCDF and caller CPU registers, and retains elapsed time and all other memory/device effects. It is intended for known subroutines while paused. It is not a full snapshot transaction or an emulated hardware interrupt. Nonreturning probes, traps or stack-guard changes halt the session; partial global/device effects remain until reset. Stack-local returned pointers do not remain valid. `last_call` records `returned`, `al`, `ah`, executed `steps`, and the final probe `pc`/`program_pc` before restoring the paused CPU. Failed probes also retain `last_call.stopped` with the stopped registers and up to 64 stack words. Explicit probes allow up to 100,000,000 steps because original display initialization alone requires over 5 million instructions.

Tests:

```
zig build test -j2
python3 native/test_protocol.py
IRIDIUM_TEST_FIRMWARE=/path/to/firmware python3 native/test_protocol.py
```

The inferred buffer MMU is identified in `mmu_assumption`. Invalid handles/pages and unsupported reads stop execution with a precise `model_error`; unknown registers outside this model retain the upstream latch behavior. Tests explicitly calling original initialization at 0x6365E produce the known 43-byte LCD command stream. This forced initialization is distinct from natural boot.

The flash profile is an inferred Am29LV320DB-compatible 4 MiB device, with JEDEC ID `01:22F9`, CFI query data and matching bottom-sector geometry from [AMD's datasheet](https://www.insidegadgets.com/wp-content/uploads/2012/12/AM29LV320D.pdf). It is not a measured identification of the physical handset. Programming and erase complete immediately; erase suspend and protection changes remain unmodelled. Original firmware discovers its geometry and writes factory settings through normal flash commands. A regression executes the complete original factory-default path, observes the firmware's reset request, warm reboots, and checks that original startup validators accept the retained settings. A fresh reset discards them.

The first two commands require no original firmware. The last adds real-image boot checks and verifies that CRC stripping leaves BC5 execution unchanged. Original-image tests skip when the environment variable is unset. Tests include independent synthetic guest instructions, mutation-sensitive execution, malformed IPC recovery, bounded requests, atomic RAM writes and probe context/stack restoration.
