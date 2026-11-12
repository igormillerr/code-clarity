"""Run a fresh Codex agent with the repository Skill and real Java MCP; verify raw receipts.

Uses existing CLI authentication/default model. Configuration overrides apply only
to this invocation; no plugin installation or home repo-root.txt changes are made.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from llm_evals import METRICS, check_report, git, prepare, write_json
from llm_codex_evidence import objects
from python_smoke_test import connect, close

PROJECT = Path(__file__).resolve().parents[1]


def discovery_errors(rules, record, review_id, discovery_path):
    """Compare the decision payload separately from its report-side artifact link."""
    errors = []
    if record.get("reviewId", review_id) != review_id or any(
            record.get(key) != value for key, value in rules.items() if key != "artifact"):
        errors.append("Final discovery status differs from the separate artifact")
    if "artifact" in rules:
        link = rules["artifact"]
        if not isinstance(link, str) or not link:
            errors.append("Invalid discovery artifact link")
        else:
            linked_path = Path(link)
            if not linked_path.is_absolute():
                linked_path = discovery_path.parent / linked_path
            if linked_path.resolve() != discovery_path.resolve():
                errors.append("Final discovery artifact link points to a different file")
    return errors


def verify(output):
    attempt = json.loads((output / "attempt.json").read_text(encoding="utf-8"))
    raw = (output / "events.jsonl").read_bytes()
    events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    errors, trace, calls, freezes, starts = [], [], [], [], []
    for index, event in enumerate(events):
        item = event.get("item", {})
        if item.get("type") == "mcp_tool_call" and item.get("server") == "codeclarity":
            if event["type"] == "item.started" and item["tool"].startswith("analyze_"):
                starts.append(index)
            if event["type"] == "item.completed":
                if item.get("error") or item.get("status") != "completed":
                    errors.append("MCP call failed: " + item["tool"])
                    continue
                result = item.get("result") or {}
                if result.get("isError", result.get("is_error", False)):
                    errors.append("MCP tool returned an error: " + item["tool"])
                    continue
                structured = result.get("structuredContent", result.get("structured_content"))
                if structured is None:
                    structured = json.loads(next(c["text"] for c in result["content"] if c["type"] == "text"))
                receipt = {"event": "tool_call", "tool": item["tool"], "arguments": item["arguments"], "result": structured}
                trace.append(receipt)
                calls.append({"eventIndex": index, **receipt})
        if event["type"] == "item.completed" and item.get("type") == "command_execution":
            for line in item.get("aggregated_output", "").splitlines():
                try:
                    document = json.loads(line)
                except ValueError:
                    continue
                for candidate in objects(document):
                    if candidate.get("event") == "independent_review_frozen":
                        trace.append(candidate)
                        freezes.append({"eventIndex": index, **candidate})

    reports = list((output / "artifacts").rglob("report.final.json"))
    if len(reports) != 1:
        errors.append("Expected exactly one agent-generated report.final.json")
    if attempt.get("status") != "COMPLETED" or not any(e["type"] == "turn.completed" for e in events):
        errors.append("Agent run did not finish successfully")
    if len(freezes) != 1 or not starts or freezes[0]["eventIndex"] >= min(starts):
        errors.append("Raw events do not prove freeze before the first analysis invocation")
    tools = {c["tool"] for c in calls}
    for language in attempt.get("languages", ["java"]):
        if not tools.intersection({"get_changes", "list_" + language + "_changes"}) or not tools.intersection({"analyze_changes", "analyze_" + language + "_changes"}):
            errors.append("Missing real discovery/analysis MCP calls for " + language)
    observed = {}
    measured_languages = set()
    for call in calls:
        if not call["tool"].startswith("analyze_"):
            continue
        if call["result"].get("status") != "ok":
            errors.append("Java fixture analysis was not complete")
        for file in call["result"].get("files", []):
            measured_languages.add(file["language"])
            path = file.get("newPath") or file.get("oldPath")
            for entity in file["changedMethods"]:
                values = {m["metric"]: m for m in file["metrics"] if m["entity"] == entity}
                if set(values) != METRICS:
                    errors.append(f"MCP did not return six metric IDs for {path}/{entity}")
                for metric in values.values():
                    if metric["status"] != "COMPARED" or any(metric[side]["status"] != "AVAILABLE" for side in ("before", "after")):
                        errors.append(f"Expected comparable numerical Java values: {path}/{entity}/{metric['metric']}")
                observed[(path, entity)] = values
    expected_entities = 2 * len(attempt.get("languages", ["java"]))
    if len(observed) != expected_entities:
        errors.append("Expected actual MCP coverage of all selected-language fixture entities")
    if measured_languages != set(attempt.get("languages", ["java"])):
        errors.append("Actual measured languages differ from the requested scope")
    if report_languages := attempt.get("languages"):
        if reports and set(json.loads(reports[0].read_text(encoding="utf-8"))["scope"]["languages"]) != set(report_languages):
            errors.append("Report language scope differs from the selected integration languages")

    report = None
    schema_validation = "NOT_RUN"
    if reports:
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        errors.extend(check_report(report, trace, Path(attempt["repo"])))
        if report.get("verdict") not in {"PASS", "WARN"}:
            errors.append("Complete Java review incorrectly failed to produce PASS/WARN")
        spec = importlib.util.spec_from_file_location("review_artifacts", PROJECT / "plugin/scripts/review_artifacts.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        if freezes:
            try:
                helper.validate(report, helper.load(freezes[0]["artifact"]))
            except (ValueError, KeyError, TypeError) as error:
                errors.append("Artifact validation: " + str(error))
        main_path = reports[0].with_name("report.main.json")
        discovery_path = reports[0].with_name("discovery.json")
        if not main_path.exists() or not discovery_path.exists():
            errors.append("Missing retained main report or separate discovery artifact")
        else:
            main_report = json.loads(main_path.read_text(encoding="utf-8"))
            if main_report["ruleDiscovery"].get("status") != "NOT_RUN":
                errors.append("Pre-discovery main report was overwritten")
            if {k: v for k, v in main_report.items() if k not in {"ruleDiscovery", "skips"}} != {
                    k: v for k, v in report.items() if k not in {"ruleDiscovery", "skips"}}:
                errors.append("Final report changed measured/review results after discovery")
            if any(skip not in report["skips"] for skip in main_report["skips"]) or any(
                    skip not in main_report["skips"] and skip.get("stage") != "rule-discovery"
                    for skip in report["skips"]):
                errors.append("Discovery changed primary review omissions")
            discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
            errors.extend(discovery_errors(report["ruleDiscovery"], discovery, report["reviewId"], discovery_path))
            main_markdown = main_path.with_suffix(".md")
            if not main_markdown.exists() or main_markdown.read_text(encoding="utf-8") != helper.render(main_report):
                errors.append("Retained main Markdown does not match its report")
        markdown = reports[0].with_suffix(".md")
        if not markdown.exists():
            errors.append("Agent did not produce final Markdown")
        elif markdown.read_text(encoding="utf-8") != helper.render(report):
            errors.append("Final Markdown differs from the validated report rendering")
        # The MCP JAR already bundles a full Draft 2020-12 validator. No extra Python packages required.
        with TemporaryDirectory(prefix="codeclarity-schema-") as directory:
            source = Path(directory) / "ReviewSchemaCheck.java"
            source.write_text('''
import java.nio.file.Files;
import java.nio.file.Path;
import com.networknt.schema.InputFormat;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;
class ReviewSchemaCheck {
    public static void main(String[] args) throws Exception {
        var schema = SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12)
                .getSchema(Files.readString(Path.of(args[0])), InputFormat.JSON);
        var errors = schema.validate(Files.readString(Path.of(args[1])), InputFormat.JSON);
        if (!errors.isEmpty()) { throw new IllegalArgumentException(errors.toString()); }
        System.out.println("Draft 2020-12 review schema: valid");
    }
}
''', encoding="utf-8")
            checked = subprocess.run(["java", "--class-path", attempt["jar"], str(source),
                                      str(PROJECT / "plugin/contracts/review.schema.json"), str(reports[0])],
                                     capture_output=True, text=True, encoding="utf-8", check=False)
            (output / "schema-validation.log").write_text(checked.stdout + checked.stderr, encoding="utf-8")
            schema_validation = "PASS" if checked.returncode == 0 else "FAIL"
            if checked.returncode:
                errors.append("Full JSON Schema validation failed; see schema-validation.log")
    if git(Path(attempt["repo"]), "status", "--porcelain"):
        errors.append("Input fixture was modified")
    for name in ("skill", "jar"):
        if hashlib.sha256(Path(attempt[name]).read_bytes()).hexdigest() != attempt[name + "Sha256"]:
            errors.append("Tested " + name + " changed since the agent invocation")
    history_proof = None
    if attempt.get("withHistory"):
        writes = [call for call in calls if call["tool"] == "update_review_history" and "review" in call["arguments"]]
        if not writes or "get_review_history" not in tools:
            errors.append("Agent did not read and save history through native MCP tools")
        elif report:
            payload = writes[0]["arguments"]
            history_path = Path(attempt["repo"]) / ".codeclarity/review-history.json"
            try:
                original = history_path.read_bytes()
                stamp = history_path.stat().st_mtime_ns
                # Each connect starts a new JVM: verify persistence independently of the agent process.
                process, client = connect(Path(attempt["jar"]), Path(attempt["repo"]))
                try:
                    restored = client.tool("get_review_history", {})
                    replay = client.tool("update_review_history", payload)
                    after_replay = client.tool("get_review_history", {})
                finally:
                    close(process)
                process, client = connect(Path(attempt["jar"]), Path(attempt["repo"]))
                try:
                    second_restart = client.tool("get_review_history", {})
                finally:
                    close(process)
                assert restored == json.loads(original) == after_replay == second_restart, "History changed across restart/replay"
                assert restored["reviews"] == [payload["review"]], "Stored review differs from agent's MCP payload"
                assert payload["review"]["reviewId"] == report["reviewId"]
                assert payload["review"]["ruleDiscovery"]["status"] == "NOT_RUN"
                assert replay["status"] == "unchanged" and replay["revision"] == restored["revision"]
                assert history_path.read_bytes() == original and history_path.stat().st_mtime_ns == stamp
                assert restored["statistics"]["reviewCount"] == 1
                assert restored["statistics"]["occurrenceCount"] == len(report["findings"])
                assert restored["statistics"]["fixedCount"] == 0 and not restored["feedback"]
                assert all(f["status"] == "DETECTED" for f in restored["findings"])
                history_proof = {"status": "PASS", "path": str(history_path), "revision": restored["revision"],
                                 "statistics": restored["statistics"], "replay": replay,
                                 "restartReads": 2, "bytesAndMtimeUnchangedOnReplay": True,
                                 "sha256": hashlib.sha256(original).hexdigest()}
            except (AssertionError, OSError, ValueError, KeyError) as error:
                errors.append("History E2E: " + str(error))
    if attempt.get("navigationConfiguration"):
        for name, target in (("get_symbol_definition", "Totals.java"), ("find_symbol_references", "Usage.java")):
            receipts = [c["result"] for c in calls if c["tool"] == name]
            if not any(r.get("scope") == "WORKTREE" and r.get("status") == "ok" and
                       any(loc.get("path") == target for loc in r.get("locations", [])) for r in receipts):
                errors.append("Missing successful real JDT LS navigation receipt: " + name)
    summary = {"schemaVersion": 1, "executionLevel": "CODEX_CLI_WITH_REAL_MCP",
               "status": "FAIL" if errors else "PASS", "errors": errors,
               "attempt": attempt, "eventsSha256": hashlib.sha256(raw).hexdigest(),
               "rawEvents": str(output / "events.jsonl"), "calls": calls, "freeze": freezes,
               "analysisStartedEventIndices": starts, "entitiesMeasured": len(observed),
               "metricComparisons": sum(len(v) for v in observed.values()),
               "report": str(reports[0]) if reports else None,
               "reportSha256": hashlib.sha256(reports[0].read_bytes()).hexdigest() if reports else None,
               "schemaValidation": schema_validation,
               "coverage": report.get("coverage") if report else None,
               "findingsCount": len(report.get("findings", [])) if report else None,
               "verdict": report.get("verdict") if report else None,
               "history": history_proof,
               "limitations": ["Tests repository Skill and JAR via process-local MCP configuration; does not verify installed plugin cache.",
                               "Disposable synthetic source repository; its history is not the user's production history.",
                               "One agent run does not guarantee deterministic future behavior."]}
    write_json(output / "evidence.json", summary)
    print(json.dumps({k: summary[k] for k in ("status", "errors", "entitiesMeasured", "metricComparisons", "verdict", "report")}, indent=2))
    return not errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--with-history", action="store_true", help="Authorize native MCP history writes in the disposable fixture and verify restart/replay")
    parser.add_argument("--languages", nargs="+", choices=("java", "python"), default=["java"],
                        help="Review Java, Python, or both with the repository Skills and explicit MCP server")
    parser.add_argument("--jdtls-home", type=Path, help="Also require actual agent definition/references calls with this JDT LS distribution")
    parser.add_argument("--jdtls-java", default="java")
    args = parser.parse_args()
    if len(args.languages) != len(set(args.languages)):
        parser.error("--languages must not contain duplicates")
    if args.jdtls_home and "java" not in args.languages:
        parser.error("--jdtls-home requires java in --languages")
    output = args.output.resolve()
    if args.verify_only:
        return int(not verify(output))
    if not args.codex:
        parser.error("Codex CLI is required; pass --codex with its executable path")
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be new or empty; previous evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="codeclarity-java-fixture-") as staging:
        fixtures = []
        if "java" in args.languages:
            fixtures += [("good-code", "Totals.java"), ("java-complexity", "Eligibility.java")]
        if "python" in args.languages:
            fixtures += [("good-code", "totals.py"), ("python-naming", "invoice_totals.py")]
        for case, name in fixtures:
            for side in ("before", "after"):
                target = Path(staging) / side / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT / "evals/fixtures" / case / side / name, target)
        for side in ("before", "after"):
            (Path(staging) / side / ".gitignore").write_text("/.codeclarity/\n")
            if args.jdtls_home:
                (Path(staging) / side / "Usage.java").write_text(
                    "final class Usage {\n    static long price(long quantity, long cents) {\n"
                    "        return Totals.lineTotal(quantity, cents);\n    }\n}\n")
        manifest = prepare({"id": "java-six-metrics-skill", "kind": "code-review", "fixture": staging,
                            "languages": args.languages, "request": "Review committed changes main..HEAD using readability-review."},
                           output / "fixture")
    repo = Path(manifest["repoRoot"])
    artifacts = output / "artifacts"
    artifacts.mkdir()
    skill = PROJECT / "plugin/skills/readability-review/SKILL.md"
    jar = PROJECT / "plugin/server/codeclarity-mcp.jar"
    prompt = (
        f"Use the readability-review Skill at {skill} to review committed {', '.join(args.languages)} changes main..HEAD in {repo}. "
        f"Read that Skill and its supporting stage Skills when applicable. Save the review artifacts in {artifacts}. "
        "Use the real codeclarity MCP tools exposed to this session; do not emulate MCP with shell clients. "
        "Read source from the resolved Git commits, preserve the independent review before requesting measured results, "
        "and follow the Skill's report validation/rendering workflow. All source files here are synthetic test inputs. "
        "Do not spawn subagents or create chats; perform the logical stages in this one context. "
        "Use the explicitly configured codeclarity MCP server for this invocation. "
        f"The harness records this session's native events at {output / 'events.jsonl'}. "
        "After making a tool call, you may parse your OWN completed native event result to save the raw response "
        "instead of transcribing it. Extract structuredContent/structured_content, or parse the JSON text content. "
        "Do not read other runs or evaluator expectations. Numeric responses must still follow the independent freeze. "
        "Do not edit input source/configuration, install anything, or read evaluator "
        "scripts/expected answers. If MCP is unavailable, report the blocker honestly. Return artifact paths and the review verdict."
    )
    if args.with_history:
        prompt += (" Run the Rule Discovery stage with real get_review_history/update_review_history calls: "
                   "history writes through MCP are authorized ONLY in this disposable test repository. "
                   "Retain the stable pre-discovery payload and read back history as the Skill instructs. "
                   "Do not record human feedback or confirm any finding as FIXED.")
    else:
        prompt += " Do not write history."
    navigation = None
    if args.jdtls_home:
        navigation = {"CODECLARITY_JDTLS_HOME": str(args.jdtls_home.resolve()), "CODECLARITY_JDTLS_JAVA": args.jdtls_java}
        prompt += (" Also exercise get_symbol_definition on the Totals.lineTotal call in Usage.java and "
                   "find_symbol_references on its declaration. First verify the worktree matches the head snapshot; "
                   "keep WORKTREE navigation evidence distinct from committed source evidence. "
                   "Save the navigation receipts with the review artifacts.")
    (output / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    server = '{codeclarity={command="java",args=' + json.dumps(["-jar", str(jar), "--repo-root", str(repo)])
    server_environment = {"CODECLARITY_PYTHON": sys.executable, **(navigation or {})}
    server += ',env={' + ','.join(key + '=' + json.dumps(value) for key, value in server_environment.items()) + '}'
    if args.with_history:
        # This explicit opt-in authorizes only append/update in the newly created
        # disposable repository. Other tools retain the user's approval policy.
        server += ',tools={update_review_history={approval_mode="approve"}}'
    server += '}}'
    command = [args.codex, "--no-daemon", "exec", "--ephemeral", "--json", "--disable", "multi_agent", "--sandbox", "workspace-write",
               "-C", str(repo), "--add-dir", str(artifacts), "-c", "mcp_servers=" + server,
               "-o", str(output / "last-message.md"), prompt]
    attempt = {"status": "FAILED", "repo": str(repo), "skill": str(skill),
               "skillSha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
               "jar": str(jar), "jarSha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
               "withHistory": args.with_history, "languages": args.languages, "navigationConfiguration": navigation,
               "historyApprovalOverride": {"tool": "update_review_history", "mode": "approve", "repository": str(repo)} if args.with_history else None,
               "command": command[:-1] + ["<see prompt.txt>"], "configuration": "process-local MCP override"}
    try:
        with (output / "events.jsonl").open("w", encoding="utf-8") as stdout, (output / "stderr.log").open("w", encoding="utf-8") as stderr:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    timeout=args.timeout, check=False,
                                    env=dict(os.environ, CODECLARITY_PYTHON=sys.executable))
        attempt.update(exitCode=result.returncode, status="COMPLETED" if result.returncode == 0 else "FAILED")
    except subprocess.TimeoutExpired:
        attempt["status"] = "TIMEOUT"
    except OSError as error:
        attempt["error"] = str(error)
    write_json(output / "attempt.json", attempt)
    return int(not verify(output))


if __name__ == "__main__":
    sys.exit(main())
