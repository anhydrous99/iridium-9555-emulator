# Architecture and debugger API

`iridium/firmware.py` validates source bytes and strips container metadata.
`iridium/profiles.py` records the two supported builds' layouts and software
entry points; the loaded image selects the handset throughout the host and UI.
`iridium/engine.py` owns a native worker and its bounded JSON-lines transport.
`iridium/session.py` serializes debugger actions, input events and satellite
scenarios. `iridium/board.py` connects BC5 serial DMA to the executing AVR SPI
slave and AVR USART0 to the selected modem's UART1. `iridium/server.py` exposes that session
on all IPv4 interfaces by default (`--host 127.0.0.1` restricts access to loopback).
`ui/` renders state without synthesizing firmware menus.
While running it polls 50 ms after each completed response, with only one state
request in flight, so intermediate LCD animation frames can be displayed.
Paused sessions retain the slower 1,250 ms polling interval.

`native/main.zig` adapts the original CPU/SoC implementations under
`native/vendor/`. Each processor lives in a separate OS process because the
inherited models use process-global state. The host schedules 4096-instruction
quanta, reducing them to 128 while SPI transfers need service. This is a
deterministic digital board schedule, not measured physical clock ratios.
The scenario clock remains separate from the firmware transports.

## Input and execution boundaries

The supported profiles are HT25003 for 9555 and HL25003 for 9575 Extreme.
DFU layouts and USB product IDs must both match. Raw images are selected by
their exact profile lengths; shared modem binaries inherit the selected model.
BC5 program addresses
are word addresses based at `0x800C`; the API exposes both `program_pc` and the
image-byte `pc`. BC5 data-memory addresses and `read`/`write` values are words.
AVR/SPARC memory operations use bytes; their displayed PCs use byte addresses.
SPARC instruction fetches use big-endian data. BC5/AVR program words are little
endian.

Native `run` accepts at most ten million instructions per request; `call` accepts
at most one hundred million for bounded application initialization. A separate
bus-access budget bounds pathological block copies. Device logs are drained
regularly, with cumulative unclassified-access counts. Unknown hardware reads
may use inherited latches/defaults; inspect the model qualifications before
interpreting firmware results. Unsupported instructions and known panic entry
stop execution rather than producing a successful phone state.

Both the loader and native board profile check input bounds. Firmware patches
are executed from the actual supplied bytes. Original firmware is not writable
through the API. RAM changes and emulated flash programming exist only in the
worker. A cold `reset` reloads the source image; BC5 `warm_reset` retains RAM and
flash programming while resetting CPU/device state. Process exit discards both.

## Native protocol

After `zig build -j2`:

```sh
zig-out/bin/iridium-core --image bc5 --firmware /path/to/bc5_main.bin
zig-out/bin/iridium-core --model 9575 --image bc5 --firmware firmware/9575/bc5_main.bin
```

The worker emits startup state, then one JSON object per newline-terminated
request. It reads raw extracted payloads; use `./run` for DFU validation.
Available images are `bc5`, `avr`, `trx`, and `ptt`.

```json
{"op":"run","steps":7000000}
{"op":"state"}
{"op":"read","address":63840,"count":1}
{"op":"write","address":41216,"values":[1,2,3]}
{"op":"call","entry":476,"al":41216,"ah":48879,"stack":[3],"steps":10000}
{"op":"warm_reset"}
{"op":"reset"}
```

The `call` example runs original BC5 `memset` at byte `0x1DC`, filling three
words at `0xA100` with `0xBEEF`. Probes restore the paused CPU registers and stack
on return, retaining global memory/device effects. They are debugger experiments,
not a substitute for hardware interrupts or safe reentrant firmware execution.
Calling arbitrary functions in the middle of a firmware transaction can corrupt
guest state; reset starts a fresh experiment. A probe that does not return is
reported as a halt. `last_call.stopped` preserves the stopped registers and up
to 64 stack words before the paused CPU state is restored, including on a probe
stack-guard failure. The registers are ordered AH, AL, X, Y, XH, UX, UY, flags;
`stack_address` and `stack_count` identify the valid part of `stack_words`.

BC5 `warm_reset` resets CPU, device state and observation counters while
retaining RAM and emulated flash contents. Original reset code validates retained
persistent-store records before clearing RAM. This is an explicit host operation;
watchdog timing is not modeled. The ordinary `reset` also clears RAM and restores
flash from the supplied firmware, returning the worker to a fresh experiment.
AVR `warm_reset` retains program/EEPROM, fuses, SRAM and external digital/analog
fixtures, reseeds edge detectors and records EXTRF while retaining sticky reset
flags. Its original reset code executes from the configured reset vector. A cold
AVR reset restores the supplied program and clears the experiment's device state.

