# Phonebook retention needs modem startup

The original handset initializes its saved-contact index after receiving modem
startup data. A BC5/AVR-only fixture can create and reopen a contact in its
current session, then show an empty book after restart even though the record
remains in flash. This result does not establish erased storage.

Both handset profiles reproduced that incomplete-startup result. Read-only
HT25003 storage snapshots isolated it:

- Saving `Adg / +123` changed twelve flash words. The record at physical word
  `0x1F0060` begins `FFFE, 0041, 0064, 0067, 0000`; the original record classifier
  returns type `2`, meaning an active record.
- The complete flash image stayed byte-identical through completed shutdown,
  the next original setup call, and restarted home. Flash remained in read mode.
- The filesystem stayed ready (`F728=1`). Its first directory triple retained
  `[0001, 0080, 0002]`. The separate phonebook index pointer `F84E` was cleared
  during startup and had not been rebuilt.

Original HT25003 instructions explain the missing initialization:

```text
inbound modem envelope
  9B4AC -> registered receive callback 6BF86
        -> 6BFF4 -> 6C0F6: startup state 0x10 -> 0x20
        -> registered callback 8CA1E -> 712CA -> 85A58 -> BCBDC
        -> rebuild F84E from saved flash records
```

Setup `6BE5E` registers the receive callback through `9B156`; setup `8CC8C`
registers the transition callback. `BCBDC` initializes its iterator to `FFFF`
and enumerates active records through `6C5BC -> 6CEEE -> 6D294`. The underlying
filesystem header checks and record reads succeeded in the diagnostic run.
The BC5/AVR-only startup remained in state `0x10`.

A separate **real factory BC5/AVR/TRX** HT25003 probe passed in 253.212 seconds.
It dismissed only recognized original SIM/identity alerts, saved and reopened
the contact, completed shutdown state `8`, and restarted. Genuine modem traffic
again reached state `0x20`, rebuilt index `[1, 1, 029A, 029A]`, and restored the
actual `Adg / +123` LCD contents. No firmware, guest state, modem reply or cache
callback was substituted. No native storage fix was justified.

The [persistence journeys](../tests/test_factory_persistence_e2e.py) therefore
load the pinned TRX image and process original startup warnings on every boot.
They separately check saved settings/contacts/notes across warm startup,
contact/note retention through Reset to Defaults, and the reset setting across
restart. Their reported runtime results belong in the [coverage ledger](factory-e2e.md).
These warm-start tests retain guest flash in the same experiment; they do not
establish storage across reloading a source image or restarting the host process.

Private local evidence: `/tmp/iridium-persistence-flash-probe/` and
`/tmp/iridium-persistence-flash-read-probe/` contain the read-only storage
snapshots; `/tmp/iridium-text-entry-expansion/contact-retention-findings.json`
records original callbacks and the successful real-modem probe. Diagnostic
classification calls are separate from the HTTP persistence tests, which use
handset keys and LCD assertions. Native DSP execution and real service remain
unimplemented. The 9575 reset-retention case verifies the saved name, number
and note, then reaches the existing DSP-fatal signature while returning home.
It remains enabled and failing; the verified storage behavior does not make
the complete journey pass.
