"""Verify Python cross-version identity through Git and the public MCP API."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from python_smoke_test import connect, close
from smoke_test import git


def module(extra=False):
    parameter = ", extra=None" if extra else ""
    complex_body = "    if value: send(value)\n" * 9 + "    return value\n"
    property_body = "return value" if extra else "pass"
    choices = "x, y, z=None" if extra else "x, y"
    source = (
        f"def count(value{parameter}):\n    return value\n\n"
        f"def complex_function(value{parameter}):\n" + complex_body + "\n"
        f"class Left:\n    def run(self, x{parameter}):\n        return x\n\n"
        "class Right:\n    def run(self, x, y):\n        return x + y\n\n"
        f"def outer(flag{parameter}):\n    def inner(x{parameter}):\n        return x\n    return inner(flag)\n\n"
        "class Property:\n    @property\n    def item(self):\n        return 1\n"
        f"    @item.setter\n    def item(self, value):\n        {property_body}\n\n"
        "if flag:\n    def choice(x):\n        return x\nelse:\n"
        f"    def choice({choices}):\n        return x\n\n"
        "def repeated(x):\n    return x\n"
    )
    if extra:
        source += "def repeated(x):\n    return x + 1\n"
        source += "def new_name(x):\n    return x\n"
        source += "def remove_only(x):\n    return 0\n"
        source += "class Rebound:\n    pass\nclass Rebound:\n    def run(self, x, y=None):\n        return x\n"
        source += "def comment_only(x):\n    return x  # clarification\n"
        source += "@other_decorator\ndef decorated(x):\n    return x\n"
    else:
        source += "def old_name(x):\n    return x\n"
        source += "def remove_only(x):\n    if x:\n        return 1\n    return 0\n"
        source += "class Rebound:\n    def run(self, x):\n        return x\nclass Rebound:\n    pass\n"
        source += "def comment_only(x):\n    return x\n"
        source += "@decorate\ndef decorated(x):\n    return x\n"
    return source


def run_checks(client):
    changes = client.tool("list_python_changes", {"baseRef": "main", "headRef": "HEAD"})
    shas = {key: changes[key] for key in ("baseSha", "headSha")}
    report = client.tool("analyze_python_changes", shas)
    assert client.tool("analyze_python_changes", shas) == report, "same SHAs/config must give the same Python result"
    assert report["status"] == "partial", report
    files = {f.get("newPath") or f["oldPath"]: f for f in report["files"]}
    main = files["matching.py"]
    matches = {m["key"]: m for m in main["matches"]}
    metrics = {(m["entity"], m["metric"]): m for m in main["metrics"]}

    for key in ("count", "complex_function", "Left.run", "outer", "outer.inner"):
        match = matches[key]
        assert match["status"] == "MATCHED" and len(match["before"]) == len(match["after"]) == 1, match
        signature = match["after"][0]["signature"]
        value = metrics[(signature, "parameter_count")]
        assert value["status"] == "COMPARED" and value["delta"] == 1, value
        assert match["before"][0]["signature"] != signature
    assert "Right.run" not in matches, matches
    diagnostics = [f for f in main["findings"] if f["method"].startswith("complex_function(")]
    assert len(diagnostics) == 1 and diagnostics[0]["status"] == "CHANGED", diagnostics

    for key in ("Property.item", "choice", "repeated", "Rebound.run"):
        match = matches[key]
        assert match["status"] == "AMBIGUOUS", match
        signature = (match["after"][0]["signature"] if len(match["after"]) == 1
                     else match["before"][0]["signature"] if len(match["before"]) == 1 else key)
        values = [m for m in main["metrics"] if m["entity"] == signature]
        assert len(values) == 6, (key, values)
        for value in values:
            assert value["status"] == "UNAVAILABLE" and value.get("delta") is None, value
            assert "ERROR" in (value["before"]["status"], value["after"]["status"]), value
            if key == "repeated":
                assert value["before"]["status"] == "AVAILABLE" and value["after"]["status"] == "ERROR", value
        assert any(key in warning for warning in report["warnings"]), report["warnings"]
    assert matches["old_name"]["status"] == "REMOVED" and matches["new_name"]["status"] == "ADDED"
    for key, side in (("old_name(x)", "after"), ("new_name(x)", "before")):
        value = metrics[(key, "parameter_count")]
        assert value[side]["status"] == "ENTITY_ABSENT" and value.get("delta") is None, value
    assert metrics[("remove_only(x)", "return_count")]["delta"] == -1
    for key in ("comment_only", "decorated"):
        assert matches[key]["status"] == "MATCHED", matches[key]
        values = [m for m in main["metrics"] if m["entity"] == key + "(x)"]
        assert len(values) == 6 and all(m["status"] == "COMPARED" and m["delta"] == 0 for m in values), values

    for path, status, absent in (("deleted.py", "REMOVED", "after"), ("added.py", "ADDED", "before")):
        file = files[path]
        assert file["matches"][0]["status"] == status, file
        assert len(file["metrics"]) == 6, file
        for value in file["metrics"]:
            assert value[absent]["status"] == "ENTITY_ABSENT" and value.get("delta") is None, value
            assert value["before" if absent == "after" else "after"]["status"] == "AVAILABLE", value

    renamed = files["renamed.py"]
    assert renamed["oldPath"] == "rename.py", renamed
    assert renamed["matches"][0]["status"] == "MATCHED", renamed
    assert next(m for m in renamed["metrics"] if m["metric"] == "parameter_count")["delta"] == 1
    for path, status, absent in (("from.py", "REMOVED", "after"), ("to.py", "ADDED", "before")):
        file = files[path]
        assert next(m for m in file["matches"] if m["key"] == "moved")["status"] == status, file
        value = next(m for m in file["metrics"] if m["entity"] == "moved(x)" and m["metric"] == "parameter_count")
        assert value[absent]["status"] == "ENTITY_ABSENT" and value.get("delta") is None, value


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-matching-") as folder:
        root = Path(folder)
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "Matching test")
        git(root, "config", "user.email", "matching@example.test")

        def write(path, text):
            (root / path).write_text(text, encoding="utf-8")

        moving = "    value = x\n" + "    value += 1\n" * 12 + "    return value\n"
        write("matching.py", module())
        write("rename.py", "def moving(x):\n" + moving)
        write("from.py", "def keep_from():\n    pass\ndef moved(x):\n    return x\n")
        write("to.py", "def keep_to():\n    pass\n")
        write("deleted.py", "def deleted(x):\n    return x\n")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        git(root, "switch", "-c", "feature")
        write("matching.py", module(True))
        git(root, "mv", "rename.py", "renamed.py")
        write("renamed.py", "def moving(x, extra=None):\n" + moving)
        write("from.py", "def keep_from():\n    pass\n")
        write("to.py", "def keep_to():\n    pass\ndef moved(x):\n    return x\n")
        (root / "deleted.py").unlink()
        write("added.py", "def added():\n    pass\n")
        git(root, "add", ".")
        git(root, "commit", "-m", "head")
        process, client = connect(jar, root)
        try:
            run_checks(client)
        finally:
            close(process)
    print("Passed: parameter deltas, class/nested owners, duplicate/property/conditional ambiguity, "
          "diagnostic comparison, deletion-only edits, comment/decorator edits, added/deleted files, "
          "repeatability, file rename and cross-file move boundaries.")


if __name__ == "__main__":
    main()
