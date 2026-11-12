"""Validate and package the relocatable CodeClarity 0.4.0 desktop/CLI plugin.

Uses only Python's standard library. This does not install a plugin, change Codex
configuration, download dependencies, or claim an OS/model end-to-end result.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from urllib.parse import unquote, urlsplit
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
VERSION = "0.4.0"
SERVER_VERSION = "0.1.7"
PACKAGE_NAME = "codeclarity-" + VERSION
SKILLS = ("readability-review", "independent-review", "metrics-correlation", "rule-discovery")
SCHEMAS = ("review", "review-history", "history-update", "history", "rule-candidate")
REQUIRED = {
    "plugin.json", "mcp.json", "README.md", "INSTALL.md", "requirements-python.txt",
    "scripts/LaunchMcp.java", "scripts/setup.py", "scripts/review_artifacts.py",
    "skills/readability-review/scripts/review_ids.py", "server/codeclarity-mcp.jar",
    "contracts/mcp-compatibility.md",
    *("skills/" + skill + "/SKILL.md" for skill in SKILLS),
    *("contracts/" + schema + ".schema.json" for schema in SCHEMAS),
}
ALLOWED_TOP_LEVEL = {"plugin.json", "mcp.json", "README.md", "INSTALL.md", "requirements-python.txt",
                     "skills", "contracts", "scripts", "server", "assets", ".codex-plugin", ".mcp.json"}
EXCLUDED_DIRS = {"__pycache__", ".git", ".venv", ".codeclarity", "node_modules"}
JAR_DESCRIPTOR = "META-INF/maven/dev.codeclarity/codeclarity-mcp/pom.properties"
JAR_REQUIRED = {"META-INF/MANIFEST.MF", "dev/codeclarity/Main.class", "python_analyzer.py", JAR_DESCRIPTOR,
                *("contracts/" + schema + ".schema.json" for schema in SCHEMAS if schema != "history")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(data, label):
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid JSON in " + label + ": " + str(error)) from error


def validate_files(files):
    """Validate a plugin payload represented as relative POSIX paths and bytes."""
    require(REQUIRED <= files.keys(), "Missing required plugin files: " + ", ".join(sorted(REQUIRED - files.keys())))
    for name in files:
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts and "\\" not in name,
                "Unsafe plugin member: " + name)
        require(path.parts[0] in ALLOWED_TOP_LEVEL, "Unexpected plugin entry: " + name)
    manifest = read_json(files["plugin.json"], "plugin.json")
    require(manifest.get("name") == "codeclarity", "Plugin name must be codeclarity")
    require(manifest.get("version") == VERSION, "Plugin version must be " + VERSION)
    require(manifest.get("$schema") == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "Portable Agent Plugins manifest schema is required")
    mcp = read_json(files["mcp.json"], "mcp.json")
    require(mcp.get("$schema") == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
            "Portable MCP schema is required")
    servers = mcp.get("mcpServers", {})
    require(set(servers) == {"codeclarity"}, "Expected exactly the bundled codeclarity MCP server")
    server = servers["codeclarity"]
    require(server.get("type") == "stdio" and server.get("command") == "java", "Expected Java stdio launcher")
    require(server.get("cwd") == "${PLUGIN_ROOT}", "MCP cwd must be ${PLUGIN_ROOT}")
    require(server.get("args") == ["${PLUGIN_ROOT}/scripts/LaunchMcp.java",
                                   "${PLUGIN_ROOT}/server/codeclarity-mcp.jar"],
            "MCP arguments must resolve bundled launcher and JAR through ${PLUGIN_ROOT}")
    requirements = [line.strip() for line in files["requirements-python.txt"].decode("utf-8-sig").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    require(requirements == ["complexipy==8.3.0"], "Bundle the exact complexipy==8.3.0 requirement")
    for name, data in files.items():
        if name.endswith(".json"):
            read_json(data, name)
        if name.endswith(".md"):
            text = data.decode("utf-8-sig")
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = target.strip().split(' "', 1)[0].strip("<>")
                url = urlsplit(target)
                if url.scheme or target.startswith("#"):
                    continue
                relative = unquote(url.path)
                if not relative:
                    continue
                require(not relative.startswith(("/", "\\")), "Absolute Markdown link in " + name)
                parts = list(PurePosixPath(name).parent.parts)
                for part in PurePosixPath(relative).parts:
                    if part == "..":
                        require(parts, "Markdown link escapes plugin: " + name + " -> " + target)
                        parts.pop()
                    elif part != ".":
                        parts.append(part)
                resolved = "/".join(parts)
                require(resolved in files or any(p.startswith(resolved.rstrip("/") + "/") for p in files),
                        "Broken bundled Markdown link: " + name + " -> " + target)
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(files["server/codeclarity-mcp.jar"])) as jar:
            require(jar.testzip() is None, "Corrupted bundled MCP JAR")
            require(JAR_REQUIRED <= set(jar.namelist()), "MCP JAR lacks runtime classes/resources/contracts")
            props = jar.read(JAR_DESCRIPTOR).decode("utf-8")
            values = dict(line.split("=", 1) for line in props.splitlines() if "=" in line and not line.startswith("#"))
            require(values.get("version") == SERVER_VERSION, "Bundled server version must be " + SERVER_VERSION)
            require(values.get("artifactId") == "codeclarity-mcp", "Wrong bundled Maven artifact")
            require("Main-Class: dev.codeclarity.Main" in jar.read("META-INF/MANIFEST.MF").decode("utf-8"),
                    "MCP JAR has no expected executable Main-Class")
            for schema in SCHEMAS:
                if schema != "history":
                    require(jar.read("contracts/" + schema + ".schema.json") == files["contracts/" + schema + ".schema.json"],
                            "Bundled JAR schema differs from plugin contract: " + schema)
    except zipfile.BadZipFile as error:
        raise ValueError("Bundled MCP JAR is not a valid ZIP/JAR") from error
    return {"pluginVersion": VERSION, "serverVersion": SERVER_VERSION, "pluginFiles": len(files),
            "jarSha256": sha256(files["server/codeclarity-mcp.jar"])}


def collect_plugin(root):
    root = Path(root)
    def is_link(path):
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0)
                                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    require(root.is_dir() and not is_link(root), "Plugin root must be a real directory")
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        for name in dirs + sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root)
            if path.suffix in {".pyc", ".pyo"}:
                continue
            require(not is_link(path), "Links/reparse points are not distributable: " + relative.as_posix())
            if path.is_file():
                files[relative.as_posix()] = path.read_bytes()
    return files


def marketplace_bytes():
    return json_bytes({"name": "codeclarity-local", "interface": {"displayName": "CodeClarity Local"},
                       "plugins": [{"name": "codeclarity", "source": {"source": "local", "path": "./plugin"},
                                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                                    "category": "Productivity"}]})


def make_payload(files):
    details = validate_files(files)
    payload = {"plugin/" + name: data for name, data in files.items()}
    payload[".agents/plugins/marketplace.json"] = marketplace_bytes()
    payload["INSTALL.md"] = files["INSTALL.md"]
    payload["README.md"] = ("# CodeClarity " + VERSION + "\n\n"
        "Portable local plugin for Codex desktop and CLI with local Java/Python execution.\n\n"
        "Start with [installation instructions](INSTALL.md). The complete plugin is in `plugin/`; "
        "`.agents/plugins/marketplace.json` registers this extracted directory as a marketplace.\n\n"
        "Requires a plugin-capable local Codex client, JDK 21+, Git, Python 3.10+ and "
        "`complexipy==8.3.0`. It does not bundle a Codex account, Java or Python installation.\n\n"
        "`SHA256SUMS` covers the payload and `release.json`. Archive integrity and package structure "
        "do not establish an end-to-end result on every operating system.\n").encode("utf-8")
    metadata = {"schemaVersion": 1, "name": "codeclarity", "version": VERSION, "serverVersion": SERVER_VERSION,
                "distribution": "local-codex-desktop-cli", "marketplace": "codeclarity-local",
                "requirements": {"java": ">=21", "python": ">=3.10", "git": True, "complexipy": "8.3.0",
                                 "codex": "local client supporting plugin marketplaces and stdio MCP"},
                "jarSha256": details["jarSha256"],
                "inventory": [{"path": name, "bytes": len(data), "sha256": sha256(data)}
                              for name, data in sorted(payload.items())]}
    payload["release.json"] = json_bytes(metadata)
    payload["SHA256SUMS"] = "".join(sha256(data) + "  " + name + "\n" for name, data in sorted(payload.items())).encode("utf-8")
    return payload, details


def verify_archive(archive):
    with zipfile.ZipFile(archive) as zipped:
        require(zipped.testzip() is None, "Archive CRC failure")
        names = zipped.namelist()
        require(len(names) == len(set(names)), "Duplicate archive entries")
        prefix = PACKAGE_NAME + "/"
        require(all(name.startswith(prefix) and ".." not in PurePosixPath(name).parts and "\\" not in name
                    and not name[len(prefix):].startswith("/") and ":" not in name
                    for name in names), "Archive must contain one safe " + PACKAGE_NAME + "/ root")
        require(all(not info.is_dir() and (info.external_attr >> 16) & 0o170000 in {0, stat.S_IFREG}
                    for info in zipped.infolist()), "Archive entries must be regular files")
        payload = {name[len(prefix):]: zipped.read(name) for name in names}
    root_files = {"SHA256SUMS", "release.json", "INSTALL.md", "README.md", ".agents/plugins/marketplace.json"}
    require(all(name in root_files or name.startswith("plugin/") for name in payload), "Unexpected archive root payload")
    require({"SHA256SUMS", "release.json", "INSTALL.md", "README.md", ".agents/plugins/marketplace.json"} <= payload.keys(),
            "Release metadata or installation instructions missing")
    checked = {}
    for line in payload["SHA256SUMS"].decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None and name not in checked, "Invalid checksum record")
        checked[name] = digest
    require(set(checked) == set(payload) - {"SHA256SUMS"}, "Checksum file does not cover the exact release payload")
    for name, digest in checked.items():
        require(sha256(payload[name]) == digest, "Release checksum mismatch: " + name)
    plugin = {name[len("plugin/"):]: data for name, data in payload.items() if name.startswith("plugin/")}
    details = validate_files(plugin)
    require(payload[".agents/plugins/marketplace.json"] == marketplace_bytes(), "Marketplace has non-portable source")
    require(payload["INSTALL.md"] == plugin["INSTALL.md"], "Root instructions differ from bundled instructions")
    metadata = read_json(payload["release.json"], "release.json")
    require(metadata.get("version") == VERSION and metadata.get("serverVersion") == SERVER_VERSION,
            "Release version metadata mismatch")
    require(metadata.get("jarSha256") == details["jarSha256"], "Release JAR digest mismatch")
    inventory = metadata.get("inventory", [])
    expected = [{"path": name, "bytes": len(data), "sha256": sha256(data)} for name, data in sorted(payload.items())
                if name not in {"SHA256SUMS", "release.json"}]
    require(inventory == expected, "Release inventory differs from archive payload")
    return dict(details, archiveFiles=len(payload), archiveSha256=sha256(Path(archive).read_bytes()))


def build_release(plugin_root, output_dir):
    payload, _ = make_payload(collect_plugin(plugin_root))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (PACKAGE_NAME + ".zip")
    temporary = archive.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(PACKAGE_NAME + "/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                zipped.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        details = verify_archive(temporary)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    (output / (archive.name + ".sha256")).write_text(details["archiveSha256"] + "  " + archive.name + "\n", encoding="utf-8")
    return dict(details, archive=str(archive.resolve()), status="PASS")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, default=PROJECT / "plugin")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "dist")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="Validate the plugin folder without writing a release")
    mode.add_argument("--verify-archive", type=Path, help="Verify structure, inventory and checksums of an existing ZIP")
    args = parser.parse_args(argv)
    try:
        if args.verify_archive:
            details = dict(verify_archive(args.verify_archive), status="PASS")
        elif args.validate_only:
            details = dict(validate_files(collect_plugin(args.plugin_root)), status="PASS")
        else:
            details = build_release(args.plugin_root, args.output_dir)
        print(json.dumps(details, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print("CodeClarity package: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
