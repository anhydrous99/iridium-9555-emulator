# Original modem SIM boundary

The telephony model supplies separate external SIM inputs, firmware output
pins and card-presence edge delivery. Factory contracts execute original TRX
instructions from reset through real UART3 exchanges. On both models, finite
synthetic cards now establish original file-data publication and empty SMS
storage-controller initialization, including a disabled-service control and a
card memory-error case. Separate empty/populated ADN contracts also establish
original phonebook-cache consumption. Four further contracts establish a finite
SMS write/reinsertion/readback path and original rejected-write handling.
Four service-center contracts further distinguish the early CSCA acknowledgement
and cached number from committed SMSP data and a fresh post-reinsertion query.
The original handset SIM phonebook is read-only, exposing Call/SMS/Copy rather
than Edit/Delete/New. Separate serial ADN-write contracts reach create/edit and
immediate readback, but all four halt during reinsertion at the existing DSP
reset signature. These results do not establish general SIM provisioning,
restricted-entry/PIN2 authentication or network service. GUI drafts are a
separate local BC5 flash feature.

The [current reconciliation](../test-artifacts/factory-storage-settings-gps/report.json)
contains **236 HTTP outcomes: 210 passes and 26 ordinary failures**.
The sixteen current HTTP additions include four passing stored-SIM Inbox
journeys: full read/Reply/Forward cancellation and real-card Delete No/Yes.
See [stored SIM messages](stored-sim-messages.md) for finite PDU/status boundaries.
These cases preload an external card; they do not supply incoming RF messages,
subscriber authentication or Send success.

The **34 inherited peripheral case IDs remain 30 passes and four serial ADN
reinsertion failures**. Ten latest ADN-card pure checks remain separate
historical evidence; no peripheral or pure fixture IDs are added now. The
preceding 220-outcome/144-source contact phase remains unchanged in
`test-artifacts/factory-contact-coverage/`. Its eight additions had four passes
and four ordinary maximum-field failures. All 144 earlier execution files and
native `38fb483a…` remain unchanged; the current 148-source aggregate is
`6614fd70eb8ce8120ac1e85dccdd183f2a4bdf9d27044ea9aa5cad6736229b9e`.
The [coverage ledger](factory-e2e.md) records the complete scope and checks.

## Pins and interrupt evidence

Original SIM task `0xB4148` selects TRX UART3, base `0x80001600`, separately
from DPL on UART1. Original output mask `0xFE` and input mask `0x101` keep
external levels distinct from firmware writes at base+`0x10`. Card detection
`0x3E010` samples input bit 0; high is the software's available-card state.
Input bit 8 is exposed as a level, but its purpose and edge behavior remain
unestablished.

The paused debugger operation `uart_pins`, with `port: 3`, reads
`inputs`, `outputs`, combined `pins` and both masks. An optional `value` and
`mask` change only external input bits `0x101`; malformed requests are rejected
before mutation. Whole-word and big-endian byte writes from the guest cannot
erase inputs. Other UARTs and PTT retain their existing pin behavior. A warm
modem reset retains external levels while resetting output/FIFO/event state;
a fresh reset clears them.

A high level alone is insufficient after boot. Original `0x343F8(3, 0x4E)`
installs the SIM modem-control callback at `0x400A6018`. Aggregate ISR
`0xDCE64` dispatches summary bit 1 to port-3 handler `0x348F4`, which reads
`0x80001314` bit 0 and schedules callback `0x4E`. Its original table entry at
`0x700836E4` points to `0x3DF08`; that routine sets stabilization word
`0x70003234`. CKM task `0x3DD14` then polls the input until the changed sample
and eight stable increments are followed by completion. It clears the word
and sends original SIM queue event `0x9860` or `0x9861` for insertion/removal.
Port-2 handler `0x347E8` uses the other callback table and status byte.

The model latches input-bit-0 changes on interrupt source 10, preserves them
across UART interrupt-mask writes, and retains status after the outer ISR's
`0x80001304` acknowledgement. Reading the containing lane at `0x80001314`
acknowledges the status. This read-to-ack behavior is an explicit inference
from the original read/ack order; it is not a verified ASIC specification.
Repeated identical levels and changes to bit 8 create no edge event. No
callback is invoked by the host: executing firmware handles the interrupt.

## Original reset and wire exchange

Original reset `0xB4C20` clears output mask `0x20`, waits, sets `0x10` and
`0x04`, waits, then sets `0x20` and reads ATR. Observed outputs are
`0x40 -> 0x54 -> 0x74`. Exact physical control labels, polarities and timing
still need independent hardware evidence.

The external peer supplies direct-convention default-T=0 ATR `3B 00` only
after that observed release sequence. Original `0xB517C` accepts it. The
firmware then transmits `A0 A4 00 00 02`; after the peer's actual T=0 procedure
byte `A4`, it transmits file identifier `7F 20`. No successful SELECT status
or file metadata is supplied by these tests. Removing the card during the
exchange completes original absence debouncing and returns controls to `0x40`.
An invalid initial ATR byte is rejected and causes another reset without a
command. Retained high input is also detected after natural warm startup,
without another external edge.

[test_factory_sim_contract.py](../tests/test_factory_sim_contract.py) contains
these three contracts for each model. They load the hash-pinned shared TRX
payload, make no guest-memory writes or forced calls, assert no SIM TX loss,
and retain JSON pin/wire/state evidence. Native unit/protocol tests separately
cover mask validation, independent inputs, byte writes, interrupt ordering,
wrong processor images and reset lifecycle. These are peripheral contracts,
separate from HTTP handset feature coverage.

