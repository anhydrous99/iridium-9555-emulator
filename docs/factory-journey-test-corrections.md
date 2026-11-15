# Corrections of four factory journeys

Four journeys, each with a 9555 and a 9575 case, stop on the released firmware at firmware faults before they reach
their later stages (see the [coverage ledger](factory-e2e.md)):

| journey | where the released firmware stops |
|---|---|
| `test_factory_messages_draft_patient_e2e` … `test_patient_1000_character_limit_rejects_extra_and_reopens_every_glyph` | modem restart (DSP command queue full) after about 50 characters |
| `test_factory_security_e2e` … `test_phone_lock_with_factory_modem_rejects_wrong_pin_and_unlocks_after_restart` | 9555: the PIN form never appears after the restart; 9575: modem restart |
| `test_factory_phonebook_limits_persistence_e2e` … `test_all_six_maximum_fields_survive_completed_shutdown_and_original_warm_startup` | BlueCore allocation panic while the fields are typed |
| the same file … `test_no_tone_all_six_maximum_fields_survive_completed_shutdown_and_original_warm_startup` | modem restart |

Their later stages had therefore never run. They were reached for the first time on modified firmware: HT25003 and
HL25003 rebuilt from source with those faults corrected at source level (that firmware is not part of this
repository). There each journey stopped on an expectation of the test itself.

Each such expectation was then compared with the released firmware. The rule: where the released firmware shows the
same behaviour, the test is wrong and is corrected; where it does not, the firmware is at fault. All three
corrections below are of the first kind. No check is removed and no comparison is loosened.

| journey (both handsets) | released firmware, before and after this change | modified firmware, tests as before | modified firmware, corrected tests |
|---|---|---|---|
| patient 1000-character draft | fails at the modem restart | fails at the budget check, 5,002M of 5,000M | passes |
| phone lock | fails: PIN form never shown (9555), modem restart (9575) | fails waiting for home after the right code | passes |
| six maximum fields, both cases | fails at the panic / the modem restart | fails in the read-back after the warm start | passes |

The outcomes on the released firmware do not change, so the ledger's factory counts stand.

## 1. Patient 1000-character draft: the budget belongs to another journey

`healthy()` in `test_factory_messages_draft_limits_e2e.py` fails when the modem has run more than 5,000M instructions
since `setUp`. It was written for the rapid journey of that file. The patient variant takes it by alias and adds
`self.handset.step(2000000)` after every accepted key: 1002 keys, 2,004M instructions that the rapid journey does
not have, charged to the same 5,000M.

- The test's own waits are 4,499.5M (1002 keys at 2.25M, 898 read-back moves at 2.5M). Start, save and reopen take
  234.4M. That leaves 266.1M for 1000 counter updates and 898 view updates.
- The released editor needs far more. With the released BlueCore and AVR images of both handsets, and only the modem
  kept from restarting, a key costs 2.64M, 2.89M, 2.97M, 3.09M and 3.27M instructions at 25, 100, 200, 400 and 600
  characters (the test's own 2.25M included). The firmware's share was 914.2M after 975 characters on the 9555 and
  657.7M after 775 on the 9575, when those runs stopped on a lost key press, a separate firmware fault.
- The same costs per key were measured on the modified firmware, where the whole journey takes 5,957.1M.

Correction: the modem instructions executed during the variant's added wait, read from the modem's step counter, are
added to `_origin`. The allowance for everything else stays 5,000M.

## 2. Phone lock: a journey without a card

The journey has no card. Three later steps do not describe a handset without one.

1. After the right code the test waited for the home soft keys. The handset first shows "SIM Error: insert a valid
   SIM card". The first start of the same test requires that alert (`boot_with_known_modem_alerts`).
2. After the lock is switched off the test expected the menu picture of entering the menu, cursor on the first
   entry. The cursor had been moved to "Disable Phone Lock", and the menu returns with the cursor there.
3. At the last start the test again waited for home with no step for the alert, although card and lock state are
   those of the first start.

On the released firmware:

- Every start without a card shows the alert: the modem answers the BlueCore's `AT+CICCID+CPIN?` with
  `+CME ERROR:013`, and the alert follows (at about 100M modem instructions). A start with the lock off after it had
  been on does the same.
- `test_factory_firmware_version_e2e` and the two warm-start cases of `test_factory_persistence_e2e` pass on the
  released firmware and require this alert after a warm restart.
- After `AT+CLCK="CS",0,"1234"` → `OK` in the Phone Lock menu the handset shows the menu with the cursor on "Disable
  Phone Lock" (rows 16:113 hash `a4f878f1…97b9`); after enabling it shows `PHONE_LOCK_MENU`.

Correction: the alert loop of `boot_with_known_modem_alerts` is also called after the unlock and at the last start,
in front of the original waits for home, which stay; the menu picture after switching the lock off is
`PHONE_LOCK_MENU_ON_DISABLE`. The 9575 case passes with the same picture; its alert loop already handled the 9575's
"IERCC not configured" alert.

The corrected test still fails on the released firmware. On the 9555 it fails at `expect(PHONE_PIN)` after the
restart: without a card the released modem answers `+CME ERROR:013` to the PIN query whether or not the phone lock is
on, so the handset never asks for the code. On the 9575 it fails earlier, at the modem restart.

## 3. Maximum-field read-back: a half-drawn frame taken as the picture

For a cursor move during the read-back, `keys()` in `test_factory_phonebook_limits_persistence_e2e.py` stepped 50,000
instructions at a time until the field's pixels differed from the frame before the key, and `full_text` then read
that frame as the complete picture. The handset sends a changed field to the display page by page (8 pixel rows per
page), so a sample can fall between two pages of one update. The half-drawn frame matches no expected window, and
the next move scrolls that window away.

On the released firmware: `test_factory_phonebook_fields_e2e` passes with its own 2M waits. Run with this helper in
their place it fails (field 0, window 0 not seen): in move 23, page 2 changes at +696,056 and +697,056 instructions,
the helper samples at +700,000, and page 3 changes at +705,096 and +706,096. With the corrected helper the same run
passes all 120 moves.

Correction: after the first change the helper keeps stepping until two consecutive samples of the field are equal,
within the same 2,000,000 limit. The longest field update measured is 18,920 instructions, the longest pause between
two pages 13,824. A pause longer than one sample would still give a half-drawn frame, and then the test fails; it
cannot make a wrong text pass.

## What the corrected tests still catch

- A saved text with one wrong character (first digit of a phone number; first character of the e-mail address):
  both cases fail in the read-back.
- A lock that is never switched off: fails at the last start, with the PIN form on the screen.
- A handset that accepts any code, or never locks: caught by lines this change does not touch
  (`expect(INCORRECT_PIN)`, `expect(PHONE_LOCKED)`, `expect(PHONE_PIN)`).
- A journey that redraws more slowly than the rapid journey allows still exceeds its instruction limit.

Results hold for the exact images they were measured on: several journeys depend on the phase between display
updates and the test's samples.
