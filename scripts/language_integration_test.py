"""Check both language adapters, six Java metric deltas and partial results through one MCP server."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from smoke_test import git
from python_smoke_test import connect, close


JAVA_METRICS = {"cyclomatic_complexity", "cognitive_complexity", "function_sloc",
                "max_nesting_depth", "parameter_count", "return_count"}


def metric(report, entity, metric_id):
    return next(m for file in report["files"] for m in file["metrics"]
                if m["entity"] == entity and m["metric"] == metric_id)


def check(client):
    snapshots = {}
    reports = {}
    for language, path in (("java", "Sample.java"), ("python", "sample.py")):
        changes = client.tool(f"list_{language}_changes", {"baseRef": "main", "headRef": "HEAD"})
        assert {f["newPath"] for f in changes["files"]} == {path, f"broken.{language if language == 'java' else 'py'}"}, changes
        snapshots[language] = {key: changes[key] for key in ("baseSha", "headSha")}
        reports[language] = client.tool(f"analyze_{language}_changes", {**snapshots[language], "paths": [path]})
        assert reports[language]["status"] == "ok", reports[language]
        partial = client.tool(f"analyze_{language}_changes", snapshots[language])
        assert partial["status"] == "partial" and partial["warnings"], partial
        assert next(f for f in partial["files"] if f["newPath"] == path)["metrics"], partial
    assert snapshots["java"] == snapshots["python"], snapshots

    changes = client.tool("get_changes", {"baseRef": "main", "headRef": "HEAD"})
    assert changes["status"] == "ok" and not changes["warnings"], changes
    assert {key: changes[key] for key in ("baseSha", "headSha")} == snapshots["java"], changes
    assert {f["newPath"] for f in changes["files"]} == {"Sample.java", "sample.py", "broken.java", "broken.py"}, changes
    mixed = client.tool("analyze_changes", {**snapshots["java"], "paths": ["Sample.java", "sample.py"]})
    assert mixed["status"] == "ok" and not mixed["warnings"], mixed
    assert {f["language"] for f in mixed["files"]} == {"java", "python"}, mixed
    file_keys = {"oldPath", "newPath", "language", "changedMethods", "findings", "metrics"}
    metric_keys = {"entity", "metric", "status", "before", "after", "delta"}
    for file in mixed["files"]:
        assert set(file) == file_keys, file
        assert file == reports[file["language"]]["files"][0], "Generic and legacy tools must share the same result format"
        assert all(set(m) == metric_keys for m in file["metrics"]), file
    partial = client.tool("analyze_changes", snapshots["java"])
    assert partial["status"] == "partial" and len(partial["files"]) == 4, partial
    for path in ("broken.java", "broken.py"):
        assert any(path in warning for warning in partial["warnings"]), partial
    for file in mixed["files"]:
        assert next(f for f in partial["files"] if f["newPath"] == file["newPath"]) == file, partial
    assert client.tool("analyze_changes", {**snapshots["java"], "paths": ["Sample.java", "sample.py"]}) == mixed

    java = reports["java"]
    assert not java["files"][0]["findings"], "Numeric measurements must exist below diagnostic thresholds"
    assert set(m["metric"] for m in java["files"][0]["metrics"]) == JAVA_METRICS, java
    expected = {"cyclomatic_complexity": (1, 2), "cognitive_complexity": (0, 1),
                "function_sloc": (3, 6), "max_nesting_depth": (0, 1),
                "parameter_count": (1, 1), "return_count": (1, 2)}
    for metric_id, (before, after) in expected.items():
        comparison = metric(java, "Sample#compute(int)", metric_id)
        assert comparison["status"] == "COMPARED", comparison
        assert comparison["before"]["value"] == before and comparison["after"]["value"] == after, comparison
        assert comparison["delta"] == after - before, comparison
        definition = comparison["before"]["definition"]
        assert definition == comparison["after"]["definition"] and definition["language"] == "java", comparison
        assert definition["analyzer"].startswith("pmd/" if "complexity" in metric_id else "javaparser/"), definition
        assert definition["algorithm"], definition

    reverse = client.tool("analyze_java_changes", {"baseSha": snapshots["java"]["headSha"],
                                                  "headSha": snapshots["java"]["baseSha"],
                                                  "paths": ["Sample.java"]})
    assert reverse["status"] == "ok", reverse
    for metric_id, (before, after) in expected.items():
        comparison = metric(reverse, "Sample#compute(int)", metric_id)
        assert comparison["before"]["value"] == after and comparison["after"]["value"] == before, comparison
        assert comparison["delta"] == before - after, comparison

    for metric_id in JAVA_METRICS:
        constructor = metric(java, "Sample#Sample(int)", metric_id)
        assert constructor["status"] == "COMPARED" and constructor["delta"] is not None, constructor
        for entity, absent_side in (("Sample#removed()", "after"), ("Sample#added()", "before")):
            comparison = metric(java, entity, metric_id)
            assert comparison[absent_side]["status"] == "ENTITY_ABSENT" and comparison["delta"] is None, comparison

    for metric_id in ("cyclomatic_complexity", "cognitive_complexity", "max_nesting_depth", "return_count"):
        comparison = metric(java, "Sample#bodyless(String)", metric_id)
        assert comparison["before"]["status"] == "UNSUPPORTED", comparison
        assert comparison["after"]["status"] == "AVAILABLE" and comparison["delta"] is None, comparison
    for metric_id in ("function_sloc", "parameter_count"):
        assert metric(java, "Sample#bodyless(String)", metric_id)["status"] == "COMPARED"

    python = reports["python"]
    comparison = metric(python, "compute(value)", "cyclomatic_complexity")
    assert comparison["before"]["value"] == 1 and comparison["after"]["value"] == 2 and comparison["delta"] == 1, comparison
    unsupported = metric(python, "compute(value)", "cognitive_complexity")
    assert unsupported["status"] == "UNAVAILABLE" and unsupported["delta"] is None, unsupported
    assert unsupported["after"]["status"] == "UNSUPPORTED", unsupported

    sha = snapshots["java"]["headSha"]
    assert client.tool("inspect_java_method", {"commitSha": sha, "path": "Sample.java", "line": 6})["signature"] == "Sample#compute(int)"
    assert client.tool("inspect_python_function", {"commitSha": sha, "path": "sample.py", "line": 2})["signature"] == "compute(value)"
    for path, line, tool in (("Sample.java", 6, "inspect_java_method"), ("sample.py", 2, "inspect_python_function")):
        arguments = {"commitSha": sha, "path": path, "line": line}
        assert client.tool("inspect_symbol_ast", arguments) == client.tool(tool, arguments)
        context = client.tool("get_symbol_context", arguments)
        legacy = client.tool(tool, arguments)
        assert context["commitSha"] == sha and context["path"] == path and context["status"] == "ok", context
        assert context["language"] == ("java" if path.endswith(".java") else "python"), context
        assert {key: context[key] for key in legacy} == legacy and not context["warnings"], context
        assert context["lines"]["startLine"] <= line <= context["lines"]["endLine"], context
        assert len(context["source"].splitlines()) == context["lines"]["endLine"] - context["lines"]["startLine"] + 1, context
    client.tool("inspect_symbol_ast", {"commitSha": sha, "path": "ignored.txt", "line": 1}, error=True)
    client.tool("analyze_changes", {**snapshots["java"], "paths": ["ignored.txt"]}, error=True)
    client.tool("analyze_java_changes", {**snapshots["java"], "paths": ["sample.py"]}, error=True)
    client.tool("analyze_python_changes", {**snapshots["python"], "paths": ["Sample.java"]}, error=True)
    return mixed


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-languages-") as folder:
        root = Path(folder)
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "Language integration test")
        git(root, "config", "user.email", "languages@example.test")
        (root / "Sample.java").write_text(
            "abstract class Sample {\n"
            "    Sample(int x) {}\n"
            "    int compute(int value) {\n        return value;\n    }\n"
            "    abstract int bodyless(String value);\n"
            "    int removed() { return 0; }\n}\n", encoding="utf-8")
        (root / "sample.py").write_text("def compute(value):\n    return value\n", encoding="utf-8")
        (root / "ignored.txt").write_text("before\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        git(root, "switch", "-c", "feature")
        (root / "Sample.java").write_text(
            "abstract class Sample {\n"
            "    Sample(int x) { if (x < 0) return; }\n"
            "    int compute(int value) {\n        if (value > 0) {\n            return value;\n        }\n"
            "        return 0;\n    }\n"
            "    int bodyless(String value) { return value.length(); }\n"
            "    void added() {}\n}\n", encoding="utf-8")
        (root / "sample.py").write_text("def compute(value):\n    if value:\n        return value\n    return 0\n", encoding="utf-8")
        (root / "broken.java").write_text("class Broken { void f( }", encoding="utf-8")
        (root / "broken.py").write_text("def broken(:", encoding="utf-8")
        (root / "ignored.txt").write_text("after\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "head")
        # Both adapters must read the committed snapshot, not these working tree files.
        (root / "Sample.java").write_text("broken working tree", encoding="utf-8")
        (root / "sample.py").write_text("broken working tree", encoding="utf-8")
        process, client = connect(jar, root)
        try:
            mixed = check(client)
        finally:
            close(process)
        process, client = connect(jar, root, missing=True)
        try:
            shas = {key: mixed[key] for key in ("baseSha", "headSha")}
            partial = client.tool("analyze_changes", {**shas, "paths": ["Sample.java", "sample.py"]})
            assert partial["status"] == "partial" and len(partial["files"]) == 2, partial
            assert any("CODECLARITY_PYTHON" in warning for warning in partial["warnings"]), partial
            assert next(f for f in partial["files"] if f["language"] == "java") == next(
                f for f in mixed["files"] if f["language"] == "java"), partial
        finally:
            close(process)
    print("Passed: mixed Java/Python snapshots, six Java before/after/deltas, constructors, bodyless/added/removed "
          "methods, below-threshold values, version definitions, automatic routing, identical result format, "
          "unified analysis/inspection, retained healthy files and missing-Python isolation.")


if __name__ == "__main__":
    main()
