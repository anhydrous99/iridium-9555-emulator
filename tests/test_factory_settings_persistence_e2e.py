"""Selected locale, time/display and input preferences across real warm startup.

Only French and the listed values are covered. Displayed labels do not establish
physical timeout timing, audio completion, RTC accuracy or network service.
"""

from hashlib import sha256
import os
import struct
import unittest

from factory_handset import HOME_CAPTIONS
from iridium.assets import BC5Assets
from test_factory_phonebook_limits_persistence_e2e import MaximumFieldPersistenceChecks as _Fixture
from test_factory_persistence_e2e import SharedPersistenceChecks as _Power
from test_factory_settings_e2e import (
    SETUP, VOLUME_MENU, KEYPAD_TONE_MENU, KEYPAD_SINGLE_TONE, KEYPAD_NO_TONE,
    TIME_ZONE_MENU, TIME_ZONE_UTC, TIME_ZONE_PLUS_HALF,
    TIME_FORMAT_MENU, TIME_TWENTY_FOUR_HOURS, TIME_AM_PM,
    DATE_FORMAT_MENU, DATE_DEFAULT, DATE_SLASHES,
    BACKLIGHT_MENU, BACKLIGHT_FIVE_SECONDS, BACKLIGHT_TEN_SECONDS,
)
from test_factory_customization_e2e import (
    LANGUAGE_MENU, MENU_ENGLISH, LANGUAGE_FRENCH, MENU_FRENCH,
    MENU_FRENCH_ENGLISH_FOCUS, NUMBER_ENTRY_MENU, PREFIX_PLUS, PREFIX_ZERO,
    DIAL_ZERO_TWELVE, DIAL_PLUS_TWELVE,
)
from test_factory_security_e2e import (
    STARTUP_SIM_ERROR, FIRMWARE_IDENTITY_WARNING, IERCC_NOT_CONFIGURED,
    IERCC_DISABLED, SOS_MESSAGE_RECIPIENT_WARNING,
)


ALERTS = {STARTUP_SIM_ERROR: "absent-sim", FIRMWARE_IDENTITY_WARNING: "firmware-identity",
          IERCC_NOT_CONFIGURED: "iercc-not-configured", IERCC_DISABLED: "iercc-disabled",
          SOS_MESSAGE_RECIPIENT_WARNING: "sos-message-recipient"}
FRENCH_ALERTS = {
    0x1047: ("absent-sim", ("Erreur", "insérer", "carte", "valide")),
    0x1255: ("firmware-identity", ("Microprog", "incohérent.", "Exécuter", "niveau.")),
    0x1307: ("iercc-not-configured", ("ATTENTION", "n'avez", "configuré", "IERCC")),
    0x1305: ("iercc-disabled", ("ATTENTION", "désactivé,", "programmer", "d'AP")),
    0x1306: ("sos-message-recipient", ("ATTENTION", "désactivé,", "programmer", "destinataire...")),
}


