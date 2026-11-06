"""Shared three-core factory handset lifecycle and original modem startup.

Scenario-specific field, preference and terminal-diagnostic assertions belong
to the calling tests. This helper supplies no card or service responses.
"""

from hashlib import sha256
from pathlib import Path

from factory_handset import FactoryHandset, HOME_CAPTIONS
from iridium.engine import Engine
from test_factory_phonebook_capacity_e2e import OriginalASCII1
from test_factory_security_e2e import (
    FIRMWARE_IDENTITY_WARNING, IERCC_DISABLED, IERCC_NOT_CONFIGURED,
    SOS_MESSAGE_RECIPIENT_WARNING, STARTUP_SIM_ERROR,
)


class FactoryModemChecks:
    def start_handset(self):
        self.evidence = []
        self.boots = 0
        self.request_method = Engine.request
        self.handset = FactoryHandset(self, self.model, self.firmware_directory, modem=True)
        self.workers = {
            image: {"pid": engine._process.pid,
                    "executable_sha256": sha256(Path(f"/proc/{engine._process.pid}/exe").read_bytes()).hexdigest()}
            for image, engine in self.handset.session.engines.items()
        }
        self.addCleanup(self.finish)
        self.font = OriginalASCII1(self.handset.session.firmware["bc5"])

    def setUp(self):
        self.start_handset()
        self.boot_with_modem_alerts()

    def physical(self, key, *, hold=300000, released=100000):
        state = self.handset.press(key, hold_steps=hold, settle_steps=released)
        return state if released else self.handset.assert_healthy(state)

    def keys(self, *keys, settle=1000000):
        for key in keys:
            self.physical(key, hold=500000, released=settle - 500000)

    def expect(self, screen, first=16, last=113):
        return self.handset.wait_screen(screen, first=first, last=last, max_steps=20000000)

    def snapshot(self, label, state=None):
        state = self.handset.state() if state is None else state
        label = f"{len(self.evidence):03d}-{label}"
        target = self.handset.save_artifacts(label, state)
        self.evidence.append({"label": label, "artifact": str(target), "boot": self.boots,
                              "steps": {cpu["image"]: cpu["steps"] for cpu in state["processors"]},
                              "frame_sha256": sha256(bytes(state["lcd"]["pixels"])).hexdigest()})
        print(f"{self.model}: {label} boot{self.boots} TRX "
              f"{next(cpu['steps'] for cpu in state['processors'] if cpu['image'] == 'trx')}", flush=True)
        return target

    def save_final_state(self):
        state = self.handset.state()
        self.final_state = state
        self.final_images = state["images"]
        self.final_artifact = str(self.handset.save_artifacts("final", state))
        return state

    def close_handset(self):
        server_thread = self.handset.thread
        self.handset.close()
        self.http_server_thread_closed = server_thread is not None and not server_thread.is_alive()
        self.engine_request_method_unchanged = Engine.request is self.request_method
        self.worker_closure = {image: not Path(f"/proc/{worker['pid']}").exists()
                               for image, worker in self.workers.items()}
        self.assertTrue(all(self.worker_closure.values()))
        self.assertTrue(self.http_server_thread_closed)
        self.assertTrue(self.engine_request_method_unchanged)

    def finish(self):
        try:
            self.save_final_state()
        finally:
            self.close_handset()

    def boot_with_modem_alerts(self):
        handset = self.handset
        if self.boots:
            state = handset.state()
            self.assertEqual(next(cpu for cpu in state["processors"] if cpu["image"] == "bc5")["power_state"], 8)
            self.assertFalse(state["ui_initialized"])
            self.snapshot("completed-shutdown-before-original-warm-startup", state)
        handset.control("initialize_ui")
        handset.control("pause")
        alerts = {STARTUP_SIM_ERROR: "absent-sim", FIRMWARE_IDENTITY_WARNING: "firmware-identity"}
        required = {"absent-sim"}
        if self.model == "9575":
            alerts.update({IERCC_NOT_CONFIGURED: "iercc-not-configured", IERCC_DISABLED: "iercc-disabled",
                           SOS_MESSAGE_RECIPIENT_WARNING: "sos-message-recipient"})
            required = {"iercc-not-configured", "iercc-disabled", "sos-message-recipient"}
        seen = set()
        for elapsed in range(0, 200000001, 1000000):
            state = handset.assert_healthy(require_lcd=False)
            body = handset.screen_hash(state=state)
            if body in alerts:
                label = alerts[body]
                self.assertNotIn(label, seen, "Original startup repeated an alert")
                seen.add(label)
                self.snapshot("startup-" + label, state)
                handset.press("soft_right", hold_steps=500000, settle_steps=500000)
            elif required <= seen and handset.screen_hash(113, 128, state) == HOME_CAPTIONS:
                self.assertEqual({cpu["image"] for cpu in state["processors"]}, {"bc5", "avr", "trx"})
                self.assertTrue(state["processor_link"]["connected"])
                self.assertEqual(state["keys"], [])
                self.assertEqual({image: engine._process.pid for image, engine in handset.session.engines.items()},
                                 {image: worker["pid"] for image, worker in self.workers.items()})
                self.boots += 1
                self.snapshot(f"original-boot-{self.boots}-home", state)
                return
            else:
                handset.step(1000000)
        self.snapshot("unknown-startup-screen")
        self.fail("Original modem startup did not reach Home after recognized alerts")