The Python transport applies one 30-second deadline to sending a request and
receiving its reply. Timeouts, disconnects, malformed replies and oversized replies
close the worker so a later command cannot consume an earlier command's response.
Explicit native request errors with `fatal: false` leave the worker available.

The worker reports `halt: "firmware-reset-requested"` when the original reset
routine reaches byte `0x184F0` with its watchdog armed (`0x76 == 1` and bit 0 of
`0xFF91` set). This records an original firmware reset request at a known boundary;
it does not infer watchdog timing. The initialization scenario handles this stop
with an explicit warm reset; other occurrences remain visible as debugger halts.

The AVR worker reports the same halt when its watchdog model requests a reset.
It stays stopped until an explicit `reset`; no automatic AVR reboot is performed.

`read` observes raw memory without consuming MMIO events. `write` accepts RAM
only, checks all values before mutation and rejects ROM/MMIO writes. Neither
operation changes the original file. The AVR also exposes device stimuli:

```json
{"op":"pins","port":0,"value":255}
{"op":"uart_rx","port":0,"value":65}
{"op":"run","steps":1000}
{"op":"uart_tx","port":0}
{"op":"spi","value":0}
```

UART queues and SPI replies require intervening CPU execution. The coupled board wires AVR SPI to BC5 and USART0 to the selected modem.
`uart_io`, `pin_state`, `serial`, `adc`, `comparator`, `async_clock`, `twi`,
`fuses` and `program_read` expose explicit device stimuli/observations; see the
[inferred hardware protocol](inferred-hardware.md).
Each AVR UART output capture holds 255 bytes. Overflow increments cumulative
per-port `uart_tx_dropped` counts in processor state; `uart_tx` also returns the
selected port's `dropped` count. Draining the queue preserves the counts, and
reset clears them. The browser displays any capture loss in the AVR row.

BC5 state includes `lcd_bytes`: bytes transferred through the serial-controller
model from the original TX MMU handle (`0xFE94`),
with a bounded buffer and `lcd_dropped` counter. Observation does not skip its
instructions. `iridium/lcd.py` decodes this stream using ST7541 command framing,
tracks which DDRAM bytes have actually been written and exposes nominal logical
pixels. Unknown commands latch an error; capture overflow invalidates the screen
until reset. The generic decoder exposes SEG0 at the left. The handset session
uses `ST7541(segment_zero_on_right=True)` to place SEG127 at the left, matching
the original bitmap and readable Iridium lettering. Firmware ADC/COM commands
still determine pixel and known-mask direction; the browser does not flip the
projected image or asset previews. Electrical panel wiring and analog luminance
remain unverified.

The native BC5 `idle` operation executes at least one instruction, then stops at
scheduler byte `0xB774`, within its requested budget. `at_idle` indicates whether
that boundary was reached. The host uses it before injecting functions, avoiding
interruption in the middle of a firmware allocation transaction. It allows up to
three consecutive ten-million-instruction requests to reach idle during a warm
boot, stopping immediately if the worker reports a halt.

`initialize_ui` requires BC5 and AVR images. It starts from a warm reset, reaches
scheduler idle and invokes original device/factory setup only to provision the
settings absent from the upgrade package. The original code writes its own
persistent-store records. The host then warm resets with the active-low AVR
power button released HIGH. Guest IRQs, ADC completion, GRev classification,
application setup and power polling perform the rest of startup. No application
start, charging-state or animation-completion callback is injected after reset.
AIO0=640 is an explicit virtual GRev board-ID fixture.
Power-on is rejected while a client still owns the power button; release the
button before starting a new boot. Reset attempts every loaded processor before
reporting a worker failure, so surviving processors release their contacts.

The AVR executes every SPI command and produces the handshake/attention GPIO
levels. The host services both processors during bounded probes; `last_call.pending`
and `call_resume` preserve a live probe while an external peripheral needs CPU
time. The original instruction budget and bus fuel remain bounded across all
continuations. A second call, ordinary run/idle or debugger write is rejected
while a probe is pending; reset cancels it.

Keys change the emulated 5×5 contacts. Guest row-latch writes and column reads
feed GPIO IRQ15, debounce, scanning and the original key mapper. UI press/release
requests include 150,000 instructions for contact settling; native `key` plus
explicit `run` requests permit timing-sensitive tests. Power drives PC0 on 9555
or PJ3 on 9575 LOW while pressed, including the original 500ms shutdown hold.
The 9575 SOS wire is unestablished and retains the original software-input
boundary. The convenience key, location screens and emergency countdown execute
in guest code. No GPS coordinates or emergency-service responses are fabricated.

