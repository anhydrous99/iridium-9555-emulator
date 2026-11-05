"""Firmware-free checks that the factory suite cannot give false assurance."""

from contextlib import redirect_stderr
from copy import deepcopy
from hashlib import sha256
import io
import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, mock_open, patch

from factory_handset import (
    FACTORY_HASHES, FIRMWARE_ENV, ROOT, FactoryHandset, factory_firmware, require_factory_host,
)
from iridium.firmware import parse_firmware
from iridium.profiles import PROFILES


class FactoryFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def images(self, model):
        directory = self.directory / model
        directory.mkdir(exist_ok=True)
        hashes = {}
        for image, filename in (("bc5", "bc5_main.bin"), ("avr", "avr.bin"), ("trx", "trx_seg1_0x10000.bin")):
            data = bytes(PROFILES[model].image_sizes[image])
            (directory / filename).write_bytes(data)
            hashes[image] = sha256(data).hexdigest()
        return directory, hashes

    def test_factory_host_rejects_unsupported_system_before_starting_workers(self):
        for platform in ("darwin", "win32"):
            with self.subTest(platform=platform), patch("factory_handset.sys.platform", platform), \
                    patch("factory_handset.Session") as session:
                with self.assertRaisesRegex(ValueError, "require Linux.*readable /proc"):
                    FactoryHandset(self, "9555", self.directory)
                session.assert_not_called()

    def test_factory_host_rejects_missing_or_unreadable_procfs(self):
        for error in (FileNotFoundError("no procfs"), PermissionError("unreadable procfs")):
            with self.subTest(error=type(error).__name__), patch("factory_handset.sys.platform", "linux"), \
                    patch("factory_handset.Path.open", side_effect=error):
                with self.assertRaisesRegex(ValueError, "require Linux.*readable /proc"):
                    require_factory_host()

    def test_factory_host_accepts_readable_linux_procfs(self):
        opened = mock_open(read_data=b"x")
        with patch("factory_handset.sys.platform", "linux"), patch("factory_handset.Path.open", opened):
            require_factory_host()
        opened.assert_called_once_with("rb")
        opened().read.assert_called_once_with(1)

    def test_procfs_contracts_reject_unsupported_host_before_loading_or_starting_workers(self):
        cases = (
            ("storage", "SharedSIMStorageChecks", "run_storage_card", {"sms_available": True}),
            ("phonebook", "SharedSIMPhonebookChecks", "run_adn_card", {"populated": True}),
            ("phonebook_write", "SharedSIMPhonebookWriteChecks", "run_phonebook", {"reject_edit": False}),
            ("sms_write", "SharedSIMSMSWriteChecks", "run_sms_store", {"memory_failure": False}),
            ("service_center", "SharedSIMServiceCenterChecks", "run_service_center", {"memory_failure": False}),
        )
        for name, checks, method, arguments in cases:
            module = importlib.import_module(f"test_factory_sim_{name}_contract")
            fixture = getattr(module, checks)()
            with self.subTest(contract=name), patch("factory_handset.sys.platform", "darwin"), \
                    patch.object(module, "factory_firmware") as firmware, \
                    patch.object(module, "Engine") as engine:
                with self.assertRaisesRegex(ValueError, "require Linux.*readable /proc"):
                    getattr(fixture, method)(**arguments)
                firmware.assert_not_called()
                engine.assert_not_called()

    def test_factory_gate_rejects_modified_bytes_even_with_valid_model_and_size(self):
        for model in PROFILES:
            directory, hashes = self.images(model)
            # Approve a synthetic baseline; no proprietary image is needed to test identity checks.
            with self.subTest(model=model), patch.dict(FACTORY_HASHES, {model: hashes}):
                self.assertEqual([image.image for image in factory_firmware(model, directory)], ["bc5", "avr"])
                for image, filename in (("bc5", "bc5_main.bin"), ("avr", "avr.bin")):
                    with self.subTest(image=image):
                        path = directory / filename
                        original = path.read_bytes()
                        changed = b"\x04" + original[1:]
                        self.assertEqual(parse_firmware(changed, filename, model=model).image, image)
                        path.write_bytes(changed)
                        try:
                            with self.assertRaisesRegex(ValueError, f"{model} {image} is not the pinned factory image"):
                                factory_firmware(model, directory)
                        finally:
                            path.write_bytes(original)

    def test_factory_gate_rejects_other_handset_and_missing_avr(self):
        for model in PROFILES:
            directory, _ = self.images(model)
            other = "9575" if model == "9555" else "9555"
            with self.subTest(model=model, failure="wrong handset"):
                with self.assertRaises(ValueError):
                    factory_firmware(other, directory)
            (directory / "avr.bin").unlink()
            with self.subTest(model=model, failure="missing AVR"):
                with self.assertRaises(FileNotFoundError):
                    factory_firmware(model, directory)

    def test_modem_journeys_require_the_original_telephony_payload(self):
        for model in PROFILES:
            directory, hashes = self.images(model)
            with self.subTest(model=model), patch.dict(FACTORY_HASHES, {model: hashes}):
                self.assertEqual([image.image for image in factory_firmware(model, directory, modem=True)],
                                 ["bc5", "avr", "trx"])
                path = directory / "trx_seg1_0x10000.bin"
                original = path.read_bytes()
                path.write_bytes(b"\x04" + original[1:])
                with self.assertRaisesRegex(ValueError, f"{model} trx is not the pinned factory image"):
                    factory_firmware(model, directory, modem=True)
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    factory_firmware(model, directory, modem=True)

    def run_cli(self, **firmware_environment):
        environment = dict(os.environ)
        for variable in FIRMWARE_ENV.values():
            environment.pop(variable, None)
        environment["IRIDIUM_E2E_ARTIFACTS"] = str(self.directory / "artifacts")
        environment.update(firmware_environment)
        return subprocess.run([sys.executable, str(ROOT / "test-factory")], cwd=self.directory,
                              env=environment, capture_output=True, text=True, timeout=10)

    def test_runner_requires_both_handsets_before_building(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("IRIDIUM_TEST_FIRMWARE", result.stderr)
        result = self.run_cli(IRIDIUM_TEST_FIRMWARE=str(self.directory / "absent-9555"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("IRIDIUM_TEST_9575_FIRMWARE", result.stderr)

    def test_runner_reports_nonexistent_firmware_directory(self):
        missing = self.directory / "absent-9555"
        result = self.run_cli(IRIDIUM_TEST_FIRMWARE=str(missing),
                              IRIDIUM_TEST_9575_FIRMWARE=str(self.directory / "absent-9575"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Factory E2E preflight failed", result.stderr)
        self.assertIn(str(missing), result.stderr)

    def test_failed_preflight_or_build_cannot_leave_a_stale_passing_report(self):
        artifact_directory = self.directory / "artifacts"
        artifact_directory.mkdir()
        report = artifact_directory / "report.json"
        report.write_text('{"passed":true}')
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertFalse(report.exists())

        directories, approved_hashes = {}, {}
        for model, variable in FIRMWARE_ENV.items():
            directories[variable], approved_hashes[model] = self.images(model)
        directories = {variable: str(path) for variable, path in directories.items()}
        directories["IRIDIUM_E2E_ARTIFACTS"] = str(artifact_directory)
        with patch.object(sys, "path", sys.path.copy()):
            main = runpy.run_path(str(ROOT / "test-factory"))["main"]
        report.write_text('{"passed":true}')
        with patch.dict(os.environ, directories), patch.dict(FACTORY_HASHES, approved_hashes), \
                patch.dict(main.__globals__, {"require_factory_host": lambda: None}), \
                patch("subprocess.run", side_effect=OSError("build unavailable")), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(main(), 2)
        self.assertFalse(report.exists())

    def test_runner_refuses_empty_skipped_or_expected_failure_suite(self):
        directories, approved_hashes = {}, {}
        for model, variable in FIRMWARE_ENV.items():
            directories[variable], approved_hashes[model] = self.images(model)
        directories = {variable: str(path) for variable, path in directories.items()}
        directories["IRIDIUM_E2E_ARTIFACTS"] = str(self.directory / "artifacts")
        with patch.object(sys, "path", sys.path.copy()):
            main = runpy.run_path(str(ROOT / "test-factory"))["main"]

        def skip():
            raise unittest.SkipTest("missing firmware must not look like success")

        class KnownFailure(unittest.TestCase):
            @unittest.expectedFailure
            def test_feature(self):
                self.fail("known feature failure must not look like success")

        class UnexpectedSuccess(unittest.TestCase):
            @unittest.expectedFailure
            def test_feature(self):
                pass

        cases = ((unittest.TestSuite(), 0, 0, 0, 0),
                 (unittest.TestSuite([unittest.FunctionTestCase(skip)]), 1, 1, 0, 0),
                 (unittest.TestSuite([KnownFailure("test_feature")]), 1, 0, 1, 0),
                 (unittest.TestSuite([UnexpectedSuccess("test_feature")]), 1, 0, 0, 1))
        for suite, tests, skips, expected_failures, unexpected_successes in cases:
            with self.subTest(tests=tests, skips=skips, expected_failures=expected_failures), \
                    patch.dict(os.environ, directories), patch.dict(FACTORY_HASHES, approved_hashes), \
                    patch.dict(main.__globals__, {"require_factory_host": lambda: None}), \
                    patch("subprocess.run") as build, \
                    patch.object(unittest.defaultTestLoader, "discover", return_value=suite), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(main(), 1)
                build.assert_called_once()
                report = json.loads((Path(directories["IRIDIUM_E2E_ARTIFACTS"]) / "report.json").read_text())
                self.assertFalse(report["passed"])
                self.assertEqual(report["tests_run"], tests)
                self.assertEqual(len(report["skipped"]), skips)
                self.assertEqual(len(report["expected_failures"]), expected_failures)
                self.assertEqual(len(report["unexpected_successes"]), unexpected_successes)

    def test_runner_records_successful_test_ids_and_fixture_identities(self):
        directories, approved_hashes = {}, {}
        for model, variable in FIRMWARE_ENV.items():
            directories[variable], approved_hashes[model] = self.images(model)
        directories = {variable: str(path) for variable, path in directories.items()}
        directories["IRIDIUM_E2E_ARTIFACTS"] = str(self.directory / "artifacts")
        with patch.object(sys, "path", sys.path.copy()):
            main = runpy.run_path(str(ROOT / "test-factory"))["main"]
        success = unittest.FunctionTestCase(lambda: None)
        with patch.dict(os.environ, directories), patch.dict(FACTORY_HASHES, approved_hashes), \
                patch.dict(main.__globals__, {"require_factory_host": lambda: None}), \
                patch("subprocess.run"), \
                patch.object(unittest.defaultTestLoader, "discover", return_value=unittest.TestSuite([success])), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(main(), 0)
        report = json.loads((Path(directories["IRIDIUM_E2E_ARTIFACTS"]) / "report.json").read_text())
        self.assertTrue(report["passed"])
        self.assertEqual(report["tests_run"], 1)
        self.assertEqual(report["passed_tests"], [success.id()])
        self.assertGreaterEqual(report["duration_seconds"], 0)
        self.assertTrue(report["started_at"].endswith("+00:00"))
        for model, firmware in report["firmware"].items():
            self.assertEqual({image["image"]: image["payload_sha256"] for image in firmware},
                             approved_hashes[model])

    def test_runner_host_failure_invalidates_report_before_build_or_discovery(self):
        directory = self.directory / "artifacts"
        directory.mkdir()
        report = directory / "report.json"
        report.write_text('{"passed":true}')
        environment = {variable: "declared-factory-input" for variable in FIRMWARE_ENV.values()}
        environment["IRIDIUM_E2E_ARTIFACTS"] = str(directory)
        with patch.object(sys, "path", sys.path.copy()):
            main = runpy.run_path(str(ROOT / "test-factory"))["main"]
        fixture = Mock()
        fixture.describe.return_value = {}
        host = Mock(side_effect=ValueError("Factory-firmware tests require Linux with mounted, readable /proc"))
        stderr = io.StringIO()
        with patch.dict(os.environ, environment), \
                patch.dict(main.__globals__, {"factory_firmware": lambda *a, **k: [fixture],
                                              "require_factory_host": host}), \
                patch("subprocess.run") as build, \
                patch.object(unittest.defaultTestLoader, "discover") as discovery, \
                redirect_stderr(stderr):
            self.assertEqual(main(), 2)
        self.assertIn("require Linux", stderr.getvalue())
        host.assert_called_once()
        build.assert_not_called()
        discovery.assert_not_called()
        self.assertFalse(report.exists())


class FactoryKeyContactTests(unittest.TestCase):
    def handset(self):
        handset = Mock()
        handset.test = self
        handset.key.return_value = {"delivered": True}
        handset.step.return_value = {"phase": "stepped"}
        handset.state.return_value = {"phase": "released"}
        return handset

    def test_key_contacts_preserve_edge_held_and_zero_release_budgets(self):
        cases = (
            ({}, [("key", "1", True), ("key", "1", False), ("step", 2000000)]),
            ({"hold_steps": 500000, "settle_steps": 1500000},
             [("key", "1", True), ("step", 500000), ("key", "1", False), ("step", 1500000)]),
            ({"hold_steps": 250000, "settle_steps": 0},
             [("key", "1", True), ("step", 250000), ("key", "1", False), ("state",)]),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                handset = self.handset()
                FactoryHandset.press(handset, "1", **arguments)
                actual = [(call[0], *call[1]) for call in handset.mock_calls]
                self.assertEqual(actual, expected)

    def test_failed_hold_releases_contact_without_running_release_budget(self):
        handset = self.handset()
        handset.step.side_effect = RuntimeError("original processor halted")
        with self.assertRaisesRegex(RuntimeError, "processor halted"):
            FactoryHandset.press(handset, "2", hold_steps=500000, settle_steps=1500000)
        self.assertEqual(handset.key.call_args_list,
                         [call("2", True), call("2", False)])
        handset.step.assert_called_once_with(500000)

    def test_unconsumed_press_still_releases_client_ownership(self):
        handset = self.handset()
        handset.key.return_value = {"delivered": False}
        with self.assertRaisesRegex(AssertionError, "press was not delivered"):
            FactoryHandset.press(handset, "3", hold_steps=500000)
        self.assertEqual(handset.key.call_count, 2)
        self.assertEqual(handset.key.call_args, call("3", False))
        handset.step.assert_not_called()

    def test_rejected_release_fails_instead_of_running_more_instructions(self):
        handset = self.handset()
        handset.key.side_effect = [{"delivered": True}, {"delivered": False}]
        with self.assertRaisesRegex(AssertionError, "release was not delivered"):
            FactoryHandset.press(handset, "4")
        handset.step.assert_not_called()

    def test_invalid_key_budgets_fail_before_changing_contacts(self):
        for arguments in ({"hold_steps": -1}, {"settle_steps": 10000001},
                          {"hold_steps": True}, {"settle_steps": 0.5}):
            with self.subTest(arguments=arguments):
                handset = self.handset()
                with self.assertRaisesRegex(ValueError, "Key budgets"):
                    FactoryHandset.press(handset, "5", **arguments)
                handset.key.assert_not_called()


class FactorySIMEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def fixtures(self):
        from sim_language_card import StorageSIM
        from sim_message_card import MessageSIM
        from sim_service_center_card import ServiceCenterSIM
        from test_factory_messages_local_e2e import MessagesLocalChecks
        from test_factory_messages_inbox_e2e import MessagesInboxChecks
        from test_factory_messages_service_center_e2e import MessagesServiceCenterChecks
        return ((MessagesLocalChecks, StorageSIM), (MessagesInboxChecks, MessageSIM),
                (MessagesServiceCenterChecks, ServiceCenterSIM))

    def fixture(self, checks, card_type):
        from factory_sim_peer import FactorySIMPeer
        from iridium.engine import Engine
        fixture = unittest.TestCase()
        fixture.card = card_type()
        fixture.initial_records = deepcopy(fixture.card.records)
        fixture.initial_contents = dict(fixture.card.contents)
        fixture.handset = Mock()
        fixture.handset.state.return_value = {"images": []}
        path = self.directory / checks.__name__
        fixture.handset.save_artifacts.return_value = path
        fixture.peer = Mock(spec=FactorySIMPeer)
        fixture.peer.card = fixture.card
        fixture.peer.controls = []
        fixture.peer.wire = [{"tx": [0xA0, 0xDC, 1, 4, 32]}]
        fixture.peer.workers = {}
        fixture.peer.errors = []
        fixture.peer.request_method = Engine.request
        fixture.peer.thread = Mock()
        fixture.peer.thread.is_alive.return_value = False
        fixture.peer.evidence.side_effect = lambda: FactorySIMPeer.evidence(fixture.peer)
        return fixture, Path(str(path) + ".peer.json")

    def test_failed_card_validation_preserves_peer_evidence_and_closes_handset(self):
        for checks, card_type in self.fixtures():
            faults = ("write",) if checks.__name__ == "MessagesLocalChecks" else ("write", "contents")
            for fault in faults:
                with self.subTest(fixture=checks.__name__, fault=fault):
                    fixture, sidecar = self.fixture(checks, card_type)
                    sidecar.unlink(missing_ok=True)
                    if fault == "write":
                        fixture.card.events.append({"kind": "header", "selected": 0x6F3A,
                                                    "bytes": [0xA0, 0xDC, 1, 4, 32]})
                    else:
                        fixture.card.contents[0x6F05] = b"\x05\x04"
                    with self.assertRaises(AssertionError):
                        checks.finish(fixture)
                    self.assertEqual(json.loads(sidecar.read_text()), fixture.peer_evidence)
                    fixture.peer.close.assert_called_once_with()
                    fixture.handset.close.assert_called_once_with()

    def test_failed_peer_evidence_write_still_closes_handset(self):
        for checks, card_type in self.fixtures():
            with self.subTest(fixture=checks.__name__):
                fixture, _ = self.fixture(checks, card_type)
                with patch.object(Path, "write_text", side_effect=OSError("disk full")), \
                        self.assertRaisesRegex(OSError, "disk full"):
                    checks.finish(fixture)
                fixture.peer.close.assert_called_once_with()
                fixture.handset.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
