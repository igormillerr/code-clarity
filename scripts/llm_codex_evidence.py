"""Verify completed Codex JSONL evidence, not a model-authored execution claim."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from llm_evals import check_report

LANGUAGE_TOOLS = {
    "java": ("list_java_changes", "analyze_java_changes"),
    "python": ("list_python_changes", "analyze_python_changes"),
}


def language_errors(languages, scope, calls):
    """Compare the requested scope with actual tool invocations, not model prose."""
    errors = []
    reported = scope.get("languages")
    if (not isinstance(reported, list) or not all(isinstance(item, str) for item in reported)
            or len(reported) != len(set(reported)) or set(reported) != set(languages)):
        errors.append("Reported scope.languages differs from the selected probe languages")
    names = {call["tool"] for call in calls}
    required = {tool for language in languages for tool in LANGUAGE_TOOLS[language]}
    if not required <= names:
        errors.append("Missing actual selected-language list/analysis calls: " + ", ".join(sorted(required - names)))
    unexpected = {tools[1] for language, tools in LANGUAGE_TOOLS.items() if language not in languages} & names
    if unexpected:
        errors.append("Analysis exceeded the selected language scope: " + ", ".join(sorted(unexpected)))
    return errors


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
    parser.add_argument("--languages", nargs="+", choices=tuple(LANGUAGE_TOOLS),
                        default=["java", "python"], help="Languages selected for this probe (default: both)")
    args = parser.parse_args()
    if len(args.languages) != len(set(args.languages)):
        parser.error("--languages must not contain duplicates")
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
    errors.extend(language_errors(args.languages, report.get("scope", {}), calls))
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
               "plugin": attempt["plugin"], "attempt": attempt, "languages": args.languages,
               "eventsSha256": hashlib.sha256(raw).hexdigest(), "rawEvents": str(run / "events.jsonl"),
               "calls": calls, "freeze": freezes, "analysisStartedEventIndices": analysis_started,
               "report": str(report_path), "markdown": str(report_path.with_suffix(".md")),
               "reportSha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
               "scope": report["scope"], "verdict": report["verdict"], "findings": report["findings"],
               "metrics": report["metrics"], "ruleDiscovery": report["ruleDiscovery"],
               "limitations": ["This verifier does not establish Core history persistence, feedback authorization or idempotence.",
                               "One observed live run is not proof of deterministic model behavior."]}
    if "entityMatches" in report:
        summary["entityMatches"] = report["entityMatches"]
    if report["verdict"] == "INCOMPLETE":
        summary["limitations"].append("The main review is INCOMPLETE; see its recorded skips and metric statuses.")
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
