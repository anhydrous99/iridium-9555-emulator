# Long SMS entry: command backlog and TRX reset boundaries

The rapid-input journeys still reach an original BC5 allocation panic. A fresh
9555 lifetime diagnostic now attributes its pool pressure to the original
outgoing command queue at RAM `F898`: pending nine-word commands occupy larger
allocation classes when the input cadence outruns their disposal. Idle time
drains that queue and restores the free lists. A genuine No Tone preference
contrast suppresses the observed queue growth. These results do not establish
a permanent text-allocation leak, a native allocator defect or a native fix.

Four complementary patient-input cases retain the factory tone preference and
allow another 2M original instructions with each accepted key released. They
stop at a different boundary: a TRX reset after 53 accepted characters on 9555
and 52 on 9575, with BC5 still healthy. Neither set completes the intended
201-character storage-boundary or 1,000-character limit journey. All complete
assertions remain enabled as ordinary regressions; no observed stop count is
claimed as a handset capacity limit.

The original firmware and native runtime are unchanged. Queue disposal is not
proof of successful audio or DSP execution. No heap expansion, forced callback,
consumer advancement or panic bypass was used.

## Preserved rapid-input regressions

The four original failures use one frozen test source, real key contacts, an
instruction allowance sufficient for the complete intended journeys, and the
unchanged native worker. There are no errors, skips or expected failures.

| Model | Intended journeys | Accepted count / remaining | BC5 instructions | Healthy TRX instructions |
| --- | --- | --- | --- | --- |
| 9555 HT25003 | 201-character and 1,000-character, separately | 81 / 919 | 280,973,207 | 256,504,680 |
| 9575 HL25003 | 201-character and 1,000-character, separately | 70 / 930 | 273,616,095 | 248,814,271 |

Both cases within each model share the initial input prefix and fail at the
same point. Their later save, capacity, overflow and full-readback assertions
remain present and unreached. These outcomes have not been replaced or
reclassified by the diagnostics or patient cases. The rapid-input source
[tests/test_factory_messages_draft_limits_e2e.py](../tests/test_factory_messages_draft_limits_e2e.py)
remains SHA256
`c4412efcdc4cbded0c724ed68c73f1121c91e3b3c029c924823df6b6a842d9c8`.
All twelve workers and four external peer threads closed.

## Calibration observations and original panic path

Two independently captured 9555 calibrations used genuine HTTP electrical keys
in numeric mode, with a finite external read-only SIM and original BC5/AVR/TRX.
Each character had to change the independently rendered remaining-count field;
inputs were not supplied through guest memory or a text-widget callback.

| Input cadence | Accepted characters before stop | BC5 instructions | TRX instructions |
| --- | --- | --- | --- |
| Hold until visible count changes, then release | 90 | 292,706,193 | 267,987,666 |
| Fixed held contact, release, then wait for visible count | 81 | 280,973,207 | 256,110,219 |

Both stop at BC5 byte PC `70A0`, panic `51` (`33` hex). TRX and AVR are still
healthy, and no native model error is recorded. The different counts rule out
treating the first observed count as a fixed capacity boundary. This is separate
from the TRX reset reached by the patient cases below.

Fresh original instructions and the captured stack identify the failing path:

- Panic-entry link register `X=B432`, `XH=0`, with program base `800C`, maps to
  return byte `684C`: the must-allocate wrapper `683C` called `6DCA`, received
  allocation failure and entered the panic routine.
- Its saved return `BAE2` maps to `75AC`. Original `75A6` loads request size 9;
  `75A8` calls `683C`. The failed request is a nine-word timer record.
- The subsequent actual frames lead through relative-timer wrapper `769A` to
  `B3214`, with callback `B3216` and delay 5,000 guest timer ticks. `B3074` creates
  the type-3 UI-event payload and `B316A` schedules it. This identifies an event
  timer, rather than a glyph bitmap allocation.
- Original `B3216` dispatches the event and frees its payload; original `7408`
  frees the timer record after the callback. These UI-event objects are distinct
  from the outgoing command nodes measured below.

