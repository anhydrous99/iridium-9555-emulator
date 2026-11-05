# HL25003 negative-altitude display defect

The original 9575 HL25003 BC5 formatter loses a negative GPS altitude sign.
An external receiver sample with mean-sea-level altitude **−5 m** reaches the
parsed position correctly, but Current Location shows **+16 ft** or **+5 m**.
Both unit branches were observed through the real HTTP/native/LCD path.

The probe used the pinned HL25003 BC5/AVR images, RealTime mode, and receiver
bytes on AVR USART0. It first published the existing positive fixture, then a
second complete UBX/NMEA epoch without reopening Current Location:

| Field | First epoch | Second epoch |
| --- | --- | --- |
| iTOW | 123000 ms | 124000 ms |
| Latitude | 37.7749 | −33.8688 |
| Longitude | −122.4194 | 151.2093 |
| hMSL | +30000 mm | −5000 mm |
| hEllipsoid | +32000 mm | −3000 mm |
| Satellites | 8 | 9 |
| Receiver UTC | 2026-11-04 12:00:00 | 2026-11-04 12:00:01 |

The original AVR publishes the second position with flags `C0` and altitude
magnitude `5`; the positive fixture has flags `B0`. Original BC5 parser
`0xB4CDC` extracts altitude flag `0x10` into position word `+9` and magnitude
into words `+10/+11`. A read-only live snapshot showed manager `DE32`, cached
position `DE0A`, and these thirteen words:

```text
1, 1, 33, 52, 128, 0, 151, 12, 558, 0, 0, 5, 9
```

Thus the negative sign and five-meter magnitude survive the receiver, AVR,
SPI, and BC5 parsing stages. Latitude, longitude, and satellite count also
update correctly on the LCD.

Original Current Location refresh `0x8374A` copies the thirteen cache words
through `0xB84BC`, then passes the position unchanged through
`0x83B80 → 0x8452A → 0xC04A2`. The altitude formatter at `0xC04A2–0xC0618`
does not read sign word `+9`:

- The feet branch loads magnitude words `+10/+11`, multiplies by `3.281`,
  truncates, and uses file 48 word `0x279`, `%+d ft`. Five meters becomes +16 ft.
- The meters branch loads magnitude word `+11` and uses word `0x280`,
  `%+d m`. Five meters becomes +5 m.

These original instructions explain the observed display; no emulator sign
loss was demonstrated. Firmware bytes and guest memory were not patched, and
no coordinate or display callback was forced. GNSS radio acquisition and clock
synchronization are outside this probe.

Local reproduction and captured states are in `/tmp/iridium-gps-next-epoch.py`
and `/tmp/iridium-next-epoch/`, including `cached-position.json`, `second-fix`
and `negative-meters` PNG/JSON pairs. The two
[signed-altitude regressions](../tests/test_factory_gps_negative_e2e.py) require
the negative result and remain enabled and failing while this formatter is unchanged;
matching its incorrect plus sign is not evidence that signed altitude works.
Corrected firmware or a separately identified firmware patch would be needed
to change the original formatter. The emulator must not manufacture corrected
LCD pixels while claiming unchanged factory execution.

The expected signed LCD crops are constructed expectations, not falsely labeled
captures of working factory output. An independent renderer extracts the
original ASCII-1 font at raw `0x19DFE8`, validates its header/code/metric tables,
and renders at x2/y48. It exactly reproduces all 2048 pixels of the observed
unsigned `Alt:+98 ft`, `Alt:+16 ft` and `Alt:+5 m` crops at rows48:64. The font's
minus cell also exactly matches the observed negative-latitude glyph. Rendering
`Alt:-16 ft` and `Alt:-5 m` produces the regression hashes. The local oracle
reproducer is `/tmp/iridium-signed-altitude-oracle.py` and its output directory
is `/tmp/iridium-signed-altitude-oracle/`.
