"""Run mandatory local checks against the packaged JAR; no model or real JDT LS required."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=project / "target/codeclarity-mcp.jar")
    parser.add_argument("--output", type=Path, default=project / "target/workflow-checks")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout in seconds per check")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    jar, output = args.jar.resolve(), args.output.resolve()
    if not jar.is_file():
        parser.error("Packaged JAR missing; run mvn package first.")
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONOPTIMIZE="0",
                       CODECLARITY_PYTHON=sys.executable)
    if environment.get("JAVA_HOME"):
        environment["PATH"] = str(Path(environment["JAVA_HOME"]) / "bin") + os.pathsep + environment.get("PATH", "")
    jar_checks = ["mcp_smoke_test", "smoke_test", "python_smoke_test", "java_metrics_test",
                  "language_integration_test", "history_test", "history_storage_test", "lsp_client_test",
                  "java_regression_test", "python_matching_test"]
    plain_checks = ["python_worker_test", "core_test", "llm_artifact_test"]
    commands = [(name, [sys.executable, "scripts/" + name + ".py", str(jar)]) for name in jar_checks]
    commands += [(name, [sys.executable, "scripts/" + name + ".py"]) for name in plain_checks]
    commands += [
        ("llm_launcher_test", [sys.executable, "scripts/llm_launcher_test.py", "--jar", str(jar),
                               "--python", sys.executable, "--output", tempfile.mkdtemp(prefix="launcher-", dir=output)]),
        ("python_metrics_spec_check", [sys.executable, "scripts/python_metrics_spec_check.py", "--require-cognitive"]),
        ("python_experiments", [sys.executable, "scripts/python_experiments.py", "--jar", str(jar),
                                "--output-dir", str(project / "target/python-experiments")]),
        ("lsp_smoke_test", [sys.executable, "scripts/lsp_smoke_test.py", "--jar", str(jar)]),
        ("eval-self-test", [sys.executable, "scripts/llm_evals.py", "self-test"]),
        ("ids-self-test", [sys.executable, "plugin/skills/readability-review/scripts/review_ids.py", "--self-test"]),
        ("protocol", [sys.executable, "scripts/llm_evals.py", "protocol", "--jar", str(jar),
                      "--output", tempfile.mkdtemp(prefix="protocol-", dir=output)]),
    ]

    def run(item):
        name, command = item
        log = output / (name + ".log")
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as stream:
            try:
                result = subprocess.run(command, cwd=project, env=environment, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=args.timeout)
                code = result.returncode
            except (OSError, subprocess.TimeoutExpired) as error:
                stream.write("\nRunner error: " + str(error) + "\n")
                code = -1
        record = {"name": name, "exitCode": code, "seconds": round(time.monotonic() - started, 2),
                  "command": command, "log": str(log)}
        print(("PASS " if code == 0 else "FAIL ") + name, flush=True)
        if code != 0:
            print(log.read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
        return record

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, commands))
    (output / "checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = sum(result["exitCode"] != 0 for result in results)
    print(f"{len(results) - failed}/{len(results)} checks passed; results: {output}")
    return int(failed != 0)


if __name__ == "__main__":
    sys.exit(main())
