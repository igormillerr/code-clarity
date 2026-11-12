"""Release-container regression checks; synthetic JAR, no Codex/model execution."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import package_plugin as package


def fixture(root):
    files = {name: b"fixture\n" for name in package.REQUIRED}
    files["plugin.json"] = package.json_bytes({
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "codeclarity", "version": package.VERSION})
    files["mcp.json"] = package.json_bytes({
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"codeclarity": {"type": "stdio", "command": "java", "cwd": "${PLUGIN_ROOT}",
            "args": ["${PLUGIN_ROOT}/scripts/LaunchMcp.java", "${PLUGIN_ROOT}/server/codeclarity-mcp.jar"]}}})
    files["requirements-python.txt"] = b"# Runtime dependency\ncomplexipy==8.3.0\n"
    for name in files:
        if name.endswith(".schema.json"):
            files[name] = b"{}\n"
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as zipped:
        for name in sorted(package.JAR_REQUIRED):
            if name == package.JAR_DESCRIPTOR:
                data = b"artifactId=codeclarity-mcp\nversion=0.1.7\n"
            elif name == "META-INF/MANIFEST.MF":
                data = b"Manifest-Version: 1.0\nMain-Class: dev.codeclarity.Main\n"
            elif name.startswith("contracts/"):
                data = files[name]
            else:
                data = b"synthetic container fixture; not an executable runtime"
            zipped.writestr(name, data)
    files["server/codeclarity-mcp.jar"] = jar.getvalue()
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return files


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codeclarity package tests ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plugin = self.root / "relocated plugin with spaces"
        self.files = fixture(self.plugin)

    def test_relocated_release_has_full_inventory_and_matching_checksums(self):
        result = package.build_release(self.plugin, self.root / "release with spaces")
        archive = Path(result["archive"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["serverVersion"], "0.1.7")
        self.assertEqual(result["archiveSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(archive.with_name(archive.name + ".sha256").read_text(),
                         result["archiveSha256"] + "  " + archive.name + "\n")
        with zipfile.ZipFile(archive) as zipped:
            prefix = package.PACKAGE_NAME + "/"
            metadata = json.loads(zipped.read(prefix + "release.json"))
            self.assertEqual(metadata["jarSha256"], result["jarSha256"])
            marketplace = json.loads(zipped.read(prefix + ".agents/plugins/marketplace.json"))
            self.assertEqual(marketplace["plugins"][0]["source"]["path"], "./plugin")
            self.assertEqual(zipped.read(prefix + "INSTALL.md"), self.files["INSTALL.md"])
            self.assertNotIn(str(self.root).encode(), zipped.read(prefix + "release.json"))
            for skill in package.SKILLS:
                self.assertIn(prefix + "plugin/skills/" + skill + "/SKILL.md", zipped.namelist())
        self.assertEqual(package.verify_archive(archive)["archiveSha256"], result["archiveSha256"])

    def test_output_is_deterministic_and_ignores_generated_python_cache(self):
        first = package.build_release(self.plugin, self.root / "first")
        cache = self.plugin / "scripts/__pycache__/setup.cpython-313.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"machine-specific generated cache")
        second = package.build_release(self.plugin, self.root / "second")
        self.assertEqual(first["archiveSha256"], second["archiveSha256"])

    def test_missing_dependency_manifest_is_rejected(self):
        self.files.pop("requirements-python.txt")
        with self.assertRaisesRegex(ValueError, "Missing required plugin files"):
            package.validate_files(self.files)

    def test_wrong_pinned_runtime_dependency_is_rejected(self):
        self.files["requirements-python.txt"] = b"complexipy>=8\n"
        with self.assertRaisesRegex(ValueError, "complexipy==8.3.0"):
            package.validate_files(self.files)

    def test_stale_plugin_version_is_rejected(self):
        manifest = json.loads(self.files["plugin.json"])
        manifest["version"] = "0.3.2"
        self.files["plugin.json"] = package.json_bytes(manifest)
        with self.assertRaisesRegex(ValueError, "Plugin version must be 0.4.0"):
            package.validate_files(self.files)

    def test_machine_specific_mcp_path_is_rejected(self):
        mcp = json.loads(self.files["mcp.json"])
        mcp["mcpServers"]["codeclarity"]["args"][0] = "C:/Users/someone/LaunchMcp.java"
        self.files["mcp.json"] = package.json_bytes(mcp)
        with self.assertRaisesRegex(ValueError, "MCP arguments must resolve"):
            package.validate_files(self.files)

    def test_missing_or_escaping_skill_link_is_rejected(self):
        for target, error in (("missing.md", "Broken bundled Markdown link"),
                              ("../../../outside.md", "Markdown link escapes plugin")):
            with self.subTest(target=target):
                self.files["README.md"] = ("[link](" + target + ")").encode()
                with self.assertRaisesRegex(ValueError, error):
                    package.validate_files(self.files)

    def test_jar_contract_must_equal_external_schema(self):
        self.files["contracts/review.schema.json"] = b'{"title":"changed after packaging"}\n'
        with self.assertRaisesRegex(ValueError, "JAR schema differs"):
            package.validate_files(self.files)

    def test_modified_archive_payload_is_rejected(self):
        result = package.build_release(self.plugin, self.root / "output")
        archive = Path(result["archive"])
        with zipfile.ZipFile(archive) as zipped:
            entries = {name: zipped.read(name) for name in zipped.namelist()}
        entries[package.PACKAGE_NAME + "/plugin/README.md"] = b"changed after release\n"
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, data in entries.items():
                zipped.writestr(name, data)
        with self.assertRaisesRegex(ValueError, "Release checksum mismatch"):
            package.verify_archive(archive)

    def test_archive_path_traversal_is_rejected(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(package.PACKAGE_NAME + "/../outside.txt", "outside")
        with self.assertRaisesRegex(ValueError, "safe"):
            package.verify_archive(archive)

    def test_symlink_is_not_packaged(self):
        target = self.plugin / "scripts/linked.txt"
        try:
            target.symlink_to(self.root / "outside.txt")
        except OSError as error:
            self.skipTest("Symlink creation unavailable on this host: " + str(error))
        with self.assertRaisesRegex(ValueError, "not distributable"):
            package.collect_plugin(self.plugin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
