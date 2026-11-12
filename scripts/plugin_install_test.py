"""Install the release in an empty Codex profile and exercise the cached MCP package.

No login, model call or user Codex configuration is used. Test files are retained
in a new system temporary directory for diagnostics. Requires the real Codex CLI.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from package_plugin import collect_plugin, verify_archive
from smoke_test import Client, git

PROJECT = Path(__file__).resolve().parents[1]
METRICS = {"cyclomatic_complexity", "cognitive_complexity", "function_sloc",
           "max_nesting_depth", "parameter_count", "return_count"}


def run(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}: {result.stdout}\n{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=PROJECT / "dist/codeclarity-0.4.0.zip")
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--output", type=Path, default=PROJECT / ".codeclarity/plugin-install-check.json")
    args = parser.parse_args()
    if not args.codex:
        parser.error("Codex CLI is not on PATH")
    details = verify_archive(args.archive)
    temporary = Path(tempfile.mkdtemp(prefix="codeclarity portable install "))
    codex_home = temporary / "clean codex profile"
    codex_home.mkdir()
    extracted = temporary / "relocated package with spaces"
    with zipfile.ZipFile(args.archive) as zipped:
        zipped.extractall(extracted)
    market = extracted / "codeclarity-0.4.0"
    env = dict(os.environ, CODEX_HOME=str(codex_home), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    codex_version = run([args.codex, "--version"], temporary, env).strip()
    added = json.loads(run([args.codex, "plugin", "marketplace", "add", str(market), "--json"], temporary, env))
    installed = json.loads(run([args.codex, "plugin", "add", "codeclarity@codeclarity-local", "--json"], temporary, env))
    listed = json.loads(run([args.codex, "plugin", "list", "--marketplace", "codeclarity-local", "--json"], temporary, env))
    entry = next(p for p in listed["installed"] if p["pluginId"] == "codeclarity@codeclarity-local")
    assert entry["version"] == "0.4.0" and entry["enabled"], entry
    manifests = list((codex_home / "plugins/cache/codeclarity-local/codeclarity").glob("*/plugin.json"))
    cached = next(p.parent for p in manifests if json.loads(p.read_text(encoding="utf-8"))["version"] == "0.4.0")
    expected, actual = collect_plugin(market / "plugin"), collect_plugin(cached)
    assert expected == actual, "Installed cache differs from the extracted package"

    repo = temporary / "mixed git project"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Portable install test")
    git(repo, "config", "user.email", "portable@example.test")
    (repo / "Example.java").write_text("class Example {\n int adjust(int value) {\n  return value;\n }\n}\n", encoding="utf-8")
    (repo / "example.py").write_text("def adjust(value):\n    return value\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "switch", "-c", "feature")
    (repo / "Example.java").write_text("class Example {\n int adjust(int value) {\n  if (value < 0) return -value;\n  return value;\n }\n}\n", encoding="utf-8")
    (repo / "example.py").write_text("def adjust(value):\n    if value < 0:\n        return -value\n    return value\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    java_home = temporary / "isolated java user home"
    setup = json.loads(run([sys.executable, str(cached / "scripts/setup.py"), "--python", sys.executable,
                            "--repo-root", str(repo), "--config-dir", str(java_home / ".codeclarity"), "--json"], temporary, env))
    assert setup["status"] == "PASS", setup
    config = json.loads((cached / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["codeclarity"]
    expand = lambda value: value.replace("${PLUGIN_ROOT}", str(cached))
    command = [config["command"], "-Duser.home=" + str(java_home), *map(expand, config["args"])]
    # Exercise selectors rather than inheriting an interpreter from the test process.
    mcp_env = dict(env)
    mcp_env.pop("CODECLARITY_PYTHON", None)
    stderr = temporary / "mcp.stderr.log"
    with stderr.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(command, cwd=expand(config["cwd"]), env=mcp_env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                   text=True, encoding="utf-8")
        try:
            client = Client(process)
            hello = client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                "clientInfo": {"name": "portable-install-check", "version": "1"}})
            assert hello["serverInfo"]["version"] == "0.1.7", hello
            client.send("notifications/initialized", notification=True)
            tools = client.send("tools/list")["tools"]
            assert len(tools) == 15, tools
            changes = client.tool("get_changes", {"baseRef": "main", "headRef": "HEAD"})
            assert len(changes["files"]) == 2, changes
            shas = {key: changes[key] for key in ("baseSha", "headSha")}
            analysis = client.tool("analyze_changes", shas)
            assert analysis["status"] == "ok" and len(analysis["files"]) == 2, analysis
            for file in analysis["files"]:
                assert {metric["metric"] for metric in file["metrics"]} == METRICS, file
                assert all(metric["before"]["value"] is not None and metric["after"]["value"] is not None
                           for metric in file["metrics"]), file
                context = client.tool("get_symbol_context", {"commitSha": changes["headSha"],
                                                             "path": file["newPath"], "line": 2})
                assert context["source"] and context["status"] == "ok", context
            history = client.tool("get_review_history", {})
            assert history["statistics"]["reviewCount"] == 0, history
            process.stdin.close()
            assert process.wait(timeout=15) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    receipt = dict(details, status="PASS", executionLevel="CLEAN_CODEX_CLI_INSTALL_AND_CACHED_PACKAGE_STDIO",
                   codexVersion=codex_version, pluginVersion=entry["version"], enabled=entry["enabled"],
                   cachedFilesIdentical=True, selectorConfiguration="PASS", toolsDiscovered=len(tools),
                   languages=sorted({file["language"] for file in analysis["files"]}),
                   metricComparisons=sum(len(file["metrics"]) for file in analysis["files"]),
                   sourceContext="PASS", historyRead="PASS", pathsWithSpaces=True,
                   installedCacheJarSha256=hashlib.sha256((cached / "server/codeclarity-mcp.jar").read_bytes()).hexdigest(),
                   modelInvocation=False, testDirectory=str(temporary),
                   limitations=["Executed on Windows only; Linux/macOS instructions were syntax-checked.",
                                "Runs cached manifest command after installation; not a model-driven Codex turn."])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
