import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configuration import (
    ORDINARY_UNIT_TEST_RUN,
    load_local_environment,
    running_unittest_command,
)


class ConfigurationTests(unittest.TestCase):
    def test_ordinary_unit_test_process_does_not_auto_load_project_env(self):
        self.assertTrue(ORDINARY_UNIT_TEST_RUN)

    def test_local_file_is_loaded_without_overriding_os_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "AGRIBOT_TEST_LOCAL=local\nAGRIBOT_TEST_PRIORITY=file\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"AGRIBOT_TEST_PRIORITY": "operating-system"},
                clear=False,
            ):
                os.environ.pop("AGRIBOT_TEST_LOCAL", None)
                self.assertTrue(load_local_environment(env_file))
                self.assertEqual(os.getenv("AGRIBOT_TEST_LOCAL"), "local")
                self.assertEqual(
                    os.getenv("AGRIBOT_TEST_PRIORITY"), "operating-system"
                )
                os.environ.pop("AGRIBOT_TEST_LOCAL", None)

    def test_missing_local_file_is_a_safe_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.env"
            self.assertFalse(load_local_environment(missing))

    def run_isolated_configuration(self, updates=None, removals=()):
        environment = os.environ.copy()
        for name in removals:
            environment.pop(name, None)
        environment.update(updates or {})
        code = (
            "import configuration; "
            "from services.abena_tts_service import AbenaTTSService; "
            "print(configuration.ORDINARY_UNIT_TEST_RUN); "
            "print(configuration.LOCAL_ENV_LOADED); "
            "print(AbenaTTSService().availability()['enabled'])"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parent,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip().splitlines()

    def test_imported_unittest_does_not_make_normal_startup_a_test(self):
        environment = os.environ.copy()
        environment.pop("AGRIBOT_TEST_MODE", None)
        environment.pop("RUN_LIVE_ABENA_TTS", None)
        environment.pop("RUN_GEMINI_LIVE_TESTS", None)
        environment["ABENA_TTS_ENABLED"] = "true"
        code = (
            "import unittest, configuration; "
            "from services.abena_tts_service import AbenaTTSService; "
            "print(configuration.ORDINARY_UNIT_TEST_RUN); "
            "print(configuration.LOCAL_ENV_LOADED); "
            "print(AbenaTTSService().availability()['enabled'])"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parent,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        output = result.stdout.strip().splitlines()
        self.assertEqual(output[0], "False")
        self.assertEqual(output[2], "True")

    def test_explicit_test_mode_blocks_local_env_loading(self):
        output = self.run_isolated_configuration(
            {"AGRIBOT_TEST_MODE": "1"},
            removals=(
                "ABENA_TTS_ENABLED",
                "RUN_LIVE_ABENA_TTS",
                "RUN_GEMINI_LIVE_TESTS",
            ),
        )
        self.assertEqual(output, ["True", "False", "False"])

    def test_abena_live_opt_in_overrides_explicit_test_mode(self):
        output = self.run_isolated_configuration(
            {
                "AGRIBOT_TEST_MODE": "1",
                "RUN_LIVE_ABENA_TTS": "1",
                "ABENA_TTS_ENABLED": "true",
            },
            removals=("RUN_GEMINI_LIVE_TESTS",),
        )
        self.assertEqual(output[0], "False")
        self.assertEqual(output[2], "True")

    def test_gemini_live_opt_in_still_overrides_explicit_test_mode(self):
        output = self.run_isolated_configuration(
            {
                "AGRIBOT_TEST_MODE": "1",
                "RUN_GEMINI_LIVE_TESTS": "true",
                "ABENA_TTS_ENABLED": "true",
            },
            removals=("RUN_LIVE_ABENA_TTS",),
        )
        self.assertEqual(output[0], "False")
        self.assertEqual(output[2], "True")

    def test_unittest_detection_uses_command_path_not_loaded_modules(self):
        self.assertTrue(running_unittest_command(["C:/Python/Lib/unittest/__main__.py"]))
        self.assertFalse(running_unittest_command(["app.py"]))


if __name__ == "__main__":
    unittest.main()
