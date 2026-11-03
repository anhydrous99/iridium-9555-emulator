# Firmware-derived hardware testing

The emulation target is the hardware contract recoverable from the HT25003 and
HL25003 instructions, supplemented by the CPU and peripheral specifications.
An inferred digital device is a useful test model without claiming measured
electrical equivalence. Missing modem boot-ROM and DSP images are not replaced
with fabricated code or successful service responses.

## Implemented devices

- The AVR profiles include the model-specific GPIO and interrupt maps, external
  interrupt levels/edges, synchronous and asynchronous timers, capture inputs,
  PWM/force-compare pin outputs, four USARTs on the Extreme, SPI, EEPROM,
  watchdog, ADC mux/differential/conversion behavior, analog comparator and TWI.
  External samples and TWI peers are explicit test stimuli.
- AVR program-memory tests can load the upgrade payload or a complete flash
  image: 16 KiB for the 9555, 128 KiB for the inferred Extreme profile. The
  source file is read-only. Program reads and fuse configuration are exposed
  through the native protocol; reset restores the supplied program bytes and
  retains the configured fuse fixture.
- SPARC tagged integer arithmetic, atomic byte/word operations, interrupt levels
  and power-down are executed by the interpreter. Failed stores retain the
  faulting PC. There is no FPU or coprocessor in the selected CPU profile.
- The transceiver has four UART FIFOs with guest-visible status and capture-loss
  counters, guest-configured interrupt levels/source selection, a prescaled
  timer block, RTOS tick interrupts and a watchdog reset request. One modeled
  clock per instruction is an explicit deterministic timing hypothesis.
- The inferred BC5 flash supports the AMD unlock-bypass programming protocol.
  Its CFI and autoselect modes remain read-only until reset.
- LCD bytes come from serial-controller transfers using the original output
  MMU handle, rather than a program-counter hook at the firmware sender.

## Processor serial link

BC5 uses the same serial engine for the LCD and AVR. The AVR pin configuration
is `FDBF & 0x7FFF = 0x0440`. Active-low PIO4 selects the AVR; PIO12 receives
its per-byte handshake and PIO14 receives attention. PIO15 resets the AVR.
The host clocks one byte, lets the AVR execute its ISR, then acknowledges the
reply to the BC5 DMA engine. Firmware `FE95` polling sees busy until completion.
Transfers reduce the board quantum to 128 instructions.

| Signal | 9555 AVR | 9575 AVR |
|---|---|---|
| SPI handshake | PB0 | PA7 |
| Attention | PA3 | PC2 |
| Released power input | PC0 high | PJ3 high |

Original BC5 initialization `0xB165E`/`0xC707E` programs the GPIO direction,
pulses reset and waits for handshake. The original AVR SPI command parser
generates every reply. Reset retains external levels, flash, EEPROM and fuses.

When AVR and a modem image are loaded, the host connects AVR USART0 to modem
logical UART1. Telephony initializes DPL port1 at `0xE2B8C..0xE2B90`; its table
at `0x10A2F8` resolves that to physical `0x80000200`, IRQ5. PTT has an additional
logical-port remap; its DPL port1 resolves to the same physical peripheral.
The AVR's channel-routing instructions identify USART0 as the modem endpoint.
The board connection remains an inference from those two firmware contracts.

The host runs in 4096-instruction quanta and transfers completed bytes in order.
Backpressure retains bytes until the receiving queue can accept them. Capture
loss or an excessive backlog stops the experiment explicitly. This clock ratio
is a test schedule, not a measurement of the physical board.

`--modem-image trx` is the default. `--modem-image ptt` selects the alternative
modem and leaves telephony inactive; `--modem-image none` runs independent
workers. The two modem images are not simultaneous physical processors.
`processor_link` in session state reports the selected endpoint, traffic
counts, pending bytes and errors. Satellite scenarios remain separate until
an executing firmware transport supports their particular service.

## Modem timer and frame interrupts

The digital timer block advances with guest execution, including CPU sleep.
The original RTOS initializes the prescaler/reload/control registers and
acknowledges tick interrupts. TDMA's 32 programmed start/end compare channels
at `0x80001100 + 12*n` raise the event bits selected by the original mapping
tables. The aggregate interrupt is source 10, configured by guest code.
`0x80001318` bit 0 selects frame events, bit 1 UART3 and bit 2 UART2.
Both UART groups carry receive and transmit events; their event latches and
readiness snapshots allow the original deferred handlers to run without an
interrupt storm.

