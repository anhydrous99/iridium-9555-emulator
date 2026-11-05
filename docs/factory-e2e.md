# Factory-firmware end-to-end coverage

This is the coverage ledger for the Iridium 9555 **HT25003** and standard
Iridium 9575 Extreme **HL25003** profiles. A passing suite establishes the
specific journeys it asserts. It does **not** establish that every handset
feature works, that the emulator matches physical hardware, or that a service
request reached an Iridium network.

The suite exposed and fixed reversed Call/End labels on both models and a
9575 restart that entered SOS mode. The idle board fixture had held active-low
PK0 SOS asserted. Power's PJ3 change triggered the original GPIO poll, which
generated an SOS event and saved emergency state. Reset now releases PK0;
the SOS API drives that pin through the executing AVR. Both factory power-cycle
tests and the physical SOS countdown/cancellation regression pass.

Both real-modem Phone Lock regressions remain enabled and failing. After fixing
startup sequencing and the 9575 USART assignment, 9555 exchanges actual AT
commands and displays **Phone locked** for the documented default PIN. It then
enters the original TRX DSP-fatal reboot path. On 9575, a separate SPI scheduling
fix restores complete modem commands and permits home after the original IERCC
and emergency-recipient warnings. Its TRX then takes the same DSP-fatal reboot
path during PIN entry. Later restart/PIN-gate, wrong-PIN rejection, unlock and
disable assertions have not been reached. A connected processor link alone is
insufficient evidence.