A coordinated read-only snapshot after the 75-character progress marker and
near the later 81-character stop shows ordinary allocation-pool pressure.
`F55A=0` selects the ordinary pool arena; the direct scratch-arena exhaustion
and scratch-release assertions are different call sites. The observation is
not an atomic snapshot at exactly 75 characters. Raw debugger reads of MMIO
slots are not device-value observations and must not be used as MMU evidence.
The 9575 stack independently reaches the same low-level nine-word timer
allocator through its own UI-event routines. Its allocator/timer globals move
by `13` hex and scratch-depth variable is `F56D`, rather than HT's `F55A`.
Fixed HT-address dumps in the raw HL diagnostic are extra raw data, not evidence
of HL's corresponding globals. The complete ordinary heap `CA80..EC60`,
including its pool table at `CA80`, is captured correctly on both models.

## Measured command ownership and drain

One fresh 9555 HTTP diagnostic used the rapid cadence of a 400k-instruction
held contact, release, then a visible accepted-count wait. It captured complete
ordinary heaps, validated allocated membership against every pool's free chain,
and followed the actual `F898` queue root through each node's word8 link.
All 41 samples show exact equality between this queue and the allocated blocks
whose words 0, 2 and 4 are `1001`, `2` and `3`. This establishes ownership at the
sample points; it is not an instruction-by-instruction allocation/free trace.
This lifetime and preference-control investigation executed on 9555.

| Observation | Accepted characters | Pending F898 commands |
| --- | ---: | ---: |
| Before typing | 0 | 0 |
| After first key | 1 | 2 |
| After ten keys | 10 | 11 |
| Before idle | 20 | 20 |
| After 2M idle instructions | 20 | 16 |
| After another 8M idle instructions | 20 | 0 |
| After another 10M idle instructions | 20 | 0 |
| After resumed typing | 50 | 31 |
| Near the final halt | 100 | 80 |
| Actual BC5 panic 51 | 103 | 84 |

The first 10M idle instructions disposed of 20 commands, approximately 500k
modeled instructions per command. Allocation counts for classes 10/28/40
recovered to 26/18/8, versus 26/17/8 before typing. After typing resumed, the
queue grew again until every class large enough for a nine-word request was
full. The additional nine-word UI timer then failed to allocate. A modest
17..22 live timer count can coexist with 84 commands because the command queue
uses one service timer, rather than one timer per queued command.

Freshly decoded HT25003 bytes pin the original queue contract:

- `AE58A` forwards arguments to `CCF6A`. At `CCF70`, request size 9 is loaded;
  `CCF72` calls zeroing allocator `FD3A`. `CCF7C..CCF9C` initializes the node as
  `[command, 0, arg2, arg4, arg5, arg6, arg7, arg8, next]`.
- `CCFA2` calls `CCFF4`, which appends through word8 starting at `F898`.
- `CD02C` dispatches only when its timer ID at `F899:F89A` is zero. Its short
  branch calls `AC8CE→02E80→029C4`; that transport has a 10,000-tick bounded wait.
- `CD08A..CD0A2` installs callback `6:E865` (byte `CD0B2`) with delay `C350`
  (50,000 guest timer ticks) through original `769A`.
- `CD0B2` pops through `CD014`, clears the timer ID, starts the next head,
  invokes an optional callback and releases the old node at `CD10E→6DFE`.
- The key-audio control path includes `AD94E→AE8A4(4)→AE77C→AE58A`; stopping it
  includes `ADA7A→AE8B6(4)→AE77C`.

A node requests and initializes only nine words even when the allocator supplies
28/40/66/128/512 words. Words 9 onward are residual oversized-block contents,
not command-node fields. Glyph- or key-looking tails therefore do not identify
these live nodes as large renderer objects.

This explains the observed pool filling and its recovery without assuming a
permanent leak or broken interior-pointer release. The instruction/timer counts
are modeled observations, not verified physical input or audio timing.

## Genuine No Tone control

A second fresh 9555 handset used
Menu→Setup→Volume and Tones→Keypad Tones. It verified Single Tone, saved No Tone
and reopened its filled radio mark. Forty numeric characters were then accepted
with the same rapid cadence. Every sample at characters 1..20, 25, 30, 35 and 40
had `F898=0` and no `CD0B2` timer. Options→Exit discarded the composition, and
Single Tone was restored and reopened. The actual radio-mark LCD captures were
inspected. The job completed without CPU halt at TRX instruction 300,568,928.

This control ties the observed queue growth to the keypad-tone path. It is a
diagnostic, not a new feature-pass count, a replacement for the default-setting
rapid failures, or verification of 201/1,000-character storage.

