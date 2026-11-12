"""Exercise Python support through the executable MCP JAR."""

import os
import importlib.metadata
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
    assert set(files) == {"example.py", "invalid.py", "broken_existing.py", "renamed.py"}, files
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
    metrics = {(m["entity"], m["metric"]): m for m in report["files"][0]["metrics"]}
    for entity, before, after in [("introduced", 2, 10), ("existing", 10, 10), ("changed", 10, 11), ("resolved", 10, 2),
                                  ("below", 2, 3)]:
        value = metrics[(entity + "(value)", "cyclomatic_complexity")]
        assert value["status"] == "COMPARED" and value["before"]["value"] == before and value["after"]["value"] == after, value
        assert value["delta"] == after - before, value
        cognitive = metrics[(entity + "(value)", "cognitive_complexity")]
        assert cognitive["status"] == "COMPARED", cognitive
        assert cognitive["before"]["value"] == before - 1 and cognitive["after"]["value"] == after - 1, cognitive
        assert cognitive["delta"] == after - before, cognitive
        assert cognitive["after"]["definition"]["analyzer"] == "complexipy/8.3.0", cognitive
        sloc = metrics[(entity + "(value)", "function_sloc")]
        assert sloc["status"] == "COMPARED" and sloc["before"]["value"] == before + 1, sloc
        assert sloc["after"]["value"] == after + 1 and sloc["delta"] == after - before, sloc
    for metric_id, before, after, algorithm in [
            ("function_sloc", 2, 5, "codeclarity/python-physical-sloc/v1"),
            ("max_nesting_depth", 0, 2, "codeclarity/python-nesting/v1"),
            ("parameter_count", 2, 2, "codeclarity/python-parameters/include-receiver/v1"),
            ("return_count", 0, 2, "codeclarity/python-explicit-returns/v1")]:
        value = metrics[("structure(value, *, flag)", metric_id)]
        assert value["status"] == "COMPARED" and value["before"]["value"] == before, value
        assert value["after"]["value"] == after and value["delta"] == after - before, value
        assert value["after"]["definition"]["algorithm"] == algorithm, value
    # Parameter changes still change the matching key until the planned Core matching stage.
    old_parameters = metrics[("parameters(value)", "parameter_count")]
    new_parameters = metrics[("parameters(value, extra)", "parameter_count")]
    assert old_parameters["before"]["value"] == 1 and old_parameters["after"]["status"] == "ENTITY_ABSENT", old_parameters
    assert new_parameters["before"]["status"] == "ENTITY_ABSENT" and new_parameters["after"]["value"] == 2, new_parameters
    assert old_parameters.get("delta") is None and new_parameters.get("delta") is None
    cognitive = metrics[("structure(value, *, flag)", "cognitive_complexity")]
    assert cognitive["before"]["value"] == 0 and cognitive["after"]["value"] == 3 and cognitive["delta"] == 3, cognitive
    partial = client.tool("analyze_python_changes", shas)
    assert partial["status"] == "partial" and any("invalid.py" in w for w in partial["warnings"]), partial
    added_file = next(file for file in partial["files"] if file["newPath"] == "invalid.py")
    assert not added_file["metrics"], added_file
    broken = next(file for file in partial["files"] if file["newPath"] == "broken_existing.py")
    assert len(broken["metrics"]) == 6, broken
    for metric in broken["metrics"]:
        assert metric["after"]["status"] == "ERROR" and metric.get("delta") is None, metric
        assert metric["before"]["status"] == "AVAILABLE", metric
    context = client.tool("inspect_python_function", {"commitSha": changes["headSha"],
                                                      "path": "example.py", "line": 2})
    assert context["signature"] == "introduced(value)", context
    assert context["calls"][0]["enclosingIfs"][0]["condition"] == "value", context
    client.tool("inspect_python_function", {"commitSha": changes["headSha"], "path": "../example.py", "line": 2}, error=True)
    client.tool("inspect_python_function", {"commitSha": changes["headSha"], "path": "Example.java", "line": 1}, error=True)
    client.tool("inspect_python_function", {"commitSha": changes["headSha"], "path": "invalid.py", "line": 1}, error=True)
    return shas


