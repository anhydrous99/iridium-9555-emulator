# Contact and recipient boundary journeys

These tests use the hash-pinned HT25003 and HL25003 factory images and the
unchanged native runtime. Each case starts fresh original BC5, AVR and TRX
workers. Local UI observations do not establish network delivery or physical
handset equivalence.

## Simultaneous SMS recipients

[Multiple-recipient tests](../tests/test_factory_messages_multiple_recipients_e2e.py)
create and completely reread a local contact with Name `Adg`, Home `+123` and
Email `a@b.c`. They select Email separately and require its actual original
kind-1 recipient node, complete NUL-terminated name/address and visible row.
That node is removed before the simultaneous telephone scenario.

Four telephone recipients coexist: named `Adg`/`+123`, then manual `+456`,
`+789` and `+246`. Every observation checks complete ordered LCD rows and all
five words of each original node, including unique addresses and both links.
Cancelling the chooser must preserve the list; removing first, middle and
last entries must preserve the surviving values/order/links. The complete
`adg` body survives, explicit discard leaves empty Drafts, and Home returns.
The read-only SIM fixture remains unchanged. Send is never activated; mixed
phone-and-email coexistence and service delivery are separate gaps.

## Selected Latin-1 contact-name symbols

[Latin-1 tests](../tests/test_factory_phonebook_latin1_e2e.py) pass on both
models. They check the complete original 43-symbol grid and selection focus,
then insert `£`, `ø` and `é` after `A`. Complete `A£øé` and Home `+123` survive
original Save, departure to Home and reopening. Cancelling a tentative symbol
leaves every glyph/count unchanged. A visible Backspace removes exactly `é`;
cancelling that edit restores the full saved Name and phone.

These are selected original Latin-1 symbols. Other Unicode characters,
non-ASCII initial casing, lookup/sort order, dictionaries and power retention
are not asserted. The external card is read-only and all three processors
remain active.

## All six maximum-length fields across warm startup

[Maximum-field persistence tests](../tests/test_factory_phonebook_limits_persistence_e2e.py)
retain the entire intended journey: 24-character Name, four distinct
24-character phones and a 64-character Email; zero remaining counts and a
rejected extra key for each field; original Save; completed shutdown; original
warm startup; and every glyph of all six saved fields, including hidden text.
The full readback uses overlapping six-glyph windows rather than just the
visible suffix or a nonempty-list check.

Default Single Tone cases remain enabled. Separate No Tone cases save and
reopen that genuine preference before the same journey, then require saved
No Tone after startup and restore/reopen Single Tone at the end. Accepted
numeric input is observed through the actual focused field, exact counter and
complete six-glyph suffix; no accepted key is replayed. Input cadence differs
between the default and configured cases, so they do not isolate the effect
of tone selection alone.

These cases deliberately use no synthetic SIM or peer. Original absent-SIM
or 9575 emergency warnings are acknowledged through the real UI. Every native
halt is an ordinary failure; reaching some input fields cannot pass the
Save/shutdown/startup/readback journey. Original firmware RAM, DSP consumers,
AT replies and success callbacks are never patched.

The final configured No Tone runs both fail at original TRX
`firmware-reset-requested`, PC `7004A0C8`, at 311,574,125 / 311,574,149 TRX
instructions (9555 / 9575). Each has one completed boot, healthy BC5/AVR, all
four phone fields at 24 characters and rejected-extra-input checkpoints. The
last accepted Email prefixes are `23571113171923` (14 characters) and `23571113`
(8). Neither reaches Save, completed shutdown, second startup, saved-field
readback or tone restoration. These are two enabled failures, not persistence
passes. The 9555 terminal outgoing tone queue is empty; this run does not stop
at the default-tone allocation panic. Different cadence prevents attributing
that difference solely to the setting.

An earlier No Tone helper called the API with zero steps after key release.
The API rejected it; those two harness failures and their source/captures are
preserved separately. The one-line correction returns the actual released
state when no additional steps are requested. It changes no native code,
original firmware, accepted-key cadence or journey assertion. Final outcomes
come only from the corrected source.

The final default Single Tone runs both fail at original BC5 `firmware-panic`,
PC `70A0`, while TRX remains healthy. They accept 68 / 50 numeric key inputs
(9555 / 9575); their last observed third-phone prefixes are
`+3456789012468035791208` and `+3456`, including the configured plus. TRX totals
are 249,662,808 / 239,687,733. Both reached the first two phone maxima and
rejected-extra-input checks, but neither completes the third phone or reaches
Save/shutdown/startup/readback. The stable 9555 terminal `F898` chain contains
79 original outgoing keypad-tone nodes. This is evidence of the same
allocation/backlog failure investigated in [long SMS allocation](sms-long-text-allocation.md),
not a demonstrated contact-field capacity limit or a proved physical-firmware
bug. Earlier f3 default failures remain preserved as genuine failure evidence;
these final failures use the current frozen source and remain enabled.

The [contact-phase reconciliation](../test-artifacts/factory-contact-coverage/report.json)
adds eight HTTP cases: four passes and four ordinary failures. It retains all
212 earlier outcomes unchanged, producing 220 HTTP outcomes: 198 passes and
22 failures, with no errors, skips or expected failures. The 34 older peripheral
outcomes remain 30 passes/four failures, and the latest ten pure card checks
remain separate historical evidence. The corrected 144-source snapshot also
passes `./test`: 464 Python cases with 271 explicit fixture skips and 193
executed cases. UI checks pass 25 cases. Native protocol runs 59 cases (41 pass, 18 skips);
the sole hardware case is skipped and no hardware test executes.
These fixture skips are not factory handset coverage. This is reconciliation
of component invocations, not one complete 220-case run.
