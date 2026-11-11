"""Verify completed Codex JSONL evidence, not a model-authored execution claim."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from llm_evals import check_report


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    attempt = json.loads((run / "attempt.json").read_text(encoding="utf-8"))
    raw = (run / "events.jsonl").read_bytes()
    events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    trace, calls, freezes, analysis_started, errors = [], [], [], [], []
    for index, event in enumerate(events):
        item = event.get("item", {})
        if item.get("type") == "mcp_tool_call" and item.get("server") == "codeclarity":
            if event["type"] == "item.started" and item["tool"].startswith("analyze_"):
                analysis_started.append(index)
            if event["type"] == "item.completed":
                if item.get("error") or item.get("status") != "completed":
                    errors.append("MCP call failed: " + item["tool"])
                    continue
                result = item.get("result") or {}
                structured = result.get("structured_content", result.get("structuredContent"))
                if structured is None:
                    structured = json.loads(next(block["text"] for block in result["content"] if block["type"] == "text"))
                if result.get("isError", result.get("is_error", False)):
                    errors.append("MCP returned an error: " + item["tool"])
                receipt = {"event": "tool_call", "tool": item["tool"], "arguments": item["arguments"], "result": structured}
                trace.append(receipt)
                calls.append({"eventIndex": index, "id": item["id"], "tool": item["tool"], "arguments": item["arguments"]})
        if item.get("type") == "command_execution" and event["type"] == "item.completed":
            for line in item.get("aggregated_output", "").splitlines():
                try:
                    document = json.loads(line)
                except ValueError:
                    continue
                for candidate in objects(document):
                    if candidate.get("event") == "independent_review_frozen":
                        trace.append(candidate)
                        freezes.append({"eventIndex": index, **candidate})
    reports = list(run.rglob("report.final.json")) or list(run.rglob("report.json"))
    if len(reports) != 1:
        raise ValueError("Expected exactly one final report in the completed run")
    report_path = reports[0]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if attempt["status"] != "COMPLETED" or not any(event["type"] == "turn.completed" for event in events):
        errors.append("Codex invocation did not finish successfully")
    if len(freezes) != 1 or not analysis_started or freezes[0]["eventIndex"] >= min(analysis_started):
        errors.append("Raw Codex event order does not prove freeze BEFORE analysis invocation")
    if not {"list_java_changes", "list_python_changes", "analyze_java_changes", "analyze_python_changes"} <= {call["tool"] for call in calls}:
        errors.append("Missing actual Java/Python list/analysis calls in installed plugin run")
    errors.extend(check_report(report, trace, Path(attempt["repo"])))
    project = Path(__file__).resolve().parents[1]
    specification = importlib.util.spec_from_file_location("review_artifacts", project / "plugin/scripts/review_artifacts.py")
    helper = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(helper)
    if freezes:
        frozen = helper.load(freezes[0]["artifact"])
        try:
            helper.validate(report, frozen)
        except (ValueError, KeyError, TypeError) as error:
            errors.append("Artifact validation: " + str(error))
    summary = {"schemaVersion": 1, "executionLevel": "INSTALLED_PLUGIN_CODEX_CLI",
               "status": "FAIL" if errors else "PASS", "errors": errors,
               "plugin": attempt["plugin"], "attempt": attempt,
               "eventsSha256": hashlib.sha256(raw).hexdigest(), "rawEvents": str(run / "events.jsonl"),
               "calls": calls, "freeze": freezes, "analysisStartedEventIndices": analysis_started,
               "report": str(report_path), "markdown": str(report_path.with_suffix(".md")),
               "reportSha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
               "scope": report["scope"], "verdict": report["verdict"], "findings": report["findings"],
               "metrics": report["metrics"], "ruleDiscovery": report["ruleDiscovery"],
               "limitations": ["Core history tools are absent: no persistence/feedback/idempotence E2E claim.",
                               "Current Core lacks mandatory metrics: INCOMPLETE is the correct review verdict.",
                               "One observed live run is not proof of deterministic model behavior."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "errors": errors, "calls": len(calls),
                      "verdict": report["verdict"], "output": str(args.output)}))
    return int(bool(errors))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Evidence verification failed: " + str(error), file=sys.stderr)
        sys.exit(1)