The captured fatal is background **modem DSP command queue full** (`0xFFFF`),
not an incorrect-PIN result. The model stores the DSP blobs embedded in TRX
but does not execute them or advance their queue consumer. The original burst
search command consequently fills the queue. See the
[hardware evidence](inferred-hardware.md#modem-timer-and-frame-interrupts).
The [DSP execution investigation](dsp-execution.md) records the embedded blobs,
observed HPI start/entry strobes, rings and IRQ routing. Original loading and
startup now have separate automated contracts; the exact Sapphyre core
configuration/instruction encoding is still missing.

The original 14-case run on 2026-11-04 found the restart issue; subsequent
targeted runs verified its fix. The expanded suite adds settings, keypad
locking, PIN form validation, real-modem Phone Lock, factory model uploads,
receiver fixes, voicemail configuration and Reset to Defaults.
Each journey starts fresh workers and executes its own boot.

The current aggregate has **236 HTTP cases: 210 passed, 26 failed,
0 errors and 0 skips**. Sixteen new cases cover stored-SIM Inbox actions,
selected preferences through completed shutdown and original warm startup,
every local Single/Repetitive Alert minute choice, and GPS geographic-range
robustness. They add 12 passes and 4 ordinary failures; every earlier outcome
and whole failure dictionary remains unchanged. See [stored SIM messages](stored-sim-messages.md)
and [GPS coordinate ranges](gps-coordinate-ranges.md) for the exact boundaries.
This combines completed component invocations, rather than one 236-case run.

The preceding aggregate has **220 HTTP cases: 198 passed, 22 failed,
0 errors and 0 skips**. The 220-case phase adds eight enabled cases, producing
four passes and four ordinary failures. Both models pass journeys for four
simultaneous phone recipients, including chooser cancellation and removals,
and selected Latin-1 contact-name save/reopen/cancel journeys. Four further
cases retain Save/shutdown/startup/full-readback assertions for all six fields
at their maximum lengths, separately under default Single Tone
and genuine configured No Tone. See [contact boundaries and persistence](contact-boundaries-persistence.md)
for exact reached stages and failure evidence. No earlier failure is reclassified.
This is component reconciliation, not one 220-case invocation.

The preceding aggregate has **212 HTTP cases: 194 passed, 18 failed, 0 errors and
0 skips**. It combines the frozen full 157-case run on 2026-11-04–05 UTC
(149 passed, 8 failed) with five passing targeted additions: two simultaneous
contact-limit journeys and three GPS coordinate-boundary journeys, then six
further passes: two extended-contact restart cases and four Messages cases.
Eight more passes cover composition/recipients, local draft editing/deletion
and draft retention through completed shutdown and warm startup. The four older
Messages cases also passed again after the external-card helper revision;
those reruns replace earlier evidence and are not additional case IDs.
Ten further journeys add six passes for Red/Delete All and saved-contact SMS
recipients, plus four enabled rapid-input long-entry failures. The preceding
14-case expansion adds eight passes: four Service Center save/cancel/card-fault/
warm-start journeys and four SMS symbol/input-mode journeys. Its six failures
are four patient long-entry cases and two unchanged-Service-Center integrity
cases, producing the previous **200 HTTP cases: 182 passed, 18 failed**.
The preceding six HTTP additions all passed: four read-only SIM-phonebook
empty/name/actions/return journeys and two multiple-number local-contact SMS
chooser journeys, producing **206 HTTP outcomes: 188 passed, 18 failed**.
The 212-case phase adds two passing direct SIM-to-SMS journeys, two passing
saved-SIM-shortcut journeys and two passing SIM-to-local Copy journeys. There
has not been a full 212-case run. Three earlier failures reach the
previously traced DSP-fatal path: both Phone Lock journeys and the 9575
Reset-to-Defaults contact/note journey while returning home. That last case
passes its retained-content assertions before the background modem halts.
Two signed-altitude cases expose an
[original HL25003 formatting defect](gps-altitude-sign.md). One maximum-length
email case exposes an [original exact-fit prefill defect](email-prefill-limit.md):
the editor accepts 74 characters but cannot reopen a saved address of that length.
Two GPS-validity cases expose an [original AVR byte-selection defect](gps-solution-validity.md):
an invalid 3D fix is accepted and a valid 2D fix is rejected.
The four rapid-input long-entry cases instead reach an original BC5 allocation panic:
9555 accepts 81 characters and 9575 accepts 70 in the final runs, then a
nine-word event-timer allocation fails while TRX remains healthy. A later
read-only diagnostic identifies a drainable outgoing key-tone command backlog
occupying the allocation pools. Its underlying transport/model behavior and a
safe physical cadence remain unresolved; these counts are not demonstrated
character limits or an established original firmware defect. Four separate
patient cases add 2M released original instructions per accepted key, retain
the full intended assertions and instead stop at the previously traced TRX
DSP-fatal reset signature, with BC5 healthy, after 53/52 characters. Neither
cadence reaches the intended 201-character storage boundary, 1,000-character
limit, overflow or complete saved-readback checks. See the
[allocation evidence](sms-long-text-allocation.md).

The two unchanged-Service-Center failures are a distinct data-integrity result:
without editing the displayed digits, GUI Save performs an actual SMSP update
that changes only byte 18 from `91` to `81` hex, losing the international address
type. The four passing Service Center workflows assert digit editing,
cancellation, actual committed/rejected card writes and fresh warm-start
readback; they do not establish preservation of international address semantics.
See the [address-type preservation evidence](service-center-type-preservation.md).

The full 157-case run used eight isolated per-case processes, each starting fresh
factory workers. All 107 execution/test source files and the native executable
stayed byte-identical throughout that run and the five subsequent HTTP targets.
Its 14 additions all passed: four call-option, six information/Help and four
further predictive-Notes cases. The independent
Help audit also checked 21 original bodies across 288 native viewports.
The preceding source snapshot had **133 execution/test/fixture files**, aggregate
SHA256 `cd8dbc63fedfd1bd51e168d0042571b9495e644cfd2ad1776e4ad45a4329d4d6`.
Its 129 earlier sources and native worker `38fb483a…` remained unchanged. Four
modules added Service Center GUI workflows, its unchanged-save integrity check,
SMS editor tools and patient long-entry regressions. The preceding 129-source
phase added SMSP card support and pure checks, original service-center serial
contracts, draft actions, rapid long-entry regressions and saved-contact SMS
selection; its four serial contracts and six pure checks still pass.
The earlier optional-card
helper revision and narrow delete-method source proof remain in that phase's
unchanged evidence; this phase needs no old-source exception or replacement.
The preceding snapshot had **138 execution/test/fixture files**, aggregate SHA256
`ce2c5486fa81a64fd7b63985e49f7da24755fccefb80ed49288b3e208f65041b`.
Its 133 earlier sources and native `38fb483a…` remained unchanged. Five files
add the finite writable ADN fixture and ten pure checks, original serial
phonebook contracts, read-only handset SIM views and the multiple-number SMS
chooser. The preceding snapshot has **141 execution/test/fixture files**, aggregate
SHA256 `b6c4d6347156318ff3bff6966b1feeb87c613790e7528c07ef8fd52db0d234eb`. All 138 preceding sources and native `38fb483a…` remain
unchanged; three new HTTP modules add direct SIM-to-SMS, saved SIM shortcuts
and SIM-to-local Copy. All eighteen prior HTTP failure IDs remain ordinary enabled failures,
including the
DSP failures whose required core configuration/instruction encoding is still
unavailable.

The preceding snapshot has **144 execution/test/fixture files**, aggregate SHA256
`0bef3606bf97b6cd2a25200160d6c42c0e99b19872e13abd50c7cf0cbcd032f4`. All 141 preceding sources
and native `38fb483a…` remain unchanged; only three new HTTP modules were added.
The current snapshot has **148 execution/test/fixture files**, aggregate SHA256
`6614fd70eb8ce8120ac1e85dccdd183f2a4bdf9d27044ea9aa5cad6736229b9e`. All 144 earlier files and
the native executable remain unchanged; four new HTTP modules provide this phase.

The full 157-case report, per-case JSON/logs/screens, source snapshot and
integrity audit remain in `test-artifacts/factory-local-completion/`. Its
`report-143-case-baseline.json` preserves the earlier aggregate. Historical
batch reports and their oracle-revision evidence remain available. The prior
168-case aggregate and ADN/Messages evidence remain in
`test-artifacts/factory-sim-consumers/`. The 176-case aggregate, its twelve HTTP
component reports and narrow source proof remain in
`test-artifacts/factory-sms-drafts/`. The preceding source proof, copied 176-case
baseline, ten new HTTP outcomes and four new serial outcomes are in
`test-artifacts/factory-sms-extended/`. Its diagnostic archives retain LCDs,
execution logs, original-byte research, excluded calibration history and the
complementary allocator diagnostic. Forced-function diagnostics are not E2E passes.
The previous 133-source proof, copied 186-case baseline, all fourteen HTTP
reports/logs and final reconciliation are in
`test-artifacts/factory-sms-editor-settings/`.
The previous 138-source proof, copied 200-case baseline, six passing HTTP
reports, four failing serial contracts and ten passing pure fixture checks are
in `test-artifacts/factory-sim-phonebook/`. The preceding 141-source proof, copied
206-case baseline, six new HTTP outcomes and excluded calibration are in
`test-artifacts/factory-sim-workflows/`. There are no new peripheral or pure
fixture IDs in that phase; the prior 34 peripheral outcomes and ten newest
pure fixture passes are inherited unchanged.
The preceding 144-source snapshot, copied 212-case baseline, eight new HTTP
component outcomes and diagnostic archives are in
`test-artifacts/factory-contact-coverage/`. No new peripheral or pure fixture
cases are added; all 34 peripheral outcomes and the ten newest pure checks
remain inherited evidence.
The current source snapshot, copied 220-case baseline, sixteen new HTTP
component outcomes and five diagnostic archives are in
`test-artifacts/factory-storage-settings-gps/`. No new peripheral or pure fixture
IDs are added.
The five preceding targeted HTTP reports and eight preceding
SIM file/storage contracts remain in `test-artifacts/factory-storage-expansion/`.
Original firmware binaries are excluded from the archives.

The identical current report is published at
`test-artifacts/factory-current-source/report.json` and
`test-artifacts/factory-e2e/report.json`; its `evidence_directory` points to
`test-artifacts/factory-storage-settings-gps/`. `./test-factory` discovers all 236
HTTP cases and executes them serially. There are **34 separate peripheral case
IDs: 30 passed and 4 failed**. The thirty passing GPS/DSP/SIM contracts are
unchanged: the earlier ten, four SIM file/cache/error cases and four
SIM storage/service-gating cases, four empty/populated ADN consumer cases,
then four SMS write/readback/error contracts and four service-center
commit/reload/rejection contracts. Four inherited ADN write contracts establish
partial original create/edit or rejected-edit/immediate-CPBR behavior, then
halt at the existing TRX DSP-reset signature during reinsertion. They are
ordinary failures; fresh reinserted readback, deletion and recovery remain
unreached. They are not four additional peripheral passes. The preceding pure
card-fixture checks, including the ten ADN-fixture checks, remain passing; fixture
checks are not handset feature passes. See [SIM phonebook workflows](sim-phonebook-workflows.md).
The firmware-free test script passes on the 148-source snapshot: Python discovery runs 480 cases
with 287 explicit fixture-dependent skips and 193 non-skipped cases. The
preceding 138-source run passed 450 Python cases with 257 fixture skips and
193 non-skipped cases. Current UI checks pass 25 cases. Native protocol discovery runs 59 cases:
41 pass and 18 require omitted fixtures. The sole hardware case is skipped,
so no hardware test executes in this check. Fixture skips are not successful
factory coverage.

## Running the factory suite

```sh
IRIDIUM_TEST_FIRMWARE=/path/to/9555 \
IRIDIUM_TEST_9575_FIRMWARE=/path/to/9575 \
./test-factory
```

To run just the 9575 power-cycle regression from the repository root:

```sh
zig build -j2
IRIDIUM_TEST_9575_FIRMWARE=/path/to/9575 PYTHONPATH=tests:. \
python3 -m unittest test_factory_e2e.Factory9575E2ETests.test_power_shutdown_and_reboot -v
```

The lower-level GPS checksum/publication contracts can be run separately:

```sh
IRIDIUM_TEST_9575_FIRMWARE=/path/to/9575 PYTHONPATH=tests:. \
python3 -m unittest test_factory_gps_receiver_contract -v
```

The dedicated runner requires both directories with BC5, AVR and telephony TRX
images. Missing fixtures, a fixture
for the wrong model, and a payload that differs from the recorded factory
hashes are errors. Firmware is supplied locally and is never committed to the
repository. The 9575 acquisition procedure and inspected package identities
are in [firmware evidence](9575-firmware.md). The 9555 identities were already
recorded in the [performance baseline](performance/baseline.json). Hashes pin
these inspected copies; they do not establish manufacturer signature trust.

Ordinary `./test` remains useful without proprietary firmware. Its opt-in
factory suites explicitly skip an omitted firmware directory; those skips
must not be reported as successful factory coverage. A supported layout or a
valid container CRC alone does not prove factory byte identity: the emulator
also supports deliberately modified images.

The runner writes `test-artifacts/factory-e2e/report.json` with successful test
IDs, failure details, timing and loaded firmware identities. It invalidates a
previous report before preflight/build, so a failed invocation cannot leave a
stale passing report. Each journey saves its final state and LCD;
screen-wait failures also save the timeout state as JSON and a PNG. Set
`IRIDIUM_E2E_ARTIFACTS` to choose another artifact directory. Empty runs, skips
and expected failures make the dedicated runner fail.

The fixture in [factory_handset.py](../tests/factory_handset.py) starts the
real HTTP server with native BC5 and AVR workers. Tests send the same API
requests as the handset UI and observe the executing firmware's LCD output.
This covers HTTP, session scheduling, the coupled board, original
instructions, keypad handling and display decoding. Browser layout and DOM
event delivery remain outside this boundary.

Startup provisions initially absent settings through original factory code,
then warm resets with the AVR power input released. Board identification uses
the documented virtual AIO0=640 fixture. See [architecture](architecture.md)
and [inferred hardware](inferred-hardware.md) for the implemented contracts.
Local UI journeys load BC5/AVR. Modem-dependent journeys request
`FactoryHandset(..., modem=True)` and load the hash-pinned original telephony
image too. A connected processor link does not establish service registration.

## Status meanings

| Status | Meaning |
| --- | --- |
| Tested | A named automated assertion exercises the stated behavior using factory instructions. The scope column limits the claim. |
| Failing | The asserted journey ran and found a behavior mismatch. The strict suite stays failing until it is resolved. |
| Pending | A useful journey remains to be asserted. No success is implied by reaching its menu or by the absence of a crash. |
| Blocked | The complete journey needs a missing device or service contract. Menu behavior may still be testable separately. |
| N/A | The feature is specific to the other handset profile. |

## Asserted HTTP journeys

| Suite | Models | Observable results |
| --- | --- | --- |
| [Shared journeys](../tests/test_factory_e2e.py) | Both | Boot to readable home; select, open and leave all nine main menus; Help through both entry points; absent-SIM and SMS configuration errors; USB connection prompt. |
| Shared journeys, dialing | Both | Render every digit plus star/hash, delete and restore the final character, cancel to home. |
| Shared journeys, power | Both | Hold the AVR power input, observe completed shutdown and assert restart to a working menu without an unintended SOS event. |
| Shared journeys, session controls | Both | Running advances both processors; pause holds instruction counts; manual step advances; two clients share one actual menu key; reset clears held input/display, rejects a stale epoch and permits a fresh boot. |
| [Local phonebook](../tests/test_factory_phonebook_e2e.py) | Both | Create and reopen `Adg / +123`, edit and reopen `Adj / +1234`, decline deletion, then confirm deletion and return to an empty phonebook. |
| [Call controls](../tests/test_factory_calls_e2e.py) | Both | Green opens empty dialed-call history; red returns home and cancels number entry; green with `+12` shows the original pending call-request screen. No modem or completed call is asserted. |
| [Extreme journeys](../tests/test_factory_extreme_e2e.py) | 9575 | Decline GPS enable and return home; accept and reopen Current Location with blank coordinates and Updating status; advance SOS from 20 to 19 and cancel, twice. |
| [Settings](../tests/test_factory_settings_e2e.py) | Both | Save, reopen, cancel a tentative reversal and restore ringer/speaker volume, backlight/contrast, time/date formats and tone/vibration choices. |
| [Local security](../tests/test_factory_security_e2e.py) | Both | Lock keypad, reject ordinary digits, unlock and restore dialing; reject missing and mismatched PIN form fields while masking input. |
| Security with original TRX | Both | Assert enabling Phone Lock, restart PIN enforcement, wrong-PIN rejection and correct unlock/disable. Both fail with original TRX DSP-fatal resets: 9555 after enable success, 9575 during PIN entry. Later stages remain unexecuted. |
| [Factory model uploads](../tests/test_factory_model_switch_e2e.py) | Both | Upload original BC5/AVR images in both directions, retire prior workers, invalidate held browser input and boot the resulting model's controls. |
| [GPS receiver](../tests/test_factory_gps_e2e.py) | 9575 | Enable through the handset, supply external UBX/NMEA on AVR USART0, acknowledge actual receiver configuration requests, assert coordinates/altitude/eight satellites on the original LCD, then return home and reopen the retained fix. RF acquisition and time synchronization are excluded. |
| [GPS coordinate boundaries](../tests/test_factory_gps_coordinate_limits_e2e.py) | 9575 | RealTime external receiver epochs cross equator/prime-meridian zero, reach legal exact ±90° poles and ±180° dateline endpoints, and recover to nearby coordinates. Assert fresh publication, parsed cache, complete original-font latitude/longitude/satellite rows, reopening and cached decimal/DMS reformatting without new receiver bytes. Invalid coordinate ranges and RF acquisition are excluded. |
| [Signed-altitude regressions](../tests/test_factory_gps_negative_e2e.py) | 9575 | In RealTime mode, deliver a second South/East epoch with nine satellites and -5m, assert updated coordinates/count and preserved parsed sign, then require -16ft or -5m. Both cases currently fail at the original unsigned formatter. |
| [Voicemail configuration](../tests/test_factory_voicemail_e2e.py) | Both | Save and reopen an edited voicemail number, cancel a tentative deletion and restore the original number. No voicemail call is completed. |
| [Reset to Defaults](../tests/test_factory_reset_e2e.py) | Both | Change ringer volume, decline a settings reset and assert the change survives, then confirm reset and assert the original default is restored. |
| [Customization](../tests/test_factory_customization_e2e.py) | Both | Save/reopen/cancel/restore English/French menu language, English/Multi-Tap editor mode, convenience-key phonebook assignment, all three right-soft choices and all three number prefixes. Assert translated widgets, editor headers, shortcut destinations and rendered `+12` / `0012` / `12`. |
| [Contact details](../tests/test_factory_phonebook_details_e2e.py) | Both | Save/reopen notes, observe a tentative `Ad` edit then cancel back to saved `Adg`, display used-memory changes 0→1→0, accept/save/reopen 64 note characters and reject an extra character. |
| [Selected Latin-1 contact names](../tests/test_factory_phonebook_latin1_e2e.py) | Both | Complete original symbol-grid/focus checks; save/reopen A£øé and +123; cancel a symbol and a visible Backspace edit, retaining both saved fields. Other Unicode, sort/case behavior and power retention remain unasserted. |
| [Multiple SMS recipients](../tests/test_factory_messages_multiple_recipients_e2e.py) | Both | Four simultaneous phone recipients with complete ordered LCD rows and original five-word links/NUL data; chooser cancellation, first/middle/last removal, retained body and explicit discard/empty Drafts. Separate saved Email eligibility; no Send or mixed phone-and-email coexistence claim. |
| [Maximum-field warm startup](../tests/test_factory_phonebook_limits_persistence_e2e.py) | Both | Default Single Tone and separately saved No Tone variants retain input/overflow checks for Name and four phones at 24 characters and Email at 64, original Save/completed shutdown/warm startup and every hidden saved glyph/count. All four halt before Save, completed shutdown and warm readback; these are intended requirements, not reached persistence evidence. No Tone must also restore/reopen Single Tone, which remains unreached. |
| [Alphabetical contact lookup](../tests/test_factory_phonebook_search_e2e.py) | Both | Create D/+123 before A/+456, assert A/D sorting and both saved details, navigate with arrow keys, close/reopen and reread the selected contact. Numeric incremental search is not asserted. |
| [Call settings](../tests/test_factory_call_settings_e2e.py) | Both | Assert all three empty history titles, zero counters, reset No/Yes and zero readback; save/cancel/restore display and audible-timer preferences; hold 1 to reach the original pending voicemail request. No active call, elapsed timing or sound is asserted. |
| [Extreme settings](../tests/test_factory_extreme_settings_e2e.py) | 9575 | Save/reopen/cancel/restore GPS modes and permission; assert prompt gating, the external-input condition and actual receiver power/standby; protect edits with the GPS PIN; render supplied coordinates in decimal/meters and DMS/feet; configure Emergency Actions/Beep, manage a message recipient and reject empty/short IERCC input. |
| [Convenience actions](../tests/test_factory_convenience_e2e.py) | Both | Save/read back/cancel Start Call, End Call, Redial, SIM phonebook, Messages and Call Voicemail assignments. Assert pending requests, original unavailable errors, and the End Call idle/number-entry guard. Active-call termination and service completion are excluded. |
| [Extended text entry](../tests/test_factory_text_entry_e2e.py) | Both | Rapid repeated 2 selects C; original commit waits produce Ca/Caa. Cycle case/numeric modes, enter AaD4j@@ through punctuation and the symbol picker, cancel another symbol, then save/leave/reopen actual names and +123. Guest instruction intervals are not calibrated physical timing. |
| [Location configuration](../tests/test_factory_location_config_e2e.py) | 9575 | Change GPS PIN 3333→2468, reject the old PIN, use the new PIN, restore 3333 and verify it. Save/cancel/restore three report frequencies and numeric recipients; copy a real phonebook number and retain it after deleting the source. Add Quick GPS recipients from first/last empty rows, assert compaction and Delete All No/Yes; cancel portal registration and retain Not registered status. No service request is delivered. |
| [Persistence with original TRX](../tests/test_factory_persistence_e2e.py) | Both | Saved ringer/contact/note survive completed shutdown and warm startup; a restored default ringer also survives restart. Reset to Defaults preserves saved contact/note content. That last 9575 journey fails during its final return home with the existing DSP-fatal signature; its retained-content assertions pass. [Startup evidence](phonebook-startup.md) explains why genuine modem traffic must initialize the saved index. |
| [Extended contact persistence](../tests/test_factory_phonebook_fields_persistence_e2e.py) | Both | Save six distinct short Name/Home/Work/Mobile1/Mobile2/Email values and a note; independently check complete field glyphs, counts and actual focus. Cancel a visible Work `+450` draft, complete shutdown and original modem-driven warm startup, then reread all six fields, retained Work `+456` and the note before returning to healthy home. Maximum-length, Unicode and cold-power retention are excluded. |
| [Messages with an external read-only SIM](../tests/test_factory_messages_local_e2e.py) | Both | Four fresh-worker cases wait for the original scan to complete, then enter usable Messages. Expiry cases assert titled empty Inbox/Drafts/Outbox lists and save/reopen all six expiry choices, cancel a visible change and restore the original one-week default. Separate Delivery Reports cases save/reopen On, cancel Off and restore/read Off. Original radio assets prove stored marks separately from cursor focus. No card write, message composition/save, service-center operation or delivery is asserted. |
| [Stored SIM Inbox actions](../tests/test_factory_messages_inbox_e2e.py) | Both | Four passing journeys read the full preloaded adg/+12345 message, assert exact original sender nodes for Reply, edit/cancel Reply, clear Forward recipients, retain the stored record and leave empty Drafts. Delete No preserves all 176 bytes; Yes actually frees status 00 with PDU retained, then empty Inbox/Home. Enumeration marks 03→01 before explicit Read; no RF reception or Send/Call. |
| [Selected settings across warm startup](../tests/test_factory_settings_persistence_e2e.py) | Both | Four passing cases retain French, No Tone, prefix 00, timezone +0.5, am/pm, slash date and 10-second backlight through completed shutdown and original boot two, then cancel drafts and restore defaults. French startup/Setup/Language widgets and softkeys use original-font/source predicates; prefix dispatch must produce 0012 then +12. See component outcomes for reached stages. |
| [All call-alert minute choices](../tests/test_factory_call_alert_choices_e2e.py) | Both | Single and Repetitive Alert each require 1/5/10/15/30/60 saved/reopened with original-font labels and actual radio marks, upper/lower bounds, cancelled Off draft and restored/reopened Off/Home. This establishes preferences, not elapsed alerts or sound. |
| [Invalid GPS geographic ranges](../tests/test_factory_gps_range_e2e.py) | 9575 | Four ordinary robustness failures: checksum-valid complete epochs with±91 latitude or±181 longitude replace the last valid cache and LCD. Initial complete control passes; legal recovery/reopen/Home remain enabled but unreached. All3processors stay healthy; no real-receiver/RF promise. |
| [Messages composition and recipients](../tests/test_factory_messages_editor_e2e.py) | Both | Assert complete `adg` text and remaining count, reject empty and bare-plus recipient input, add/cancel/remove local recipients without Send, retain text on return, clear one character and exit. Reopening Drafts asserts `(empty)`; a fresh composition is empty. No number syntax beyond these guards or message delivery is claimed. |
| [SMS editor tools](../tests/test_factory_messages_editor_tools_e2e.py) | Both | Compare all 43 original picker glyphs, their order, focused rectangle and unused cells; select £/ø, cancel another symbol, change case/numeric modes and Red-save/reopen complete `aD£ø42j`. Separate cases exercise short English LetterWise/WordWise and punctuation Next alternatives through numeric/Multi-Tap transitions, explicitly save and reopen complete `$42a red`. Both clean up to empty Drafts. Other symbols, languages and dictionaries are excluded. |
| [Local Messages drafts](../tests/test_factory_messages_drafts_e2e.py) | Both | Save `123` into local flash, observe the original toast and natural close, reopen full text, edit to `1234`, retain it through Options→Back, resave and reopen complete text. Separate cases decline deletion and retain the draft, then confirm deletion, observe both original notifications, re-enter Drafts and assert empty. |
| [Local draft warm-start retention](../tests/test_factory_messages_draft_persistence_e2e.py) | Both | Save `123`, complete shutdown with BC5 power state 8/UI uninitialized, execute a second original startup/scan, then reopen the draft preview and full text/count. Cold-power retention and maximum-length content are excluded. |
| [Draft Red and Delete All actions](../tests/test_factory_messages_draft_actions_e2e.py) | Both | Red leaves an empty editor unsaved, autosaves nonempty `adg`, and full Edit readback verifies text/count. Separate cases retain both `789`/`123` after Delete All No and folder reopening; Yes displays All Messages Deleted and leaves Drafts empty. |
| [Saved phonebook SMS recipient](../tests/test_factory_messages_phonebook_recipient_e2e.py) | Both | Create/reread saved `Adg / +123`; cancel contact selection without adding, then select it, assert visible name and read-only original name/number copy, remove without Send, preserve composition and Exit to empty Drafts. Full model-specific chooser rows include Quick GPS List only on 9575. |
| [Multiple saved contact phone numbers](../tests/test_factory_messages_contact_numbers_e2e.py) | Both | Save/reread `Adg` and all four distinct short Home/Work/Mobile1/Mobile2 numbers with complete glyphs, counts and field focus. Back out of a tentative number selection without adding; separately select Work `+456`, Mobile1 `+789` and Mobile2 `+246`, inspect each exact original one-node name/number copy, then remove it. The `adg` composition survives; explicit Exit leaves Drafts empty. Email, simultaneous multiple recipients and sending are excluded. |
| [Read-only handset SIM phonebook](../tests/test_factory_sim_phonebook_e2e.py) | Both | Four fresh-worker cases verify original ADN consumption, then actual SIM Phonebook navigation. Empty cards show literal `(Empty)`, blank left caption and Back; populated cards show selected `Adg` and only the original Call/SMS/Copy actions. Both return to healthy Home without card mutation or writes. These four display-only cases do not activate the actions; separate SMS/Copy journeys appear below. |
| [Direct SIM-to-SMS](../tests/test_factory_messages_sim_recipient_e2e.py) | Both | Actual SIM Phonebook→SMS opens New/1000, then complete `adg`/997. The default optional name resolver is unset; read-only original nodes contain exact `+12345` with a null name and both links zero, and Send To renders that number. Remove empties the list; text survives and Exit leaves Drafts empty/Home. No Send or card update occurs. |
| [Saved SIM shortcuts](../tests/test_factory_sim_shortcuts_e2e.py) | Both | Save/readback/cancel convenience-key and right-soft-key SIM assignments, then activate both against the ready populated card. Each opens selected Adg and the original Call/SMS/Copy menu, and Back returns to Home. Restore/read No Action on 9555 or Location on 9575, and Show Help, including saved radio marks and Home captions. Card records remain unchanged; actions are not activated. |
| [SIM-to-local Copy](../tests/test_factory_sim_phonebook_copy_e2e.py) | Both | Both final cases pass. Require the original complete success message; reread local Name Adg/Home +12345, three empty secondary phones, empty Email and Notes. A focused empty phone may temporarily show only its configured plus prefix, which clears on blur. Cancel a visible Ad name draft and reread Adg/all fields, then reopen the unchanged SIM entry. Same-boot one-record Copy only; no SIM programming or delivery. |
| [Rapid long draft entry regressions](../tests/test_factory_messages_draft_limits_e2e.py) | Both | Retain complete intended 201-character cross-chunk save/full-glyph readback and 1,000-character overflow/backspace/resave/readback journeys. All four stop earlier at BC5 panic 51 after 81/70 accepted characters, with TRX healthy. A separate diagnostic identifies drainable key-tone command backlog and pool pressure; no later milestone or fixed character limit is verified. |
| [Patient long draft regressions](../tests/test_factory_messages_draft_patient_e2e.py) | Both | Separate fresh factory-default cases add 2M normal released instructions after each accepted key. All four stop at the existing TRX DSP-fatal reset signature after 53/52 characters, with BC5 healthy. Full 201/1,000-character, overflow, save and readback assertions remain enabled and unreached. |
| [Handset Service Center](../tests/test_factory_messages_service_center_e2e.py) | Both | Assert complete digit/caret forms, visible cancel/no write, held-zero plus input and `+67890` entry. Require the actual SMSP commit or `9240` rejection, then completed shutdown, original fresh SMSP read and correct digits after warm startup. Four passes do not prove international type preservation: the GUI omits TON and the modem defaults to `81` hex. |
| [Unchanged Service Center integrity](../tests/test_factory_messages_service_center_integrity_e2e.py) | Both | Two ordinary failures: Save without editing digits emits an actual 32-byte SMSP update, changing only byte 18 from international type `91` to `81` hex. All other record bytes remain identical. No sending or delivery is attempted. |
| [Extreme No Action](../tests/test_factory_convenience_no_action_e2e.py) | 9575 | Save/reopen No Action, cancel a visible Location draft, assert delivered convenience-key presses preserve idle Home and entered +12, then restore Location and assert the actual GPS-enable prompt. |
| [Phonebook capacity and required name](../tests/test_factory_phonebook_capacity_e2e.py) | Both | Reject unnamed-number Save without consuming a slot, then save/read a named control. Save 100 distinct contacts with every draft field checked, assert 99/100 counts and first/middle/last saved records, reject entry 101 while retaining its draft, cancel/confirm deletion, then save/read that previously rejected contact into the freed capacity. Saved-record integrity is sampled; cold-power retention and physical flash-slot reuse are excluded. |
| [Additional menu languages](../tests/test_factory_languages_e2e.py) | Both | Save/reopen/cancel/restore all 22 remaining menu locales, including CJK, Cyrillic and RTL scripts. Compare complete Language parent/selector screens and soft keys, independently check translated Text Entry glyphs against original resources, and restore English. Other translated screens and language-dependent input remain unasserted. |
| [Emergency configuration](../tests/test_factory_emergency_config_e2e.py) | 9575 | Save/reopen/cancel/restore Call Only; manage voice/email recipients; copy a real contact and retain its number after source deletion; fill all three message-recipient slots, replace the last, cancel edits, delete/compact/reuse and Delete All No/Yes. Assert the 74-character email input boundary separately from its failing saved-value reopening. No request is delivered. |
| [Location limits](../tests/test_factory_location_limits_e2e.py) | 9575 | Save/reopen/cancel all 14 report frequencies and restore No Update. Fill all five Quick GPS slots, clamp navigation, replace the last with a sixth distinct number, delete/compact/refill, reread all five and Delete All No/Yes. Save/read/edit/cancel/delete an email recipient and leave blank Save empty. No elapsed schedule or delivery is asserted. |
| [Cursor editing and held shortcuts](../tests/test_factory_cursor_shortcuts_e2e.py) | Both | Move backward/forward in name and number fields, insert/delete, save and reopen complete Adjm/+12964. Compare brief literal 0/star with held plus/comma, assert exact held/released fields and no extra release character, then save/reopen Adg/+12,9. Guest instruction holds are not physical timing; no call or pause audio is asserted. |
| [Predictive Notes](../tests/test_factory_prediction_e2e.py) | Both | English LetterWise f→Next d→don't and WordWise see→Next red; French Bonjour and été→Next due; Spanish Hoja→Next Hola and inverted ¡/¿. Check original-font words, modes/counts/trailing blanks, save/reopen, cancel a changed draft, delete the contact and restore/read back Multi-Tap. These examples do not establish complete dictionaries. |
| [Extended contact fields](../tests/test_factory_phonebook_fields_e2e.py) | Both | Save/reopen distinct Name, Home, Work, Mobile1, Mobile2 and Email; cancel a visible Work edit and retain all six. Exercise 24-character name/phone and 64-character email limits, rejected extra input and slot recovery. Save/reopen complete 24-character fields and both 63/64-character emails; check all hidden glyph windows and remaining counts. A fresh full-name cursor-at-end action stays healthy. Same-boot readback is asserted; wider restart/stress behavior is excluded. |
| [Simultaneous contact maxima](../tests/test_factory_phonebook_combined_limits_e2e.py) | Both | Select No Prefix, fill Name and all four distinct bare numbers to 24 characters and Email to 64 in one contact, reject extra phone input, save and inspect every hidden glyph window/count in all six fields. Cancel a visible maximum-length Work edit and reread all six saved values; restore Plus and assert dialer +12. Unicode and restart retention of this contact are excluded. |
| [GPS validity and recovery](../tests/test_factory_gps_validity_e2e.py) | 9575 | Corrupt UBX, missing/bad/incomplete NMEA, mixed epochs and complete no-fix data preserve the last valid fix, then valid data updates cache and LCD. Two enabled failures expose invalid-3D acceptance and valid-2D rejection in the original AVR; the 2D fixture retains its previous altitude. Radio acquisition, service and fix age are excluded. |
| [Call-option gates](../tests/test_factory_call_options_e2e.py) | Both | Waiting, Forwarding and Barring show original network-unavailable errors and reopen. A visible Fixed Dialling Enabled draft is cancelled; reopening retains Disabled. No successful supplementary service, SIM/PIN2 authentication or card persistence is asserted. |
| [Information and Help](../tests/test_factory_information_help_e2e.py) | Both | Setup and the actual keypad shortcut show original build strings and literal identity placeholders, with page bounds/back/reopening. Check every English Help topic (six on 9555, nine on 9575), both Text Entry sub-bodies, Spanish predictive punctuation/Multi-Tap help, viewport glyphs/scroll bounds and language restoration. Actual IMEI and physical hardware identity are excluded. |
| [Further predictive Notes modes](../tests/test_factory_prediction_modes_e2e.py) | Both | Exercise the eight remaining supported punctuation groups, Next/wrap, save/reopen and visible draft cancellation. WordWise produces saved/reopened `red red,red42 red` through spaces, inline comma, literal digits and ww→lw→#?@→123→Abc→ww, preserving prior glyphs/counts. Broader Help character availability in other editor contexts remains unresolved. |

Each scenario gets fresh native workers. LCD expectations are known-answer
pixel crops; transient status icons and blinking caret regions are excluded
where needed. The strict report records which tests ran and their outcomes;
the table is an assertion inventory, not a claim about unlisted behavior.

The inventory combines observed firmware behavior with the Extreme manual's
feature families. Exact shared-menu options and model differences still need
execution evidence. HL25003 release changes take precedence over older manual
GPS/emergency descriptions; see [9575 firmware evidence](9575-firmware.md).

Additional factory execution assertions in
[test_integration.py](../tests/test_integration.py) verify intermediate
animation frames and deliberate instruction mutations. Original-image tests
in [native/test_protocol.py](../native/test_protocol.py) verify the full
electrical matrix and original power-state transitions. These are lower-level
evidence, distinguished from the HTTP journeys above.

[GPS receiver contracts](../tests/test_factory_gps_receiver_contract.py) run
the original 9575 AVR parser directly: corrupt UBX/NMEA checksums and incomplete
epochs must not publish a position; complete receiver data must produce the
exact packed SPI register. They do not replace the separate HTTP LCD assertion.

[DSP startup contracts](../tests/test_factory_dsp_contract.py) run original TRX
reset under both model profiles and compare all four observed program/data
copies with the pinned payload. They assert the complete HPI entry/start write
sequence without forced calls or dropped trace events. They do not establish
DSP instruction execution or service completion.

[SIM contracts](../tests/test_factory_sim_contract.py) add three natural
original-TRX journeys per model: insertion/debounce/reset accepts external ATR
and emits the actual SELECT/data for Iridium DF `7F20`; removal aborts the
exchange; an invalid ATR causes another reset without a command; retained high
input is detected after warm startup. No host writes guest RAM or forces calls.
Those initial cases supply no SELECT success, file metadata or service.
These initial edge/ATR contracts are complemented by
[SIM file contracts](../tests/test_factory_sim_file_contract.py): actual SELECT,
metadata and READ BINARY publish two distinct synthetic language preferences in
the original F100 cache; an external card memory error publishes failure
without file data. [SIM storage contracts](../tests/test_factory_sim_storage_contract.py)
then supply the same read-only card geometry with SMS enabled or disabled in
SST. Both model profiles consume F107 SST. Enabled SMS reads actual `6F3C`
metadata and records 1/2, reaching capacity 2, flags 3 and controller state 1;
disabled SMS issues no `6F3C` SELECT/read and retains zero capacity/controller
through 120 million total original instructions. No guest RAM writes or forced
calls are used. The [SIM boundary](sim-device-contract.md) records this local
device contract and the remaining GUI/provisioning/authentication work.

[ADN consumer contracts](../tests/test_factory_sim_phonebook_contract.py) add
four natural original-TRX cases. Each model reads the declared `6F3A` geometry
and both records, changes capacity from the original default to two, and
completes initialization. A populated `Adg / +12345` record additionally sets
used count one, the original name cache, compact digit index and lookup order.
The compact index is not full-number/TON or handset SIM-phonebook readback.

[ADN write contracts](../tests/test_factory_sim_phonebook_write_contract.py) retain
four ordinary peripheral failures, distinct from those passing read-only cache
cases. The finite [ADN card](../tests/sim_phonebook_card.py) accepts only complete
declared `6F3A` record updates. Original CPBW/CPBR use logical indices 101..102,
after the 100 local slots; physical card records remain 1..2. Positive runs on
both models actually create `Adg / +12345`, edit it to `B / 67`, and read back
complete names, numbers and types immediately. Negative runs create the initial
entry, reject its edit with card `9240`, observe original `+CME ERROR:003` and
read the unchanged initial entry. All four later halt during natural
reinsertion at the existing TRX DSP-reset signature. Fresh post-reinsertion
readback, deletion and recovery remain enabled and unreached. Ten passing pure
checks establish the finite card fixture, not successful complete modem
workflows. The [SIM phonebook evidence](sim-phonebook-workflows.md) distinguishes
these partial serial results from the four passing handset display cases.

[SMS write contracts](../tests/test_factory_sim_sms_write_contract.py) add four
ordinary peripheral passes. On each model, the original modem accepts CMGW
over the external serial DPL channel, writes one complete 176-byte SMS card
record, then reads the exact stored PDU through CMGR after natural card removal
and reinsertion. An external `9240` write failure instead yields the original
`+CMS ERROR:322` without committing a record. The finite
[writable card](../tests/sim_message_card.py) models only SMS and its associated
status file; it supplies no successful AT response. CMGR's quoted alpha and
printed length are outside these assertions. These serial contracts are
separate from HTTP GUI drafts, which the original BC5 stores in local flash.

The Messages HTTP cases use [factory_sim_peer.py](../tests/factory_sim_peer.py)
only for physical card inputs and UART3 responses. The peer never clocks CPUs,
touches DPL/UART1 or replaces transport methods. The original failed startup
scan retries after 20M guest timer ticks; the tests allow it to finish. Preference
commits also schedule an original one-second delayed close. Bounded visible
waits allow that timer, rather than treating an unchanged early selector as a
failed store. The inferred clock is not calibrated physical handset timing.

## Shared handset features

| Feature family and subfeatures | 9555 | 9575 | Evidence, remaining scope or blocker |
| --- | --- | --- | --- |
| Factory BC5/AVR/TRX identity and matching handset profile | Tested | Tested | E2E fixture pins loaded payload hashes; the strict runner preflights all three processors. Release names inferred only from lengths are insufficient. |
| Initial settings, warm startup, animation, readable home captions | Tested | Tested | HTTP boot reaches home; lower-level integration tests additionally verify successive animation frames. Network registration is excluded. |
| All nine main menu entries, select/back, Help and unavailable-path errors | Tested | Tested | HTTP tests open each top-level entry and return, check the Help shortcut, missing-SIM error, SMS configuration error and USB prompt. Submenu completeness is not established. |
| English Help bodies and English/Spanish Text Entry help | Tested | Tested | Assert every available English topic (six on 9555, nine on 9575), including both Text Entry sub-bodies and Extreme additions. Independent original-font viewports cover scrolling and bounds; Spanish predictive punctuation/Multi-Tap bodies and language restoration are asserted. Other Help locales remain unverified. |
| Electrical keypad press/release: digits, star/hash, navigation, soft keys, call/end and side controls | Tested | Tested | Native original-image tests exercise matrix contacts, GPIO/IRQ/debounce and release. Context-specific actions for every key remain pending. SOS is separate below. |
| Power input polarity, released operation and held shutdown/restart | Tested | Tested | Both enter completed shutdown and restart to a working menu. PK0 SOS is released independently from PJ3 Power on 9575. Physical power consumption and timing are unverified. |
| Dialer entry: every digit, star/hash, deleting/replacing a character and cancel | Tested | Tested | HTTP assertions compare rendered `0123456789*#` before and after editing and verify return home. Saved prefixes are tested separately; long-press entry shortcuts and connected redial remain unverified. |
| Keypad locking/unlocking and ordinary-digit rejection | Tested | Tested | Original lock/unlock prompts, rejected digits and subsequent restored dialing are asserted through HTTP. |
| Held-key and repeat behavior in every context | Pending | Pending | Electrical delivery and one keypad-lock journey do not establish contextual repeat behavior. |
| Basic name/number entry and correction | Tested | Tested | Phonebook lifecycle asserts saved and reopened name/number pixels after entry and editing. |
| Required contact name and failed-save recovery | Tested | Tested | Number-only Save shows Please enter a name, retains the draft and leaves usage zero. The same Save path succeeds after entering Adg; usage becomes one and Adg/+1 reopens. |
| Saved English LetterWise/Multi-Tap mode and contact-editor selection | Tested | Tested | Both models save/read back/cancel/restore the choice and assert actual Lw/Abc editor headers. Prediction quality is not established by a mode indicator. |
| Multi-tap repeated-key/commit behavior, case/numeric cycle and symbol selection/cancel | Tested | Tested | Actual C→Ca→Caa and AaD4j@@ glyphs are asserted, saved, left and reopened. Complete saved names independently match the original font. Intervals are guest-instruction budgets. |
| Side-key cursor editing in contact names and numbers | Tested | Tested | Actual backward insertion and forward deletion/insertion produce Adjm/+12964, whose complete glyphs save/reopen. This short-string case does not establish every field length or contextual repeat behavior. |
| Held zero/plus and star/comma entry with release suppression | Tested | Tested | Brief 0/star remain literal. Held 0 produces one plus; held star produces one comma; continued holds and release add no extra character. Saved Adg/+12,9 reopens. A lone plus is normalized away on field change, so digits are entered before leaving it. Physical timing and dialing with pauses remain unverified. |
| English/French/Spanish predictive word examples and punctuation | Tested | Tested | LetterWise and WordWise produce independently rendered words/alternatives, including don't, see/red, Bonjour, été/due and Hoja/Hola. Spanish !/? cycle to ¡/¿ and Hola¡¿ saves/reopens; changed drafts cancel. Mode/count/trailing blanks and Multi-Tap restoration are asserted. |
| Notes punctuation groups, spaces and text-preserving mode transitions | Tested | Tested | Keys 3–9/0 exercise their supported punctuation/Next cycles, saved readback and draft cancellation. WordWise spaces/comma, literal 42 and the complete ww/lw/#?@/123/Abc cycle preserve saved `red red,red42 red`. This does not establish every character advertised by general Help in a filtered Notes context. |
| Complete dictionaries, symbol maps and other contextual shortcuts | Pending | Pending | Named words and particular punctuation do not establish every prediction, symbol/currency choice, editor context or held-key shortcut. Menu locales do not imply predictive dictionaries for every language. |
| Local phonebook: create, reopen/read, edit, cancel deletion and delete | Tested | Tested | Both profiles execute the complete HTTP contact lifecycle with saved-content assertions. |
| Local phonebook notes and displayed memory usage | Tested | Tested | Save/reopen/cancel actual note edits, accept 64 characters and reject an extra one, and assert displayed usage 0/100→1/100→0/100 after contact creation/deletion. |
| Six local contact fields, cancellation and exact input limits | Tested | Tested | Distinct Name/Home/Work/Mobile1/Mobile2/Email values save/reopen; a visible Work draft cancels without changing any field. Names and each phone accept 24 characters (including '+'); email accepts 64. Different overflow input leaves visible glyphs/count unchanged; Backspace frees one place and retyping restores it. |
| Complete long-field readback and full-name cursor bound | Tested | Tested | Saved 24-character names/four phones and 63/64-character emails expose every unique overlapping six-glyph window through real side-key movement. Completion counters enforce length. A Right action at the reopened full-name end retains healthy readback. This is glyph/length evidence, not arbitrary byte integrity or unbounded repeated-edit stability. |
| Six distinct short contact fields and note across shutdown/startup | Tested | Tested | Complete shutdown reaches BC5 power state 8 with UI uninitialized; original modem-driven startup rebuilds the saved index. All six independently rendered fields and note reopen, including Work `+456` after cancelling a visible `+450` draft. Both cases finish at healthy home with released keys. |
| Maximum-length fields across completed shutdown and warm startup | Failing | Failing | Four enabled journeys require input/overflow, Save, completed shutdown, original startup and complete hidden-glyph readback for all six maxima. Default tones reach BC5 panic 51; genuine No Tone reaches the TRX DSP-reset signature. All four stop before Save and boot two, so persistence remains unproved. |
| Physical cold-power retention | Pending | Pending | Warm resets retain emulator flash and RAM contracts. Source-image reload, lost power and physical flash retention are separate unverified behaviors. |
| Simultaneous six-field maxima and bare 24-digit numbers | Tested | Tested | With No Prefix selected, one contact saves a 24-character name, four distinct bare 24-digit phone numbers and a 64-character email. Full hidden-window/count checks reread all six before and after cancelling a visible Work draft. Extra phone input is rejected; restoring Plus restores dialer +12. Same-boot local ASCII storage is asserted. |
| Selected Latin-1 contact-name symbols | Tested | Tested | Original full 43-symbol grids/focus select £, ø and é into A£øé. Complete Name/+123 save/reopen and survive symbol cancellation and cancellation of a visible Backspace edit. No general Unicode, non-ASCII initial casing, sort order or power retention claim. |
| Further contact encoding/boundary combinations | Pending | Pending | Characters and mixed encodings beyond the selected ASCII/Latin-1 examples, non-ASCII initial casing, sort/lookup behavior and wider edit/stress or retention combinations remain unasserted. |
| Local phonebook alphabetical ordering and Navi-key lookup | Tested | Tested | Reverse-created D/A contacts sort as A/D; both saved names/numbers, arrow lookup and close/reopen/readback are asserted. The original list handler accepts navigation, not numeric incremental search. |
| Local phonebook full-capacity rejection and recovery | Tested | Tested | Both save 100 distinct contacts, checking every draft name/number and Save success. Assert usage 99/100, sample first/middle/last saved records, reject 101 with its draft retained and usage still 100, and clamp at the real last record. Delete No preserves 100; Yes reduces to 99 and removes the first contact; saving the previously rejected contact returns to 100 and reopens its value. This establishes logical capacity reuse, not every saved field or physical flash-address reuse. |
| Select a local contact as a report recipient | N/A | Tested | The original recipient selector copies saved Adg/+123; reopening retains +123 even after deleting the source contact. SMS composition has a separate saved-contact journey on both models below. |
| SIM read-only file metadata, first READ/cache and card error | Tested | Tested | Original UART3 T=0 consumes external language-file metadata and two distinct two-byte values, publishing them in F100. A card memory error instead publishes the original failure cache without file data. These are synthetic file observations, not subscriber authentication. |
| SIM SST gating and empty SMS record/controller initialization | Tested | Tested | Original F107 consumes SST `CC00`, selects SMS EF `6F3C`, reads its metadata and both 176-byte records, then reaches capacity 2, flags 3 and controller state 1. The same geometry with SST `0C00` consumes SST successfully but makes no SMS SELECT/read and keeps capacity/controller zero through 120M total instructions. |
| SIM empty/populated ADN metadata and original consumer cache | Tested | Tested | Four peripheral cases consume `6F3A` metadata and both 32-byte records, then report capacity two, alpha limit 18 and initialized state. A populated record produces used count one, original `Adg` name cache, compact `12345` digit index and logical slot 101 in lookup order. No full-number/TON GUI readback or ADN service-gating claim is made. |
| Read-only handset SIM phonebook: empty/name/actions/return | Tested | Tested | Four HTTP cases assert original ADN consumption and actual SIM Phonebook display: literal `(Empty)` with blank left caption, or selected Adg with Options and only Call/SMS/Copy. Back returns to healthy Home without a card write/mutation. The original handset offers no SIM Edit/Delete/New; this is not a missing GUI CRUD implementation. These display-only cases do not read the number; the separate Copy/SMS cases below verify canonical +12345. See [SIM workflows](sim-phonebook-workflows.md). |
| Direct SIM-to-SMS recipient and unsent composition | Tested | Tested | Original SMS action opens New; complete adg/count and actual number-only +12345 recipient node/string/links are asserted, with null name/default unset callback. Send To renders +12345. Removal empties the original list, complete body survives and Exit leaves Drafts empty/Home. No Send or subscriber service is established. |
| SIM-to-local My Phonebook Copy | Tested | Tested | Copy success is followed by complete local Name `Adg`/Home `+12345`, three empty secondary phones, empty Email and Notes readback. A focused empty phone may show only its configured plus; all inactive phones must become blank. Cancel a visible `Ad` name draft and reopen `Adg`/all fields, then reopen the original SIM Adg with card bytes unchanged. This is one same-boot local copy, not SIM programming, cold-power retention or delivery. |
| Serial ADN create/edit/reinsertion/delete/recovery | Failing | Failing | Four contracts reach actual create/edit and immediate full CPBR readback, or rejected edit/CME003 with unchanged immediate CPBR/card data. All four halt at the existing TRX DSP-reset signature during reinsertion; fresh readback, deletion and recovery are unreached. These are partial serial observations, not passing persistence or handset CRUD. |
| Restricted SIM entries and PIN2 checks | Blocked | Blocked | The finite cards do not supply the required restricted-file/authentication contract. Read-only ordinary ADN display and partial external serial writes do not establish restricted entries or PIN2 behavior. |
| Usable Messages and titled empty Inbox/Drafts/Outbox | Tested | Tested | The supplied read-only card initializes storage, then the original delayed CMGL retry sets handset scan readiness. HTTP navigation asserts all three folder titles, selected `(empty)` rows, blank remaining rows and return to the correct parent selection. No stored-message content is supplied. |
| SMS expiry and delivery-report preferences | Tested | Tested | Separate fresh-worker cases save/reopen all six expiry choices and On/Off delivery reports, cancel visible drafts without changing saved radio marks, and restore one week/Off. Original delayed-close timers execute normally. These are local stored preferences, not elapsed expiry or delivered reports. |
| SMS compose/recipient guards and unsaved Exit | Tested | Tested | Complete adg/count and Clear readback; empty/bare-plus rejection; local recipient add, cancel and remove without Send; retained text on return; Exit followed by empty Drafts and a fresh empty composition. Broader syntax and editor boundaries remain pending. |
| Saved phonebook contact as an SMS recipient | Tested | Tested | The single-number path rereads saved Adg/+123; chooser Back adds nothing and Select copies exact Adg/+123 with terminators into one original recipient node. Remove empties the list, composition survives and Exit leaves Drafts empty. The separate multiple-number path is asserted below; sending remains excluded. |
| Multiple-number local contact chooser for SMS recipients | Tested | Tested | Both models reread all four saved short phone fields and their focus/counts, then assert all four ordered number choices. Inner Back and outer Back leave the original recipient list empty. Selecting Work/Mobile1/Mobile2 copies exact `+456`/`+789`/`+246` with Adg and both node links zero; each Remove empties it. Complete composition/count survives and unsaved Exit leaves Drafts empty. This does not establish Email selection, other formats, multiple simultaneous recipients or delivery. |
| Local SMS draft save, full readback, edit/resave and deletion | Tested | Tested | Save `123`, reopen complete text/count, append `4` in explicit numeric mode, retain `1234` through Options Back, resave and reopen full `1234`. Delete No preserves `123`; Yes yields Message Deleted/No more messages, returns to Messages and re-entering Drafts is empty. The card stays read-only; storage is local BC5 flash. |
| Local SMS draft across completed shutdown and warm startup | Tested | Tested | Both complete power state 8, perform a second original startup/scan, then reread preview `123` and full editor `123`/count 997. A fresh source-image load, loss of RAM/power, long content and Unicode are excluded. |
| Red-key draft autosave and empty-editor guard | Tested | Tested | Empty Red leaves Drafts empty; nonempty adg Red returns Home and saves a draft whose full Edit text/count is asserted. Cleanup leaves an empty folder and healthy Home. No retained recipient list or restart claim. |
| Delete All draft confirmation and empty-folder readback | Tested | Tested | Two short drafts appear newest-first as `789`/`123`. No preserves both after actual folder closing/reopening; Yes shows All Messages Deleted with Drafts title, naturally returns to Messages and re-entering Drafts is empty. No unsupported No more messages notification is required. |
| SMS symbol picker, selected Latin-1 symbols and short English input-mode transitions | Tested | Tested | Four cases compare the complete original 43-glyph grid and focus, insert £/ø, cancel a tentative symbol, preserve exact text/counts through case/numeric modes, Red-save/reopen `aD£ø42j`, and explicitly save/reopen English prediction result `$42a red`. Edit-discard cleanup leaves Drafts empty. This does not establish insertion of every listed glyph, full Unicode or complete dictionaries. |
| Rapid long SMS entry, 201-character storage boundary and 1,000-character limit | Failing | Failing | Four intended journeys stop at original BC5 allocation panic 51 after 81/70 accepted characters, with TRX healthy. Source/stack identify a nine-word event timer; a separate diagnostic ties pool pressure to a drainable outgoing key-tone queue. These counts are not established capacity limits; the underlying transport/model behavior and successful storage/overflow/readback remain unresolved. |
| Patient long SMS entry with original modem execution | Failing | Failing | Four fresh cases retain all full-length assertions and add 2M released original instructions per accepted key. TRX instead halts at the existing DSP-fatal reset signature after 53/52 characters; BC5 remains healthy. Neither 201/1,000-character input nor later save/overflow/full readback is reached. No processor pause or tone-setting workaround is used. |
| Simultaneous SMS recipients and separate saved Email selection | Tested | Tested | Four phone recipients coexist with complete ordered LCD rows and all five original node words/NUL data/unique links. Chooser cancellation and first/middle/last removal preserve the survivors and body; explicit discard leaves empty Drafts. Separate Email kind-1 selection is asserted before the phone scenario. Mixed phone-and-email coexistence, maximum recipient count and delivery remain unverified. |
| Other draft/editor actions and encodings | Pending | Pending | Further Unicode/mixed encodings, unexercised symbols/languages/dictionaries, mixed phone-and-email coexistence and maximum recipient count need separate assertions. Opening Edit removes the stored entry before editing; a readback alone does not prove that entry remains saved afterward. |
| Modem SMS card write, reinsertion readback and rejected-write recovery | Tested | Tested | Separate serial contracts assert original CMGW, exact 176-byte card content, unchanged second record, natural reinsertion and exact CMGR PDU/status/OK. A rejected DC command yields CMS322 without a body or mutation. This does not establish GUI inbox/outbox, CMGR alpha formatting or delivery. |
| Original-modem service-center storage | Tested | Tested | Four serial contracts read the declared SMSP number, issue CSCA with explicit type, distinguish early OK from actual 32-byte card commit, then remove/reinsert and query the genuinely reloaded number. A rejected write leaves storage unchanged; immediate cache readback differs from the fresh result. Broader number formats are excluded. |
| SMS service-center handset digit editing, cancel, save/fault and warm readback | Tested | Tested | Four HTTP cases assert the literal number form, cancel without a write, plus/digit entry, actual SMSP commit or rejected-write status and a fresh original read after completed shutdown/warm startup. Saved digits reload; rejected changes do not. The GUI omits the address type, so these passes do not establish international-number preservation. |
| Unchanged SMS service-center address/type integrity | Failing | Failing | Saving the initial digits without editing changes only SMSP record byte 18, `91`→`81` hex, through an actual UPDATE RECORD. Two enabled failures require unchanged full address/type; digits-only UI readback is insufficient. See [address-type evidence](service-center-type-preservation.md). |
| Stored-SIM Inbox read, Reply/Forward cancellation and deletion | Tested | Tested | A declared unread SMS-DELIVER enters through real UART3 card reads. Full body/sender and original Reply node, empty Forward recipients, unsaved Exit/empty Drafts, declined deletion, actual free-status commit and empty Inbox/Home pass on both models. This is preloaded storage, not incoming RF or notification. |
| SMS network reception/notification, sending, delivery reports and email gateway | Blocked | Blocked | Offline scenario SMS remains disconnected from modem execution; no authenticated network or service transport provides those outcomes. Stored-card Inbox actions above do not establish delivery. |
| Voicemail: number storage, editing and cancellation | Tested | Tested | Both HTTP journeys save/reopen an edited number, cancel a tentative deletion and restore the original. |
| Voicemail: one-touch request initiation | Tested | Tested | Holding 1 through real key ownership reaches the original pending request and releases cleanly. Notification, connection and retrieval require service. |
| Call/end key semantics before service completion | Tested | Tested | HTTP tests assert empty dialed-call history, exiting it, cancelling number entry and the pending request screen after Call. They do not assert ending an active call. |
| Voice calls: outgoing/incoming, answer/end, missed calls, emergency dialing and voicemail retrieval | Blocked | Blocked | SIM/authentication, RF/service behavior and call transport remain outside implemented contracts. A dial/error screen is not a completed call. |
| In-call controls: mute, speakerphone, earpiece volume and alerts | Blocked | Blocked | Complete behavior needs an active call and audio transport. Local settings can be covered separately. |
| Empty call histories, initial zero meters and local reset flow | Tested | Tested | Distinct received/missed/dialed titles, 00:00:00 last/total/lifetime counters, reset No/Yes and zero readback are asserted. Resetting an already-zero counter does not prove clearing a nonzero duration. |
| In-call display and audible-timer preferences | Tested | Tested | Both models save/reopen/cancel/restore the display setting and all 1/5/10/15/30/60-minute Single and Repetitive Alert choices, including Off restoration and navigation bounds. Timed alerts and audio remain unverified. |
| Authentic call records, elapsed meters, nonzero reset and actual timed alerts | Blocked | Blocked | A connected call and audio/time contract is needed. Empty histories and saved alert preferences do not establish these outcomes. |
| Call-option unavailable gates and cancelled Fixed Dialling draft | Tested | Tested | Waiting/Forwarding/Barring show their original unavailable errors and reopen. A visible Enabled draft cancels back to cached Disabled on readback. PIN2 validation and authenticated SIM/service state are excluded. |
| Call options: forwarding, waiting, barring and associated credentials | Blocked | Blocked | Successful network-dependent outcomes and credential handling cannot be inferred from the tested unavailable menus or cancelled Fixed Dialling draft. |
| Ringer/speaker levels and ring/alert/keypad/network/vibration configuration | Tested | Tested | Settings journeys assert saved/reopened values, cancellation and restoration. Audible output and physical vibration remain outside these assertions. |
| Backlight duration and contrast configuration | Tested | Tested | Saved/reopened selections and cancelled/restored edits are asserted. Physical brightness and analog contrast are unverified. |
| English/French menu language selection, cancellation and restoration | Tested | Tested | Actual localized parent widgets and saved selection marks are asserted on both models. |
| Remaining 22 menu language selections and localized Language widgets | Tested | Tested | Together with English/French, all 24 original selector choices have save/readback/cancel/restore assertions. The new cases compare full parent/selector/soft-key screens and independently render all 44 translated Text Entry rows, including CJK, Cyrillic and RTL layouts. |
| Selected preferences through completed shutdown/warm startup | Tested | Tested | French/NoTone/prefix00 and timezone+0.5/am-pm/slash-date/backlight10s journeys require original boot2, complete saved-widget readback, cancelled defaults, restored values and actual prefix dispatch. Only French and these preferences are covered; no physical timing, clock sync or audio. |
| Other translated screens and locale-dependent behavior | Pending | Pending | The Language widgets do not establish every translated screen, locale input, dictionaries, sorting, date rendering or unselected restart combinations. The older French case checks its parent body but not translated soft-key captions. |
| Time zone, 24-hour/am-pm and date formats | Tested | Tested | Saved/reopened selections, cancellation and restoration are asserted. |
| Acquired network time and epoch handling | Blocked | Blocked | Needs firmware-connected network time data; local display formats are insufficient evidence. |
| Convenience key: local-phonebook assignment and default restoration | Tested | Tested | Saved phonebook action opens the real local book; restore No Action on 9555 or Location on 9575, including its enable prompt. |
| Convenience key: six further action assignments and local dispatch | Tested | Tested | Six choices have save/readback/visible-draft cancellation assertions. Start/Voicemail and empty-history Redial reach pending requests; earlier card-absent SIM/Messages cases show original unavailable errors. Separate populated-card SIM shortcut cases reach actual Adg/actions and restore the default. End is tested only on idle home/number entry; active-call termination and dialed destination are unverified. |
| Convenience key: No Action | Tested | Tested | 9555 restores its default and checks idle dispatch. 9575 explicitly saves/readbacks/cancels a Location draft, preserves both idle Home and entered +12 on delivered presses, then restores Location and verifies the real GPS-enable prompt. |
| Right soft key: Help, local phonebook and SIM phonebook | Tested | Tested | Earlier card-absent cases assert the original SIM not-ready error. Separate populated-card cases save/readback/cancel the assignment and prove both the actual right-key and convenience-key destinations: selected Adg plus original read-only actions. Default convenience action/Help and saved radio marks restore. This does not activate Call/SMS/Copy. |
| Number Entry: plus, 00 and no prefix | Tested | Tested | All three stored choices produce `+12`, `0012` and `12`; cancellation preserves the saved choice and the original plus behavior is restored. |
| Phone information | Tested | Tested | Setup and actual keypad `*#06#` plus Call routes verify original modem placeholders and local BC5 build strings, page bounds, Back and reopening. Hardware placeholder is literal `GRev@-XXXX`; IMEI remains `XXXX`. This does not identify physical hardware or recover an unshipped boot block. |
| Reset to Defaults confirmation, cancellation and saved setting effect | Tested | Tested | The handset menu preserves a changed ringer level after No and restores its default after Yes. Resetting every other setting remains unasserted. |
| Saved ringer/contact/note across completed shutdown and warm startup | Tested | Tested | Genuine factory TRX traffic rebuilds the saved phonebook index; actual changed volume, Adg/+123 and Adg note glyphs survive restart. Source-image reload and loss of power/RAM are outside this assertion. |
| Reset ringer default persists across warm startup | Tested | Tested | Change and read back the ringer, confirm Reset to Defaults, complete shutdown/startup, and assert the original default. |
| Reset to Defaults preserves local contact and note | Tested | Failing | Both models pass retained-name/number/note assertions; the complete 9575 journey then fails returning home at TRX step311574149, PC7004A0C8, the previously traced DSP-fatal path. The 9555 journey completes. |
| Local PIN form validation and masked input | Tested | Tested | Missing fields and mismatched new/verification PINs produce original errors; masked input is checked. |
| Phone Lock enable, restart enforcement, PIN authentication/change and disable | Failing | Failing | 9555 displays Phone locked for the factory PIN, then TRX requests a DSP-fatal reboot. 9575 reaches home but TRX takes the same path during PIN entry. Later authentication stages and successful PIN changes remain unverified. |
| SIM lock, SIM PIN/PIN2 changes and blocked-SIM recovery | Blocked | Blocked | Requires subscriber provisioning and authentication exchanges beyond the finite read-only card; no successful authentication claim is available. |
| Data modem, USB data connection and data transfer | Blocked | Blocked | Complete host/device and service contracts are missing. HL25003 also restricts direct Internet dial-up; older manual behavior is not a success criterion. |
| Signal, searching/registration and loss/reacquisition of service | Blocked | Blocked | Offline scenario signal/registration is separate from modem execution. Its state changes cannot satisfy handset coverage. |
| Battery level, low-battery warning, charging and external power | Blocked | Blocked | Some firmware-derived digital inputs exist, but complete battery/charger/connector behavior is not established. |
| Accessories and physical outputs: headset, external antenna, status LEDs and audio | Blocked | Blocked | No complete hardware contract or physical-device comparison. Browser artwork is not evidence of an electrical output. |

## 9575 Extreme features

| Feature family and subfeatures | 9555 | 9575 | Evidence, remaining scope or blocker |
| --- | --- | --- | --- |
| Convenience key, GPS-enable decline/accept, Current Location and reopening | N/A | Tested | HTTP tests verify both prompt choices, home restoration and reopening without another enable prompt. Coordinates stay blank and the fix status remains Updating. |
| GPS OneTime/RealTime and On/Off preference persistence and prompt gating | N/A | Tested | Save/reopen/cancel/restore both settings. Enabled opens Current Location directly; Disabled restores its enable prompt. Other scheduling modes remain unasserted. |
| Receiver ownership, external digital gate and standby power | N/A | Tested | A real receiver epoch releases the startup owner and allows original delayed standby. Both PJ5 levels are tested: default HIGH inhibits the automatic hold; LOW plus saved Enabled starts PJ7, cancellation retains it, and saved Disabled permits standby. PJ5's physical role is unknown; no antenna identity or production-default change is claimed. |
| GPS settings lock, PIN length/wrong-PIN rejection, protected edit and unlock | N/A | Tested | Default 3333 enables the lock; empty input and wrong 3334 are rejected; correcting the masked PIN permits an edit, mode restoration and unlock. |
| GPS PIN change, mismatch/cancel, old/new PIN authentication and restoration | N/A | Tested | Original three-field UI changes 3333→2468; the old PIN fails, the new PIN enables/disables the lock, then restored 3333 does the same. Masked fields and saved state are asserted. |
| Position/altitude preference persistence and positive-fix formatting | N/A | Tested | Save/reopen/cancel/restore DMS/decimal and feet/meters; the same supplied fix renders 37.774900/-122.419400/+30m, then DMS/+98ft after restoration. |
| Portal registration cancellation and local status | N/A | Tested | The original form is opened and cancelled; reopening status still says Not registered. Valid provisioning, registration requests and portal service remain unverified. |
| Valid portal registration and extended configuration | N/A | Pending | A cancelled form does not establish valid provisioning, registration requests or service behavior. Stored report frequencies are covered separately below. |
| Receiver bytes to current position, altitude and satellite count | N/A | Tested | HTTP UART0 input traverses the original AVR parser and SPI to BC5 LCD: 37deg46'29" N, 122deg25'09" W, +98 ft and eight satellites. Reopening preserves coordinates and count. Lower-level contracts reject bad checksums/incomplete epochs. |
| Physical receiver acquisition, signal loss/reacquisition and GNSS timing | N/A | Blocked | Receiver packets are supplied by the test; no radio/acquisition model or physical receiver is connected. |
| RealTime second-epoch coordinates and satellite-count update | N/A | Tested | Both signed-altitude cases pass the first/second-epoch coordinate, eight→nine satellite and parsed-cache assertions before their final sign check fails. This establishes that update path, not arbitrary epochs or timing. |
| Legal GPS zero crossings, poles/dateline and nearby recovery | N/A | Tested | Three valid receiver journeys cross latitude/longitude zero, reach exact ±90° and ±180°, and recover to nearby legal coordinates. Fresh publications update parsed coordinates/count and complete original-font LCD rows. Reopening and decimal/DMS switching preserve and render the cached final fix without another epoch. Only the selected exact milliminute values are asserted. |
| Checksum, complete-epoch and no-fix rejection through the LCD | N/A | Tested | HTTP cases retain the last valid cache/coordinates/altitude/eight satellites after corrupt UBX, incomplete epoch, bad or unterminated NMEA, mixed epochs and a published no-fix epoch. Corrected/completed/fresh valid data updates the original cache and LCD to nine satellites. |
| NAV-SOL validity flags and valid 2D acceptance | N/A | Failing | Original AVR uses fix-type byte 10 bit 0 instead of validity byte 11 bit 0. Type 3/flags 0 is wrongly accepted; type 2/flags 1 is wrongly rejected. The latter keeps its prior altitude while varying horizontal coordinates/count. See [original-source evidence](gps-solution-validity.md). |
| Geographic-range guards for receiver input | N/A | Failing | Four enabled robustness cases show original acceptance/publication/display of±91 latitude and±181 longitude. They require the preceding valid fix to survive, then legal recovery/reopen/Home; the latter stages are unreached. These are out-of-spec digital inputs, not normal receiver/RF failures. |
| Fix age and broader continuous-update behavior | N/A | Pending | Fix age, physical signal loss/reacquisition, every interval, invalid UTC, arbitrary fractional rounding and handset/network time synchronization remain unasserted. |
| Negative GPS altitude sign | N/A | Failing | Both enabled regressions retain sign0/magnitude5 in the parsed cache but display +16ft/+5m for -5m. Original HL25003 formatter ignores the sign; see [defect evidence](gps-altitude-sign.md). |
| SOS activation, countdown advance and repeated cancellation | N/A | Tested | HTTP tests drive AVR PK0 and assert original 20 and 19 screens and home restoration twice, with no software-key probe. Pin mapping is firmware-derived; physical board wiring remains unmeasured. |
| Emergency Actions and Beep preference persistence | N/A | Tested | All three actions, Message and Call, Message Only and Call Only, have save/reopen/visible-draft cancellation/restoration assertions. Disabled/enabled beep is tested as a preference; actual sound and delivered requests remain unverified. |
| Emergency message recipient validation and lifecycle | N/A | Tested | Reject bare+, save/reopen +12345, decline deletion, confirm deletion and restore the empty recipient list. No message is sent. |
| Emergency voice/email recipients and contact selection | N/A | Tested | Save/reopen/edit/cancel/clear a voice number; blank email Save adds none, a@b.c saves/reopens and b@b.c replaces it, with cancelled edits and Delete No/Yes. A selected contact's +123 survives deletion of its source. The original UI also accepts adg and +*; strict syntax rejection is not claimed. |
| Emergency message-recipient three-slot capacity and recovery | N/A | Tested | Fill all three rows, clamp at the last, replace it without creating a fourth, cancel a visible edit, delete the middle, assert compaction, reuse the free slot, then Delete All No/Yes. |
| Email input length and rejected extra-character recovery | N/A | Tested | The original counter reaches zero at 74 ASCII characters; an extra key changes no input, Backspace frees one character and retyping consumes it. Cancel preserves an empty list. |
| Maximum-length Emergency email reopening | N/A | Failing | A 73-character control reopens with one place remaining and independently checked visible suffix/list prefix. A saved 74-character address reopens with 74 places remaining and a ? placeholder. Original prefill rejects the exact-fit string plus terminator; see [boundary evidence](email-prefill-limit.md). Hidden prefix glyphs are not independently reread. |
| IERCC registration cancellation and invalid short PIN | N/A | Tested | Decline registration, reject empty/one-digit input, and assert the service remains unconfigured. This does not establish five-digit acceptance, valid provisioning or activation. |
| SOS test mode and valid IERCC activation | N/A | Pending | The explored original Emergency Options route ends at IERCC and exposes no Test Mode item. Alternative routes, valid IERCC credentials, provisioning and activation remain unasserted. |
| Completed emergency call/message, retries and acknowledgement | N/A | Blocked | No service transport provides the full outcome. Countdown completion or a supplied receiver fix is not proof of a delivered emergency request. |
| Regular location reporting frequencies and numeric recipient lifecycle | N/A | Tested | All 14 choices, No Update through 1 Week, save/reopen, cancel a distinct visible draft and restore No Update. Reject a bare plus, save/reopen +12345 and verify delete No/Yes. A contact's copied number survives source deletion. These are stored preferences, not elapsed transmissions. |
| Location email recipient lifecycle | N/A | Tested | Blank Save adds none; adg@adg.adg saves/reopens, a visible tentative adj suffix cancels, the changed address then saves/reopens, and Delete No/Yes restores empty. Malformed syntax rejection is not asserted. |
| Quick GPS five-slot capacity, replacement, compaction and Delete All | N/A | Tested | Fill all five rows; Down clamps without a sixth row or Add choice. Editing the last with a sixth distinct number replaces that row. Delete the middle, refill the freed last row, reopen all five saved values, then Delete All No/Yes restores five empty rows. |
| Actual location schedule execution and coordinate-sharing payloads | N/A | Pending | Stored frequencies and recipient editors do not establish elapsed scheduling, payload composition or successful sharing. Delivery remains blocked. |
| Location report delivery, online portal interaction and SBD | N/A | Blocked | Service transport and third-party portal integration are not connected. A supplied receiver fix alone cannot establish delivery. |
| SOS LED, cover/switch mechanics, ingress protection and physical robustness | N/A | Blocked | The firmware-derived button input does not establish these physical properties. |

## Emulator controls and isolation

These checks protect test validity and session behavior; they are not additional
handset features.

| Area | Current evidence | Remaining scope |
| --- | --- | --- |
| Run, pause and bounded step | Factory HTTP tests assert advancement, paused stability and resumed manual execution for BC5 and AVR. | Memory-probe validation and effects have separate protocol/session coverage. |
| Shared key ownership and reset generations | Factory HTTP tests assert two-client menu input, held-key reset cleanup, stale-epoch rejection and a new boot. | Broader duplicate/reordered-request cases remain in session/server tests. |
| Reload and model switch | Factory HTTP uploads exercise both model directions, key epochs, processor replacement and model-specific controls. Native/session tests cover retaining AVR and releasing held buttons. | Broader simultaneous upload/browser event races remain unasserted. |
| Failures and mutations | Original-image tests deliberately replace instructions and require visible halts or initialization failure. | Keep factory E2E fixture validation strict so modified-image experiments cannot be mistaken for factory runs. |
| Offline satellite scenarios | Factory HTTP tests register the host scenario, answer/hang up its call and receive its SMS, asserting `firmware_connected=false`, `delivered=false`, unchanged CPUs and unchanged LCD. | Scenario success never substitutes for a handset call, message or fix. |
| Browser input and rendering | Node tests cover input mapping and ownership with a DOM harness. | A real-browser journey and layout/accessibility checks remain pending. |

## Extending coverage

Add independent journeys with fresh sessions, bounded waits, worker/LCD health
checks and observable expected results. Promote a pending row only after its
assertion runs against the claimed model. Keep local-menu coverage separate
from service delivery, and unblock a device-dependent journey only when the
original firmware consumes a supported device or transport contract. Report
skips, failures and remaining gaps alongside passes.

Remaining local journeys include Unicode/mixed contact encodings,
maximum-length fields across restart, cold-power retention, long-SMS queue/DSP
failures and successful input/storage boundaries, other draft actions,
complete ADN reinsertion/delete/recovery, additional card
writes and service-center address-type preservation/broader formats,
other contextual shortcuts, translated
screens, invalid GPS ranges and broader GPS age/update behavior. General Help lists characters
that the filtered Notes editor did not expose; availability in the appropriate
SMS/editor context beyond the asserted picker and short English examples needs
evidence before treating this as a firmware defect.
The [SIM device contract](sim-device-contract.md) records the tested
card-detect/ATR/SELECT, read/cache/error, SST, SMS record/controller and finite
SMS write/reinsertion/readback boundaries. Local GUI draft storage is asserted
separately; broader inbox/outbox workflows and subscriber provisioning/
authentication remain unresolved.
