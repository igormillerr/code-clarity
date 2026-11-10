"""Exercise Python support through the executable MCP JAR."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from smoke_test import Client, git


def function(name, decisions):
    return f"def {name}(value):\n" + "    if value: send(value)\n" * decisions + "    return value\n\n"


def check(client, root):
    changes = client.tool("list_python_changes", {"baseRef": "main", "headRef": "HEAD"})
    files = {f.get("newPath") or f["oldPath"]: f for f in changes["files"]}
    assert set(files) == {"example.py", "invalid.py", "renamed.py"}, files
    assert files["renamed.py"]["oldPath"] == "rename.py", files
    java = client.tool("list_java_changes", {"baseRef": "main", "headRef": "HEAD"})
    assert len(java["files"]) == 1 and java["files"][0]["newPath"] == "Example.java", java
    shas = {key: changes[key] for key in ("baseSha", "headSha")}
    report = client.tool("analyze_python_changes", {**shas, "paths": ["example.py"]})
    assert report["status"] == "ok", report
    findings = {f["method"]: f for f in report["files"][0]["findings"]}
    expected = {"introduced(value)": "INTRODUCED", "existing(value)": "EXISTING",
                "changed(value)": "CHANGED", "resolved(value)": "RESOLVED"}
    assert {key: value["status"] for key, value in findings.items()} == expected, findings
    assert "10" in findings["introduced(value)"]["after"]["message"], findings
    partial = client.tool("analyze_python_changes", shas)
    assert partial["status"] == "partial" and any("invalid.py" in w for w in partial["warnings"]), partial
    context = client.tool("inspect_python_function", {"commitSha": changes["headSha"],
                                                      "path": "example.py", "line": 2})
    assert context["signature"] == "introduced(value)", context
    assert context["calls"][0]["enclosingIfs"][0]["condition"] == "value", context
    client.tool("inspect_python_function", {"commitSha": changes["headSha"], "path": "../example.py", "line": 2}, error=True)
    client.tool("inspect_python_function", {"commitSha": changes["headSha"], "path": "Example.java", "line": 1}, error=True)
    client.tool("inspect_python_function", {"commitSha": changes["headSha"], "path": "invalid.py", "line": 1}, error=True)
    return shas


def connect(jar, root, missing=False):
    env = dict(os.environ, CODECLARITY_PYTHON="codeclarity-missing-python" if missing else sys.executable)
    process = subprocess.Popen(["java", "-jar", str(jar), "--repo-root", str(root)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    client = Client(process)
    client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "python-test", "version": "1"}})
    client.send("notifications/initialized", notification=True)
    return process, client


def close(process):
    process.stdin.close()
    try:
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-python-") as folder:
        root = Path(folder)
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "Python test")
        git(root, "config", "user.email", "python@example.test")
        (root / "example.py").write_text("".join(function(n, c) for n, c in
            [("introduced", 1), ("existing", 9), ("changed", 9), ("resolved", 9)]), encoding="utf-8")
        (root / "rename.py").write_text("def renamed():\n    pass\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        git(root, "switch", "-c", "feature")
        (root / "example.py").write_text("".join(function(n, c) for n, c in
            [("introduced", 9), ("existing", 9), ("changed", 10), ("resolved", 1)]).replace(
                "def existing(value):", "def existing(value): # touched"), encoding="utf-8")
        (root / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
        (root / "Example.java").write_text("class Example {}\n", encoding="utf-8")
        git(root, "mv", "rename.py", "renamed.py")
        git(root, "add", ".")
        git(root, "commit", "-m", "head")
        (root / "example.py").write_text("invalid working tree ignored", encoding="utf-8")
        process, client = connect(jar, root)
        try:
            shas = check(client, root)
        finally:
            close(process)
        process, client = connect(jar, root, missing=True)
        try:
            report = client.tool("analyze_python_changes", {**shas, "paths": ["example.py"]})
            assert report["status"] == "partial" and any("CODECLARITY_PYTHON" in w for w in report["warnings"]), report
            assert client.tool("analyze_java_changes", shas)["status"] == "ok"
        finally:
            close(process)
    print("Passed: Python MCP tools, language isolation, four diagnostic statuses, rename, syntax errors, "
          "inspection, committed source and missing interpreter handling.")


if __name__ == "__main__":
    main()
