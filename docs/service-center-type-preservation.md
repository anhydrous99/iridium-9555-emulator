# Service Center Save changes an unchanged address type

Both HT25003 (9555) and HL25003 (9575) change the stored service-center address
type when the user opens Messages → Settings → Service Center and presses OK
without editing the number. The synthetic card initially contains digits
`12345` with type `0x91`. The original handset displays `12345`; saving it writes
the same digits with type `0x81`. Only byte 18 of the 32-byte SMSP record changes.

The [enabled regression](../tests/test_factory_messages_service_center_integrity_e2e.py)
requires the entire represented address to survive an unchanged Save. It fails
on both models. It makes no assumption about displaying a plus sign or sending
an SMS.

The test starts the actual BC5, AVR and TRX factory images, waits for the original
message scan, and verifies the complete number using the original font. It
submits the unedited form through HTTP keys, then waits beyond the early setter
callback for the actual card transaction. In both runs, the original TRX sends
`A0 DC 01 04 20`, transmits all 32 SMSP bytes, and receives the card's `DC 90 00`
procedure/status sequence. The retained card record matches those transmitted
bytes. All other bytes, including digits, padding and other SMSP fields, remain
identical.

Original HT25003 code explains the loss. The query parser at `0xC4BB2` copies
the text between quotes from the CSCA reply and discards its separate type
parameter. The setter at `0xC497C` builds `AT+CSCA="<text>"` followed by carriage
return, with no type parameter. Freshly decoded instructions and the local
decompilation agree on this command construction.

The shared TRX handler at `0xD3D80` initializes its type byte to `0x81`
(`mov -0x7f` followed by a byte store). It changes that value only when the
command includes a comma and a numeric type. Thus the GUI setter's omitted
parameter selects `0x81`. The 9575 form was located independently in its own
original instructions; its same address-type loss is established by its actual
wire transaction. The HT25003 parser address is not asserted as an HL25003
address.

The separate [Service Center tests](../tests/test_factory_messages_service_center_e2e.py)
pass digit editing, cancellation, completed card writes, rejected writes, and
fresh readback after a completed power cycle on both models. Those passes are
scoped to the observed digits/default-type behavior. They do not establish
preservation of an international address type. A successful immediate callback
also does not establish card persistence: a rejected card write can leave the
GUI cache changed until a later boot reloads the old card data.

Firmware, guest memory and native execution were not patched. Only the finite
external writable SMSP fixture responds to real UART traffic. No RF connection,
authentication, SMS transmission or delivery is claimed.

Evidence is preserved with the
[200-outcome reconciliation](../test-artifacts/factory-sms-editor-settings/report.json).
Its `http/` and `captures/` directories contain the two failing final reports and
their final LCD/peer/card captures. The complete intermediate frames, wire audit,
source snapshots and original-code excerpts are in
`diagnostics/service-center-integrity-expansion.tar.gz`; the independently
decoded Service Center and shared TRX listings are also in
`diagnostics/handset-service-center-expansion.tar.gz` in that same phase.