Run them with both original fixture directories supplied:

```sh
zig build -j2
IRIDIUM_TEST_FIRMWARE=/path/to/9555 \
IRIDIUM_TEST_9575_FIRMWARE=/path/to/9575 PYTHONPATH=tests:. \
python3 -m unittest test_factory_sim_contract test_factory_sim_file_contract \
  test_factory_sim_storage_contract test_factory_sim_phonebook_contract -v
```

## Original file-data publication and memory error

[sim_language_card.py](../tests/sim_language_card.py) provides versioned,
read-only external test cards. `LanguageSIM` declares only MF `3F00`, GSM DF
`7F20` and transparent language EF `6F05`. The card supplies legacy metadata,
T=0 procedure bytes, data and status in response to actual original commands.
Unsupported files return `94 04`; no subscriber identity or authentication
response is supplied. The
[ETSI SIM specification](https://www.etsi.org/deliver/etsi_TS/151000_151099/151011/04.09.00_60/ts_151011v040900p.pdf),
sections 9.2.1, 9.4 and 10.3.1, is the primary metadata/file reference. Card
contents and access declarations are synthetic fixtures, not manufacturer
provisioning.

The original firmware executes SELECT, GET RESPONSE and READ BINARY, then
publishes logical `F100` through its own SEEM consumer. Pointer entry
`0x70002270` identifies cache `0x400B4278`. The two successful fixture variants
produce these first six bytes:

| Synthetic EF data | Original F100 cache |
| --- | --- |
| `01 04` | `00 00 01 02 01 04` |
| `04 01` | `00 00 01 02 04 01` |

Cache offset 1 is the mapped result, offset 2 is the metadata validity bit,
offset 3 is accumulated length, and data starts at offset 4. The tests also
assert the original intermediate buffer at `0x400B4010`, its length at
`0x400B400E`, the real READ header and the original UART receive buffer.
This establishes original consumption and publication beyond host FIFO
acceptance. The earlier temporary probe stopped one 4,096-instruction quantum
before publication; its unchanged-cache observation is no longer the current
completion boundary.

The fault variant supplies genuine card status `92 40` immediately on READ,
without a data procedure ACK or file data. Original classifier `0x29464`
maps that status to internal result 2; `0x28104` maps the read result to public
error 4. The fresh cache becomes `00 04 01 00 FF FF`, with intermediate length
zero. No success or new file data is published. The original `9823` transport
reply's declared length remains based on requested Le even on early status;
that field alone is not a successful-read oracle.

`LanguageSIM` retains selected files, partial commands and unaccepted response
suffixes across original bit-`0x04` clock stop/restart. It supplies ATR only
after actual reset release and active clock. The original stop is
`0xB4964 -> 0x33E54(port3, 0x04)`; resume is
`0xB481C -> 0x33EA8(port3, 0x04)`.

[test_factory_sim_file_contract.py](../tests/test_factory_sim_file_contract.py)
has four passing test methods across both models: two data orders per model
and one memory-error variant per model, using six fresh original workers in
total. The [final log](../test-artifacts/factory-storage-expansion/checks/sim-file-contract.log)
and six raw peripheral captures are retained with the aggregate evidence.
[test_sim_language_card.py](../tests/test_sim_language_card.py) has nine
firmware-free fixture checks for framing, retained suffixes, reset/clock
lifecycle, genuine errors and the storage declarations below. These checks
test the external card fixture; they are not handset feature passes.

## Empty SMS storage-controller initialization

`StorageSIM` adds a finite GSM service table and TELECOM files under MF `3F00`:

| Path | Declared synthetic contents |
| --- | --- |
| `7F20/6F05` | Two language bytes |
| `7F20/6F38` | SST `CC 00` with ADN and SMS allocated/activated, or control `0C 00` with SMS unavailable |
| `7F10/6F3A` | Two empty 32-byte ADN records, each all `FF` |
| `7F10/6F3C` | Two empty 176-byte SMS records, each `00` followed by 175 `FF` bytes |

The enabled and disabled variants retain identical file metadata and record
contents; only the SST data changes. The layout and service bits follow
sections 10.3.7, 10.5.1 and 10.5.3 of the ETSI reference. Directory metadata
declares CHV1 disabled, so no fabricated credential verification is needed.
The peer supports the required reads and rejects file updates; it does not
provide an identity or general-purpose card filesystem.

Original EF GET RESPONSE consumes 15 legacy bytes: zero-based offsets 2–3
give file size and offset 14 gives record length. Original descriptors map
logical `F202` to SMS `6F3C`. Its declared size `0x0160` and record length
`0xB0` give two records through `(file_size / record_length) & 0xFF`.
Original SMS initializer `0x83E08` caps that count at 50, requires a nonzero
count, starts record loading and sets readiness bit 0.

Before requesting that geometry, original `0x83028` requires a successful SST
read whose first byte masked with `0xC0` equals `0xC0`. The four passing
[storage contracts](../tests/test_factory_sim_storage_contract.py) prove this
gate on both models:

| Variant | Original observations on both 9555 and 9575 |
| --- | --- |
| SMS enabled, SST `CC 00` | F107 cache publishes `00 00 01 02 CC 00`; real SELECT/GET RESPONSE of `6F3C`; exact `A0 B2 01 04 B0` and `A0 B2 02 04 B0` reads; both empty records consumed; capacity 2, flags 3, controller word 1 at 103.9M original instructions |
| SMS unavailable, SST `0C 00` | F107 cache publishes `00 00 01 02 0C 00`; no `6F3C` selection or SMS reads; capacity, flags and controller remain zero through the full 120M-instruction bound |

The independently captured state addresses are capacity byte `0x400AA2D6`,
flags byte `0x400AA2D3` and big-endian controller word `0x400AA30C`. Original
command headers, SELECT bodies, card bytes and these consumer states are
asserted together. All UART capture drops are zero. The verified reports record
unchanged test/fixture hashes, unchanged 107 baseline source files, the live
worker executable hash and closed workers. No AT command is used.

The retained [9555 report](../test-artifacts/factory-storage-expansion/peripheral/storage-9555.json),
[9575 report](../test-artifacts/factory-storage-expansion/peripheral/storage-9575.json)
and [raw peripheral captures](../test-artifacts/factory-storage-expansion/peripheral/)
contain the final automated evidence. The verified logs, capture audit and
provenance are also retained under
`/tmp/iridium-sim-storage-contract-expansion/`. ADN geometry is declared in
this fixture; those SMS contracts stop before ADN consumer completion. The
separate ADN contracts below extend that original execution path.

## Original ADN record consumption and phonebook cache initialization

[test_factory_sim_phonebook_contract.py](../tests/test_factory_sim_phonebook_contract.py)
adds four passing peripheral methods: empty and populated ADN variants on both
model profiles. Each uses a fresh original TRX worker and the unchanged
read-only `StorageSIM` peer, starting with 60M card-absent instructions before
external card detection and real UART3 T=0 exchanges. No guest RAM writes,
forced calls or AT requests are used. These are separate from HTTP journeys.

Both variants declare two 32-byte ADN records in TELECOM EF `6F3A`. The
populated variant changes only the external first record to `Adg / +12345`;
the second remains empty. Its 18-byte alpha field, length byte, TON/NPI, BCD
digits and absent capability/extension identifiers follow section 10.5.1 of
the ETSI reference.

| Variant | Original observations on both models |
| --- | --- |
| Two empty ADN records | Actual `6F3A` SELECT/GET RESPONSE and `A0 B2 01 04 20` / `A0 B2 02 04 20` reads; capacity 2, alpha-field limit 18 bytes, used-SIM count 0, phonebook initialization word 1 and no read in flight |
| `Adg / +12345` followed by an empty record | The same original metadata/record path; capacity 2 and used-SIM count 1; original name cache contains `Adg` with NUL padding, compact digit index contains `21 43 F5`, and both lookup-order arrays begin with logical slot 101 |

Original metadata handler `0x92708` uses `0xB32A0` to divide file size by record
length, then `0x918DC(..., 1)` updates SIM capacity byte `0x400AA9FE`. It sets
alpha-field limit `0x400ABEFA` to record length minus 14. Geometry changes from
the original default of 155 records to 2 at 106M instructions, before
initialization completes. Record consumer `0x93540` then reaches `0x918CC`,
which stores the big-endian initialization word 1 at `0x400AA9F8`. Both
variants reach that state at 112.9M instructions, within the 120M total bound.
Instruction counts are execution budgets, not physical timing guarantees.

For the populated record, original `0x92498 -> 0x9240C -> 0x92340` increments
used-SIM byte `0x400AA9FC` and stores the parsed name and compact digit index.
Original local capacity 100 places SIM record 1 at logical slot 101: the name
is observed at `0x400AB33D`, and the three digit-index bytes at `0x400AAB2C`.
The compact index removes the international prefix and can retain at most six
trailing digits. All five supplied digits are checked; full-number or TON
readback through a handset UI is not established.

A separate 9555 diagnostic changes only SST from `CC00` to `C000`, declaring
ADN unavailable while retaining SMS. Original F107 consumes that value, but
the same eager ADN initialization still completes. This diagnostic is excluded
from the four automated pass counts. The metadata/record consumer has no
direct SST-bit guard; later caller or GUI availability policy remains
unestablished. No ADN service-gating requirement or firmware defect is inferred.

The final [9555 report](../test-artifacts/factory-sim-consumers/peripheral/adn-9555-report.json)
and [9575 report](../test-artifacts/factory-sim-consumers/peripheral/adn-9575-report.json)
record all four outcomes. Their exact raw captures are:

| Model | Empty-record capture | Populated-record capture |
| --- | --- | --- |
| 9555 | [Empty ADN](../test-artifacts/factory-sim-consumers/peripheral/test_factory_sim_phonebook_contract.Factory9555SIMPhonebookContractTests.test_original_adn_metadata_and_two_empty_records_initialize_phonebook_consumer.json) | [Adg / +12345](../test-artifacts/factory-sim-consumers/peripheral/test_factory_sim_phonebook_contract.Factory9555SIMPhonebookContractTests.test_original_populated_adn_record_updates_used_count_name_and_number_index.json) |
| 9575 | [Empty ADN](../test-artifacts/factory-sim-consumers/peripheral/test_factory_sim_phonebook_contract.Factory9575SIMPhonebookContractTests.test_original_adn_metadata_and_two_empty_records_initialize_phonebook_consumer.json) | [Adg / +12345](../test-artifacts/factory-sim-consumers/peripheral/test_factory_sim_phonebook_contract.Factory9575SIMPhonebookContractTests.test_original_populated_adn_record_updates_used_count_name_and_number_index.json) |

Original C/listing excerpts, source snapshots, wire/capture audits and provenance
remain under `/tmp/iridium-sim-adn-contract-expansion/`. Final source SHA256 is
`783a2b33b1e2e0dc21ecbc3620586a53acfb4dc29450f55cf0d943e453ccb7fa`.
All four workers recorded the native hash below and are closed; all 113
protected execution/test/fixture files remain unchanged. There are no skips,
expected failures or errors. The independent audit reconciles all final IDs
and artifact hashes, all 724 accepted response bytes and 46 original command
headers per case, plus critical original instruction bytes and call targets.
The earlier empty-only stage remains separate history and is not counted again.

These results establish empty and one-populated-record consumption into the
original phonebook cache. Those read-only consumer cases do not establish
handset SIM-phonebook display or card writes. Broader encodings, full capacity,
removal during storage operations, restart retention, PIN/PIN2 authentication
and subscriber/RF service remain outside those four contracts.

## Read-only handset SIM phonebook

Four [HTTP handset cases](../tests/test_factory_sim_phonebook_e2e.py) now pass,
using empty and populated external cards on both model profiles. They verify
the original ADN record/cache consumption, wait for original startup and scan,
then enter SIM Phonebook through the real Main Menu. The empty card displays
literal `(Empty)`, a blank left caption and Back. The populated card displays
selected `Adg`, Options and only **Call, SMS, Copy** in the original contact
menu. Back returns to healthy Home without a card mutation or UPDATE command.
Complete original-font name/action and caption assertions establish these
views only; these four display cases do not activate an action or read a number.
The separate Copy/SMS workflows below assert canonical `+12345`.

The original handset does not provide SIM Edit/Delete/New. The supplied manual
reserves SIM programming to external software. Copy creates a local
My Phonebook contact rather than updating the SIM. Separate direct-SMS, saved
shortcut and Copy assertions are described below. Restricted entries/PIN2
remain blocked on their separate file/authentication contract. These are not
missing generic GUI CRUD functions. The [SIM workflow evidence](sim-phonebook-workflows.md)
records the original resource/handler distinction.

The populated widget's selected rectangle is x0..118, y15..33 inclusive;
the independent name crop starts at x2/y16 with width 117, and unused rows
begin at 34. Earlier width-118/row-32 checks failed on both models despite
correct visible Adg/Options/Back. An independent native-JSON/PNG/original-font
audit identified the exact geometry errors. Those stages are retained as
excluded checker calibration; the final four cases pass on one frozen source.

## Direct SIM SMS, saved shortcuts and local Copy

Two [direct SIM-to-SMS cases](../tests/test_factory_messages_sim_recipient_e2e.py)
pass on both profiles. Actual SIM Phonebook→SMS opens an empty New editor and
seeds an original recipient node containing `+12345` plus NUL. HT `78370` and
HL `78708` pass only the CPBR number into this path. The optional name callbacks
at `F85F:F860` and `F88F:F890` are zero in these fixtures; the name pointer is
null, both list links are zero, and Send To correctly displays the number.
Complete `adg`/997 survives recipient removal; the list empties, and explicit
Exit leaves Drafts empty and returns Home. No name is invented and no Send or
card update occurs.

Two [saved SIM-shortcut cases](../tests/test_factory_sim_shortcuts_e2e.py) also
pass. They save/read back both convenience and right-soft-key SIM assignments,
cancel visible alternative drafts while retaining saved radio marks, then
activate both keys after the original scan is ready. Each opens actual Adg
and the original read-only actions, with Back to the same list/Home. Both
assignments restore/read No Action on 9555 or Location on 9575, Show Help and
Menu/Help captions; the card stays
unchanged. The Call/SMS/Copy actions are only displayed in these shortcut cases.

The [SIM-to-local Copy cases](../tests/test_factory_sim_phonebook_copy_e2e.py)
pass on both models. Their complete assertions cover the original success text,
local Name `Adg`, Home `+12345`, empty Work/Mobile1/Mobile2, empty Email and
Notes, then cancelled `Ad` name editing with all saved fields retained. A bare
plus on a focused empty phone is an editor prefix, not a copied stored number;
all three inactive phone fields must be blank after blur. Finally the original
SIM Adg is reopened and all external card data remains unchanged. Earlier Copy
calibration required an extra Back footer even though the original success
modal has a blank footer; that excluded checker error is not a feature failure.

The current component reports, frozen sources, original-font/node audits and
excluded calibration join `test-artifacts/factory-sim-workflows/`. These are
finite same-boot local workflows, not SIM programming, unrestricted contact
encodings/capacity, authentication, calls, SMS transmission or delivery.

## Serial ADN writes: partial completion before reinsertion halt

The finite [PhonebookSIM](../tests/sim_phonebook_card.py) declares two 32-byte
ADN records, with 18 alpha bytes and a 20-digit number field. It accepts only
declared `6F3A` UPDATE RECORD writes: actual `A0 DC 01 04 20`, procedure `DC`,
a complete 32-byte body and `9000`. A matched memory fault instead returns
`9240` before any procedure ACK/body or mutation; other files stay read-only.
Ten [pure card checks](../tests/test_sim_phonebook_card.py) pass for framing,
fragmentation, full-body atomicity, rejection, readback, reset, retained committed
data and write restrictions. These validate the external fixture, not original
handset/modem feature completion or manufacturer provisioning.

Four [original serial contracts](../tests/test_factory_sim_phonebook_write_contract.py)
remain ordinary failures, two per model. Original CPBR/CPBW advertise logical
indices **101..102**, after the 100 local slots; physical card records are 1..2.
Positive runs really create `Adg / +12345` with type 145 and edit to `B / 67`
with type 129, each with a full accepted card update and immediate complete
original CPBR name/number/type readback. Negative runs create the first entry,
reject its edit at the card, receive original `+CME ERROR:003` and read back the
unchanged initial entry. The second record and other files remain unchanged.

All four then halt during natural card reinsertion at TRX instruction
185,746,541, PC `7004A0C8`, saved `i7=70044934`. This matches the previously
traced DSP-reset signature; these cases do not independently trace DSP
instructions or resample its rings. Fresh reinserted readback, deletion and
recovery assertions stay enabled and unreached. The observed updates/immediate
readbacks are partial evidence, not four passing persistence contracts.
Earlier physical-index-1 AT attempts were bad-index calibration and did not
reach a card write. See [SIM phonebook workflows](sim-phonebook-workflows.md).

Final source proof, six new passing HTTP outcomes, four separate serial
failures, ten pure passes and their raw captures/audits are retained in
`test-artifacts/factory-sim-phonebook/`. No guest RAM, callback, DSP consumer,
native halt or AT success was patched or replaced. Broader encodings/capacity,
cold-power retention, subscriber authentication, calls and delivery remain
outside these results.

## Original Messages retry timer and remaining GUI work

A separate real HTTP 9555 diagnostic attached the read-only synthetic card to
the complete BC5/AVR/TRX handset. The original modem reached SMS capacity 2,
flags 3 and controller word 1, and read both empty ADN records. Actual HTTP
navigation to Messages still displayed the original error, "SMS Mailbox being
configured, please try again later". It remained after a further 10M
instructions, an actual dismiss/reopen sequence and another 2M wait. The final
native TRX counter was **174,518,928**, including 4.6M instructions from the
separate HTTP review; one managed modem power reset was recorded and all CPUs
remained healthy. The worker and external peer thread closed.

That bound did not establish a permanent GUI block or authentication diagnosis.
It established no usable Messages screen, SMS composition/save, SIM-contact
save or service completion. The raw diagnostic
is archived with its executed driver, HTTP actions and original LCDs in
[`sim-http-measured-runtime.tar.gz`](../test-artifacts/factory-storage-expansion/diagnostics/sim-http-measured-runtime.tar.gz).
The [boundary summary](../test-artifacts/factory-storage-expansion/diagnostics/messages-boundary.md)
records the instruction accounting and evidence limits. The working copy is
`/tmp/iridium-sim-http-measured-runtime/`.
Some frame names contain the main driver's instruction budget and exclude
that review; use the final native counter for the total. No 9575 GUI result
is established by this diagnostic.

A later 9555 diagnostic traced the original pending retry rather than stopping
at that earlier instruction bound. The real modem returned
`+CPMS:000,002,000,002,000,002` and `OK`, so genuine storage capacity 2 had
already reached BC5. Its scan-ready flag `F85B` remained zero while the
original timer with handle words `[0, 752]` was pending. The captured timer
deadline is **25,868,670 guest microseconds**, with callback words
`[0x0006, 0x9064]`. Natural execution issued the original `AT+CMGL=4` retry and
consumed the real modem's `OK`; `F85B` became 1 at **183,618,928 TRX
instructions**, when the modeled BC5 clock read 26,060,931 microseconds.
No timer callback or successful AT response was supplied by the host.

The native clock at `0xFFB4:0xFFB5` advances one modeled microsecond per eight
BC5 instructions. This deterministic ratio is not calibrated to handset
hardware, so TRX instruction counts or host elapsed time alone are not a
physical retry-time oracle. The later trace supersedes an inference that the
scan could not complete under the supplied read-only card.

Its final diagnostic keys returned to the main **Menu** with **My Phonebook**
selected. A changed readiness flag therefore does not establish a usable
Messages GUI or a completed message workflow. The executed driver, timer-list
snapshot, actual transport bytes and LCDs are retained under
`/tmp/iridium-sim-http-scan-retry-runtime/`, including `probe.json`. Separate
HTTP Messages journeys must establish their own navigation and content
assertions; this diagnostic supplies no 9575 GUI result.

## Usable Messages and local preferences on both models

[test_factory_messages_local_e2e.py](../tests/test_factory_messages_local_e2e.py)
now has four passing HTTP journeys, each with fresh original BC5/AVR/TRX
workers and an explicitly attached read-only external card. The
[peer](../tests/factory_sim_peer.py) changes only SIM input levels and UART3
bytes; it never clocks a processor, touches DPL or replaces transport methods.
The tests wait at original home while the original scan finishes, then enter
and assert usable Messages. No successful modem response or ready flag is
supplied by the host.

The original handset cache words differ between the pinned profiles:

| Model | SMS capacity | Scan ready |
| --- | --- | --- |
| HT25003 9555 | `F875` | `F85B` |
| HL25003 9575 | `F8A6` | `F88B` |

The HL menu/predicate/accessor, CPMS callback and scan-completion setter were
independently decoded from its pinned bytes. A uniform address offset is not
a valid substitute for that model-specific path.

| HTTP journey | Assertions on both models |
| --- | --- |
| Empty folders and expiry | Exact original-font Inbox/Drafts/Outbox titles, selected `(empty)` rows, blank remaining rows and correct parent return; save/reopen 1 hour, 2 hours, 4 hours, 1 day, 2 days and 1 week; cancel a visible week draft while retaining two days; restore/read the original one-week default |
| Delivery Reports | Read original Off; save/reopen On, cancel a visible Off draft and retain On, then restore/read Off |

Literal glyphs and original radio assets independently check cursor focus and
stored selection. A saved mark can be offscreen during a draft; the decisive
saved/reopened/cancel-survival/restored frames put the checked mark in view.
Original factory-default writers explicitly set expiry to 168 hours through
PS key `29F` and delivery reports to zero through `2A0` on both models.

Preference selection intentionally closes on an original one-second timer.
On 9555, `0x84C32` starts the store and `0xB3B3A` schedules `0xB3BC0`, which
removes the selector after one million guest timer ticks. That needs about
eight million further modeled BC5 instructions. The tests allow a bounded
12M visible wait for the actual parent screen; they do not force the timer.
Earlier waits that ended before this close were test calibration errors,
not established preference-store failures. Their sources and outcomes remain
separate diagnostic history.

The final strict reports are
[9555 expiry](../test-artifacts/factory-sim-consumers/http/messages-expiry-9555.json),
[9575 expiry](../test-artifacts/factory-sim-consumers/http/messages-expiry-9575.json),
[9555 delivery reports](../test-artifacts/factory-sim-consumers/http/messages-delivery-9555.json)
and [9575 delivery reports](../test-artifacts/factory-sim-consumers/http/messages-delivery-9575.json).
Complete captures, original-byte evidence and excluded calibration history
are retained in the
[Messages archive](../test-artifacts/factory-sim-consumers/diagnostics/messages-local-expansion.tar.gz).
All 12 workers matched native `38fb483a…` and closed; all four external peers
closed. The 113 prior execution/test/fixture files stayed unchanged.

These are same-boot local preference and empty-folder assertions. They do not
establish SMS-setting restart retention, card writes, composed or stored
message content, service-center changes, PIN authentication or message
delivery. The existing missing-card/unavailable HTTP cases remain unchanged.

Later [composition tests](../tests/test_factory_messages_editor_e2e.py) on both
models assert complete text/count, the empty/bare-plus recipient guards,
add/cancel/remove without Send, text preservation and unsaved Exit followed by
empty Drafts and a fresh empty editor.
[Local draft tests](../tests/test_factory_messages_drafts_e2e.py) save and reopen
`123`, edit/resave/reopen full `1234`, preserve the draft after Delete No, then
confirm deletion and re-enter the empty folder after the original notifications.
[Warm-start cases](../tests/test_factory_messages_draft_persistence_e2e.py) also
reopen full `123` after completed shutdown and a second original startup/scan.
All eight HTTP cases pass with the read-only card and no UPDATE command.

GUI **Save as draft** calls original local-flash storage `C3980` on HT25003
or `DE066` on HL25003 with kind 2. It is independent of modem CMGW below.
The list preview and full editor glyphs/counter are checked separately.
Opening Edit removes the stored local entry before entering the editor;
those earlier readback cases end there and do not assert it stays saved afterward.
The last-delete callback closes the folder and returns to Messages with Drafts
selected; the tests re-enter to verify `(empty)`. An earlier automatic-folder
return expectation was a test error, retained as excluded calibration history.
Those earlier ASCII short-text passes do not prove maximum/multi-chunk content, Unicode or
cold-power retention.

Later [draft-action journeys](../tests/test_factory_messages_draft_actions_e2e.py)
pass on both models: empty Red adds no draft, nonempty Red autosaves `adg`
with full readback, and Delete All No preserves both short drafts while Yes
clears the folder. [Phonebook-recipient journeys](../tests/test_factory_messages_phonebook_recipient_e2e.py)
also pass: saved `Adg / +123` is reread, chooser cancellation adds nothing,
selection copies the original name and number, removal empties the recipient
list and unsent composition text survives. Read-only recipient-list observations
complement the visible `Adg` label; no Send action or card update occurs.

Two [multiple-number contact cases](../tests/test_factory_messages_contact_numbers_e2e.py)
extend that single-number path on both models. They save and reread all four
short local Home/Work/Mobile1/Mobile2 fields, comparing complete original-font
glyphs, remaining counts and actual field focus. The real number chooser
displays the four distinct values in order. Back from a tentative Mobile2
selection, then Back from the contact chooser, leaves no recipient. Separate
selections of Work `+456`, Mobile1 `+789` and Mobile2 `+246` each copy exactly
that terminated number and `Adg` into the original one-node recipient list;
both links are zero, and each Remove returns the list to empty. Complete
`adg` text/count survives returning to composition, and explicit Exit followed
by empty Drafts proves no incidental save.

These cases use the existing read-only card and actual original startup/scan.
Contact creation/readback takes place during the initial pending scan interval;
all processors continue normally, and Messages opens only after actual scan
readiness. No card update or Send occurs. The scope is four saved short phone
fields and the selected three non-default destinations, excluding Email,
other number formats, multiple simultaneous recipients, restart retention and
delivery. Their strict reports and source/capture provenance join the
`test-artifacts/factory-sim-phonebook/` phase evidence.

Four [SMS editor-tool cases](../tests/test_factory_messages_editor_tools_e2e.py)
also pass with the read-only card. They independently render the original
43-glyph symbol grid, its focused rectangle and blank unused cells, select
£/ø, cancel another selection and preserve exact text/counts through case and
numeric modes. Red autosave and full Edit readback verify `aD£ø42j`. Separate
English examples exercise LetterWise and WordWise Next alternatives,
punctuation, digits and Multi-Tap while preserving preceding text; explicit
Save and full Edit readback verify `$42a red`. Cleanup discards the Edit copy
and rereads empty Drafts. This establishes the selected Latin-1 symbols and
short English examples, not insertion of every listed glyph, all Unicode,
languages, dictionaries, cold-power retention or delivery.

Four rapid-input [long-entry regressions](../tests/test_factory_messages_draft_limits_e2e.py)
remain enabled and failing. Both intended 201-character storage and
1,000-character limit journeys stop at original BC5 panic 51 after 81 accepted
characters on 9555 and 70 on 9575. TRX is healthy. The failed allocation is a
nine-word deferred UI-event timer. A later read-only diagnostic identifies
the occupied nine-word blocks as the original outgoing key-tone command queue:
twenty queued nodes drain to zero during 10M idle instructions. This is pending
command ownership, not proof of a permanent renderer leak or allocator defect;
the underlying transport/model behavior and safe physical cadence remain
unestablished. These counts are not demonstrated capacity limits.

Four separate [patient cases](../tests/test_factory_messages_draft_patient_e2e.py)
keep fresh factory defaults and every full-length assertion, adding 2M normal
released instructions after each accepted key. They instead stop at the
previously traced TRX DSP-fatal reset signature after 53/52 characters, with
BC5 healthy. They do not pause the modem/DSP, change key tones or bypass a
queue consumer. Neither rapid nor patient cases reach the intended 201/1,000
input, overflow, storage or complete saved-readback milestones. See
[allocation evidence](sms-long-text-allocation.md)
and the [extended SMS evidence](../test-artifacts/factory-sms-extended/README.md).

Earlier reports, source proof and captures are in
[the SMS/drafts evidence directory](../test-artifacts/factory-sms-drafts/README.md).
Four old preference journeys passed again under the revised external-peer
helper; those reruns replace earlier evidence rather than adding case IDs.
The [preceding 200-outcome reconciliation](../test-artifacts/factory-sms-editor-settings/report.json)
retains the unchanged 186-case baseline and all fourteen new strict HTTP reports,
source proof, actual worker hashes and closures. Its diagnostic archives retain
the separate cadence investigations and excluded calibration history.

The original finite write boundary was researched in the retained
[write-contract investigation](../test-artifacts/factory-sim-consumers/diagnostics/sim-message-write-contract-next.tar.gz).
Original **modem CMGW** storage targets F202/`6F3C` with
`A0 DC record 04 B0`. This differs from GUI **Save as draft**, which writes
local BC5 flash without a SIM UPDATE RECORD.
Service-center parameters instead use F205/`6F42` and require SST service 12.
The original CSCA setter can return OK before its card write finishes, so
immediate cache/AT readback alone cannot establish service-center persistence.
The serial persistence boundary has the separate assertions below. Later
handset journeys also assert digit editing, cancellation, card commit/fault
and fresh warm-start readback, while the separate unchanged-save regression
exposes [address-type loss](service-center-type-preservation.md).

## Finite SMS writes and original serial readback

[MessageSIM](../tests/sim_message_card.py) extends the read-only storage card
with absolute UPDATE RECORD only for its two 176-byte SMS records and UPDATE
BINARY only for two-byte EF_SMSS `6F43`. It sends the T=0 procedure ACK before
accepting data and commits only a complete body. Reset/removal aborts an
incomplete transfer; completed external-card storage survives reinsertion.
Its explicit SMSS seed is `00 FF`; this is synthetic test data, not recovered
subscriber provisioning. Nine focused fixture checks assert fragmented writes,
procedure ordering, bounds, faults and incomplete-transfer handling.

[Four factory serial contracts](../tests/test_factory_sim_sms_write_contract.py)
pass on both profiles. A finite external DPL host accepts actual legacy `04`
and compact `81`–`87` packets, checks framing/XOR and sends physical ACK `06`.
It supplies AT commands and PDU input, never modem replies. The first command
uses sequence flag `01`; after the real CMGW prompt, the body uses DPL type
six. Type one is the command queue and cannot substitute for body input.

With CPMS set to SM and PDU mode selected, actual `AT+CMGW=13,2` accepts
`00010005912143F500000331D90C` plus Ctrl-Z. Original code normalizes its
message-reference byte to FF, then writes the complete record with status 7.
The tests assert exact card bytes and an unchanged second record before
accepting `+CMGW:001` and terminal OK. After genuine debounced removal,
reinsertion and storage reinitialization, actual CMGR returns status 002,
the exact stored PDU `0001FF05912143F500000331D90C`, and terminal OK.
The quoted alpha and printed length are not validated as correct.

The negative case makes this card return `9240` for the valid SMS write header.
The original modem returns `+CMS ERROR:322`; no DC procedure ACK, body,
record mutation or CMGW success is accepted. Cache/AT acknowledgement alone
would not prove persistence: these tests require card storage and a fresh
post-reinsertion read. They establish serial/card behavior, not GUI inbox,
outbox, sending, subscriber authentication or delivery.

## Service-center card commit versus early acknowledgement

[ServiceCenterSIM](../tests/sim_service_center_card.py) adds one 32-byte SMSP
record `6F42`, with four alpha bytes and the standard 28 parameter bytes.
Its synthetic SST `CC00C0` declares service 12 available. The explicit `E1`
indicator declares SCA/PID/DCS/validity present and destination absent; the
initial SCA is `+12345`, TON 145, with PID/DCS/validity zero. Only a valid SMSP
UPDATE RECORD can trigger its matched `9240` fault. Six pure checks cover
fragmented/atomic writes, bounds, reset, clock-stop and rejection.

[Four service-center contracts](../tests/test_factory_sim_service_center_contract.py)
pass on the original TRX under both profiles. Actual `AT+CSCA?` first returns
`"12345",145`. The original setter for `"+67890",145` returns OK at 112.4M
instructions; actual `A0 DC 01 04 20` starts only at 115.5M. The successful
control requires the complete independently specified 32-byte body, procedure
ACK and `9000` status, preserving every byte except the changed SCA.

The fault control receives `9240` without ACK/body/mutation. Its immediate
original query still returns `67890` from cache. After genuine removal,
reset/debounce settling, reinsertion and another physical SMSP READ RECORD,
the original query returns `67890` for committed storage and `12345` for the
failed write. Both final queries reach terminal OK at 173.5M instructions.
Thus early setter acknowledgement and cache readback do not prove persistence.
The tests also require no changes to the other declared card files.

These are serial/card contracts. Multiple SMSP records, every TON/address
format, absent-parameter normalization, cold-power
retention, authentication and delivery remain outside them. Earlier calibration
used absent PID/validity fields and incorrectly expected their unused bytes to
remain FF; original getters instead serialize fallback values. That assumption
and its original-source explanation are retained as diagnostic history.

## Handset Service Center editing and unchanged-save type loss

Four [HTTP Service Center cases](../tests/test_factory_messages_service_center_e2e.py)
pass on fresh complete factory handsets with the explicitly writable, finite
SMSP card. Original-font assertions check the complete number, caret and
actions; a visible tentative change is cancelled without a write. Held-zero
input produces the actual plus glyph before `+67890` entry. The tests require
the real `A0 DC 01 04 20` transaction, its complete 32-byte record and `9000`
status, or a matched `9240` rejection with no procedure ACK/body/mutation.
They then complete shutdown, perform original warm startup and observe a new
SMSP READ RECORD before checking the digits again. A committed write reloads
`67890`; a rejected write reloads the original `12345`, despite changed immediate
cache readback. Other declared card files remain unchanged.

These digit/persistence passes do not establish international address-type
preservation. The original BC5 query parser displays only quoted digits; its
setter omits the separate type parameter. Original TRX consequently uses
`81` hex even when the entered text contains a plus. Two enabled
[unchanged-save integrity cases](../tests/test_factory_messages_service_center_integrity_e2e.py)
demonstrate the loss without editing any input: the actual card write changes
only SMSP byte 18 from initial international type `91` to `81` hex. Every other
record byte remains identical. The complete address/type preservation assertion
fails ordinarily on both models; no sending or service request occurs.
See the [original-code and wire explanation](service-center-type-preservation.md).

Final component reports and captures are in
`test-artifacts/factory-sms-editor-settings/`. Its
`diagnostics/handset-service-center-expansion.tar.gz` and
`diagnostics/service-center-integrity-expansion.tar.gz` retain original listings,
font/wire/card audits and calibration history. The raw integrity driver scope
mistakenly says read-only; its unchanged raw bytes, actual writable SMSP fixture
identity and captured UPDATE RECORD are retained with an explicit provenance
correction. No general card filesystem, authentication, RF, delivery, cold-power
retention or every TON/number format is established.

An earlier card-absent modem trace returned `+CMS ERROR:322` for
`AT+CPMS="SM"`. Readiness helper `0xC7C24` accepts internal status 3, while
`0xC7AC4` maps status 1 to 322. `0x86B44` can generate status 1 while
`0x400AA30C` is zero. The wire-only capture did not identify its exact internal
branch. The later genuine post-card CPMS capacity reply is recorded above.

Iridium-specific `7F20/5F30` and `4Fxx` provisioning contents remain unresolved.
The fixture returns genuine file-not-found statuses for undeclared paths;
the observed storage initialization does not prove those paths are optional
for every operation. Original ADN metadata also checks status byte 11 masked
with `0x05`; the successful declared-metadata and record-consumer paths now
have the four assertions above. Other access/status combinations, complete
restricted-file/PIN2 behavior, complete ADN
reinsertion/delete/recovery, writes to other card files, broader SMS/contact encodings and capacity,
cold-power retention and removal during an incomplete write remain separate
work. DSP execution, subscriber authentication and RF/service delivery remain
outside these results. Supplying AT success or writing readiness flags would
bypass the original boundary.

Original-byte and cache-layout research is retained in
`/tmp/iridium-sim-contract-research/`,
`/tmp/iridium-sim-storage-next-contract/` and
`/tmp/iridium-sim-read-completion-static/`; early runtime traces remain under
`/tmp/iridium-sim-input-runtime/` and `/tmp/iridium-sim-read-runtime/`.
The shared TRX payload SHA256 is
`4f7939844993b28cae3031fa3da1b5bdb5c9546045cae1e0f6e42dd2d591e54b`.
The verified native executable SHA256 is
`38fb483abb45d87881ed4abeb7cc394374432b0ced066c5e159ecbf38ca9593e`.
Firmware files remain unchanged and are not committed.