The UI's initialized state clears when original firmware enters shutdown, so a
new power-on experiment can warm boot retained settings. Failed initialization
requires reset before retrying. See [inferred hardware](inferred-hardware.md)
for the register contracts, assumptions and independent/original-image tests.

## HTTP API

`GET /api/state` returns image hashes, processors, input state, scenario state,
bounded events, an optional original asset preview and explicit fidelity limits.
Its `handset` object reports `model`, `name`, `firmware_version` (profile build)
and available physical `keys`.
Mutations use `POST` with `Content-Type: application/json`:

| Endpoint | Body |
| --- | --- |
| `/api/control` | `{"action":"run"}`; actions also `pause`, `step`, `reset`, `initialize_ui`; step accepts `steps` |
| `/api/key` | `{"key":"1","pressed":true}`; recorded event, response says whether delivered |
| `/api/probe` | `{"image":"bc5","operation":"read","address":63840,"count":1}`; execution must be paused |
| `/api/satellite` | `{"action":"configure","visible":true,"signal":5,"latency_ms":800}` |
| `/api/satellite` | `{"action":"register"}` then `{"action":"advance","milliseconds":1000}` |
| `/api/satellite` | `{"action":"incoming_call","number":"+881612345678"}`; also `answer`, `hangup` |
| `/api/satellite` | `{"action":"incoming_sms","number":"123","text":"Test"}` |

Browser key requests add `client_id`, `sequence` and `epoch`, for example
`{"key":"1","pressed":true,"client_id":"page-abc","sequence":1,"epoch":0}`.
Each page generates a unique ID and increasing sequence; each queued event
captures `key_epoch` from state. The host compares sequences per client and key,
including releases that arrive before their press. Only the first owner presses
the guest key and only the last owner's release releases it. State, key, control
and firmware responses expose `key_epoch`. Reset, loading BC5 or replacing AVR on
a board with BC5 advances the epoch, clears owners and cancels older requests.
Modem image loads preserve keypad state. A page cancels queued events and local held sources when the epoch advances,
without retrying stale events. Navigation cancels unsent events and immediately
sends keepalive releases with newer sequences and the submitted presses' epochs.
Client IDs contain 1–64 ASCII letters, digits, underscores or hyphens; sequences
are integers from 1 to 2^53−1 and epochs from 0 to 2^53−1. The host retains at most
128 clients until reset (or BC5 load), returning an explicit error at that limit.

Debugger callers may instead send the legacy `generation` from `key_generations`.
A legacy release advances that key's generation even when already up, cancelling
older legacy presses. Reset and BC5 loading advance all generations. Omitting
`generation` retains the simple debugger API without stale-request protection.
Legacy requests own a separate source and cannot release browser-owned keys.
Held-key state changes only after the original key routine returns; a failure
before injection can be retried, while a later scheduler failure does not cause
the same transition to be injected twice.

`/api/probe` accepts the native `read`, `write`, `call`, `state`, `pins`,
`uart_rx`, `uart_tx` and `spi` operations. Numeric addresses are JSON integers.
BC5 `call` and `call_resume` service the connected board while the function
waits for SPI. Continuations retain their requested instruction limit. Native
validation runs before peripheral execution, and serial MMU faults finalize the
probe and restore its paused CPU/stack while preserving the fault diagnostics.

`POST /api/firmware` accepts the raw file body with an `X-Filename` header. It
validates and starts the replacement worker before disposing of the prior one.
Replacing BC5 or restarting the board releases held electrical controls. Replacing the AVR with BC5 loaded warm resets
the retained BC5, preserving writable flash and RAM while cancelling its old SPI
DMA ownership and application display state. The next power-on starts a new board boot.
Replacing BC5 with another handset's image closes all old processors and clears
the old experiment; auxiliary images must match that handset. Identical modem
payloads uploaded alone retain the current handset context.
Firmware is staged only in a private temporary directory. Requests are bounded,
and Host validation accepts the connection's destination IP, the configured
browser authority, or localhost. Origin must match that validated Host; cross-site
browser requests are rejected. No external assets or CDNs are used.

## Extending fidelity

Keep instruction decoding separate from device behavior. Add a hardware model
at its observed bus boundary, with tests for registers, buffer isolation, transfer
ordering and error paths. Re-run original firmware to establish what progresses
and record remaining unknowns. A host-generated successful response, hand-drawn
firmware menu, or copied animation does not prove original handset behavior.

Current [inferred hardware](inferred-hardware.md) records the implemented
contracts. The retained [hardware evidence](hardware-evidence.md) describes the
earlier baseline. Firmware hashes and
[upstream source hashes](../native/vendor/SOURCE.tsv) make the baseline reproducible.
