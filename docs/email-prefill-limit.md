# HL25003 maximum-email prefill defect

The original 9575 Emergency recipient email editor accepts 74 ASCII characters,
but a saved address
of that length reopens without its text. A 73-character address works through
the same save/reopen path. This is separate from validating email syntax or
delivering a message.

The separate local-phonebook email field accepts 64 characters. Its complete
63/64-character save/reopen cases pass on both models; the Emergency
74-character failure must not be generalized to that other editor path.

The [emergency configuration tests](../tests/test_factory_emergency_config_e2e.py)
keep input-limit and saved-value behavior separate:

- At 74 characters the original remaining-character counter reaches zero.
  An extra key does not change the rendered input. Backspace frees one
  character, retyping fills it, and Cancel leaves the recipient list empty.
- A 73-character address saves and reopens with one character available. Its
  visible suffix independently matches the pinned original font; the list
  prefix is also checked. Hidden prefix glyphs are not independently reread.
- Appending one character makes a 74-character address. Saving returns to the
  recipient list, but Edit shows a `?` placeholder with all 74 characters available.
  The enabled regression requires the saved value and zero available characters;
  it fails on the original output.

Original HL25003 instructions account for this boundary. The email constructor
at `0x92780/0x927B4` supplies 75 units through `0xCE062`; `0xCE074/0xCE080`
creates the string and sets its maximum through `0xE677C/0xE6CEA`. The prefill
setter at `0xE6A76` computes offset plus string length plus the terminator, then
rejects equality with the 75-unit maximum at `0xE6AA2/0xE6AA4`. Thus 73
characters plus the terminator fit its strict comparison, while 74 plus the
terminator are rejected despite being accepted by the input editor.

The caller through `0x927CE → 0xCCC22 → 0xE6A76` ignores that rejected return
and frees the source at `0x927EE`. The observed result is a rejected prefill.
The list's retained display is not proof of a successful full-length editor
round trip. The unchanged 73-character control and the original comparison
support a firmware boundary defect, rather than demonstrated storage erasure.

Firmware and guest memory were not patched. The tests use original BC5/AVR,
HTTP keys and native LCD output; no service response or editor callback is
substituted. Malformed syntax is not claimed to be rejected: a diagnostic
showed the original UI accepting `adg` without an `@`.

Private local evidence is recorded in
`/tmp/iridium-emergency-config-expansion/boundary-provenance.json` and
`boundary-outcomes.json`. Original setter/caller instructions are retained in
`/tmp/iridium-location-limits-expansion/email-prefill.lst`. Captured input,
73-character control and failed 74-character reopening frames are under the
emergency expansion's `boundary-probe` and test artifact directories.
