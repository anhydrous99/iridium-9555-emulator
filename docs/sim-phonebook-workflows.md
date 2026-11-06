# Factory SIM phonebook and serial ADN storage

This note records pre-cleanup phase observations. Artifact paths are local-only
files ignored by Git. See the
[factory-suite instructions](factory-e2e.md#running-the-factory-suite)
to collect a new run; that command does not recreate historical
reconciliation directories.

The original handset SIM phonebook is read-only. The Extreme manual's printed
page 75 describes externally programmed SIM entries and distinguishes them
from editable My Phonebook entries. Both pinned firmware resource packs and
their actual menu handlers expose only **Call, SMS, Copy** for a SIM contact. Both
action journeys wait for that actual menu after the asynchronous selected-record
fetch before choosing SMS or Copy.
Copy creates a local handset contact; it is not an update to the SIM.

[Handset tests](../tests/test_factory_sim_phonebook_e2e.py) supply finite external
ADN records before the executing original BC5/AVR/TRX startup. They wait for the
original startup and scan, verify real metadata/record consumption and the TRX
cache, then navigate through the actual Main Menu to SIM Phonebook. The empty
card must show literal `(Empty)`, a blank left caption and Back. The populated
card must display selected `Adg`, expose the three original actions, and return
to Home without any card mutation or write command.

The populated list uses a different viewport from an ordinary options menu:
its highlight spans x0..118, y15..33, text begins at x2/y16, and unused rows
start at 34. The independent original-font crop is 117 pixels wide. Earlier
checker revisions incorrectly required exactly two ADN reads and then used the
ordinary menu's crop/blank boundary. Original BC5 enumeration legitimately
rereads a record, and the contact was visibly present in both captures. Those
revisions are retained as excluded calibration, not factory feature failures.

The original shared TRX exposes SIM indices after its 100 local indices. With
this card's two records, actual `CPBR=?` and `CPBW=?` responses advertise
**101..102**, even though physical card READ/UPDATE RECORD uses record 1 or 2.
The card declares 18 alpha bytes and a 20-digit number field. These finite
fixture limits do not establish the manual's full physical SIM capacity or
every contact encoding.

[Serial write contracts](../tests/test_factory_sim_phonebook_write_contract.py)
use original reset execution and real UART1 DPL requests/packet acknowledgments.
The separate [ADN card](../tests/sim_phonebook_card.py) implements only declared
file `6F3A` writes on external UART3: `A0 DC 01 04 20`, procedure `DC`, a complete
32-byte opaque body, then `90 00`. It commits only a full body. Other files
remain read-only; reset aborts an incomplete body, and a matched memory fault
returns `92 40` before a procedure acknowledgment or data body.

Both models' positive serial runs create `Adg` / `+12345` with address type 145
and edit it to `B` / `67` with type 129. Each step produces an actual accepted
32-byte card update and complete original CPBR name/number/type readback. The
negative runs create the initial entry, reject its edit at the card, observe
original `+CME ERROR:003`, and read back the unchanged original entry. The
second card record and other declared files remain unchanged.

All four complete serial contracts still fail during natural card reinsertion
at TRX instruction 185,746,541, PC `7004A0C8`, saved `i7=70044934`. This matches
the previously traced [DSP reset signature](dsp-execution.md); these cases do
not independently trace DSP instruction execution or resample its rings.
Fresh reinserted readback, deletion and recovery assertions remain enabled and
unreached. The observed writes and immediate readbacks are partial evidence,
not four passing persistence contracts. Earlier index-1 attempts are excluded
bad-index calibration; they did not reach a card write.

The [ten pure card checks](../tests/test_sim_phonebook_card.py) separately verify
fragmentation, procedure acknowledgment, full-body atomicity, rejection,
readback, reset, reinsertion retention and write restrictions. Their passes
establish the test fixture, not successful execution of those handset or modem
journeys.

The [multi-number SMS tests](../tests/test_factory_messages_contact_numbers_e2e.py)
also pass on both models. They reread four distinct saved local numbers,
cancel the inner chooser without adding a recipient, then select Work,
Mobile 1 and Mobile 2. Original recipient nodes contain exactly `+456`, `+789`
and `+246`; each removal empties the list. Composition survives the choices,
and explicit Exit leaves Drafts empty. Separate direct SIM-to-SMS assertions
appear below; email recipients, simultaneous recipients and delivery are excluded.

Previous evidence is retained in
factory-sim-phonebook (`test-artifacts/factory-sim-phonebook/README.md`), including
raw reports, native LCD/card captures, source snapshots, original-code listings,
excluded calibration and independent audits. Firmware, guest RAM, callbacks,
queue consumers and native halts were not replaced or patched. The recorded
workflow additions below retain those boundaries; no subscriber authentication,
network call, SMS delivery or physical card behavior is established here.

## Direct SIM-to-SMS

Two [direct SIM SMS cases](../tests/test_factory_messages_sim_recipient_e2e.py)
pass on the original complete handsets. Each selects actual SIM Phonebook→SMS,
asserts empty New/1000 and complete `adg`/997, and reads the original five-word
recipient node. Both default name callbacks are unset; its name pointer is
null, its number is exact `+12345` plus NUL, and both links are zero. Send To
renders `+12345`. Remove empties that list without sending, the complete body
survives, and explicit Exit leaves empty Drafts and healthy Home. The test does
not borrow the SIM name as an invented recipient label.

Original HT `78370` / HL `78708` pass CPBR result+6 only to `83DD8` / `86D22`.
The recipient builder can invoke an optional separate name resolver, but the
observed `F85F:F860` / `F88F:F890` pointer is `0:0`. The number-only result is
therefore expected for this fixture, not a failed name-copy feature.

## Saved SIM shortcut destinations

Two [shortcut cases](../tests/test_factory_sim_shortcuts_e2e.py) save/read back
SIM Phonebook for the convenience and right-soft keys, cancel a visible Redial
or Help draft, and assert saved selections separately from focus. After the
original scan, each physical key reaches actual selected Adg and the three
read-only actions, then returns to the same list/Home. The original convenience
default (No Action on 9555, Location on 9575) and Show Help restore with
saved-mark readback and Menu/Help captions.
These cases display Call/SMS/Copy without activating them and leave the card
unchanged; no service or default-action dispatch after restoration is claimed.

## SIM-to-local Copy

The two [Copy cases](../tests/test_factory_sim_phonebook_copy_e2e.py) pass on both
models. They require the original success message, then actual My
Phonebook readback of all six local fields: Name `Adg`, Home `+12345`, three
empty secondary phones and empty Email. An empty phone temporarily displays
its configured plus prefix only while focused; all inactive secondary phones
must be blank after blur. Notes is empty with 64 remaining. A visible `Ad`
name draft is cancelled; reopening restores `Adg`, Home and all empty fields.
The original SIM Adg is reopened and all external records remain unchanged.
This is a same-boot local copy, not SIM programming or cold-power retention.

The initial 7c Copy source mistakenly required a Back caption on the success
modal; the original footer is blank. Those harness-only failures and their
source/captures are preserved as excluded calibration. The corrected source
changes only that footer expectation; its two complete final journeys pass.
The successful calibration alone is not counted as a factory feature pass.

The SIM workflow phase evidence is in
factory-sim-workflows (`test-artifacts/factory-sim-workflows/report.json`).
It adds six HTTP cases to the previous 206 and no peripheral or pure fixture
IDs. The 34 inherited peripheral outcomes remain 30 passes/four ADN-reinsertion
failures, with ten newest pure card-fixture passes retained separately.
Complete original reinsertion/delete/recovery, restricted entries/PIN2,
subscriber authentication and RF/service delivery remain outside these results.

The pre-cleanup aggregate at commit `2023be0` is retained locally as
`test-artifacts/factory-storage-settings-gps/report.json`.
Its additional local-contact/recipient assertions are described in
[contact boundaries and persistence](contact-boundaries-persistence.md); they add
no peripheral or pure fixture IDs and preserve all earlier ordinary failures.