Frame channel 28's original handler calls `0x37944`, clearing the modem's
watchdog supervision counter. The original regression runs telephony for
60 million instructions, observes over 20 real frame-handler entries and
checks that supervision remains enabled with counter zero. Without compare
interrupts, original code reached a mode 3 reset at 47,585,237 instructions.
No host changes the supervision counter or suppresses its reset request.
Register acknowledgment and the source-clock ratio are explicit digital
inferences; this model supplies no RF or DSP outcome.

## Strict tests and bus traces

```sh
./run /path/to/firmware --headless --strict-hardware --steps 10000000
```

Strict mode stops before an unimplemented register fallback or an unclassified
data-bus access. `model_error` identifies an unimplemented register and its
operation. It does not certify physical timing or eliminate the assumptions
inside explicitly modeled peripherals. Normal mode retains the existing
open-bus/latch hypotheses for exploration.

The native JSON-lines protocol accepts:

```json
{"op":"hardware","strict":true}
{"op":"trace","enabled":true}
{"op":"run","steps":1000}
{"op":"trace"}
{"op":"adc","channel":0,"value":640}
{"op":"comparator","positive":900,"negative":200,"bandgap":350}
{"op":"async_clock","ticks":32768}
{"op":"uart_io","port":0,"rx":[65,66],"tx_limit":255}
{"op":"program_read","address":14336,"count":16}
{"op":"fuses"}
{"op":"key","code":150,"pressed":true}
{"op":"pin_state"}
{"op":"serial"}
```

Trace captures contain ordered data-bus accesses, not instruction fetches or
per-access PCs. Reading a trace drains its 4096-entry buffer. `dropped` is a
cumulative loss counter; reset clears it while retaining trace configuration.
Raw debugger memory reads are observational and are not added to the bus trace.
The AVR-only comparator and asynchronous-clock operations do not execute guest
instructions. `adc` accepts the BC5's four AIO inputs or the AVR profile's 8/16
normalized 10-bit channels.
`key` and `serial` apply to BC5; `pin_state` observes AVR electrical/external
levels. The BC5 `gpio` state contains live direction/output, edge masks,
key-latch/contact state and pending IRQs; raw memory reads do not substitute
for this device state.

`uart_io` validates every input before changing either queue. It returns the
accepted input prefix, completed output bytes and cumulative output loss.
Remaining input belongs to the caller. The original single-byte UART operations
are also available on the modem processors.

The TWI `twi` operation has actions `reply`, `address`, `receive`, `transmit`,
`stop` and `events`. Replies are `ack`, `nack`, `arbitration_lost` or `bus_error`.
An absent peer NACKs an address; no imaginary peripheral supplies data. The
events response reports bounded capture loss.

## Reproducible checks

```sh
IRIDIUM_TEST_FIRMWARE=/path/to/9555 \
IRIDIUM_TEST_9575_FIRMWARE=/path/to/9575 ./test
```

Independent machine-code snippets verify actual AVR-to-SPARC and SPARC-to-AVR
byte transfer. The optional original-modem probe executes both images' UART
drivers, timer initializers, tick ISRs and watchdog-reset routines, including
assertions on the original OS tick words. Original LCD initialization must
still emit its known 43-byte stream through the emulated serial controller.
Original UI, menu, GPS/SOS, flash-retention and opcode-mutation tests remain
part of the complete test command.

## Evidence for the LCD transport

Original BC5 `0x39370` installs RX/TX MMU handles at `0xFE93/0xFE94`.
`0x3954C` selects the serial configuration and GPIO pin indices.
`0x58B54..0x58DE0` accesses control/pin configuration at `0xFDBE/0xFDBF`,
mode at `0xFDC0`, count at `0xFDC1` and direction at `0xFDC3`.
The LCD configuration selects mode 3 and pin indices `0,1,1`, encoded as
`0x420`; original `0x39354` polls busy bit 0 at `0xFE95`.

These instruction observations support a synchronous digital transfer model
with a separate circular output cursor. They do not establish baud rate or
analog waveforms. REA process capture
`ev_c0ae9a457a9a1273c7377dc2efff464b931d2d3f56f65324d540a53f5e9db0f5`
records the decoder's `0x58B54..0x58D20` output; it observes decoding, not
execution of a physical handset. Runtime regressions provide the independent
guest-execution check of the inferred register contract.

## BC5 interrupt, ADC and power inputs

