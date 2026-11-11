"""LLM evaluation fixtures, real MCP receipts and semantic artifact checks (stdlib).

This is test tooling. It neither computes code metrics nor writes review history.
Protocol success is deliberately distinct from live Codex/Skill evaluation.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
import unittest

PROJECT = Path(__file__).resolve().parents[1]
EVALS = PROJECT / "evals"
METRICS = {"cyclomatic_complexity", "cognitive_complexity", "function_sloc",
           "max_nesting_depth", "parameter_count", "return_count"}
LANGUAGE_TOOLS = {"java": ("list_java_changes", "analyze_java_changes"),
                  "python": ("list_python_changes", "analyze_python_changes")}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scenarios():
    return {case["id"]: case for case in read_json(EVALS / "scenarios.json")["scenarios"]}


def git(repo, *arguments):
    environment = dict(os.environ, GIT_AUTHOR_DATE="2026-11-11T12:00:00+00:00",
                       GIT_COMMITTER_DATE="2026-11-11T12:00:00+00:00", GIT_TERMINAL_PROMPT="0")
    completed = subprocess.run(["git", "-C", str(repo), *arguments], check=True,
                               capture_output=True, text=True, encoding="utf-8", env=environment)
    return completed.stdout.strip()


def prepare(case, output):
    """Create a new disposable repository, never overwrite or delete an existing one."""
    if case["kind"] != "code-review":
        raise ValueError("History scenarios are JSON fixtures, not Git repositories.")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Fixture output must be a new or empty directory.")
    repo = output / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    for key, value in (("user.name", "CodeClarity synthetic evaluation"),
                       ("user.email", "eval@example.invalid"), ("commit.gpgsign", "false"),
                       ("core.autocrlf", "false"), ("core.hooksPath", str(repo / ".git" / "hooks"))):
        git(repo, "config", key, value)
    fixture = EVALS / case["fixture"]
    for side in ("before", "after"):
        for source in sorted((fixture / side).rglob("*")):
            if source.is_file():
                target = repo / source.relative_to(fixture / side)
                target.parent.mkdir(parents=True, exist_ok=True)
                # Normalize line endings so the same fixture produces the same blobs.
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        git(repo, "add", ".")
        git(repo, "commit", "-m", f"Synthetic {case['id']} {side}")
        if side == "before":
            git(repo, "switch", "-c", "review-target")
    manifest = {"schemaVersion": 1, "scenarioId": case["id"], "synthetic": True,
                "repoRoot": str(repo), "baseRef": "main", "headRef": "HEAD",
                "baseSha": git(repo, "rev-parse", "main"), "headSha": git(repo, "rev-parse", "HEAD"),
                "languages": case["languages"], "request": case["request"]}
    write_json(output / "manifest.json", manifest)
    return manifest


class McpClient:
    """Bounded newline JSON-RPC client for a real local JAR, not a mock server."""
    def __init__(self, jar, repo):
        self.events = []
        self.counter = 0
        self.inbox = Queue()
        self.process = subprocess.Popen(
            ["java", "-jar", str(Path(jar).resolve()), "--repo-root", str(repo)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=dict(os.environ, CODECLARITY_PYTHON=sys.executable))
        self.stderr = []

        def read_stdout():
            for line in self.process.stdout:
                self.inbox.put(line)
            self.inbox.put(None)

        def read_stderr():
            for line in self.process.stderr:
                if len(self.stderr) < 100:
                    self.stderr.append(line.rstrip())

        Thread(target=read_stdout, daemon=True).start()
        Thread(target=read_stderr, daemon=True).start()

    def send(self, method, params, notification=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.counter += 1
            message["id"] = self.counter
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if notification:
            return None
        while True:
            try:
                line = self.inbox.get(timeout=45)
            except Empty as error:
                raise RuntimeError(f"MCP timeout waiting for {method}") from error
            if line is None:
                raise RuntimeError("MCP closed stdout: " + "\n".join(self.stderr))
            response = json.loads(line)
            if response.get("id") == self.counter:
                if "error" in response:
                    raise RuntimeError(json.dumps(response["error"]))
                return response["result"]

    def tool(self, name, arguments):
        result = self.send("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"{name}: {result.get('content')}")
        structured = result.get("structuredContent")
        if structured is None:
            structured = json.loads(next(item["text"] for item in result["content"] if item["type"] == "text"))
        self.events.append({"event": "tool_call", "tool": name, "arguments": arguments, "result": structured})
        return structured

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def protocol(jar, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in scenarios().values():
        if case["kind"] != "code-review":
            results.append({"scenarioId": case["id"], "status": "NOT_RUN",
                            "reason": "History decision requires Skill evaluation; persistence tools are a Core dependency."})
            continue
        client = None
        record = {"scenarioId": case["id"], "executionLevel": "MCP_PROTOCOL", "status": "FAIL"}
        try:
            manifest = prepare(case, output / "fixtures" / case["id"])
            client = McpClient(jar, manifest["repoRoot"])
            hello = client.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                               "clientInfo": {"name": "codeclarity-llm-evals", "version": "1"}})
            client.send("notifications/initialized", {}, notification=True)
            catalog = client.send("tools/list", {})
            names = {tool["name"] for tool in catalog["tools"]}
            record.update(serverInfo=hello["serverInfo"], discoveredTools=sorted(names), scope=manifest)
            for language in case["languages"]:
                list_tool, analyze_tool = LANGUAGE_TOOLS[language]
                if not {list_tool, analyze_tool} <= names:
                    raise ValueError(f"Missing {language} tools")
                changes = client.tool(list_tool, {"baseRef": "main", "headRef": "HEAD"})
                report = client.tool(analyze_tool, {key: changes[key] for key in ("baseSha", "headSha")})
                if report["baseSha"] != manifest["baseSha"] or report["headSha"] != manifest["headSha"]:
                    raise ValueError("MCP snapshots differ from the prepared committed fixture")
                if case["id"] == "partial-analysis":
                    if report["status"] != "partial" or not any("broken.py" in warning for warning in report["warnings"]):
                        raise ValueError("Invalid file was not reported as partial")
                    if not any(file.get("newPath") == "valid.py" and file.get("metrics") for file in report["files"]):
                        raise ValueError("Valid file results disappeared after another file failed")
                elif report["status"] != "ok":
                    raise ValueError(f"Unexpected static analysis status: {report['status']}")
                if not report["files"]:
                    raise ValueError("Fixture changes were not analyzed")
                for file in report["files"]:
                    for metric in file.get("metrics", []):
                        for side in ("before", "after"):
                            value = metric[side]
                            if value["status"] != "AVAILABLE" and value.get("value") is not None:
                                raise ValueError("Unavailable metric was replaced with a number")
            record["status"] = "PASS"
            record["note"] = "Real MCP transport/static analysis only. No claim of Codex, independent review or complete MVP."
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            record["error"] = str(error)
        finally:
            if client is not None:
                client.close()
                record["events"] = client.events
                if client.stderr:
                    record["stderr"] = client.stderr
        write_json(output / f"{case['id']}.json", record)
        results.append({key: value for key, value in record.items() if key not in {"events", "stderr", "scope"}})
    summary = {"schemaVersion": 1, "executionLevel": "MCP_PROTOCOL", "jar": str(Path(jar).resolve()),
               "jarSha256": hashlib.sha256(Path(jar).read_bytes()).hexdigest(),
               "codexEndToEnd": "NOT_RUN", "results": results}
    write_json(output / "summary.json", summary)
    return summary


def tool_name(event):
    return event.get("tool", "").split("__")[-1]


def check_report(report, trace, repo=None):
    """Check supplied artifacts against observed receipts; never supply missing measurements."""
    errors = []
    events = trace.get("events", []) if isinstance(trace, dict) else trace
    analysis = [(index, event) for index, event in enumerate(events)
                if event.get("event") == "tool_call" and tool_name(event) in
                {"analyze_java_changes", "analyze_python_changes", "analyze_changes"}]
    frozen = [(index, event) for index, event in enumerate(events) if event.get("event") == "independent_review_frozen"]
    no_changes = report.get("verdict") == "NO_CHANGES" and not report.get("scope", {}).get("paths")
    if not no_changes and (not frozen or not analysis or frozen[0][0] >= analysis[0][0]):
        errors.append("Independent findings were not frozen before the first metric analysis call.")
    if len(frozen) > 1:
        errors.append("Independent review has multiple freeze events; preserve one initial artifact.")
    independent = report.get("independentReview", {})
    if frozen and "findings" in frozen[0][1] and frozen[0][1]["findings"] != independent.get("findings"):
        errors.append("Independent findings differ from the frozen artifact.")
    if frozen and frozen[0][1].get("artifact"):
        try:
            artifact_path = Path(frozen[0][1]["artifact"])
            payload = artifact_path.read_bytes()
            if frozen[0][1].get("sha256") != hashlib.sha256(payload).hexdigest():
                errors.append("Frozen independent artifact hash no longer matches.")
            if json.loads(payload)["findings"] != independent.get("findings"):
                errors.append("Independent findings differ from the frozen artifact file.")
        except (OSError, KeyError, ValueError) as error:
            errors.append(f"Frozen independent artifact could not be verified: {error}")
    scope = report.get("scope", {})
    observed = {}
    mandatory_missing = False
    for _, event in analysis:
        result = event.get("result", {})
        if result.get("baseSha") != scope.get("baseSha") or result.get("headSha") != scope.get("headSha"):
            errors.append("Reported snapshots do not match the MCP analysis receipt.")
        if result.get("status") == "partial":
            mandatory_missing = True
        for file in result.get("files", []):
            path = file.get("newPath") or file.get("oldPath")
            for measurement in file.get("metrics", []):
                observed[(path, measurement["entity"], measurement["metric"])] = measurement
            for entity in file.get("changedMethods", []):
                available_ids = {m["metric"] for m in file.get("metrics", []) if m["entity"] == entity}
                if not METRICS <= available_ids:
                    mandatory_missing = True
    reported = {}
    for metric in report.get("metrics", []):
        key = (metric.get("path"), metric.get("entity"), metric.get("metric"))
        if key in reported:
            errors.append(f"Duplicate metric row: {key}")
        reported[key] = metric
        receipt = observed.get(key)
        if receipt:
            for field in ("status", "before", "after", "delta"):
                if metric.get(field) != receipt.get(field):
                    errors.append(f"Metric {key} field {field} differs from its MCP receipt.")
        else:
            if metric.get("delta") is not None or any(metric.get(side, {}).get("value") is not None for side in ("before", "after")):
                errors.append(f"Unobserved numeric measurement: {key}")
        for side in ("before", "after"):
            value = metric.get(side) or {}
            if value.get("status") != "AVAILABLE" and value.get("value") is not None:
                errors.append(f"Unavailable metric has a numeric value: {key}/{side}")
            if value.get("status") not in {"AVAILABLE", "ENTITY_ABSENT"}:
                mandatory_missing = True
    for key in observed:
        if key not in reported:
            errors.append(f"MCP measurement omitted from report: {key}")
    expected_entities = {(path, entity) for path, entity, _ in observed}
    for path, entity in expected_entities:
        if not METRICS <= {metric_id for row_path, row_entity, metric_id in reported if (row_path, row_entity) == (path, entity)}:
            if not any(skip.get("stage") in {"metrics", "measurements"} and skip.get("path", path) == path and skip.get("reason")
                       for skip in report.get("skips", [])):
                errors.append(f"Missing metrics need an explicit metrics-stage skip for {path}/{entity}.")
            mandatory_missing = True
    coverage = report.get("coverage", {})
    for expected, actual in (("filesExpected", "filesAnalyzed"), ("entitiesExpected", "entitiesAnalyzed")):
        if coverage.get(actual) is None or coverage.get(expected) is None or coverage[actual] < coverage[expected]:
            mandatory_missing = True
    if independent.get("status") != "COMPLETE":
        mandatory_missing = True
    independent_coverage = independent.get("coverage", {})
    for expected, actual in (("filesExpected", "filesReviewed"), ("entitiesExpected", "entitiesReviewed")):
        if expected in independent_coverage and (independent_coverage.get(actual) is None
                or independent_coverage.get(expected) is None
                or independent_coverage[actual] < independent_coverage[expected]):
            mandatory_missing = True
    if mandatory_missing and report.get("verdict") != "INCOMPLETE":
        errors.append("Missing mandatory code review/metrics or partial analysis requires INCOMPLETE.")
    ids = set()
    for finding in report.get("findings", []):
        finding_id = finding.get("findingId")
        if not finding_id or finding_id in ids:
            errors.append("Findings must have unique non-empty findingId values.")
        ids.add(finding_id)
        location = finding.get("location", {})
        if not finding.get("evidence") or not finding.get("recommendation") or not finding.get("description"):
            errors.append(f"Finding {finding_id} lacks evidence, description or recommendation.")
        if finding.get("snapshotId") not in {scope.get("baseSha"), scope.get("headSha"), scope.get("snapshotId")}:
            errors.append(f"Finding {finding_id} references an unrelated snapshot.")
        start, end = location.get("startLine", 0), location.get("endLine", 0)
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            errors.append(f"Finding {finding_id} has an invalid line range.")
        elif repo:
            try:
                snapshot = finding["snapshotId"]
                if snapshot not in {scope.get("baseSha"), scope.get("headSha")}:
                    raise ValueError("Cannot verify a non-commit snapshot with this Git fixture checker")
                source = git(repo, "show", f"{snapshot}:{location['path']}")
                if end > len(source.splitlines()):
                    raise ValueError("Range exceeds committed source")
            except (KeyError, ValueError, subprocess.SubprocessError) as error:
                errors.append(f"Finding {finding_id} location could not be verified: {error}")
    retained = ids | {origin for finding in report.get("findings", []) for origin in finding.get("originFindingIds", [])}
    if any(finding.get("findingId") not in retained for finding in independent.get("findings", [])):
        errors.append("A frozen independent finding was dropped without a retained originFindingIds link.")
    return errors


def check_case(case, result, trace=None, repo=None):
    errors = []
    if case["kind"] == "code-review":
        errors.extend(check_report(result, trace or [], repo))
        expected = case["expected"]
        ai_findings = [finding for finding in result.get("findings", []) if finding.get("source") == "AI_REVIEW"]
        if len(ai_findings) < expected.get("minimumFindings", 0):
            errors.append("The labelled readability issue was not found.")
        if len(ai_findings) > expected.get("maximumAiFindings", float("inf")):
            errors.append("The good-code fixture received an unexpected AI finding; inspect for a false positive.")
        if "requiredVerdict" in expected and result.get("verdict") != expected["requiredVerdict"]:
            errors.append("Scenario verdict differs from the required verdict.")
        for path in expected.get("requiredSkipPaths", []):
            if not any(skip.get("path") == path for skip in result.get("skips", [])):
                errors.append(f"Missing explicit skip for {path}.")
    else:
        decision = result
        expected = case["expected"]
        if result.get("executionLevel") != "SYNTHETIC_SKILL_EVAL" or result.get("synthetic") is not True:
            errors.append("Offline history assessment must explicitly identify SYNTHETIC_SKILL_EVAL and synthetic=true.")
        if "ruleDiscovery" in result or "status" in result:
            errors.append("Synthetic assessment uses decision, never a production ruleDiscovery.status or status.")
        if result.get("persisted") or result.get("saved") or result.get("activated") or result.get("persistence") not in (None, False, "NOT_ATTEMPTED"):
            errors.append("Offline assessment must not claim a rule was persisted or activated.")
        if result.get("userFacingMessage") != "":
            errors.append("Synthetic assessment must have an empty userFacingMessage.")
        if decision.get("decision") != expected["decision"]:
            errors.append("Rule Discovery outcome differs from the labelled history scenario.")
        if expected["decision"] == "NO_SUGGESTION":
            if decision.get("candidate"):
                errors.append("NO_SUGGESTION must not include a rule candidate.")
            if result.get("userFacingMessage", ""):
                errors.append("NO_SUGGESTION must be silent in user-facing output.")
        else:
            candidate = decision.get("candidate") or {}
            if candidate.get("status") != "PROPOSED" or candidate.get("categoryId") != expected["categoryId"] or candidate.get("synthetic") is not True:
                errors.append("Candidate must remain PROPOSED and synthetic, and reuse opaque_names.")
            for field in ("examples", "exceptions", "supportingFindingIds", "confirmedFeedbackIds"):
                if not candidate.get(field):
                    errors.append(f"Candidate lacks {field}.")
            history = read_json(EVALS / case["history"])
            by_id = {finding["findingId"]: finding for finding in history["findings"]}
            support = candidate.get("supportingFindingIds", [])
            if len(set(support)) < 3 or any(finding_id not in by_id for finding_id in support):
                errors.append("Candidate must cite at least three distinct fixture findings.")
            confirmed = {feedback["feedbackId"]: feedback for feedback in history["feedback"]
                         if feedback.get("decision") == "FIXED" and feedback.get("confirmationEvidence")}
            cited = candidate.get("confirmedFeedbackIds", [])
            if len(set(cited)) < 2 or any(feedback_id not in confirmed for feedback_id in cited):
                errors.append("Candidate must cite at least two externally confirmed fixture fixes.")
            elif len({confirmed[feedback_id]["findingId"] for feedback_id in cited}) < 2:
                errors.append("Two feedback events for one finding are not two confirmed fixes.")
    return errors


class CheckerTests(unittest.TestCase):
    def setUp(self):
        definition = {"id": "cyclomatic_complexity", "language": "python", "analyzer": "test/1", "algorithm": "test/1"}
        metric = {"entity": "total(x)", "metric": "cyclomatic_complexity", "status": "COMPARED",
                  "before": {"definition": definition, "status": "AVAILABLE", "value": 1, "reason": None},
                  "after": {"definition": definition, "status": "AVAILABLE", "value": 1, "reason": None}, "delta": 0}
        self.receipt = {"baseSha": "a" * 40, "headSha": "b" * 40, "status": "ok",
                        "files": [{"oldPath": "total.py", "newPath": "total.py", "changedMethods": ["total(x)"], "metrics": [metric]}]}
        self.trace = [{"event": "independent_review_frozen", "findings": []},
                      {"event": "tool_call", "tool": "analyze_python_changes", "result": self.receipt}]
        rows = [{"path": "total.py", **copy.deepcopy(metric)}]
        for metric_id in METRICS - {"cyclomatic_complexity"}:
            rows.append({"path": "total.py", "entity": "total(x)", "metric": metric_id, "status": "UNAVAILABLE",
                         "before": {"status": "MISSING", "reason": "Not returned by analyzer"},
                         "after": {"status": "MISSING", "reason": "Not returned by analyzer"}, "delta": None})
        self.report = {"scope": {"baseSha": "a" * 40, "headSha": "b" * 40, "snapshotId": "b" * 40},
                       "independentReview": {"status": "COMPLETE", "findings": []}, "metrics": rows,
                       "findings": [], "coverage": {"filesExpected": 1, "filesAnalyzed": 1}, "verdict": "INCOMPLETE"}

    def test_honest_incomplete_receipts_pass(self):
        self.assertEqual([], check_report(self.report, self.trace))

    def test_fabricated_value_is_rejected(self):
        self.report["metrics"][0]["after"]["value"] = 99
        self.assertTrue(any("differs" in error for error in check_report(self.report, self.trace)))

    def test_metrics_before_independent_is_rejected(self):
        self.assertTrue(any("frozen" in error for error in check_report(self.report, list(reversed(self.trace)))))

    def test_false_pass_is_rejected(self):
        self.report["verdict"] = "PASS"
        self.assertTrue(any("INCOMPLETE" in error for error in check_report(self.report, self.trace)))

    def test_metric_omission_is_rejected(self):
        self.report["metrics"].pop(0)
        self.assertTrue(any("omitted" in error for error in check_report(self.report, self.trace)))

    def test_pending_history_is_silent(self):
        case = scenarios()["history-insufficient"]
        result = {"executionLevel": "SYNTHETIC_SKILL_EVAL", "synthetic": True, "decision": "NO_SUGGESTION", "userFacingMessage": ""}
        self.assertEqual([], check_case(case, result))
        result["userFacingMessage"] = "No new rules today"
        self.assertTrue(check_case(case, result))

    def test_nullable_coverage_is_incomplete(self):
        self.report["coverage"].update(entitiesExpected=None, entitiesAnalyzed=None)
        self.assertEqual([], check_report(self.report, self.trace))
        self.report["verdict"] = "PASS"
        self.assertTrue(any("INCOMPLETE" in error for error in check_report(self.report, self.trace)))

    def test_omitted_unimplemented_metrics_require_skip(self):
        self.report["metrics"] = self.report["metrics"][:1]
        self.assertTrue(any("explicit" in error for error in check_report(self.report, self.trace)))
        self.report["skips"] = [{"stage": "metrics", "path": "total.py", "reason": "Analyzer does not provide the remaining five metrics."}]
        self.assertEqual([], check_report(self.report, self.trace))

    def test_measurements_stage_alias_preserves_valid_missing_data_report(self):
        self.report["metrics"] = self.report["metrics"][:1]
        self.report["skips"] = [{"stage": "measurements", "path": "total.py", "entity": "total(x)",
                                 "metric": "function_sloc", "reason": "Analyzer omitted this required measurement."}]
        self.assertEqual([], check_report(self.report, self.trace))
        self.report["skips"][0]["stage"] = "history"
        self.assertTrue(any("explicit" in error for error in check_report(self.report, self.trace)))

    def test_rule_candidate_cannot_invent_confirmations(self):
        case = scenarios()["history-sufficient"]
        candidate = {"status": "PROPOSED", "synthetic": True, "categoryId": "opaque_names", "examples": [{"findingId": "demo-finding-1"}],
                     "exceptions": ["Conventional loop indices with unambiguous local meaning."],
                     "supportingFindingIds": ["demo-finding-1", "demo-finding-2", "demo-finding-3"],
                     "confirmedFeedbackIds": ["demo-feedback-1", "demo-feedback-2"]}
        result = {"executionLevel": "SYNTHETIC_SKILL_EVAL", "synthetic": True, "decision": "RULE_SUGGESTED", "candidate": candidate, "userFacingMessage": ""}
        self.assertEqual([], check_case(case, result))
        candidate["confirmedFeedbackIds"] = ["demo-feedback-1", "invented-feedback"]
        self.assertTrue(check_case(case, result))

    def test_synthetic_assessment_cannot_claim_persistence(self):
        result = {"executionLevel": "SYNTHETIC_SKILL_EVAL", "synthetic": True, "decision": "NO_SUGGESTION", "userFacingMessage": "", "saved": True}
        self.assertTrue(check_case(scenarios()["history-insufficient"], result))
        self.assertTrue(check_case(scenarios()["history-insufficient"], {"status": "NO_SUGGESTION"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare", help="Create an empty-directory Git fixture")
    create.add_argument("--scenario", required=True, choices=scenarios())
    create.add_argument("--output", required=True, type=Path)
    run = commands.add_parser("protocol", help="Run four source fixtures against the real JAR; not a model eval")
    run.add_argument("--jar", type=Path, default=PROJECT / "plugin/server/codeclarity-mcp.jar")
    run.add_argument("--output", required=True, type=Path)
    check = commands.add_parser("check", help="Check a real agent report against recorded MCP receipts")
    check.add_argument("--scenario", required=True, choices=scenarios())
    check.add_argument("--report", required=True, type=Path)
    check.add_argument("--trace", type=Path)
    check.add_argument("--repo", type=Path)
    check.add_argument("--output", type=Path)
    commands.add_parser("self-test", help="Test evaluator safeguards with explicitly synthetic unit artifacts")
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(scenarios()[args.scenario], args.output), ensure_ascii=False, indent=2))
    elif args.command == "protocol":
        summary = protocol(args.jar, args.output)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return int(any(result["status"] == "FAIL" for result in summary["results"]))
    elif args.command == "check":
        case = scenarios()[args.scenario]
        if case["kind"] == "code-review" and args.trace is None:
            parser.error("code-review artifact checks require --trace with actual MCP receipts")
        errors = check_case(case, read_json(args.report), read_json(args.trace) if args.trace else None, args.repo)
        result = {"scenarioId": args.scenario, "executionLevel": "ARTIFACT_CHECK", "status": "FAIL" if errors else "PASS",
                  "errors": errors, "note": "Checks supplied artifacts, not independent proof that Codex generated them."}
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(bool(errors))
    else:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CheckerTests))
        return int(not result.wasSuccessful())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exception:
        print(f"llm_evals: {exception}", file=sys.stderr)
        sys.exit(2)
