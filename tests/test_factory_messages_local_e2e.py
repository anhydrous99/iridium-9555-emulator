"""Original read-only SIM initialization, empty Messages and local preferences.

No card write, composed message, service-center operation or delivery is tested.
Guest instruction intervals and the inferred clock ratio are not physical time.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS
from factory_sim_peer import FactorySIMPeer
from iridium.assets import BC5Assets
from test_factory_e2e import MAIN_MENU
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_security_e2e import (
    FIRMWARE_IDENTITY_WARNING, IERCC_DISABLED, IERCC_NOT_CONFIGURED,
    SOS_MESSAGE_RECIPIENT_WARNING, STARTUP_SIM_ERROR,
)


MESSAGES = ("Create Message", "Inbox", "Drafts", "Outbox", "Settings")
SETTINGS = ("Service Center", "Expiry Period", "Delivery Reports")
DELIVERY = ("Off", "On")
EXPIRY = ("1 hour", "2 hours", "4 hours", "1 day", "2 days", "1 week")
SCAN_READY = {"9555": 0xF85B, "9575": 0xF88B}
CAPACITY = {"9555": 0xF875, "9575": 0xF8A6}
ALERTS = {
    STARTUP_SIM_ERROR: "sim-error", FIRMWARE_IDENTITY_WARNING: "firmware-identity",
    IERCC_NOT_CONFIGURED: "iercc-not-configured", IERCC_DISABLED: "iercc-disabled",
    SOS_MESSAGE_RECIPIENT_WARNING: "sos-message-recipient",
}


class MessagesLocalChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.evidence = []
        self.peer = FactorySIMPeer(self, self.handset)
        self.addCleanup(self.finish)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])
        firmware = self.handset.session.firmware["bc5"]
        assets = BC5Assets(firmware.data, firmware.profile)
        radio_id = 7 if self.model == "9575" else 5
        self.assertEqual(sha256(assets.file_bytes(radio_id)).hexdigest(),
                         "7b0ee05692b8f09f5909302a7f6f051dc662b5422dd03dbd49c271ed63ec4e99")
        self.radio = tuple(assets.bitmap(radio_id, frame).pixels for frame in range(2))

    def finish(self):
        path = None
        try:
            try:
                state = self.handset.state()
                path = self.handset.save_artifacts("final", state)
                self.final_images = state["images"]
            finally:
                self.peer.close()
        finally:
            self.peer_evidence = self.peer.evidence()
            self.assertFalse(any(event["kind"] == "header" and event["bytes"][1] in (0xD6, 0xDC, 0x32)
                                 for event in self.peer.card.events), "Read-only journey attempted a card write")
            if path:
                Path(str(path) + ".peer.json").write_text(
                    json.dumps(self.peer_evidence, indent=2) + "\n")
            self.handset.close()
            self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                                   for image, worker in self.peer.workers.items()}
            self.assertTrue(all(self.worker_closure.values()))

    def read(self, image, address, count=1):
        return self.handset.request("POST", "/api/probe", {
            "image": image, "operation": "read", "address": address, "count": count,
        })["values"]

    def record(self, label):
        state = self.handset.assert_healthy()
        self.peer.check()
        self.assertTrue(state["processor_link"]["connected"])
        self.assertEqual(next(cpu for cpu in state["processors"] if cpu["image"] == "trx")
                         ["uart_tx_dropped"][3], 0)
        path = self.handset.save_artifacts(label, state)
        self.evidence.append({"label": label, "artifact": str(path),
                              "steps": {cpu["image"]: cpu["steps"] for cpu in state["processors"]},
                              "frame_sha256": sha256(bytes(state["lcd"]["pixels"])).hexdigest()})
        print(f"{self.model}: {label} at TRX "
              f"{next(cpu['steps'] for cpu in state['processors'] if cpu['image'] == 'trx')}",
              flush=True)
        return state

    def press(self, key, *, hold=500000, settle=500000):
        self.peer.check()
        self.assertTrue(self.handset.key(key, True)["delivered"])
        self.handset.step(hold)
        self.assertTrue(self.handset.key(key, False)["delivered"])
        state = self.handset.step(settle)
        self.peer.check()
        return state

    def submit(self):
        # A patient physical contact interval for the original settings action;
        # never replay an accepted key or bypass the actual widget callback.
        return self.press("soft_left", hold=1000000, settle=2000000)

    def original_home_and_scan(self):
        self.handset.control("initialize_ui")
        self.handset.control("pause")
        seen = set()
        for _ in range(125):
            state = self.handset.state()
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, seen, "Repeated startup modal")
                seen.add(body)
                self.record("startup-" + ALERTS[body])
                self.press("soft_right")
            elif self.handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.record("home-before-natural-scan")
                break
            else:
                self.handset.step(1000000)
                self.peer.check()
        else:
            self.handset.save_artifacts("startup-timeout")
            self.fail("Original modem startup did not reach a recognized home screen")
        # The failed early CMGL schedules20M original timer ticks, which take
        # 160M further modeled BC5 instructions. Never force that timer/flag.
        while self.read("bc5", SCAN_READY[self.model]) != [1]:
            state = self.handset.state()
            trx = next(cpu for cpu in state["processors"] if cpu["image"] == "trx")
            self.assertLess(trx["steps"], 240000000, "Original initial scan did not complete")
            body = self.handset.screen_hash(state=state)
            if body in ALERTS:
                self.assertNotIn(body, seen, "Repeated startup modal while waiting")
                seen.add(body)
                self.record("startup-" + ALERTS[body])
                self.press("soft_right")
            else:
                self.assertEqual(self.handset.screen_hash(113, 128, state), HOME_CAPTIONS,
                                 "Natural scan wait must remain at original home")
                self.handset.step(2000000)
                self.peer.check()
        self.assertEqual(self.read("bc5", CAPACITY[self.model]), [2])
        self.assertEqual(self.read("trx", 0x400AA2D6), [2])
        self.assertEqual(self.read("trx", 0x400AA2D3), [3])
        self.assertEqual(self.read("trx", 0x400AA30C, 4), [0, 0, 0, 1])
        self.record("original-scan-ready-at-home")

    def text(self, state, value, row, left=2, width=118, selected=False):
        expected, _ = self.font.render(value, width)
        if selected:
            expected = bytes(3 - pixel for pixel in expected)
        actual = bytes(state["lcd"]["pixels"][(row + y) * 128 + left + x]
                       for y in range(15) for x in range(width))
        return actual == expected

    def title(self, state, label):
        _, width = self.font.render(label, 128)
        return self.text(state, label, 0, (127 - width) // 2, width)

    def menu(self, labels, selected, label, *, left=2, width=118, stored=None, max_steps=4000000):
        titles = {MESSAGES: "Messages", SETTINGS: "Settings",
                  DELIVERY: "Delivery Reports", EXPIRY: "Expiry Period"}
        # Original B99F4 may page to the focused item after an offscreen move.
        # Require visible focus and every visible saved/unsaved radio mark.
        # The stored choice can be offscreen during an unsaved draft; decisive
        # readbacks require visible focus==stored. Page-start policy can vary.
        starts = range(max(0, selected - 4), selected + 1) if labels == EXPIRY else (0,)
        for elapsed in range(0, max_steps + 1, 200000):
            state = self.handset.assert_healthy()
            for top in starts:
                visible = labels[top:top + 5]
                if not self.title(state, titles[labels]):
                    continue
                if not all(self.text(state, text, 16 + 17 * row, left, width,
                                     top + row == selected)
                           for row, text in enumerate(visible)):
                    continue
                if stored is not None and not all(
                        bytes(state["lcd"]["pixels"][(19 + 17 * row + y) * 128 + 2 + x]
                              for y in range(9) for x in range(9)) == self.radio[top + row == stored]
                        for row in range(len(visible))):
                    continue
                if any(state["lcd"]["pixels"][y * 128 + x]
                       for y in range(16 + 17 * len(visible), 111) for x in range(2, 120)):
                    continue
                self.assertTrue(self.text(state, "Select", 112, 2, 36))
                self.assertTrue(self.text(state, "Back", 112, 99, 28))
                self.record(label)
                self.evidence[-1]["oracle"] = {"title": titles[labels], "visible_labels": visible,
                    "first_visible_index": top, "focused_index": selected, "stored_index": stored,
                    "unused_rows_blank": True}
                return state
            if elapsed < max_steps:
                self.handset.step(200000)
        self.handset.save_artifacts(label + "-timeout", state)
        self.fail(f"Original-font menu did not match {labels!r}, selected {selected}, stored {stored}")

    def empty_mailbox(self, index, label):
        self.press("soft_left")
        for _ in range(21):
            state = self.handset.assert_healthy()
            if (self.title(state, label) and
                    self.text(state, "(empty)", 16, selected=True) and
                    not any(state["lcd"]["pixels"][row * 128 + x]
                            for row in range(32, 110) for x in range(2, 120))):
                self.record(label + "-empty")
                self.evidence[-1]["oracle"] = {"title": label, "placeholder": "(empty)",
                                              "unused_rows_blank": True}
                break
            self.handset.step(200000)
        else:
            self.handset.save_artifacts(label + "-empty-timeout")
            self.fail("Original mailbox did not render its literal (empty) row")
        self.press("soft_right")
        self.menu(MESSAGES, index, label + "-back")

    def move_selection(self, current, target):
        for _ in range(abs(target - current)):
            self.press("down" if target > current else "up")

    def preference(self, parent_index, choices, label, original=0, changed=1):
        self.press("soft_left")
        self.menu(choices, original, label + "-default", left=13, width=107, stored=original)
        self.move_selection(original, changed)
        self.menu(choices, changed, label + "-draft-changed", left=13, width=107, stored=original)
        self.submit()
        self.menu(SETTINGS, parent_index, label + "-saved", max_steps=12000000)
        self.press("soft_left")
        self.menu(choices, changed, label + "-reopened", left=13, width=107, stored=changed)
        self.move_selection(changed, original)
        self.menu(choices, original, label + "-cancel-visible-default-draft",
                  left=13, width=107, stored=changed)
        self.press("soft_right")
        self.menu(SETTINGS, parent_index, label + "-cancelled")
        self.press("soft_left")
        self.menu(choices, changed, label + "-saved-choice-survives-cancel",
                  left=13, width=107, stored=changed)
        self.move_selection(changed, original)
        self.submit()
        self.menu(SETTINGS, parent_index, label + "-restored", max_steps=12000000)
        self.press("soft_left")
        self.menu(choices, original, label + "-restored-readback",
                  left=13, width=107, stored=original)
        self.press("soft_right")
        self.menu(SETTINGS, parent_index, label + "-finished")

    def open_messages(self):
        self.original_home_and_scan()
        self.press("soft_left")
        self.handset.wait_screen(MAIN_MENU[0][1], last=97, max_steps=2000000)
        self.press("down")
        self.press("down")
        self.handset.wait_screen(MAIN_MENU[2][1], last=97, max_steps=2000000)
        self.press("soft_left")
        self.menu(MESSAGES, 0, "usable-messages-menu")

    def restored_home(self):
        self.press("red")
        state = self.handset.wait_screen(HOME_CAPTIONS, first=113, last=128, max_steps=2000000)
        self.assertEqual(state["keys"], [])
        self.record("defaults-restored-home")

    def test_empty_mailboxes_and_all_expiry_choices_save_cancel_restore_factory_week(self):
        self.open_messages()
        for index, name in enumerate(("Inbox", "Drafts", "Outbox"), 1):
            self.press("down")
            self.menu(MESSAGES, index, "select-" + name)
            self.empty_mailbox(index, name)
        self.press("down")
        self.press("soft_left")
        self.menu(SETTINGS, 0, "message-settings")
        self.press("down")
        self.press("soft_left")
        self.menu(EXPIRY, 5, "expiry-factory-week", left=13, width=107, stored=5)
        self.press("up")
        self.menu(EXPIRY, 4, "expiry-two-days-visible-draft", left=13, width=107, stored=5)
        self.submit()
        # Original84C32/B3B3A schedules a1M-tick delayed close. In this
        # deterministic model that needs8M further BC5 instructions; all
        # CPUs continue normally during the bounded12M observation window.
        self.menu(SETTINGS, 1, "expiry-two-days-saved", max_steps=12000000)
        self.press("soft_left")
        self.menu(EXPIRY, 4, "expiry-two-days-readback", left=13, width=107, stored=4)
        self.press("down")
        self.menu(EXPIRY, 5, "expiry-cancel-visible-week-draft", left=13, width=107, stored=4)
        self.press("soft_right")
        self.menu(SETTINGS, 1, "expiry-week-draft-cancelled")
        self.press("soft_left")
        self.menu(EXPIRY, 4, "expiry-two-days-survives-cancel", left=13, width=107, stored=4)

        previous = 4
        for index in range(4):
            self.move_selection(previous, index)
            self.menu(EXPIRY, index, f"expiry-choice-{index}-draft",
                      left=13, width=107, stored=previous)
            self.submit()
            self.menu(SETTINGS, 1, f"expiry-choice-{index}-saved", max_steps=12000000)
            self.press("soft_left")
            self.menu(EXPIRY, index, f"expiry-choice-{index}-readback",
                      left=13, width=107, stored=index)
            previous = index
        self.move_selection(previous, 5)
        self.submit()
        self.menu(SETTINGS, 1, "expiry-factory-week-restored", max_steps=12000000)
        self.press("soft_left")
        self.menu(EXPIRY, 5, "expiry-factory-week-restored-readback", left=13, width=107, stored=5)
        self.press("soft_right")
        self.menu(SETTINGS, 1, "expiry-finished")
        self.restored_home()

    def test_delivery_reports_save_reopen_visible_cancel_and_restore_factory_off(self):
        self.open_messages()
        for _ in range(4):
            self.press("down")
        self.press("soft_left")
        self.menu(SETTINGS, 0, "message-settings")
        self.press("down")
        self.press("down")
        self.preference(2, DELIVERY, "delivery-reports")
        self.restored_home()


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"), "Set IRIDIUM_TEST_FIRMWARE")
class Factory9555MessagesLocalE2ETests(MessagesLocalChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"), "Set IRIDIUM_TEST_9575_FIRMWARE")
class Factory9575MessagesLocalE2ETests(MessagesLocalChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
