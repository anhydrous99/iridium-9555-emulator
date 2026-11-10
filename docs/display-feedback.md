# Display feedback and accessible text

The browser renders the original ST7541 pixel stream. Electronic-volume
command `0x81` contributes its six-bit value as `contrast_ratio`; the browser
uses that ratio for approximate contrast without changing the logical pixels.

Backlight feedback reads the original AVR output group through the existing
`pin_state` snapshot:

| Handset | Observed backlight outputs | Browser condition |
| --- | --- | --- |
| 9555 | PB3 and PD5 | `pins[1] & 8 or pins[3] & 32` |
| 9575 | PA3 and PA4 | `pins[0] & 24` |

The 9555 original menu setter `0x7353E` reaches timed control
`0x9840E/0x9852E`, then GPIO writers `0xAB60E/0xAB650` with selectors `0x16`
and `0x3A`. The 9575 wrappers use the same selectors at
`0xB4864/0xB48A6`; its AVR maps them to the output group above. The host does
not read preference strings or infer backlight from the selected menu.

Both factory models were exercised through Backlight Off, saving five
seconds, idle timeout, and a genuine key press. Off and timeout cleared the
listed output group; saving five seconds and key wake set it. 9555 snapshots
changed from `[48,12,1,48]` to `[48,5,1,16]`; 9575 port A changed from `0x9C`
to `0x04`. The varying SPI handshake bits are excluded. The idle check used
four chunks of ten million original instructions, not a claim of calibrated
physical clock time. LCD versus keypad wiring within each output group and
optical brightness remain unmeasured, so the browser labels brightness as
approximate.

`DisplayText` reads the original ASCII-1 and Dialling font resources and
matches their glyph bitmaps against visible pixels. It handles selected rows,
spaces, supported Latin-1 text and large digits. Results are cached by the
actual frame and copied for each caller. Unsupported, obscured or visually
ambiguous glyphs remain `[unreadable]`; it never substitutes guessed screen
labels. The accessible transcript includes selection and completeness, and
is withheld for incomplete, invalid or inactive LCD captures.

Audio synthesis and physical vibration are not implemented. Saved volume
and tone choices still belong to the original firmware; the UI identifies
the missing output rather than claiming those settings produce sound.
