"""Exercise the executable JAR through its public MCP stdio interface."""

import json
from pathlib import Path
from queue import Queue
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def source(condition_count, method):
    lines = [f"    void {method}() {{"]
    for level in range(condition_count):
        lines.append("    " * (level + 2) + "if (check()) {")
    lines.append("    " * (condition_count + 2) + "send();")
    for level in reversed(range(condition_count)):
        lines.append("    " * (level + 2) + "}")
    lines.append("    }")
    return "\n".join(lines)


def fixture(root):
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Smoke test")
    git(root, "config", "user.email", "smoke@example.test")
    path = root / "Example file.java"
    header = "class Example {\n    boolean check() { return true; }\n    void send() {}\n"
    before = source(1, "changed") + "\n" + source(6, "existing")
    path.write_text(header + before + "\n}\n", encoding="utf-8")
    (root / "Rename.java").write_text("class Rename {}\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    git(root, "switch", "-c", "feature")
    git(root, "mv", "Rename.java", "Renamed.java")
    after = source(6, "changed") + "\n" + source(6, "existing").replace("send();", "send(); // clarification")
    content = header + after + "\n}\n"
    path.write_text(content, encoding="utf-8")
    (root / "Invalid.java").write_text("class Invalid { void broken( }\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "review target")
    path.write_text("This dirty working tree file must be ignored.\n", encoding="utf-8")
    return next(i for i, line in enumerate(content.splitlines(), 1) if line.strip() == "send();")


def check_analysis_batches(client, root):
    extra = root / "extra"
    extra.mkdir()
    for index in range(91):
        name = f"Extra{index:02d}"
        (extra / f"{name}.java").write_text(f"class {name} {{}}\n", encoding="utf-8")
    git(root, "add", "extra")
    git(root, "commit", "-m", "expand comparison to 94 Java files")

    changes = client.tool("list_java_changes", {"baseRef": "main", "headRef": "HEAD"})
    paths = [file.get("newPath") or file["oldPath"] for file in changes["files"]]
    assert len(paths) == len(set(paths)) == 94, paths
    shas = {key: changes[key] for key in ("baseSha", "headSha")}

    over_limit = client.tool("analyze_java_changes", shas, error=True)
    message = over_limit["content"][0]["text"]
    assert "94" in message and "50" in message and "paths" in message, over_limit
    unified_over_limit = client.tool("analyze_changes", shas, error=True)
    assert "94" in unified_over_limit["content"][0]["text"] and "50" in unified_over_limit["content"][0]["text"], unified_over_limit

    analyzed = []
    findings = []
    for batch in (paths[:50], paths[50:]):
        report = client.tool("analyze_java_changes", {**shas, "paths": batch})
        actual = [file.get("newPath") or file["oldPath"] for file in report["files"]]
        assert actual == batch, report
        expected_status = "partial" if "Invalid.java" in batch else "ok"
        assert report["status"] == expected_status, report
        analyzed.extend(actual)
        findings.extend(finding for file in report["files"] for finding in file["findings"])
    assert analyzed == paths, analyzed
    assert any(finding["status"] == "INTRODUCED" for finding in findings), findings


class Client:
    def __init__(self, process):
        self.process = process
        self.inbox = Queue()
        self.request_id = 0

        def read():
            for line in process.stdout:
                self.inbox.put(line)
            self.inbox.put(None)

        Thread(target=read, daemon=True).start()

    def send(self, method, params=None, *, notification=False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.request_id += 1
            message["id"] = self.request_id
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if notification:
            return None
        while True:
            line = self.inbox.get(timeout=45)
            assert line is not None, "MCP server closed stdout"
            response = json.loads(line)
            if response.get("id") == self.request_id:
                assert "error" not in response, response
                return response["result"]

    def tool(self, name, arguments, *, error=False):
        result = self.send("tools/call", {"name": name, "arguments": arguments})
        assert result.get("isError", False) == error, result
        return result if error else result["structuredContent"]


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-smoke-") as folder:
        root = Path(folder)
        call_line = fixture(root)
        with subprocess.Popen(["java", "-jar", str(jar), "--repo-root", str(root)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, encoding="utf-8") as process:
            try:
                client = Client(process)
                hello = client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                    "clientInfo": {"name": "smoke-test", "version": "1"}})
                assert hello["serverInfo"]["name"] == "codeclarity", hello
                client.send("notifications/initialized", notification=True)
                assert {tool["name"] for tool in client.send("tools/list")["tools"]} == {
                    "get_changes", "analyze_changes", "get_symbol_context", "inspect_symbol_ast",
                    "get_review_history", "update_review_history", "propose_rule_candidate",
                    "get_symbol_definition", "find_symbol_references",
                    "list_java_changes", "analyze_java_changes", "inspect_java_method",
                    "list_python_changes", "analyze_python_changes", "inspect_python_function"
                }
                changes = client.tool("list_java_changes", {"baseRef": "main", "headRef": "HEAD"})
                files = {file["newPath"]: file for file in changes["files"]}
                assert {"Example file.java", "Invalid.java", "Renamed.java"} == set(files), files
                assert files["Renamed.java"]["oldPath"] == "Rename.java", files["Renamed.java"]
                assert any(r["startLine"] <= call_line <= r["endLine"]
                           for r in files["Example file.java"]["headLines"]), files["Example file.java"]
                shas = {key: changes[key] for key in ("baseSha", "headSha")}
                report = client.tool("analyze_java_changes", {**shas, "paths": ["Example file.java"]})
                assert report["status"] == "ok", report
                found = {(f["method"], f["rule"]): f["status"] for f in report["files"][0]["findings"]}
                assert found["Example#changed()", "CognitiveComplexity"] == "INTRODUCED", found
                assert found["Example#existing()", "CognitiveComplexity"] == "EXISTING", found
                metrics = {(m["entity"], m["metric"]): m for m in report["files"][0]["metrics"]}
                for metric_id, before, after in [("cyclomatic_complexity", 2, 7), ("cognitive_complexity", 1, 21)]:
                    value = metrics[("Example#changed()", metric_id)]
                    assert value["status"] == "COMPARED" and value["before"]["value"] == before and value["after"]["value"] == after, value
                    assert value["delta"] == after - before, value
                partial = client.tool("analyze_java_changes", shas)
                assert partial["status"] == "partial" and any("Invalid.java" in w for w in partial["warnings"]), partial
                request = {"commitSha": changes["headSha"], "path": "Example file.java", "line": call_line}
                context = client.tool("inspect_java_method", request)
                call = next(call for call in context["calls"] if call["expression"] == "send()")
                assert context["signature"] == "Example#changed()" and len(call["enclosingIfs"]) == 6, context
                client.tool("inspect_java_method", {**request, "path": "../Example file.java"}, error=True)
                check_analysis_batches(client, root)
                process.stdin.close()
                assert process.wait(timeout=10) == 0
            finally:
                if process.poll() is None:
                    process.kill()
    print("Passed: MCP handshake, Java and Python tool discovery, Git snapshot, rename, PMD comparison, parse error, "
          "method context and 94-file comparison analyzed in two batches.")


if __name__ == "__main__":
    main()
