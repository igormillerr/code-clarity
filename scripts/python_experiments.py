"""Run controlled before/after fixtures and save actual Git/MCP experiment results."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory

from python_smoke_test import connect, close

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "experiments/python_readability"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def behavior(experiment):
    # Only these controlled repository fixtures are executed. The analyzer still
    # parses target-repository source without importing or executing it.
    before = runpy.run_path(str(FIXTURES / experiment["id"] / "before.py"))[experiment["function"]]
    after = runpy.run_path(str(FIXTURES / experiment["id"] / "after.py"))[experiment["function"]]
    outputs = []
    require(len(experiment["behavior_cases"]) == experiment["expected_case_count"], "Behavior vector count changed.")
    for index, case in enumerate(experiment["behavior_cases"], 1):
        old_args, new_args = deepcopy(case["args"]), deepcopy(case["args"])
        old_value, new_value = before(*old_args), after(*new_args)
        require(old_value == new_value == case["expected"], f"Behavior mismatch: {experiment['id']} #{index}")
        require(type(old_value) is type(new_value) is type(case["expected"]), f"Result type mismatch: {experiment['id']} #{index}")
        require(old_args == new_args == case["args"], f"Input mutation: {experiment['id']} #{index}")
        outputs.append({"case": index, "args": case["args"], "expected": case["expected"],
                        "before": old_value, "after": new_value, "inputs_unchanged": True})
    return outputs


def summary(report):
    lines = ["# Python experiments: measured results", "",
             f"Success: **{report['success']}**", "", "Independent AI review: **not run**.", ""]
    for case in report["experiments"]:
        lines += [f"## {case['id']}", "", f"Behavior vectors passed: {len(case['behavior'])}", "",
                  "| Metric | Before | After | Delta |", "|---|---:|---:|---:|"]
        for metric in case["metrics"]:
            lines.append(f"| {metric['metric']} | {metric['before']['value']:g} | {metric['after']['value']:g} | {metric['delta']:g} |")
        lines.append("")
    if "error" in report:
        lines += ["Error: " + report["error"], ""]
    lines += ["Source, domain and interpretation: experiments/python_readability/README.md.",
              "These observations do not establish general semantic equivalence or human readability.", ""]
    return "\n".join(lines)


def execute(args, report):
    version = importlib.metadata.version("complexipy")
    require(version == "8.3.0", "Install requirements-python.txt in the selected interpreter.")
    jar = (PROJECT / args.jar).resolve()
    report["environment"] = {"python": platform.python_version(), "platform": platform.platform(),
                             "complexipy": version, "jar_sha256": sha256(jar.read_bytes())}
    data = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    report["manifest_sha256"] = sha256((FIXTURES / "manifest.json").read_bytes())
    report["ai_review"] = {"status": "not_run", "note": "Interpretation notes are authored illustrations, not an independent reviewer experiment."}
    require(len(data["experiments"]) == 2, "Expected exactly two controlled experiments.")
    with TemporaryDirectory(prefix="codeclarity-experiment-") as folder:
        root = Path(folder)
        hooks = root / ".empty-hooks"
        hooks.mkdir()

        def git(*command, date=None):
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            if date:
                env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
            return subprocess.check_output(["git", "-C", str(root), *command], env=env,
                                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", timeout=20).strip()

        git("init", "-b", "main")
        for key, value in (("user.name", "CodeClarity Experiment"), ("user.email", "experiment@example.test"),
                           ("core.autocrlf", "false"), ("core.hooksPath", str(hooks)), ("commit.gpgsign", "false")):
            git("config", key, value)
        source_hashes = {}
        for version_name in ("before", "after"):
            if version_name == "after":
                git("switch", "-c", "after")
            for experiment in data["experiments"]:
                name = experiment["id"]
                require(re.fullmatch(r"[a-z_]+", name) is not None, "Unsafe experiment id.")
                source = (FIXTURES / name / (version_name + ".py")).read_text(encoding="utf-8")
                encoded = source.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                (root / (name + ".py")).write_bytes(encoded)
                source_hashes.setdefault(name, {})[version_name] = sha256(encoded)
                git("add", "--", name + ".py")
            git("commit", "-m", "Experiment " + version_name,
                date="2026-11-12T12:00:00+03:00" if version_name == "before" else "2026-11-12T12:01:00+03:00")
        process, client = connect(jar, root)
        try:
            changes = client.tool("list_python_changes", {"baseRef": "main", "headRef": "HEAD"})
            shas = {key: changes[key] for key in ("baseSha", "headSha")}
            measured = client.tool("analyze_python_changes", shas)
            require(measured["status"] == "ok" and not measured["warnings"], "Incomplete experimental analysis.")
            require(client.tool("analyze_python_changes", shas) == measured, "Repeated analysis differs.")
            report.update(shas, changes=changes, mcp_report=measured, identical_analysis_runs=2)
            for experiment in data["experiments"]:
                name = experiment["id"]
                file = next(f for f in measured["files"] if f["newPath"] == name + ".py")
                require(len(file["matches"]) == 1 and file["matches"][0]["status"] == "MATCHED", name + ": not matched")
                require(len(file["metrics"]) == 6, name + ": expected six metrics")
                values = {m["metric"]: m for m in file["metrics"]}
                require(set(values) == set(experiment["expected_metrics"]), name + ": metric set mismatch")
                for metric, (old, new) in experiment["expected_metrics"].items():
                    value = values[metric]
                    require(value["status"] == "COMPARED" and value["before"]["value"] == old
                            and value["after"]["value"] == new and value["delta"] == new - old,
                            f"Metric mismatch: {name}/{metric}")
                contexts = {side: client.tool("inspect_python_function", {"commitSha": shas[sha],
                            "path": name + ".py", "line": 1}) for side, sha in (("before", "baseSha"), ("after", "headSha"))}
                report["experiments"].append({"id": name, "domain": experiment["domain"],
                    "source_sha256": source_hashes[name], "behavior": behavior(experiment),
                    "metrics": file["metrics"], "findings": file["findings"], "contexts": contexts})
        finally:
            close(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=Path("target/codeclarity-mcp.jar"))
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("target/experiments"))
    args = parser.parse_args()
    output = (PROJECT / args.output_dir).resolve()
    if not output.is_relative_to(PROJECT):
        parser.error("Output directory must stay inside the project.")
    if args.java_home:
        os.environ["PATH"] = str(args.java_home.resolve() / "bin") + os.pathsep + os.environ.get("PATH", "")
    report = {"schema": "codeclarity/python-experiments/v1", "success": False,
              "started_utc": datetime.now(timezone.utc).isoformat(), "experiments": []}
    try:
        execute(args, report)
        report["success"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    output.mkdir(parents=True, exist_ok=True)
    (output / "run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(summary(report), encoding="utf-8")
    print(f"{'Passed' if report['success'] else 'Failed'}: experimental report in {output}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