Queue disposal does not demonstrate audio or DSP completion. Retained RAM at
the default diagnostic's terminal state has `ED9D/ED9E/EDA3/EDB7/EDB8=0`.
Original `029C4` requires `EDB8!=0` before its send branch; otherwise its bounded
wait can return zero. `CD02C` schedules later disposal regardless. No transport
initialization, successful response or consumer advance was supplied by the
host, and no native bug or fix is established by these observations.

## Complementary patient-input regressions

[tests/test_factory_messages_draft_patient_e2e.py](../tests/test_factory_messages_draft_patient_e2e.py)
adds four separate enabled cases. They delegate the complete frozen 201- and
1,000-character journeys, retaining counters, overflow rejection,
backspace/retype and complete saved-text glyph readback. After every accepted
key they allow another 2M instructions with the contact released and all active
processors running normally. They use fresh factory defaults, including Single
Tone; the No Tone diagnostic is not used to make these cases pass.

| Model | Intended journeys | Accepted count / remaining | Healthy BC5 instructions | TRX reset instructions |
| --- | --- | --- | --- | --- |
| 9555 HT25003 | 201-character and 1,000-character, separately | 53 / 947 | 362,168,087 | 337,298,285 |
| 9575 HL25003 | 201-character and 1,000-character, separately | 52 / 948 | 362,252,950 | 337,298,813 |

All four finish as ordinary failures with TRX `firmware-reset-requested`, PC
`7004A0C8` and saved `i7=70044934`. This matches the previously traced
[DSP command-consumer reset signature](dsp-execution.md); these runs did not
separately sample the rings or produce a new DSP instruction trace. BC5 and AVR
remain healthy at the stop. The final key's 2M interval is interrupted by that
reset, so 52 and 51 full patient intervals completed respectively.

Independent original-font checks match all 53/52 visible prefix glyphs, the
remaining counter and the exact caret column. The maximum-length cases' final
frames are pixel-identical to the inspected 201-case frames within each model.
This is partial input evidence, not successful 201/1,000-character input,
overflow, cross-chunk storage or saved readback: those later assertions remain
unreached.

The patient source remains SHA256
`9859e9b68c3750a459d1481b10c30dbe47e08d3606c51e8dd8ba7ce0b78aee48`.
There are zero errors, skips or expected failures. All twelve workers and four
peer threads closed. These are four separate current-source invocations, not
one complete factory-suite run.

## Complementary allocator diagnostic

One fresh, isolated 9555 BC5/AVR handset booted without TRX. A diagnostic used
the existing function-call interface to execute original `6C84` allocation and
`6DFE` release with sizes 9, 18, 40, 82 and 128, freeing at the base, middle and
last word. All fifteen pairs restored the complete pool table and free chains.
There were no raw guest-memory writes, and both workers closed.

This is explicitly a forced-function diagnostic, not end-to-end feature
coverage. It checks basic interior-pointer release and its division arithmetic
for those healthy-state inputs. It does not rule out every execution defect.
The original release routine deliberately normalizes interior pointers; the
renderer passing one is not itself evidence of an invalid free.

## Evidence and unchanged runtime

The lifetime and preference-control jobs verified all 129 protected sources
against aggregate
`0995e695bfcc89d7a458a1e273d0233c7ce74fe02dddcc7e7201327c5f14bc3b`
before and after execution. Both closed their three workers and peer thread.
The patient reports independently verify the same protected baseline. The
native executable and mapped worker hashes remain
`38fb483abb45d87881ed4abeb7cc394374432b0ced066c5e159ecbf38ca9593e`.

Local evidence is retained under:

- `/tmp/iridium-draft-limits-expansion/`: the preserved four rapid-input reports,
  final source, earlier calibration stages, native captures and provenance.
- `/tmp/iridium-sms-allocation-lifetime/`: `report.json`, `audit.json`, all 41
  raw snapshots, `decoded-snapshots.json`, `queue-ownership.json`,
  `fresh-original-command-queue.lst` and `transport-initialization.json`.
  `contrast-no-tone/` contains the independent setting/control/restoration run.
- `/tmp/iridium-patient-draft-expansion/`: four
  `final-{9555,9575}-{chunk,max}.json` reports with matching logs/captures,
  `final-audit.json`, `partial-input-oracle.json` and `provenance.json`.

The [factory coverage ledger](factory-e2e.md) records the enabled outcomes and
remaining gaps. Neither the rapid nor patient cases verify the intended long
storage/input boundaries, and no audio, DSP, delivery or network-service success
is claimed here.