The original reset and interrupt instructions support an inferred XAP2 register
bank model. FLAGS bit 4 exchanges X/Y with the inactive UX/UY bank. Interrupt
entry selects the supervisor bank, saves FLAGS and the program counter below
its stack, and branches through image word 2. The original wrapper restores the
interrupted bank and executes its own RTI. Compiler scratch addresses
`0xFFE2,0xFFE5..0xFFFF` refer to the supervisor stack's final 32 words; the live
AH/AL/X/Y aliases remain registers. In particular, the wrapper writes `[Y-3]`
at image byte `0x96`, switches banks and reads the same location through
`0xFFFD` at `0x9E`. REA capture
`ev_1fee4b479d6b9c957e9e4a1259c3f127f1965fa84087bd87e3ccbfa97f71380f`
records this instruction evidence. The independent CPU executor retains its
legacy mode for isolated instruction experiments.

Timer B compare `0x43:0x44`, enable bit 2 at `0xFF94`, raises IRQ0, including
priority 0. Register `0x69` pulses software events 0..4 as IRQ11..15: the
original `0x6820` adds 11 when configuring a source, while `0x6834` pulses the
unshifted event. Masking, nested priorities, previous-level restoration and
guest end-of-interrupt writes are modeled. Timer A's IRQ2 and Timer C's IRQ13
assignments remain explicit hypotheses. Time advances by one modeled timer
unit per eight BC5 instructions.

ADC command `0xFF8D` and result `0xFF8E` follow the handshake executed by
`0x1B182`; auxiliary ADC uses `0xFF7B/0xFF7C`. Start bit 13 controls busy bit 4,
and the 10-bit result occupies bits 15..6. Original `0x107DC` selects AIO0..3
through the two bytes of `0xFF8C` and `0xFF79`. The host provides samples at
this hardware boundary; the original software queue, interrupt handlers and
callback instructions execute normally. Analog settling time is uncalibrated.

Both board-detection callbacks classify 8-bit samples 154..168 as revision 11,
`GRev`. AIO0=640 is an explicit virtual board fixture within that interval,
not a measured handset voltage. External AIO samples survive reset. Original
integration tests provision factory settings through original routines once,
then warm-reset and verify natural ADC completion, `GRev` selection and
application LCD output without application probes after that reset. They also
exercise the actual interrupt wrapper, nested interrupts and debugger probes
with hardware enabled on both models.

The power-button input is active-low: logical AVR PC0 maps to physical PC0
on 9555 and PJ3 on 9575. The adjacent logical PC1/PD4 inputs map to PC1/PD4
and PJ4/PJ5 respectively. Inactive fixtures are PC0=1, PC1=0, PD4=1 in the
logical namespace. The 9575 flash table at `0x36D4` maps these selectors to
`0x86/0x88/0x8A`; its GPIO driver extracts port from the high nibble and bit
from bits 3..1. REA captures
`ev_48792fe66e11d6be6ddf41a4c260352936fe5a28fefcd83a2e837f301702a1be`
and `ev_086e30bb864c7cd666eb93079c3449a55d591420938abbdb3cef935db9422c9d`
record the decoder output and table bytes. Original AVR SPI register 4 tests
verify each physical input's low/high value reaches the corresponding guest
read. The exact external charger/battery connector identities of PC1 and PD4
are unresolved; battery fuel-gauge data is a separate 1-Wire contract.

The polarity follows the normal-operation hold path, not just startup:
`0x6B32C` schedules a hold when PC0 is low, and `0x6B362` requires it still
low before requesting shutdown. Raising PC0 cancels that pending hold in
`0x6AB4A`. Startup also requires PC0 high. REA capture
`ev_d02c9c2ccf55d72744e5536647b6557f3128dce823e0d3542cdf7630afd11a58`
records the shutdown instructions. A paired runtime without matrix contacts
independently observed a 500 ms shutdown after holding PC0 low, correcting an
earlier active-high interpretation based only on startup.

Paired original-image regressions load both BC5 and AVR, provision settings once
through original code, then warm-reset with the button released. They verify
all 25 matrix contacts through GPIO columns, IRQ15, the original debounce
routine and scanner state, including release. An ordinary soft key also reaches
the original UI callback. No application probe runs after that warm reset.
Separate tests keep the released input high beyond 500 ms and verify that a
low level held for 500 ms enters the original shutdown state. The unestablished
SOS contact is rejected without changing instructions, registers or contacts.

Original power-on also enables AVR logical PA5: `0x6BE4C -> 0x69DE6 ->
0x6B030 -> 0xAB5BC` on 9555, and `0x6BED0 -> 0x69DE6 -> 0x6B046 ->
0xB4812` on 9575. That output is physical PA5/PC4 respectively and starts
the AVR USART links. The matching power-down helper clears it. This establishes
serial-link gating; it does not establish a physical modem reset or CPU power
pin. REA decoder capture
`ev_34dddbb434f839d778c38094dfe0e95e8f7a54d0b139a8478f5536549ea826af`
records the 9555 enable/disable helpers.
