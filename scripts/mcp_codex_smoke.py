"""Verify actual Codex discovery/calls for the unified MCP API using a fresh CLI session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from mcp_smoke_test import JAVA_PATH, PYTHON_PATH, fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--jar", type=Path, default=Path("plugin/server/codeclarity-mcp.jar"))
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not args.codex:
        parser.error("Pass --codex /path/to/codex when CLI is not on PATH")
    output, jar = args.output.resolve(), args.jar.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new output directory; raw evidence is not overwritten")
    output.mkdir(parents=True, exist_ok=True)
    repo = output / "repo"
    fixture(repo)
    prompt = (
        "Check the connected codeclarity MCP API for the current repository. Use real MCP calls, not a shell client. "
        "Call get_changes with baseRef main and headRef HEAD. Call analyze_changes with its returned SHA pair "
        "to analyze all changed Java and Python files together. Then call get_symbol_context for a changed Java "
        "method and a changed Python function at the resolved head commit, using the returned paths/line ranges. "
        "Return the discovered tools, snapshot SHAs, languages, source context and any warnings. "
        "Some test input is deliberately invalid: retain valid results and report partial status honestly. "
        "Do not modify files, install anything, use external services or write history."
    )
    (output / "prompt.txt").write_text(prompt + "\n")
    server = '{codeclarity={command="java",args=' + json.dumps(["-jar", str(jar), "--repo-root", str(repo)]) + '}}'
    command = [args.codex, "exec", "--ephemeral", "--json", "--sandbox", "read-only", "-C", str(repo),
               "-c", "mcp_servers=" + server, "-o", str(output / "last-message.md"), prompt]
    errors, calls, completed = [], [], False
    try:
        with (output / "events.jsonl").open("w") as stdout, (output / "stderr.log").open("w") as stderr:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    timeout=args.timeout, env=dict(os.environ, CODECLARITY_PYTHON=sys.executable))
        if result.returncode:
            errors.append("Codex exited with status " + str(result.returncode))
    except (OSError, subprocess.TimeoutExpired) as error:
        errors.append(str(error))
    raw = (output / "events.jsonl").read_bytes()
    for line in raw.decode().splitlines():
        event = json.loads(line)
        completed |= event["type"] == "turn.completed"
        item = event.get("item", {})
        if event["type"] != "item.completed" or item.get("type") != "mcp_tool_call" or item.get("server") != "codeclarity":
            continue
        if item.get("error") or item.get("status") != "completed":
            errors.append("MCP call failed: " + item["tool"])
            continue
        result = item.get("result") or {}
        if result.get("isError", result.get("is_error", False)):
            errors.append("MCP tool error: " + item["tool"])
            continue
        data = result.get("structuredContent", result.get("structured_content"))
        if data is None:
            data = json.loads(next(c["text"] for c in result["content"] if c["type"] == "text"))
        calls.append({"tool": item["tool"], "arguments": item["arguments"], "result": data})
    if not completed:
        errors.append("Codex turn did not complete")
    names = {c["tool"] for c in calls}
    if not {"get_changes", "analyze_changes", "get_symbol_context"} <= names:
        errors.append("Missing native Codex calls to one or more required tools")
    changes = next((c["result"] for c in calls if c["tool"] == "get_changes"), None)
    analysis = next((c["result"] for c in calls if c["tool"] == "analyze_changes"), None)
    if changes and analysis:
        if any(changes[k] != analysis[k] for k in ("baseSha", "headSha")):
            errors.append("Snapshot mismatch")
        if analysis["status"] != "partial" or not any("broken.py" in w for w in analysis["warnings"]):
            errors.append("Invalid file did not produce a partial report with warnings")
        healthy = {f["newPath"]: f for f in analysis["files"] if f["newPath"] in (JAVA_PATH, PYTHON_PATH)}
        if set(healthy) != {JAVA_PATH, PYTHON_PATH} or any(not f["metrics"] for f in healthy.values()):
            errors.append("Mixed analysis lost valid Java/Python measurements")
        contexts = {c["result"]["path"]: c["result"] for c in calls if c["tool"] == "get_symbol_context"}
        if not {JAVA_PATH, PYTHON_PATH} <= contexts.keys():
            errors.append("Codex did not retrieve context for both languages")
        for path, context in contexts.items():
            if context["commitSha"] != changes["headSha"] or context["status"] != "ok" or not context["source"]:
                errors.append("Incorrect committed source context: " + path)
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True)
    if dirty.stdout:
        errors.append("Input repository modified")
    evidence = {"schemaVersion": 1, "executionLevel": "CODEX_CLI_WITH_REAL_STDIO_MCP", "status": "FAIL" if errors else "PASS",
                "errors": errors, "repo": str(repo), "jar": str(jar), "jarSha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
                "rawEvents": str(output / "events.jsonl"), "eventsSha256": hashlib.sha256(raw).hexdigest(), "calls": calls,
                "configuration": "process-local MCP override; no installed plugin or home config changes"}
    (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": evidence["status"], "errors": errors, "toolsCalled": sorted(names), "calls": len(calls)}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
