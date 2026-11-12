"""Minimal real-STDIO check of the three universal MCP API operations."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from smoke_test import Client, git

JAVA_PATH = "src/Example file.java"
PYTHON_PATH = "scripts/example.py"


def fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "MCP API smoke test")
    git(root, "config", "user.email", "mcp@example.test")
    (root / "src").mkdir()
    (root / "scripts").mkdir()
    (root / JAVA_PATH).write_text("class Example {\n    int adjust(int value) {\n        return value;\n    }\n}\n")
    (root / PYTHON_PATH).write_text("def adjust(value):\n    return value\n")
    (root / "many.py").write_text("def many():\n" + "    send()\n" * 101)
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    git(root, "switch", "-c", "feature")
    (root / JAVA_PATH).write_text("class Example {\n    int adjust(int value) {\n        if (value < 0) return Math.abs(value);\n        return value;\n    }\n}\n")
    (root / PYTHON_PATH).write_text("def adjust(value):\n    if value < 0: return abs(value)\n    return value\n")
    (root / "broken.py").write_text("def broken(:\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "head")


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-mcp-api-") as directory:
        root = Path(directory)
        fixture(root)
        # The context must come from the commit, even with invalid worktree contents.
        (root / JAVA_PATH).write_text("dirty worktree")
        process = subprocess.Popen(["java", "-jar", str(jar), "--repo-root", str(root)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                   env=dict(os.environ, CODECLARITY_PYTHON=sys.executable))
        try:
            client = Client(process)
            hello = client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                               "clientInfo": {"name": "unified-api-smoke", "version": "1"}})
            assert hello["serverInfo"]["name"] == "codeclarity" and "tools" in hello["capabilities"], hello
            client.send("notifications/initialized", notification=True)
            tools = {t["name"]: t for t in client.send("tools/list")["tools"]}
            assert {"get_changes", "analyze_changes", "get_symbol_context", "inspect_symbol_ast"} <= tools.keys(), tools
            assert set(tools["get_symbol_context"]["inputSchema"]["required"]) == {"commitSha", "path", "line"}
            assert all(tools[name]["annotations"]["readOnlyHint"] for name in ("get_changes", "analyze_changes", "get_symbol_context"))

            def call(name, arguments):
                result = client.send("tools/call", {"name": name, "arguments": arguments})
                assert not result.get("isError"), result
                data = result["structuredContent"]
                assert json.loads(next(c["text"] for c in result["content"] if c["type"] == "text")) == data, result
                return data

            changes = call("get_changes", {"baseRef": "main", "headRef": "HEAD"})
            assert changes["status"] == "ok" and not changes["warnings"], changes
            assert {f["newPath"] for f in changes["files"]} == {JAVA_PATH, PYTHON_PATH, "broken.py"}, changes
            assert all(f["headLines"] for f in changes["files"]), changes
            shas = {key: changes[key] for key in ("baseSha", "headSha")}
            report = call("analyze_changes", shas)
            assert report["status"] == "partial" and any("broken.py" in w for w in report["warnings"]), report
            assert len(report["files"]) == 3, report
            for path, language, line in ((JAVA_PATH, "java", 3), (PYTHON_PATH, "python", 2)):
                file = next(f for f in report["files"] if f["newPath"] == path)
                assert file["language"] == language and file["changedMethods"] and file["metrics"], file
                cyclo = next(m for m in file["metrics"] if m["metric"] == "cyclomatic_complexity")
                assert cyclo["before"]["value"] == 1 and cyclo["after"]["value"] == 2 and cyclo["delta"] == 1, cyclo
                args = {"commitSha": shas["headSha"], "path": path, "line": line}
                context = call("get_symbol_context", args)
                assert context["commitSha"] == shas["headSha"] and context["path"] == path and context["language"] == language, context
                assert context["status"] == "ok" and not context["warnings"] and not context["truncated"], context
                assert context["lines"]["startLine"] <= line <= context["lines"]["endLine"], context
                committed = subprocess.run(["git", "-C", str(root), "show", shas["headSha"] + ":" + path],
                                           capture_output=True, text=True, check=True).stdout.splitlines()
                expected = "\n".join(committed[context["lines"]["startLine"] - 1:context["lines"]["endLine"]])
                assert context["source"] == expected and context["calls"][0]["enclosingIfs"], context
                legacy = call("inspect_symbol_ast", args)
                assert {key: context[key] for key in legacy} == legacy, context
                client.tool("get_symbol_context", {**args, "line": 0}, error=True)
                client.tool("get_symbol_context", {**args, "path": "../" + path}, error=True)
                client.tool("get_symbol_context", {**args, "unexpected": True}, error=True)
            limited = call("get_symbol_context", {"commitSha": shas["headSha"], "path": "many.py", "line": 2})
            assert limited["status"] == "partial" and limited["truncated"] and limited["warnings"], limited
            assert len(limited["calls"]) == 100 and len(limited["source"].splitlines()) == 102, limited
            client.tool("get_symbol_context", {"commitSha": "invalid", "path": PYTHON_PATH, "line": 1}, error=True)
            assert call("get_changes", {"baseRef": "HEAD", "headRef": "HEAD"})["files"] == []
            process.stdin.close()
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    print("Passed: STDIO initialize/discovery, three universal tools, mixed metrics, exact paths/lines/source, "
          "partial warnings, context truncation, compatibility and tool argument errors.")


if __name__ == "__main__":
    main()
