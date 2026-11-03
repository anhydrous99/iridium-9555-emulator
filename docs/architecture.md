# Architecture and debugger API

`iridium/firmware.py` validates source bytes and strips container metadata.
`iridium/engine.py` owns a native worker and its bounded JSON-lines transport.
`iridium/session.py` serializes debugger actions and keeps independent CPU state,
input events and satellite scenarios. `iridium/server.py` exposes that session
on all IPv4 interfaces by default (`--host 127.0.0.1` restricts access to loopback).
`ui/` renders state without synthesizing firmware menus.

`native/main.zig` adapts the original CPU/SoC implementations under
`native/vendor/`. Each processor lives in a separate OS process because the
inherited models use process-global state. This is not a synchronized board
simulation. Instruction budgets are deterministic; they are not elapsed time
on physical hardware. The scenario clock is also an explicitly simulated clock.

## Input and execution boundaries

The supported profile is the supplied HT25003 firmware. BC5 program addresses
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

BC5-only `warm_reset` resets CPU, device state and observation counters while
retaining RAM and emulated flash contents. Original reset code validates retained
persistent-store records before clearing RAM. This is an explicit host operation;
watchdog timing is not modeled. The ordinary `reset` also clears RAM and restores
flash from the supplied firmware, returning the worker to a fresh experiment.

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

UART queues and SPI replies require intervening CPU execution. These interfaces
are not yet wired to the BC5 or SPARC workers.
Each AVR UART output capture holds 255 bytes. Overflow increments cumulative
per-port `uart_tx_dropped` counts in processor state; `uart_tx` also returns the
selected port's `dropped` count. Draining the queue preserves the counts, and
reset clears them. The browser displays any capture loss in the AVR row.

BC5 state includes `lcd_bytes`: low bytes observed at original sender `0x68E48`,
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

Experimental `initialize_ui` pauses all host workers and follows the original
application's persistent-store initialization path:

1. Reach scheduler idle, invoke original device initialization `0x6365E` if it
   has not already run, then full application initialization `0x8CC8C`.
2. On fresh flash, `0x8CC8C` executes the original factory-default writes and
   requests a watchdog reset. Perform `warm_reset` and run to idle again; original
   reset code validates the retained records and invokes device initialization.
   Invoke full `0x8CC8C` again after this reset.
3. Invoke `0x8CC5E` to start the original animation.
   Check the installed key callback and resume scheduler execution.

The animation now advances automatically to the original home screen showing
Searching for Iridium, Acquiring time, Menu and Help. A left soft-key event opens
the original main menu. The host does not patch firmware instructions, write
persistent-store keys directly or inject the animation-completion callback.
This remains an explicit software startup scenario: the natural ADC-completion
path into the application is unresolved. Initialization failure requires a reset
before retrying, so partially initialized state is not initialized twice.

After this scenario, mapped key events enter original `0x67F04` with key code
in AL and transition 1 (down) or 4 (up) in AH. The scheduler dispatches the
allocated event through the original callback. Before initialization or for the
unmapped convenience key, the host records the event and reports non-delivery.

## HTTP API

`GET /api/state` returns image hashes, processors, input state, scenario state,
bounded events, an optional original asset preview and explicit fidelity limits.
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
and firmware responses expose `key_epoch`. Reset or loading BC5 advances the epoch,
clears owners and cancels older requests; auxiliary image loads preserve keypad
state. A page cancels queued events and local held sources when the epoch advances,
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

`POST /api/firmware` accepts the raw file body with an `X-Filename` header. It
validates and starts the replacement worker before disposing of the prior one.
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

The retained [hardware evidence](hardware-evidence.md) identifies the specific
BlueCore startup and modem gaps. Firmware hashes and
[upstream source hashes](../native/vendor/SOURCE.tsv) make the baseline reproducible.
