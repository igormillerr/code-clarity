"""Freeze and render review artifacts. Never analyzes source or writes Core history.

The stdlib validator checks operational invariants, not all of JSON Schema.
Use contracts/review.schema.json for a full schema validation by an external host.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sys

METRICS = ("cyclomatic_complexity", "cognitive_complexity", "function_sloc",
           "max_nesting_depth", "parameter_count", "return_count")
STATUSES = {"AVAILABLE", "UNSUPPORTED", "MISSING", "ERROR", "ENTITY_ABSENT"}
COVERAGE_UNITS = {"SNAPSHOT_ENTITY", "MATCH_GROUP", "LEGACY_METRIC_ENTITY"}
MATCH_STATUSES = {"MATCHED", "ADDED", "REMOVED", "AMBIGUOUS", "UNVERIFIED"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda value: fail("Non-finite JSON number: " + value))


def fail(message):
    raise ValueError(message)


def require(condition, message):
    if not condition:
        fail(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def write_new(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        require(path.read_bytes() == payload, f"Refusing to replace a different artifact: {path}")


def safe_path(path):
    require(isinstance(path, str) and path and "\\" not in path and ":" not in path,
            "Expected a repository-relative POSIX path")
    parts = path.split("/")
    require(not PurePosixPath(path).is_absolute() and all(part not in ("", ".", "..") for part in parts),
            "Path must remain within repository")


def check_finding(finding, report):
    for key in ("findingId", "reviewId", "snapshotId", "categoryId", "description", "recommendation"):
        require(isinstance(finding.get(key), str) and finding[key].strip(), f"Finding missing {key}")
    require(finding["reviewId"] == report["reviewId"], "Finding reviewId mismatch")
    require(finding["snapshotId"] in (report["scope"]["baseSha"], report["scope"]["headSha"]),
            "Finding must reference a reviewed commit")
    location = finding.get("location", {})
    safe_path(location.get("path"))
    start, end = location.get("startLine"), location.get("endLine")
    require(type(start) is int and type(end) is int and 0 < start <= end, "Invalid finding line range")
    evidence = finding.get("evidence")
    require(isinstance(evidence, list) and evidence and all(isinstance(item, str) and item.strip() for item in evidence),
            "Finding needs concrete evidence")
    require(finding.get("source") in ("AI_REVIEW", "METRIC_SIGNAL"), "Invalid finding source")
    require(finding.get("metricRelation") in ("SUPPORTED", "UNRELATED", "INSUFFICIENT_DATA"), "Invalid metric relation")
    require(finding.get("reviewStatus") == "PENDING_FEEDBACK", "New review findings cannot assert human feedback")


def check_coverage(coverage, reviewed_key, entities_key):
    require(coverage.get("entityUnit") is None or coverage["entityUnit"] in COVERAGE_UNITS,
            "Invalid entity coverage unit")
    for key in ("filesExpected", reviewed_key, "entitiesExpected", entities_key):
        require((key in ("entitiesExpected", entities_key) and coverage.get(key) is None)
                or (type(coverage.get(key)) is int and coverage[key] >= 0), "Invalid coverage count: " + key)
    if coverage.get("entitiesExpected") is None or coverage.get(entities_key) is None:
        require(coverage[reviewed_key] <= coverage["filesExpected"], "Coverage exceeds selected scope")
        return False
    require(coverage[reviewed_key] <= coverage["filesExpected"] and coverage[entities_key] <= coverage["entitiesExpected"],
            "Coverage exceeds selected scope")
    return coverage[reviewed_key] == coverage["filesExpected"] and coverage[entities_key] == coverage["entitiesExpected"]


def check_independent(artifact):
    def walk(value):
        if isinstance(value, dict):
            require(not {"metrics", "thresholds", "metricValues", "currentMetrics"}.intersection(value),
                    "Independent artifact must not contain current metric values or thresholds")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(artifact)
    require(artifact.get("status") in ("COMPLETE", "INCOMPLETE"), "Independent stage status missing")
    require(isinstance(artifact.get("reviewId"), str) and artifact["reviewId"], "Independent reviewId missing")
    require(isinstance(artifact.get("scope"), dict), "Independent scope missing")
    require(isinstance(artifact["scope"].get("paths"), list), "Independent selected paths missing")
    require(artifact.get("coverage", {}).get("filesExpected") == len(artifact["scope"]["paths"]),
            "Independent coverage denominator differs from selected paths")
    complete = check_coverage(artifact.get("coverage", {}), "filesReviewed", "entitiesReviewed")
    require(artifact["coverage"].get("entityUnit") in (None, "SNAPSHOT_ENTITY", "LEGACY_METRIC_ENTITY"),
            "Independent coverage must describe source entities, not metric match groups")
    require(artifact["status"] != "COMPLETE" or complete, "Independent COMPLETE contradicts coverage")
    require(isinstance(artifact.get("findings"), list), "Independent findings missing")
    ids = []
    for finding in artifact["findings"]:
        check_finding(finding, artifact)
        require(finding["source"] == "AI_REVIEW", "Independent stage contains a metric signal")
        ids.append(finding["findingId"])
    require(len(ids) == len(set(ids)), "Duplicate independent finding IDs")


def check_entity_matches(matches):
    """Validate supplied Core pairing records; never infer or calculate pairings."""
    require(isinstance(matches, list), "entityMatches must be an array")
    identities, displays = set(), {}
    incomplete = False
    for match in matches:
        safe_path(match.get("path"))
        for key in ("oldPath", "newPath"):
            require(key in match, "Entity match missing " + key)
            if match[key] is not None:
                safe_path(match[key])
        require(match["path"] == (match["newPath"] or match["oldPath"]), "Entity match owning path mismatch")
        require(isinstance(match.get("key"), str) and match["key"], "Entity match key missing")
        identity = (match["path"], match["key"])
        require(identity not in identities, "Duplicate entity match group")
        identities.add(identity)
        require(match.get("status") in MATCH_STATUSES, "Invalid entity match status")
        before, after = match.get("before"), match.get("after")
        require(isinstance(before, list) and isinstance(after, list) and (before or after),
                "Entity match needs at least one supplied source entity")
        for side, path in ((before, match["oldPath"]), (after, match["newPath"])):
            require(not side or path is not None, "Entity match source side has no file path")
            for entity in side:
                require(isinstance(entity.get("signature"), str) and entity["signature"], "Source entity signature missing")
                require(entity.get("matchingKey") == match["key"], "Source entity matchingKey differs from group")
                require(type(entity.get("matchingAmbiguous")) is bool, "Source entity ambiguity status missing")
                lines = entity.get("lines", {})
                start, end = lines.get("startLine"), lines.get("endLine")
                require(type(start) is int and type(end) is int and 0 < start <= end,
                        "Invalid source entity line range")
        if match["status"] == "MATCHED":
            require(len(before) == len(after) == 1, "MATCHED requires one entity on each side")
            require(not before[0]["matchingAmbiguous"] and not after[0]["matchingAmbiguous"],
                    "MATCHED cannot assert an ambiguous pair")
        elif match["status"] == "ADDED":
            require(not before and len(after) == 1, "ADDED requires only a head entity")
        elif match["status"] == "REMOVED":
            require(len(before) == 1 and not after, "REMOVED requires only a base entity")
        else:
            incomplete = True
        # Presentation identity comes from Core candidates, not a new matching algorithm.
        display = after[0]["signature"] if len(after) == 1 else before[0]["signature"] if len(before) == 1 else match["key"]
        require((match["path"], display) not in displays, "Entity match display identity is ambiguous")
        displays[(match["path"], display)] = match
    return displays, incomplete


def validate(report, independent=None):
    for key in ("schemaVersion", "reviewId", "scope", "independentReview", "metrics", "findings", "coverage", "skips", "verdict", "ruleDiscovery"):
        require(key in report, "Report missing " + key)
    require(report["schemaVersion"] == 1, "Unsupported report schemaVersion")
    scope = report["scope"]
    for key in ("repoRoot", "baseSha", "headSha", "snapshotId", "languages", "paths"):
        require(key in scope, "Scope missing " + key)
    require(scope["snapshotId"] == scope["headSha"], "Commit-only snapshotId must equal headSha")
    require(isinstance(scope["paths"], list) and len(set(scope["paths"])) == len(scope["paths"]), "Invalid selected paths")
    for path in scope["paths"]:
        safe_path(path)
    for key in ("baseSha", "headSha"):
        sha = scope[key]
        require(isinstance(sha, str) and len(sha) in (40, 64) and all(c in "0123456789abcdef" for c in sha), "Expected full commit SHA")
    stage = report["independentReview"]
    check_independent({"reviewId": report["reviewId"], "scope": scope, **stage})
    require(isinstance(stage.get("artifact"), str) and stage["artifact"], "Frozen artifact reference missing")
    if independent is not None:
        check_independent(independent)
        require(independent["reviewId"] == report["reviewId"] and independent["scope"] == scope, "Frozen scope mismatch")
        for key in ("findings", "coverage", "status"):
            require(independent[key] == stage[key], "Frozen independent stage was changed: " + key)
    covered = check_coverage(report["coverage"], "filesAnalyzed", "entitiesAnalyzed")
    require(report["coverage"]["filesExpected"] == len(scope["paths"]),
            "Report coverage denominator differs from selected paths")
    independent_complete = stage["status"] == "COMPLETE"
    matches, matches_incomplete = check_entity_matches(report["entityMatches"]) if "entityMatches" in report else ({}, False)
    coverage_unit = report["coverage"].get("entityUnit")
    require(coverage_unit != "SNAPSHOT_ENTITY", "Final coverage must describe match groups or legacy metric entities")
    if coverage_unit == "MATCH_GROUP":
        require("entityMatches" in report, "MATCH_GROUP coverage needs supplied Core entityMatches")
    if "entityMatches" in report:
        require(coverage_unit in (None, "MATCH_GROUP"), "Supplied matches require MATCH_GROUP final coverage")
        require(report["coverage"]["entitiesExpected"] is None
                or report["coverage"]["entitiesExpected"] == len(matches),
                "Final coverage denominator differs from supplied match groups")
    groups = {}
    seen = set()
    metrics_complete = True
    for metric in report["metrics"]:
        safe_path(metric["path"])
        metric_id = metric["metric"]
        require(metric_id in METRICS, "Unexpected metric: " + metric_id)
        key = (metric["path"], metric["entity"], metric_id)
        require(key not in seen, "Duplicate metric comparison")
        seen.add(key)
        groups.setdefault(key[:2], set()).add(metric_id)
        if "entityMatches" in report:
            require(key[:2] in matches, "Metric row has no supplied Core match group")
        before, after = metric["before"], metric["after"]
        for side in (before, after):
            status = side.get("status")
            require(status in STATUSES, "Invalid metric value status")
            definition = side.get("definition", {})
            require(all(isinstance(definition.get(k), str) and definition[k] for k in ("id", "language", "analyzer", "algorithm")), "Missing analyzer/algorithm provenance")
            require(definition["id"] == metric_id, "Metric definition ID mismatch")
            value = side.get("value")
            require((type(value) in (int, float) and math.isfinite(value)) if status == "AVAILABLE" else value is None,
                    "Only AVAILABLE measurements have finite values")
            if status not in ("AVAILABLE", "ENTITY_ABSENT"):
                metrics_complete = False
        both = before["status"] == after["status"] == "AVAILABLE"
        compatible = before["definition"] == after["definition"]
        expected = "COMPARED" if both and compatible else "INCOMPATIBLE" if both else "UNAVAILABLE"
        require(metric["status"] == expected, "Invalid comparison status")
        delta = metric.get("delta")
        require(delta == after["value"] - before["value"] if expected == "COMPARED" else delta is None,
                "Delta contradicts Core metric sides")
        if expected == "INCOMPATIBLE":
            metrics_complete = False
    metrics_complete = metrics_complete and all(set(METRICS) == values for values in groups.values())
    if "entityMatches" in report:
        metrics_complete = metrics_complete and set(matches) == set(groups) and not matches_incomplete
    if report["coverage"]["entitiesExpected"] and not groups:
        metrics_complete = False
    require(report["coverage"]["entitiesAnalyzed"] is None
            or len(groups) >= report["coverage"]["entitiesAnalyzed"] or not report["coverage"]["entitiesExpected"],
            "Analyzed entity count exceeds measurement coverage")
    ids = []
    for finding in report["findings"]:
        check_finding(finding, report)
        ids.append(finding["findingId"])
    require(len(ids) == len(set(ids)), "Duplicate final finding IDs")
    final_by_id = {finding["findingId"]: finding for finding in report["findings"]}
    origins = {origin for finding in report["findings"] for origin in finding.get("originFindingIds", [])}
    for original in stage["findings"]:
        require(original["findingId"] in final_by_id or original["findingId"] in origins,
                "Independent finding was silently dropped")
    verdict = report["verdict"]
    require(verdict in ("PASS", "WARN", "INCOMPLETE", "NO_CHANGES"), "Invalid verdict")
    if verdict in ("PASS", "WARN"):
        require(covered and independent_complete and metrics_complete, "Complete verdict contradicts missing review/metrics coverage")
    if verdict == "PASS":
        require(not report["findings"], "PASS contradicts findings")
    if verdict == "NO_CHANGES":
        require(not scope["paths"] and not report["findings"] and not report["metrics"]
                and report["coverage"]["filesExpected"] == 0 and report["coverage"]["entitiesExpected"] == 0,
                "NO_CHANGES contradicts selected scope")
    rules = report["ruleDiscovery"]
    require(rules.get("status") in ("NOT_RUN", "RULE_SUGGESTED", "NO_SUGGESTION", "UNAVAILABLE", "ERROR"), "Invalid discovery status")
    if rules["status"] == "RULE_SUGGESTED":
        require(rules.get("candidate", {}).get("status") == "PROPOSED", "Rule proposal cannot activate a rule")
    return report


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(report):
    scope = report["scope"]
    if report["verdict"] == "NO_CHANGES":
        return ("# CodeClarity readability review\n\n**NO_CHANGES**\n\n"
                f"Snapshots: `{scope['baseSha']}` → `{scope['headSha']}`\n\n"
                "No changes in the selected scope; no metric or rule analysis was required.\n")
    lines = ["# CodeClarity readability review", "", f"**{report['verdict']}** · `{report['reviewId']}`", "",
             f"Repository: {scope['repoRoot']}", f"Snapshots: `{scope['baseSha']}` → `{scope['headSha']}`", "",
             "Selected paths: " + (", ".join(scope["paths"]) or "none"),
             "Independent coverage: " + json.dumps(report["independentReview"]["coverage"], ensure_ascii=False),
             "Analysis coverage: " + json.dumps(report["coverage"], ensure_ascii=False)]
    if "entityMatches" in report:
        lines += ["", "Core entity matches:", "", "| Group | Status | Base source | Head source |", "|---|---|---|---|"]
        for match in report["entityMatches"]:
            def source_entities(side, path, sha):
                return "; ".join(f"{sha}:{path}:{entity['lines']['startLine']}-{entity['lines']['endLine']} {entity['signature']}"
                                 for entity in side) or "—"
            lines.append("| " + " | ".join(map(cell, [match["path"] + " / " + match["key"], match["status"],
                         source_entities(match["before"], match["oldPath"], scope["baseSha"]),
                         source_entities(match["after"], match["newPath"], scope["headSha"])])) + " |")
    lines += ["", "| File / entity | Metric | Before | After | Delta |", "|---|---|---|---|---|"]
    for entry in report["metrics"]:
        def measured(side):
            return str(side["value"]) if side["status"] == "AVAILABLE" else side["status"]
        lines.append("| " + " | ".join(map(cell, [entry["path"] + " / " + entry["entity"], entry["metric"],
                         measured(entry["before"]), measured(entry["after"]), entry.get("delta") if entry.get("delta") is not None else "—"])) + " |")
    groups = {(m["path"], m["entity"]) for m in report["metrics"]}
    for path, entity in sorted(groups):
        present = {m["metric"] for m in report["metrics"] if (m["path"], m["entity"]) == (path, entity)}
        for metric_id in METRICS:
            if metric_id not in present:
                lines.append(f"| {cell(path + ' / ' + entity)} | {metric_id} | MISSING | MISSING | — |")
    if not report["metrics"]:
        lines.extend(f"| — | {metric_id} | MISSING | MISSING | — |" for metric_id in METRICS)
    definitions = sorted({json.dumps(side["definition"], ensure_ascii=False, sort_keys=True)
                          for m in report["metrics"] for side in (m["before"], m["after"])})
    lines += ["", "Analyzer definitions:", "", *["- `" + definition + "`" for definition in definitions], "", "Findings:", ""]
    for finding in report["findings"]:
        loc = finding["location"]
        local = Path(scope["repoRoot"]) / loc["path"]
        target = local.as_posix()
        reference = f"[{cell(loc['path'])}:{loc['startLine']}](<{target}:{loc['startLine']}>)" if local.is_file() else f"`{loc['path']}:{loc['startLine']}`"
        lines += [f"- {reference} "
                  f"(snapshot `{finding['snapshotId']}`, lines {loc['startLine']}–{loc['endLine']}): "
                  f"{finding['description']} [{finding['metricRelation']}]",
                  "  Evidence: " + "; ".join(finding["evidence"]), "  Recommendation: " + finding["recommendation"]]
    if not report["findings"]:
        lines.append("No supported findings recorded; this is not proof of ideal code.")
    if report["skips"]:
        lines += ["", "Omissions:", "", *[f"- {item['stage']}: {item.get('path', '')} {item['reason']}" for item in report["skips"]]]
    # NO_SUGGESTION is deliberately silent in user-facing Markdown.
    if report["ruleDiscovery"]["status"] == "RULE_SUGGESTED":
        candidate = report["ruleDiscovery"]["candidate"]
        lines += ["", "Proposed rule (not activated): " + candidate.get("title", candidate.get("candidateId", ""))]
        if candidate.get("synthetic"):
            lines.append("Based on prepared synthetic demonstration history, not real developer confirmations.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("input", type=Path)
    freeze.add_argument("output", type=Path)
    for name in ("validate", "render"):
        command = sub.add_parser(name)
        command.add_argument("report", type=Path)
        command.add_argument("--independent", type=Path)
        if name == "render":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        document = load(args.input)
        check_independent(document)
        payload = canonical(document)
        write_new(args.output, payload)
        print(json.dumps({"event": "independent_review_frozen", "reviewId": document["reviewId"],
                          "artifact": str(args.output), "sha256": hashlib.sha256(payload).hexdigest()}))
        return
    report = validate(load(args.report), load(args.independent) if args.independent else None)
    if args.command == "render":
        write_new(args.output, render(report).encode("utf-8"))
    print(json.dumps({"valid": True, "verdict": report["verdict"], "schemaVersion": report["schemaVersion"]}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("Artifact error: " + str(error), file=sys.stderr)
        sys.exit(1)
