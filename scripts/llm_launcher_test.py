"""Exercise the packaging launcher against the real supplied MCP JAR.

Uses isolated -Duser.home directories; never changes global configuration or
installs packages. This tests a local process launch, not Codex plugin loading.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time

from smoke_test import Client

PROJECT = Path(__file__).resolve().parents[1]
METRICS = {"cyclomatic_complexity", "cognitive_complexity", "function_sloc",
           "max_nesting_depth", "parameter_count", "return_count"}
CASES = ("file-selector", "environment-precedence", "server-default", "missing-jar")


def require(value, message):
    if not value:
        raise AssertionError(message)


def child_processes(pid):
    if os.name == "nt":
        expression = f"ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter 'ParentProcessId = {pid}' | Select-Object ProcessId,Name) -Compress"
        result = subprocess.run(["powershell", "-NoProfile", "-Command", expression], check=True,
                                capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        values = json.loads(result.stdout.strip() or "[]")
        return values if isinstance(values, list) else [values]
    result = subprocess.run(["ps", "-o", "pid=,comm=", "--ppid", str(pid)], capture_output=True, text=True, timeout=5)
    return [{"ProcessId": int(line.split(None, 1)[0]), "Name": line.split(None, 1)[1]}
            for line in result.stdout.splitlines() if line.strip()]


def process_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        require(kernel.GetExitCodeProcess(handle, ctypes.byref(code)), "Cannot query test child exit status")
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def close_tree(process, children):
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        return_code = process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.kill()
        process.wait(timeout=5)
        raise AssertionError("Launcher did not exit after MCP stdin EOF")
    deadline = time.monotonic() + 3
    while any(process_alive(pid) for pid in children) and time.monotonic() < deadline:
        time.sleep(0.05)
    orphaned = [pid for pid in children if process_alive(pid)]
    if orphaned:
        # Cleanup only known children of this test's launcher, never all Java processes.
        if os.name == "nt":
            for pid in orphaned:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        raise AssertionError(f"Launcher left live child processes after EOF: {orphaned}")
    return return_code


def execute(case, repo, python, output):
    launcher = PROJECT / "plugin/scripts/LaunchMcp.java"
    jar = PROJECT / "plugin/server/codeclarity-mcp.jar"
    record = {"case": case, "status": "FAIL", "codexEndToEnd": False}
    environment = dict(os.environ)
    environment.pop("CODECLARITY_PYTHON", None)
    stderr_lines, children = [], []
    process = None
    with TemporaryDirectory(prefix="codeclarity-launcher-") as directory:
        home = Path(directory)
        config = home / ".codeclarity/python-path.txt"
        config.parent.mkdir()
        if case == "file-selector":
            config.write_text(str(python), encoding="utf-8")
        elif case == "environment-precedence":
            config.write_text("invalid-relative-interpreter", encoding="utf-8")
            environment["CODECLARITY_PYTHON"] = str(python)
        command = ["java", "-Duser.home=" + str(home), str(launcher),
                   str(home / "absent.jar") if case == "missing-jar" else str(jar), "--repo-root", str(repo)]
        record["pythonSelection"] = "file" if case == "file-selector" else "environment" if case == "environment-precedence" else "server-default"
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", env=environment,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if case == "missing-jar":
                stdout, stderr = process.communicate(timeout=20)
                require(process.returncode != 0, "Missing JAR must fail")
                require(stdout == "", "Missing JAR error must not contaminate protocol stdout")
                require("existing MCP JAR" in stderr, "Missing JAR needs a useful stderr message")
                record.update(status="PASS", exitCode=process.returncode, stdout=stdout, stderr=stderr,
                              orphanedChildPids=[])
                return record

            def drain():
                for line in process.stderr:
                    if len(stderr_lines) < 100:
                        stderr_lines.append(line.rstrip())

            stderr_reader = Thread(target=drain, daemon=True)
            stderr_reader.start()
            client = Client(process)
            hello = client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                               "clientInfo": {"name": "codeclarity-launcher-test", "version": "1"}})
            client.send("notifications/initialized", {}, notification=True)
            catalog = client.send("tools/list")
            tools = sorted(tool["name"] for tool in catalog["tools"])
            require(len(tools) == 6 and "analyze_python_changes" in tools and "analyze_java_changes" in tools,
                    "Expected both languages in actual tool discovery")
            child_records = child_processes(process.pid)
            children = [item["ProcessId"] for item in child_records]
            jar_children = [item["ProcessId"] for item in child_records if item["Name"].lower() in ("java.exe", "java")]
            require(len(jar_children) == 1, f"Expected one supplied JAR Java child, found {child_records}")
            changes = client.tool("list_python_changes", {"baseRef": "main", "headRef": "HEAD"})
            shas = {key: changes[key] for key in ("baseSha", "headSha")}
            report = client.tool("analyze_python_changes", shas)
            rows = [row for file in report["files"] for row in file["metrics"]]
            require(len(rows) == 6 and {row["metric"] for row in rows} == METRICS,
                    "Expected six actual comparisons from the naming fixture")
            by_id = {row["metric"]: row for row in rows}
            for metric_id, row in by_id.items():
                if metric_id != "cognitive_complexity":
                    require(row["status"] == "COMPARED" and all(row[side]["status"] == "AVAILABLE" for side in ("before", "after")),
                            f"Structural metric unavailable: {metric_id}")
            cognitive = by_id["cognitive_complexity"]
            if case in ("file-selector", "environment-precedence"):
                require(report["status"] == "ok", "Configured real Python analysis must be complete")
                require(cognitive["status"] == "COMPARED" and all(cognitive[side]["status"] == "AVAILABLE" for side in ("before", "after")),
                        "Configured interpreter did not supply Cognitive Complexity")
                require(all(cognitive[side]["definition"]["analyzer"] == "complexipy/8.3.0" for side in ("before", "after")),
                        "Unexpected real cognitive analyzer version")
            else:
                # The default interpreter may legitimately already contain the pinned dependency.
                require(cognitive["status"] in ("COMPARED", "UNAVAILABLE"), "Unexpected default cognitive comparison")
                if cognitive["status"] == "UNAVAILABLE":
                    require(report["status"] == "partial" and all(cognitive[side]["status"] == "ERROR" and cognitive[side].get("value") is None for side in ("before", "after")),
                            "Missing/default cognitive dependency must remain explicit ERROR without numeric zero")
                else:
                    require(report["status"] == "ok" and all(cognitive[side]["status"] == "AVAILABLE"
                            and cognitive[side]["definition"]["analyzer"] == "complexipy/8.3.0" for side in ("before", "after")),
                            "A capable default interpreter must supply the pinned real cognitive analyzer")
                java_changes = client.tool("list_java_changes", {"baseRef": "main", "headRef": "HEAD"})
                java_report = client.tool("analyze_java_changes", shas)
                require(java_report["status"] == "ok" and java_changes["files"] == java_report["files"] == [],
                        "Java routing must remain available for the Python-only fixture")
                record["javaCheck"] = "Real Java list/analyze succeeded for the empty Java scope in this Python fixture"
            record.update(serverInfo=hello["serverInfo"], tools=tools, scope=shas, metrics=rows,
                          pythonReportStatus=report["status"], childPids=children, childProcesses=child_records)
            record["exitCode"] = close_tree(process, children)
            stderr_reader.join(timeout=2)
            require(record["exitCode"] == 0, "Successful launcher must preserve the server's normal exit code")
            if case == "environment-precedence":
                require(not any("invalid Python configuration" in line for line in stderr_lines),
                        "Explicit interpreter environment should take precedence over the bad file")
            record.update(status="PASS", orphanedChildPids=[], stderr=stderr_lines)
            return record
        finally:
            if process is not None and process.poll() is None:
                close_tree(process, children)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=PROJECT / ".codeclarity/python-integration-naming/repo")
    parser.add_argument("--python", type=Path, default=PROJECT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", choices=CASES, action="append", dest="cases")
    args = parser.parse_args()
    require(args.repo.resolve().is_dir(), "Prepare the python-naming Git fixture before this launch test")
    require(args.python.resolve().is_file(), "Configured Python venv is missing")
    require(shutil.which("java"), "Java 21+ must be in PATH")
    output = args.output or PROJECT / ".codeclarity/launcher-tests" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    require(not output.exists() or not any(output.iterdir()), "Use a new or empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in args.cases or CASES:
        try:
            record = execute(case, args.repo.resolve(), args.python.resolve(), output)
        except Exception as error:
            record = {"case": case, "status": "FAIL", "error": f"{type(error).__name__}: {error}"}
        (output / (case + ".json")).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(record)
        print(f"{record['status']} {case}" + (": " + record["error"] if "error" in record else ""), flush=True)
    summary = {"schemaVersion": 1, "executionLevel": "LAUNCHER_REAL_MCP", "codexEndToEnd": False,
               "success": all(record["status"] == "PASS" for record in results),
               "jarSha256": hashlib.sha256((PROJECT / "plugin/server/codeclarity-mcp.jar").read_bytes()).hexdigest(),
               "launcherSha256": hashlib.sha256((PROJECT / "plugin/scripts/LaunchMcp.java").read_bytes()).hexdigest(),
               "repo": str(args.repo.resolve()), "results": results}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Report: " + str(output / "summary.json"), flush=True)
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
