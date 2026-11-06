# HL25003 GPS solution-validity defect

The original 9575 AVR takes the low bit of the UBX NAV-SOL **fix-type byte**
as position validity. The actual validity flag is in the next byte. As a
result, a 3D solution marked invalid replaces the last valid location, while
a valid 2D solution does not update Current Location.

The [GPS validity tests](../tests/test_factory_gps_validity_e2e.py) use genuine
receiver bytes, original AVR/BC5 instructions, SPI and the handset LCD. Each
starts with the same working 3D fix. The two failing cases remain ordinary
enabled regressions requiring the correct result.

| NAV-SOL input | Required behavior | Observed factory behavior |
| --- | --- | --- |
| Fix type 3, flags 1 | Accept the valid control | Coordinates, altitude and eight satellites appear. |
| Fix type 0, flags 0 | Retain the last valid position | Invalid epoch reaches AVR publication; the handset retains the previous fix and later accepts a valid epoch. |
| Fix type 3, flags 0 | Reject the invalid position | The BC5 cache and LCD change to the supplied invalid coordinates. |
| Fix type 2, flags 1 | Accept the valid 2D position | The handset retains its previous coordinates instead of displaying the new position. |

The 2D fixture keeps the preceding altitude unchanged and varies horizontal
position and satellite count. It does not require a new vertical solution.

The [u-blox6 protocol specification, sections 2.3 and 35.9](https://content.u-blox.com/sites/default/files/products/documents/u-blox6_ReceiverDescrProtSpec_%28GPS.G6-SW-10018%29_Public.pdf)
defines NAV-SOL payload byte 10 as the fix type, byte 11 as flags and flags bit 0
as the validity indication. Fix type 3 by itself does not establish validity.
The tests construct the 52-byte payload and both UBX checksums explicitly.
NMEA GST and the other required epoch messages remain checksum-correct and
consistent, so rejection cannot be attributed to an incomplete epoch.

Original AVR instructions explain both failures. At `0x2CF8–0x2D06`, the
NAV-SOL branch reads payload byte 47 for the satellite count. `0x2D14` then
subtracts `0x25` (37) from that index, selecting byte 10. `0x2D1C–0x2D22`
tests its bit 0 and copies it into packed-position flags bit 7. Selecting
byte 11 would require subtracting 36 instead. The current code therefore treats
odd fix types as valid regardless of flags bit 0, and rejects even fix types.
The initial type 3/flags 1 fixture could not distinguish the two bytes.

Original BC5 parser `0xB4CDC` extracts packed-position bit 7 at
`0xB4D06–0xB4D20`. The valid-only refresh path then explains the LCD result.
The fault precedes LCD formatting; firmware bytes, guest memory and display
pixels were not patched. No receiver RF acquisition, service registration,
clock synchronization or fix-age correctness is established by these tests.

Local source evidence is under `/tmp/iridium-gps-validity-expansion/`:
`current-location-parser.lst` and `position-parser-callers.lst`. The existing
complete AVR listing `/tmp/HL25003-avr.lst` was checked against 14,296 bytes of
the pinned AVR payload, SHA256
`8b2e5df7b59d04f526facfeb422939ef09d5df11603da0f7ad207262fd30ddc2`.
Native snapshots retain the LCD, CPU health, BC5 cache and both AVR position
buffers in a separate `receiver_diagnostics` field.