def connect(jar, root, missing=False, interpreter=None):
    env = dict(os.environ, CODECLARITY_PYTHON="codeclarity-missing-python" if missing else str(interpreter or sys.executable))
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
    try:
        version = importlib.metadata.version("complexipy")
    except importlib.metadata.PackageNotFoundError:
        raise SystemExit("Install requirements-python.txt into this interpreter before running the Python MCP smoke test.")
    assert version == "8.3.0", version
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-python-") as folder:
        root = Path(folder)
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "Python test")
        git(root, "config", "user.email", "python@example.test")
        (root / "example.py").write_text("".join(function(n, c) for n, c in
            [("introduced", 1), ("existing", 9), ("changed", 9), ("resolved", 9), ("below", 1)])
            + "async def structure(value, *, flag=False):\n    pass\n\n"
            + "def parameters(value):\n    return value\n", encoding="utf-8")
        (root / "rename.py").write_text("def renamed():\n    pass\n", encoding="utf-8")
        (root / "broken_existing.py").write_text("def damaged(value):\n    return value\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        git(root, "switch", "-c", "feature")
        (root / "example.py").write_text("".join(function(n, c) for n, c in
            [("introduced", 9), ("existing", 9), ("changed", 10), ("resolved", 1), ("below", 2)]).replace(
                "def existing(value):", "def existing(value): # touched")
            + "async def structure(value, *, flag=False):\n    if flag:\n        if value:\n            return value\n    return None\n\n"
            + "def parameters(value, extra=None):\n    return value\n", encoding="utf-8")
        (root / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
        (root / "broken_existing.py").write_text("def damaged(:\n", encoding="utf-8")
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
        without_cognitive = root / ".without-cognitive"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(without_cognitive)], check=True)
        clean_python = without_cognitive / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        process, client = connect(jar, root, interpreter=clean_python)
        try:
            report = client.tool("analyze_python_changes", {**shas, "paths": ["example.py"]})
            assert report["status"] == "partial" and any("complexipy" in w for w in report["warnings"]), report
            values = report["files"][0]["metrics"]
            assert values, report
            for value in values:
                if value["metric"] == "cognitive_complexity":
                    assert value["status"] == "UNAVAILABLE" and value.get("delta") is None, value
                    assert "ERROR" in (value["before"]["status"], value["after"]["status"]), value
                else:
                    assert all(value[side]["status"] in ("AVAILABLE", "ENTITY_ABSENT") for side in ("before", "after")), value
                    if all(value[side]["status"] == "AVAILABLE" for side in ("before", "after")):
                        assert value["status"] == "COMPARED", value
            # A failed metric does not make the independent CC diagnostics unverified.
            assert {f["status"] for f in report["files"][0]["findings"]} == {"INTRODUCED", "EXISTING", "CHANGED", "RESOLVED"}
            context = client.tool("inspect_python_function", {"commitSha": shas["headSha"], "path": "example.py", "line": 2})
            assert context["signature"] == "introduced(value)", context
            assert client.tool("analyze_java_changes", shas)["status"] == "ok"
        finally:
            close(process)
        process, client = connect(jar, root, missing=True)
        try:
            report = client.tool("analyze_python_changes", {**shas, "paths": ["example.py"]})
            assert report["status"] == "partial" and any("CODECLARITY_PYTHON" in w for w in report["warnings"]), report
            assert all(value["after"]["status"] == "ERROR" and value.get("delta") is None
                       for value in report["files"][0]["metrics"])
            assert client.tool("analyze_java_changes", shas)["status"] == "ok"
        finally:
            close(process)
    print("Passed: Python MCP tools, language isolation, four diagnostic statuses, rename, syntax errors, "
          "all six metrics and deltas, inspection, committed source, missing dependency and interpreter handling.")


if __name__ == "__main__":
    main()
