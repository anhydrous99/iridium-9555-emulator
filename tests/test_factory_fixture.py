"""Firmware-free checks that the factory suite cannot give false assurance."""

from contextlib import redirect_stderr
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from factory_handset import FACTORY_HASHES, FIRMWARE_ENV, ROOT, factory_firmware
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


if __name__ == "__main__":
    unittest.main()
