"""Real-MCP regressions for anonymous owners and explicit changed-line coverage."""

from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory

from smoke_test import git
from python_smoke_test import connect, close


METRICS = {"cyclomatic_complexity", "cognitive_complexity", "function_sloc",
           "max_nesting_depth", "parameter_count", "return_count"}


def covered_lines(side):
    return {line for span in side["outsideEntityLines"]
            for line in range(span["startLine"], span["endLine"] + 1)}


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    anonymous = """class Anonymous {
    Runnable first = new Runnable() {
        public void run() { System.out.println("first"); }
    };
    Runnable second = new Runnable() {
        public void run() { System.out.println("second"); }
    };
    Runnable nested = new Runnable() {
        Runnable child = new Runnable() { public void run() { System.out.println("child"); } };
        public void run() { System.out.println("parent"); }
    };
    static { Runnable same = new Runnable() { public void run() { System.out.println("init1"); } }; }
    static { Runnable same = new Runnable() { public void run() { System.out.println("init2"); } }; }
    void work() {
        Runnable left = new Runnable() { public void run() { System.out.println("left"); } };
        Runnable right = new Runnable() { public void run() { System.out.println("right"); } };
        accept(new Runnable() { public void run() { System.out.println("bare1"); } });
        accept(new Runnable() { public void run() { System.out.println("bare2"); } });
        { Runnable repeated = new Runnable() { public void run() { System.out.println("block1"); } }; }
        { Runnable repeated = new Runnable() { public void run() { System.out.println("block2"); } }; }
    }
    void accept(Runnable task) {}
}
enum Choices {
    FIRST { void work() { System.out.println("enum1"); } },
    SECOND { void work() { System.out.println("enum2"); } };
    abstract void work();
}
"""
    coverage = """class Coverage {
    int threshold = 1;
    static { System.out.println("init"); }
    int compute(int value) {
        return value;
    }
}
"""
    with TemporaryDirectory(prefix="codeclarity-java-regressions-") as folder:
        root = Path(folder)
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "Java regression test")
        git(root, "config", "user.email", "java-regression@example.test")
        sources = {"Anonymous.java": anonymous, "Fields.java": coverage,
                   "Mixed.java": coverage.replace("Coverage", "Mixed"),
                   "Body.java": coverage.replace("Coverage", "Body"),
                   "Deleted.java": "class Deleted { int field = 1; }\n",
                   "Broken.java": "class Broken { void work() {} }\n"}
        for path, source in sources.items():
            (root / path).write_text(source, encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        git(root, "switch", "-c", "feature")
        # Moving declarations and inserting an unrelated field must not change anonymous identities.
        updated_anonymous = anonymous.replace("class Anonymous {", "class Anonymous {\n\n    int unrelated = 1;")
        for marker in ("first", "second", "left", "right", "bare1", "bare2", "enum1", "enum2",
                       "parent", "child", "init1", "init2", "block1", "block2"):
            updated_anonymous = updated_anonymous.replace('println("' + marker + '")', 'println("changed-' + marker + '")')
        sources["Anonymous.java"] = updated_anonymous
        sources["Fields.java"] = coverage.replace("threshold = 1", "threshold = 2")
        sources["Mixed.java"] = sources["Mixed.java"].replace("threshold = 1", "threshold = 2").replace("return value;", "return value + 1;").replace('println("init")', 'println("changed")')
        sources["Body.java"] = sources["Body.java"].replace("return value;", "return value + 1;")
        sources["Broken.java"] = "class Broken { void work( }\n"
        sources["Added.java"] = "class Added { int field = 1; }\n"
        del sources["Deleted.java"]
        (root / "Deleted.java").unlink()
        for path, source in sources.items():
            (root / path).write_text(source, encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "head")
        process, client = connect(jar, root)
        try:
            changes = client.tool("get_changes", {"baseRef": "main", "headRef": "HEAD"})
            shas = {key: changes[key] for key in ("baseSha", "headSha")}
            report = client.tool("analyze_changes", {**shas, "paths": ["Anonymous.java"]})
            assert report["status"] == "ok" and not report["warnings"], report
            file = report["files"][0]
            runs = [entity for entity in file["changedMethods"] if entity.endswith("#run()")]
            assert len(runs) == len(set(runs)) == 12, runs
            assert "Anonymous.anonymous(first:1)#run()" in runs, runs
            assert "Anonymous.anonymous(second:1)#run()" in runs, runs
            assert "Anonymous.anonymous(nested:1).anonymous(child:1)#run()" in runs, runs
            assert {"Choices.enum(FIRST)#work()", "Choices.enum(SECOND)#work()"} <= set(file["changedMethods"]), file
            for entity in file["changedMethods"]:
                metrics = [m for m in file["metrics"] if m["entity"] == entity]
                assert {m["metric"] for m in metrics} == METRICS, metrics
                assert len(metrics) == 6 and all(m["status"] == "COMPARED" for m in metrics), metrics
            for snapshot, source in ((shas["baseSha"], anonymous), (shas["headSha"], updated_anonymous)):
                for marker in ("first", "second"):
                    line = next(i for i, text in enumerate(source.splitlines(), 1) if 'println("' in text and marker in text)
                    context = client.tool("get_symbol_context", {"commitSha": snapshot, "path": "Anonymous.java", "line": line})
                    assert context["signature"] == f"Anonymous.anonymous({marker}:1)#run()", context
                    assert "println" in context["source"], context

            report = client.tool("analyze_changes", {**shas, "paths": ["Fields.java", "Mixed.java", "Body.java", "Added.java", "Deleted.java", "Broken.java"]})
            assert report["status"] == "partial", report
            files = {f.get("newPath") or f["oldPath"]: f for f in report["files"]}
            fields = files["Fields.java"]
            assert not fields["changedMethods"] and not fields["metrics"], fields
            for side in ("base", "head"):
                entry = fields["coverage"][side]
                assert entry["status"] == "OUTSIDE_SUPPORTED_ENTITIES" and entry["reason"], entry
                assert covered_lines(entry) == {2}, entry
                mixed = files["Mixed.java"]["coverage"][side]
                assert mixed["status"] == "OUTSIDE_SUPPORTED_ENTITIES" and covered_lines(mixed) == {2, 3}, mixed
                body = files["Body.java"]["coverage"][side]
                assert body == {"status": "COMPLETE", "outsideEntityLines": [], "reason": None}, body
            assert files["Mixed.java"]["metrics"] and files["Body.java"]["metrics"], files
            for path, present, absent in (("Added.java", "head", "base"), ("Deleted.java", "base", "head")):
                assert files[path]["coverage"][present]["status"] == "OUTSIDE_SUPPORTED_ENTITIES", files[path]
                assert files[path]["coverage"][absent]["status"] == "COMPLETE", files[path]
            assert files["Broken.java"]["coverage"]["head"]["status"] == "UNKNOWN", files["Broken.java"]
            # Coverage does not change the established request-status semantics.
            fields_only = client.tool("analyze_java_changes", {**shas, "paths": ["Fields.java"]})
            assert fields_only["status"] == "ok" and not fields_only["warnings"], fields_only
            assert fields_only["files"][0] == fields, fields_only
            assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"]), "Checks must not modify source snapshots"
        finally:
            close(process)
    print("Passed: unique/stable field, local and expression anonymous owners, enum owners, six comparable metrics, "
          "committed contexts, field/initializer/mixed/body-only/add/delete coverage and unknown coverage on parse failure.")


if __name__ == "__main__":
    main()
