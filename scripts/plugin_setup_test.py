"""Regression checks for portable setup without touching user configuration."""

import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plugin_setup", PROJECT / "plugin/scripts/setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="codeclarity setup ")
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / "selectors with spaces"
        self.result = {"python": str(Path(self.temporary.name) / "venv" / "python"),
                       "repoRoot": str(Path(self.temporary.name) / "repo"),
                       "complexipy": "8.3.0", "pythonVersion": [3, 13, 2]}

    def invoke(self, *args, error=None):
        output = io.StringIO()
        with patch.object(setup, "validate", side_effect=error, return_value=dict(self.result)), \
                patch("sys.stdout", output):
            code = setup.main(["--config-dir", str(self.config), "--python", sys.executable,
                               "--repo-root", str(PROJECT), "--json", *args])
        return code, json.loads(output.getvalue())

    def test_check_creates_nothing(self):
        code, result = self.invoke("--check")
        self.assertEqual(code, 0)
        self.assertEqual(result["mode"], "check")
        self.assertFalse(self.config.exists())

    def test_write_utf8_without_bom_and_idempotent(self):
        self.assertEqual(self.invoke()[0], 0)
        python = self.config / "python-path.txt"
        repo = self.config / "repo-root.txt"
        self.assertEqual(python.read_bytes(), (self.result["python"] + "\n").encode("utf-8"))
        before = (python.stat().st_mtime_ns, repo.stat().st_mtime_ns)
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(before, (python.stat().st_mtime_ns, repo.stat().st_mtime_ns))

    def test_failed_validation_preserves_existing_selectors(self):
        self.invoke()
        before = {p.name: p.read_bytes() for p in self.config.iterdir()}
        code, result = self.invoke(error=setup.SetupError("bad dependency"))
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.config.iterdir()})

    def test_missing_configuration_fails_without_creating_directory(self):
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(setup.main(["--check", "--json", "--config-dir", str(self.config)]), 1)
        self.assertFalse(self.config.exists())

    def test_path_cannot_inject_another_selector_line(self):
        for value in ["", "relative", str(PROJECT) + "\nnext", str(PROJECT) + "\rnext", str(PROJECT) + "\0"]:
            with self.assertRaises(setup.SetupError):
                setup.selector_path(value, "test")

    def test_venv_executable_symlink_is_not_resolved(self):
        selected = Path(self.temporary.name) / "venv" / "bin" / "python"
        with patch.object(Path, "resolve", side_effect=AssertionError("must preserve venv path")):
            self.assertEqual(setup.selector_path(selected, "Python"), selected)

    def test_missing_or_old_jdk_rejected(self):
        with patch.object(setup.shutil, "which", return_value=None):
            with self.assertRaises(setup.SetupError):
                setup.java_version("java")
        with patch.object(setup.shutil, "which", return_value="java"), \
                patch.object(setup, "run", return_value='openjdk version "17.0.1"'):
            with self.assertRaises(setup.SetupError):
                setup.java_version("java")

    def test_wrong_complexipy_rejected(self):
        with patch.object(setup, "run", return_value=json.dumps({"version": [3, 13, 2], "complexipy": "9.0.0"})):
            with self.assertRaisesRegex(setup.SetupError, "complexipy==8.3.0"):
                setup.validate(sys.executable, PROJECT)

    def test_other_configuration_is_preserved(self):
        self.config.mkdir()
        extra = self.config / "jdtls-home.txt"
        extra.write_text("external JDT location", encoding="utf-8")
        self.invoke()
        self.assertEqual(extra.read_text(encoding="utf-8"), "external JDT location")


if __name__ == "__main__":
    unittest.main()
