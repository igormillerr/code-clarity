"""MCP navigation smoke: metrics isolation without JDT LS, plus optional real cross-file JDT LS checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory

from smoke_test import Client, git
from python_smoke_test import close


def connect(jar, root, **extra):
    env = dict(os.environ, CODECLARITY_PYTHON=sys.executable, **extra)
    process = subprocess.Popen(["java", "-jar", str(jar), "--repo-root", str(root)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    client = Client(process)
    client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "lsp-smoke", "version": "1"}})
    client.send("notifications/initialized", notification=True)
    return process, client


def column(text, word):
    return len(text[:text.index(word)].encode("utf-16-le")) // 2 + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=Path("target/codeclarity-mcp.jar"))
    parser.add_argument("--jdtls-home", type=Path)
    parser.add_argument("--java", default="java")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    jar = args.jar.resolve()
    evidence = {"executionLevel": "REAL_JDTLS_VIA_MCP" if args.jdtls_home else "MCP_WITHOUT_JDTLS",
                "scope": "WORKTREE", "sourceLayout": "src/main/java", "realJdtLs": "NOT_RUN", "checks": [],
                "jarSha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
                "jdtlsHome": str(args.jdtls_home.resolve()) if args.jdtls_home else None, "java": args.java}
    with TemporaryDirectory(prefix="codeclarity-lsp-smoke-") as directory:
        root = Path(directory)
        (root / "src/main/java/demo").mkdir(parents=True)
        helper = "    public static int twice(int value) { return value * 2; }"
        head = "    public int total() { /* 🚀 */ return Helper.twice(3); }"
        (root / "src/main/java/demo/Helper.java").write_text("package demo;\npublic class Helper {\n" + helper + "\n}\n")
        (root / "src/main/java/demo/App.java").write_text("package demo;\npublic class App {\n" + head.replace("twice(3)", "twice(1)") + "\n}\n")
        (root / "other.py").write_text("def other():\n    return 1\n")
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "LSP smoke")
        git(root, "config", "user.email", "lsp@example.test")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        git(root, "switch", "-c", "feature")
        (root / "src/main/java/demo/App.java").write_text("package demo;\npublic class App {\n" + head + "\n}\n")
        git(root, "add", ".")
        git(root, "commit", "-m", "head")
        query = {"path": "src/main/java/demo/App.java", "line": 3, "column": column(head, "twice")}
        for home, java in ((str(root / "missing-jdtls"), args.java),
                           (str(args.jdtls_home.resolve()), "codeclarity-missing-java") if args.jdtls_home else ("", args.java)):
            process, client = connect(jar, root, CODECLARITY_JDTLS_HOME=home, CODECLARITY_JDTLS_JAVA=java)
            try:
                catalog = {t["name"] for t in client.send("tools/list")["tools"]}
                assert {"get_symbol_definition", "find_symbol_references"} <= catalog
                changes = client.tool("get_changes", {"baseRef": "main", "headRef": "HEAD"})
                shas = {k: changes[k] for k in ("baseSha", "headSha")}
                before = client.tool("analyze_changes", shas)
                assert before["status"] == "ok" and len(before["files"][0]["metrics"]) == 6, before
                unavailable = client.tool("get_symbol_definition", query)
                assert unavailable["status"] == "unavailable" and unavailable["warnings"] and unavailable["scope"] == "WORKTREE", unavailable
                assert client.tool("analyze_changes", shas) == before
                client.tool("get_symbol_definition", {**query, "line": 0}, error=True)
                client.tool("get_symbol_definition", {**query, "path": "../App.java"}, error=True)
                client.tool("get_symbol_definition", {**query, "commitSha": changes["headSha"]}, error=True)
                no_python = client.tool("find_symbol_references", {"path": "other.py", "line": 1, "column": 5})
                assert no_python["status"] == "unavailable"
                label = "missing executable" if java == "codeclarity-missing-java" else "missing home" if home else "unconfigured"
                evidence["checks"].append({"configuration": label, "result": unavailable,
                                            "metricsPreserved": True})
            finally:
                close(process)
        if args.jdtls_home:
            process, client = connect(jar, root, CODECLARITY_JDTLS_HOME=str(args.jdtls_home.resolve()), CODECLARITY_JDTLS_JAVA=args.java)
            try:
                started = time.monotonic()
                definition = client.tool("get_symbol_definition", query)
                cold_seconds = time.monotonic() - started
                print("JDT definition:", json.dumps(definition), flush=True)
                assert definition["status"] == "ok", definition
                assert any(l["path"] == "src/main/java/demo/Helper.java" and l["range"]["start"] == {"line": 3, "column": column(helper, "twice")}
                           and l["range"]["end"]["column"] == column(helper, "twice") + len("twice") for l in definition["locations"]), definition
                started = time.monotonic()
                references = client.tool("find_symbol_references", {"path": "src/main/java/demo/Helper.java", "line": 3,
                                         "column": column(helper, "twice"), "includeDeclaration": True})
                warm_seconds = time.monotonic() - started
                print("JDT references:", json.dumps(references), flush=True)
                assert references["status"] == "ok", references
                assert {"src/main/java/demo/App.java", "src/main/java/demo/Helper.java"} <= {l["path"] for l in references["locations"]}, references
                assert all(not l["external"] for l in references["locations"]), references
                helper_path = root / "src/main/java/demo/Helper.java"
                app_path = root / "src/main/java/demo/App.java"
                original_helper, original_app = helper_path.read_text(), app_path.read_text()
                try:
                    helper_path.write_text(original_helper.replace("twice", "triple"))
                    app_path.write_text(original_app.replace("twice", "triple"))
                    refreshed = client.tool("get_symbol_definition", query)
                    assert refreshed["status"] == "ok" and any(
                        l["path"] == "src/main/java/demo/Helper.java"
                        and l["range"]["end"]["column"] - l["range"]["start"]["column"] == len("triple")
                        for l in refreshed["locations"]), refreshed
                finally:
                    helper_path.write_text(original_helper)
                    app_path.write_text(original_app)
                assert not git(root, "status", "--porcelain"), "LSP must not alter project source/config"
                evidence.update(realJdtLs="PASS", definition=definition, references=references, refreshed=refreshed,
                                coldSeconds=round(cold_seconds, 3), warmSeconds=round(warm_seconds, 3))
            finally:
                close(process)
        evidence["status"] = "PASS"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print("Passed: lazy LSP startup, missing/bad JDT LS isolation, six Java metrics retained, navigation validation; real JDT LS:", evidence["realJdtLs"])


if __name__ == "__main__":
    main()