class SettingsPersistenceChecks:
    # Alias only fixture/observation methods, never the older test methods.
    setUp = _Fixture.setUp
    finish = _Fixture.finish
    snapshot = _Fixture.snapshot
    keys = _Fixture.keys
    physical = _Fixture.physical
    expect = _Fixture.expect
    expected_counter = _Fixture.expected_counter
    shutdown_and_restart = _Power.shutdown_and_restart

    def text(self, state, value, row, left=2, width=118, selected=False):
        expected, _ = self.font.render(value, width)
        actual = bytes(state["lcd"]["pixels"][(row + y) * 128 + left + x]
                       for y in range(15) for x in range(width))
        return actual == (bytes(3 - p for p in expected) if selected else expected)

    def title(self, state, value):
        _, width = self.font.render(value, 128)
        return self.text(state, value, 0, (127 - width) // 2, width)

    def captions(self, state, left, right):
        _, lw = self.font.render(left, 128)
        _, rw = self.font.render(right, 128)
        return self.text(state, left, 112, 2, lw) and self.text(state, right, 112, 127 - rw, rw)

    def fragment(self, state, value):
        expected, width = self.font.render(value, 128)
        rows = [expected[y * 128:y * 128 + width] for y in range(15)]
        anchor = max(range(15), key=lambda y: rows[y].count(3))
        lcd = state["lcd"]["pixels"]
        for top in range(98):
            actual = bytes(lcd[(top + anchor) * 128:(top + anchor + 1) * 128])
            left = actual.find(rows[anchor])
            while left >= 0:
                if all(bytes(lcd[(top + y) * 128 + left:(top + y) * 128 + left + width]) == rows[y]
                       for y in range(15)):
                    return True
                left = actual.find(rows[anchor], left + 1)
        return False

    def load_resources(self):
        fw = self.handset.session.firmware["bc5"]
        assets = BC5Assets(fw.data, fw.profile)
        language = assets.file_bytes(45 if self.model == "9575" else 43)
        self.language_resource_sha256 = sha256(language).hexdigest()
        words = struct.unpack(">" + str(len(language) // 2) + "H", language)
        self.strings = {}
        pos = 0
        while pos < len(words):
            kind, locale, size = words[pos:pos + 3]
            part = words[pos + 3:pos + 3 + size]
            pos += 3 + size
            if kind == 4 and locale in (0, 5):
                count = part[0]
                offsets, blob = part[1:1 + count], part[1 + count:]
                self.strings[locale] = {0x1000 + i: "".join(map(chr, blob[o + 1:o + 1 + blob[o]]))
                                        for i, o in enumerate(offsets)}
        self.assertEqual(pos, len(words))
        self.assertEqual(self.strings[5][0x105A], "Langue")
        self.assertEqual(self.strings[5][0x1062], "Saisie texte")
        self.assertEqual(self.strings[5][0x1134], "Sélect")
        self.assertEqual(self.strings[5][0x112F], "Retour")
        for sid, (_, fragments) in FRENCH_ALERTS.items():
            if sid in self.strings[5]:
                self.assertTrue(all(value.removesuffix("...") in self.strings[5][sid] for value in fragments))
        radio_id = 7 if self.model == "9575" else 5
        self.assertEqual(sha256(assets.file_bytes(radio_id)).hexdigest(),
                         "7b0ee05692b8f09f5909302a7f6f051dc662b5422dd03dbd49c271ed63ec4e99")
        self.radio = tuple(assets.bitmap(radio_id, frame).pixels for frame in range(2))

    def boot_with_modem_alerts(self):
        if not hasattr(self, "strings"):
            self.load_resources()
        if self.boots:
            state = self.handset.state()
            self.assertEqual(next(p for p in state["processors"] if p["image"] == "bc5")["power_state"], 8)
            self.assertFalse(state["ui_initialized"])
            self.snapshot("completed-poweroff8-before-original-warm-startup", state)
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        seen = set()
        required = {"absent-sim"} if self.model == "9555" else {
            "iercc-not-configured", "iercc-disabled", "sos-message-recipient"}
        for _ in range(200):
            state = self.handset.assert_healthy(require_lcd=False)
            body = self.handset.screen_hash(state=state)
            label, language = ALERTS.get(body), "English"
            fragments = ()
            if label is None and state["lcd"]:
                for sid, (candidate, values) in FRENCH_ALERTS.items():
                    if sid in self.strings[5] and all(self.fragment(state, value) for value in values):
                        label, language, fragments = candidate, "French", values
                        break
            if label is not None:
                self.assertNotIn(label, seen, "Repeated original startup modal")
                seen.add(label)
                self.snapshot("startup-" + language + "-" + label, state)
                self.evidence[-1]["startup_oracle"] = {"language": language, "category": label,
                                                        "independent_source_fragments": fragments}
                self.physical("soft_right", hold=500000, released=500000)
            elif required <= seen and state["lcd"] and (
                    self.captions(state, "Menu", "Help") or self.captions(state, "Menu", "Aide")):
                self.assertEqual({p["image"] for p in state["processors"]}, {"bc5", "avr", "trx"})
                self.assertTrue(state["processor_link"]["connected"])
                self.assertEqual(state["keys"], [])
                self.assertEqual({i: e._process.pid for i, e in self.handset.session.engines.items()},
                                 {i: w["pid"] for i, w in self.workers.items()})
                self.boots += 1
                self.snapshot(f"original-boot-{self.boots}-home", state)
                return
            else:
                self.handset.step(1000000)
        self.snapshot("unrecognized-original-startup")
        self.fail("Original startup did not reach recognized Home after its actual warning dialogs")

    def body(self, expected, label):
        state = self.expect(expected)
        self.snapshot(label, state)
        self.evidence[-1]["body_sha256"] = expected
        return state

    def home(self):
        for _ in range(3):
            self.keys("red")
            state = self.handset.assert_healthy()
            if self.captions(state, "Menu", "Help") or self.captions(state, "Menu", "Aide"):
                self.assertEqual(state["keys"], [])
                return state
        self.snapshot("home-timeout", state)
        self.fail("Original Home captions not visible")

    def open_setup(self, item):
        self.keys("soft_left", *(["down"] * 6), "soft_left")
        for _ in range(21):
            state = self.handset.assert_healthy()
            french = (("Opt localisation", "Options appels", "Vol et tonalités", "Heure et date", "Langue")
                      if self.model == "9575" else
                      ("Options appels", "Vol et tonalités", "Heure et date", "Langue", "Rétroéclairage"))
            if (self.handset.screen_hash(state=state) == SETUP[self.model] or
                    (self.title(state, "Configuration") and
                     all(self.text(state, value, 16 + 17 * i, selected=i == 0)
                         for i, value in enumerate(french)) and self.captions(state, "Sélect", "Retour"))):
                break
            self.handset.step(200000)
        else:
            self.snapshot("Setup-parent-timeout", state)
            self.fail("Original English/French Setup parent not visible")
        self.keys(*(["down"] * (item + (self.model == "9575"))))

    def save_changed(self, parent, original, changed, label):
        self.expect(parent)
        self.keys("soft_left")
        self.body(original, label + "-initial")
        self.keys("down", "soft_left")
        self.expect(parent)
        self.keys("soft_left")
        self.body(changed, label + "-saved-reopened")
        self.keys("soft_right")

    def draft(self, labels, focused, stored, label):
        for _ in range(21):
            state = self.handset.assert_healthy()
            pixels = state["lcd"]["pixels"]
            if (all(self.text(state, value, 16 + 17 * i, 13, 107, i == focused)
                    for i, value in enumerate(labels)) and
                    all(bytes(pixels[(19 + 17 * i + y) * 128 + 2 + x]
                              for y in range(9) for x in range(9)) == self.radio[i == stored]
                        for i in range(len(labels))) and self.captions(state, "Select", "Back")):
                self.snapshot(label, state)
                self.evidence[-1]["radio_oracle"] = {"labels": labels, "focused": focused, "stored": stored}
                return
            self.handset.step(200000)
        self.snapshot(label + "-timeout", state)
        self.fail("Expected visible draft and independent saved radio mark: " + label)

    def retained_cancel_restore(self, parent, changed, original, labels, stored, label):
        self.expect(parent)
        self.keys("soft_left")
        self.body(changed, label + "-boot2-retained")
        self.keys("up")
        self.draft(labels, stored - 1, stored, label + "-visible-default-draft")
        self.keys("soft_right")
        self.expect(parent)
        self.keys("soft_left")
        self.body(changed, label + "-cancel-preserved-retained-choice")
        self.keys("up", "soft_left")
        self.expect(parent)
        self.keys("soft_left")
        self.body(original, label + "-default-restored-reopened")
        self.keys("soft_right")

    def language_parent(self, french, label):
        for _ in range(101):
            state = self.handset.assert_healthy()
            if (self.title(state, "Langue" if french else "Language") and
                    self.text(state, "Menu", 16, selected=True) and
                    self.text(state, "Saisie texte" if french else "Text Entry", 33) and
                    self.captions(state, "Sélect" if french else "Select", "Retour" if french else "Back")):
                self.snapshot(label, state)
                self.evidence[-1]["language_oracle"] = {"french": french,
                    "title": "Langue" if french else "Language", "second_row": "Saisie texte" if french else "Text Entry",
                    "captions": ["Sélect", "Retour"] if french else ["Select", "Back"]}
                return
            self.handset.step(200000)
        self.snapshot(label + "-timeout", state)
        self.fail("Complete independent original-font Language parent/softkeys not visible")

    def test_french_locale_keypad_tone_and_number_prefix_survive_completed_shutdown_and_restore_defaults(self):
        self.open_setup(1)
        self.keys("soft_left", *(["down"] * 4))
        self.save_changed(KEYPAD_TONE_MENU, KEYPAD_SINGLE_TONE, KEYPAD_NO_TONE, "keypad-NoTone")
        self.home()
        self.open_setup(7)
        self.save_changed(NUMBER_ENTRY_MENU[self.model], PREFIX_PLUS, PREFIX_ZERO, "prefix00")
        self.home()
        self.open_setup(3)
        self.keys("soft_left")
        self.expect(LANGUAGE_MENU)
        self.keys("soft_left")
        self.expect(MENU_ENGLISH)
        self.keys(*(["down"] * 5), "soft_left")
        self.language_parent(True, "french-saved-complete-parent-and-softkeys")
        self.home()
        resets = self.handset.state()["processor_link"]["power_resets"]
        self.shutdown_and_restart()
        self.assertEqual(self.boots, 2)
        self.assertEqual(self.handset.state()["processor_link"]["power_resets"], resets + 1)
        self.open_setup(3)  # Same original ordinal while the labels are French.
        self.keys("soft_left")
        self.language_parent(True, "boot2-retained-french-parent-and-softkeys")
        self.keys("soft_left")
        self.body(MENU_FRENCH_ENGLISH_FOCUS, "boot2-visible-tentative-English")
        self.keys("soft_right")
        self.language_parent(True, "cancel-English-preserved-French")
        self.keys("soft_left", *(["down"] * 5))
        self.body(MENU_FRENCH, "boot2-French-saved-radio-and-focus")
        self.keys(*(["up"] * 5), "soft_left")
        self.language_parent(False, "English-default-restored")
        self.keys("soft_left")
        self.body(MENU_ENGLISH, "English-saved-radio-reopened")
        self.home()
        self.open_setup(1)
        self.keys("soft_left", *(["down"] * 4))
        self.retained_cancel_restore(KEYPAD_TONE_MENU, KEYPAD_NO_TONE, KEYPAD_SINGLE_TONE,
                                    ("DTMF Tones", "Single Tone", "No Tone"), 2, "keypad-tone")
        self.home()
        self.open_setup(7)
        self.expect(NUMBER_ENTRY_MENU[self.model])
        self.keys("soft_left")
        self.body(PREFIX_ZERO, "boot2-prefix00-retained")
        self.keys("up")
        self.draft(("Prefix with +", "Prefix with 00", "Do not prefix"), 0, 1, "visible-plus-draft")
        self.keys("soft_right", "soft_left")
        self.body(PREFIX_ZERO, "cancel-plus-preserved-prefix00")
        self.home()
        self.keys("1", "2")
        self.body(DIAL_ZERO_TWELVE, "retained-prefix-actual-0012-dispatch")
        self.home()
        self.open_setup(7)
        self.keys("soft_left", "up", "soft_left")
        self.expect(NUMBER_ENTRY_MENU[self.model])
        self.keys("soft_left")
        self.body(PREFIX_PLUS, "prefix-plus-default-restored-reopened")
        self.home()
        self.keys("1", "2")
        self.body(DIAL_PLUS_TWELVE, "restored-prefix-actual-plus12-dispatch")
        self.snapshot("locale-tone-prefix-restored-final-home", self.home())

    def test_time_zone_clock_date_and_backlight_survive_completed_shutdown_and_restore_defaults(self):
        self.open_setup(2)
        self.keys("soft_left")
        for index, (parent, original, changed, label) in enumerate((
                (TIME_ZONE_MENU, TIME_ZONE_UTC, TIME_ZONE_PLUS_HALF, "timezone-plus-half"),
                (TIME_FORMAT_MENU, TIME_TWENTY_FOUR_HOURS, TIME_AM_PM, "clock-am-pm"),
                (DATE_FORMAT_MENU, DATE_DEFAULT, DATE_SLASHES, "slash-date"))):
            if index:
                self.keys("down")
            self.save_changed(parent, original, changed, label)
        self.home()
        self.open_setup(4)
        self.save_changed(BACKLIGHT_MENU[self.model], BACKLIGHT_FIVE_SECONDS,
                          BACKLIGHT_TEN_SECONDS, "backlight10")
        self.home()
        resets = self.handset.state()["processor_link"]["power_resets"]
        self.shutdown_and_restart()
        self.assertEqual(self.boots, 2)
        self.assertEqual(self.handset.state()["processor_link"]["power_resets"], resets + 1)
        self.open_setup(2)
        self.keys("soft_left")
        self.retained_cancel_restore(TIME_ZONE_MENU, TIME_ZONE_PLUS_HALF, TIME_ZONE_UTC,
                                    ("UTC", "UTC + 0.5", "UTC + 1", "UTC + 1.5", "UTC + 2"), 1, "timezone")
        self.keys("down")
        self.retained_cancel_restore(TIME_FORMAT_MENU, TIME_AM_PM, TIME_TWENTY_FOUR_HOURS,
                                    ("24 hours", "am/pm"), 1, "clock-format")
        self.keys("down")
        self.retained_cancel_restore(DATE_FORMAT_MENU, DATE_SLASHES, DATE_DEFAULT,
                                    ("01-Jan-13", "DD/MM/YY", "DD-MM-YY", "DD.MM.YY", "MM/DD/YY"), 1, "date-format")
        self.home()
        self.open_setup(4)
        self.retained_cancel_restore(BACKLIGHT_MENU[self.model], BACKLIGHT_TEN_SECONDS, BACKLIGHT_FIVE_SECONDS,
                                    ("Off", "5 seconds", "10 seconds", "15 seconds", "20 seconds"), 2, "backlight")
        self.snapshot("time-date-backlight-defaults-restored-final-home", self.home())


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "9555 factory firmware not supplied")
class Factory9555SettingsPersistenceE2ETests(SettingsPersistenceChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE", "")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "9575 factory firmware not supplied")
class Factory9575SettingsPersistenceE2ETests(SettingsPersistenceChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE", "")


if __name__ == "__main__":
    unittest.main()
