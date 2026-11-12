"""Generate deterministic review/finding IDs from JSON on stdin; write no files.

Input: {"scope": {repoRoot, baseSha, headSha, snapshotId, languages, paths},
        "findings": [...]}
Output: {"reviewId": "review-...", "findings": [...with IDs...]}

Examples: python review_ids.py < scope-and-findings.json
          python review_ids.py --self-test
"""

import argparse
import copy
import hashlib
import json
import re
import sys


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identifier(prefix, value):
    return prefix + "-" + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def relative_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("A repository-relative path must be a nonempty string.")
    value = value.replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value) or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Expected a repository-relative path without traversal.")
    return value


def normalized_scope(scope):
    required = {"repoRoot", "baseSha", "headSha", "snapshotId", "languages", "paths"}
    if not isinstance(scope, dict) or set(scope) != required:
        raise ValueError("scope must contain exactly repoRoot, baseSha, headSha, snapshotId, languages, paths.")
    result = copy.deepcopy(scope)
    if not isinstance(result["repoRoot"], str) or not result["repoRoot"].strip():
        raise ValueError("repoRoot must identify the resolved repository root.")
    # The caller resolves repoRoot; do not access the filesystem or reinterpret a
    # foreign platform's absolute path on this platform.
    result["repoRoot"] = result["repoRoot"].replace("\\", "/").rstrip("/") or "/"
    for key in ("baseSha", "headSha", "snapshotId"):
        if not isinstance(result[key], str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", result[key]):
            raise ValueError(key + " must be a full commit SHA for the current commit-only mode.")
    if result["snapshotId"] != result["headSha"]:
        raise ValueError("snapshotId must equal headSha for the current commit-only mode.")
    languages = result["languages"]
    if not isinstance(languages, list) or not languages or any(language not in ("java", "python") for language in languages):
        raise ValueError("languages must be a nonempty array of java/python identifiers.")
    result["languages"] = sorted(set(languages))
    if not isinstance(result["paths"], list):
        raise ValueError("paths must list selected changed files; an empty array means no selected changes after discovery.")
    result["paths"] = sorted(set(relative_path(path) for path in result["paths"]))
    return result


def generate(document):
    if not isinstance(document, dict):
        raise ValueError("Input must be a JSON object.")
    scope = normalized_scope(document.get("scope"))
    review_id = identifier("review", {"identityVersion": 1, "scope": scope})
    if document.get("reviewId", review_id) != review_id:
        raise ValueError("Supplied reviewId conflicts with the deterministic scope identity.")
    findings = document.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("findings must be an array.")
    result = []
    seen = set()
    for original in findings:
        if not isinstance(original, dict):
            raise ValueError("Each finding must be an object.")
        finding = copy.deepcopy(original)
        snapshot = finding.get("snapshotId")
        if snapshot not in (scope["baseSha"], scope["headSha"]):
            raise ValueError("Finding snapshotId must identify the reviewed base or head commit.")
        category = finding.get("categoryId")
        if not isinstance(category, str) or not re.fullmatch(r"[a-z][a-z0-9_\-]*", category):
            raise ValueError("categoryId must be a stable lowercase identifier.")
        location = finding.get("location")
        if not isinstance(location, dict) or set(location) != {"path", "startLine", "endLine"}:
            raise ValueError("location must contain exactly path, startLine and endLine.")
        location["path"] = relative_path(location["path"])
        start, end = location["startLine"], location["endLine"]
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            raise ValueError("Finding lines must be positive inclusive integers in ascending order.")
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise ValueError("evidence must contain at least one nonempty source/tool reference.")
        identity = {"identityVersion": 1, "reviewId": review_id, "snapshotId": snapshot,
                    "categoryId": category, "location": location, "evidence": sorted(set(evidence))}
        finding_id = identifier("finding", identity)
        if finding.get("reviewId", review_id) != review_id or finding.get("findingId", finding_id) != finding_id:
            raise ValueError("Supplied finding/review IDs conflict with their deterministic identity.")
        if finding_id in seen:
            raise ValueError("Duplicate occurrence: merge its evidence before assigning IDs.")
        seen.add(finding_id)
        finding["reviewId"] = review_id
        finding["findingId"] = finding_id
        result.append(finding)
    return {"reviewId": review_id, "findings": result}


def self_test():
    scope = {"repoRoot": "/work/project", "baseSha": "a" * 40, "headSha": "b" * 40,
             "snapshotId": "b" * 40, "languages": ["python", "java"], "paths": ["src/b.py", "src/a.java"]}
    finding = {"snapshotId": "b" * 40, "categoryId": "naming", "location": {"path": "src/b.py", "startLine": 2, "endLine": 3},
               "evidence": ["b:src/b.py:2-3", "tool:inspection:1"], "description": "Unclear role", "recommendation": "Name the role"}
    source = {"scope": scope, "findings": [finding]}
    first = generate(source)
    reordered = copy.deepcopy(source)
    reordered["scope"]["languages"].reverse()
    reordered["scope"]["paths"].reverse()
    reordered["findings"][0]["evidence"].reverse()
    assert generate(reordered)["reviewId"] == first["reviewId"]
    assert generate(reordered)["findings"][0]["findingId"] == first["findings"][0]["findingId"]
    assert "findingId" not in finding, "Input must not be mutated."
    assert generate({"scope": scope, "reviewId": first["reviewId"], "findings": first["findings"]}) == first
    changed = copy.deepcopy(source)
    changed["scope"]["headSha"] = changed["scope"]["snapshotId"] = changed["findings"][0]["snapshotId"] = "c" * 40
    assert generate(changed)["reviewId"] != first["reviewId"]
    assert generate(changed)["findings"][0]["findingId"] != first["findings"][0]["findingId"]
    deleted = copy.deepcopy(source)
    deleted["findings"][0]["snapshotId"] = "a" * 40
    assert generate(deleted)["findings"][0]["findingId"] != first["findings"][0]["findingId"]
    for mutation in (lambda doc: doc["findings"][0]["location"].update(path="../secret"),
                     lambda doc: doc["findings"][0]["location"].update(startLine=True),
                     lambda doc: doc["findings"][0].update(snapshotId="d" * 40),
                     lambda doc: doc.update(reviewId="invented"),
                     lambda doc: doc["findings"].append(copy.deepcopy(doc["findings"][0]))):
        invalid = copy.deepcopy(source)
        mutation(invalid)
        try:
            generate(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid identity input was accepted.")
    print("Passed: deterministic IDs, replay, snapshot distinction, duplicate/traversal rejection, no input mutation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    try:
        json.dump(generate(json.load(sys.stdin)), sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
        sys.stdout.write("\n")
    except (ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
