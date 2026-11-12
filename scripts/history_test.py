"""Real-MCP history checks in disposable repositories, including CLI feedback and concurrent processes."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time

from smoke_test import git
from python_smoke_test import connect, close
from llm_artifact_test import fixture, finding


def review_fixture(root, index=1, category="naming"):
    # Synthetic storage test payloads, isolated from all user history; no analyzer claim.
    report, _ = fixture()
    report["reviewId"] = f"storage-review-{index}"
    report["scope"].update(repoRoot=str(root), headSha=f"{index:040x}", snapshotId=f"{index:040x}")
    report["ruleDiscovery"] = {"status": "NOT_RUN"}
    report["verdict"] = "WARN"
    issue = finding(report, f"storage-finding-{index}")
    issue["categoryId"] = category
    report["findings"] = [issue]
    report["independentReview"]["findings"] = [copy.deepcopy(issue)]
    return report


def feedback(jar, root, decision="FIXED", evidence="Explicit approval in isolated test fixture", actor="test-developer", finding_id="storage-finding-1", error=False, review_id="storage-review-1"):
    result = subprocess.run(["java", "-jar", str(jar), "--repo-root", str(root), "--record-feedback",
                             review_id, finding_id, "--decision", decision,
                             "--confirmed-by", actor, "--evidence", evidence], capture_output=True, text=True)
    assert bool(result.returncode) == error, result.stdout + result.stderr
    return None if error else json.loads(result.stdout)


def candidate_checks(jar, root):
    """All confirmations below are explicit isolated test fixtures, never user-history receipts."""
    root.mkdir()
    git(root, "init", "-b", "main")
    history_path = root / ".codeclarity/review-history.json"
    process, client = connect(jar, root)
    try:
        tool = next(t for t in client.send("tools/list")["tools"] if t["name"] == "propose_rule_candidate")
        assert tool["annotations"]["readOnlyHint"] is False and tool["annotations"]["idempotentHint"] is True
        assert tool["inputSchema"]["required"] == ["candidate"]
        for index in range(1, 5):
            review = review_fixture(root, index, "naming" if index < 4 else "complexity")
            if index == 1:
                alias = copy.deepcopy(review["findings"][0])
                alias["findingId"] = "same-source-alias"
                review["findings"].append(alias)
                review["independentReview"]["findings"].append(copy.deepcopy(alias))
            client.tool("update_review_history", {"review": review})
        candidate = {"candidateId": "naming-candidate-1", "categoryId": "naming", "status": "PROPOSED",
                     "title": "Use domain names", "description": "Repeated confirmed domain naming concern",
                     "supportingFindingIds": [f"storage-finding-{i}" for i in (1, 2, 3)],
                     "confirmedFeedbackIds": ["unknown-1", "unknown-2"],
                     "examples": [{"findingId": "storage-finding-1"}], "exceptions": ["Externally fixed API names"]}
        def reject(value):
            before = history_path.read_bytes()
            client.tool("propose_rule_candidate", {"candidate": value}, error=True)
            assert history_path.read_bytes() == before, value
        reject(candidate)
        for index in (1, 2):
            feedback(jar, root, review_id=f"storage-review-{index}", finding_id=f"storage-finding-{index}")
        data = client.tool("get_review_history", {})
        candidate["confirmedFeedbackIds"] = [e["feedbackId"] for e in data["feedback"]]
        # A superseded FIXED event and two events for one finding cannot establish two fixes.
        feedback(jar, root, "REJECTED", "Explicit rejection of second isolated fixture",
                 review_id="storage-review-2", finding_id="storage-finding-2")
        reject(candidate)
        feedback(jar, root, evidence="New isolated confirmation for second finding",
                 review_id="storage-review-2", finding_id="storage-finding-2")
        data = client.tool("get_review_history", {})
        old_fixed = candidate["confirmedFeedbackIds"][1]
        candidate["confirmedFeedbackIds"][1] = data["feedback"][-1]["feedbackId"]
        invalid = []
        for field, value in (("status", "ACTIVE"), ("synthetic", True), ("fixedCount", 99),
                             ("categoryId", "unknown"), ("confirmedFeedbackIds", [old_fixed, candidate["confirmedFeedbackIds"][1]]),
                             ("supportingFindingIds", ["storage-finding-1", "same-source-alias", "storage-finding-2"]),
                             ("supportingFindingIds", ["storage-finding-1", "storage-finding-2", "storage-finding-4"]),
                             ("supportingFindingIds", ["storage-finding-1", "storage-finding-2", "unknown"]),
                             ("examples", [{"findingId": "storage-finding-4"}]),
                             ("examples", [{"findingId": "storage-finding-1", "snapshotId": "invented"}]),
                             ("examples", [{"findingId": "storage-finding-1", "confirmed": True}])):
            value_candidate = copy.deepcopy(candidate)
            value_candidate[field] = value
            invalid.append(value_candidate)
        for value in invalid: reject(value)
        receipt = client.tool("propose_rule_candidate", {"candidate": candidate})
        assert receipt["status"] == "saved" and receipt["candidateId"] == candidate["candidateId"]
        assert receipt["candidateStatus"] == "PROPOSED" and receipt["statistics"]["fixedCount"] == 2
        before, stamp = history_path.read_bytes(), history_path.stat().st_mtime_ns
        replay = client.tool("propose_rule_candidate", {"candidate": copy.deepcopy(candidate)})
        assert replay["status"] == "unchanged" and replay["revision"] == receipt["revision"]
        assert history_path.read_bytes() == before and history_path.stat().st_mtime_ns == stamp
        conflict = copy.deepcopy(candidate)
        conflict["description"] = "Changed immutable proposal"
        reject(conflict)
        equivalent = copy.deepcopy(candidate)
        equivalent.update(candidateId="different-candidate-id", title=" USE   DOMAIN NAMES ")
        duplicate = client.tool("propose_rule_candidate", {"candidate": equivalent})
        assert duplicate["status"] == "unchanged" and duplicate["candidateId"] == candidate["candidateId"]
        assert history_path.read_bytes() == before
        # Later feedback changes current counts without rewriting historical proposal evidence.
        feedback(jar, root, "REJECTED", "Later explicit reversal of isolated fixture")
        stored = client.tool("get_review_history", {})
        assert stored["statistics"]["fixedCount"] == 1 and stored["ruleCandidates"] == [candidate]
        assert client.tool("propose_rule_candidate", {"candidate": candidate})["status"] == "unchanged"
    finally:
        close(process)
    process, client = connect(jar, root)
    try:
        stored = client.tool("get_review_history", {})
        assert stored["ruleCandidates"] == [candidate] and stored["statistics"]["fixedCount"] == 1
        valid = history_path.read_bytes()
        for field, value in (("status", "ACTIVE"), ("confirmedFeedbackIds", ["fake-1", "fake-2"]),
                             ("supportingFindingIds", ["storage-finding-1", "storage-finding-2", "storage-finding-4"])):
            corrupt = copy.deepcopy(stored)
            corrupt["ruleCandidates"][0][field] = value
            bad = json.dumps(corrupt).encode()
            history_path.write_bytes(bad)
            client.tool("get_review_history", {}, error=True)
            assert history_path.read_bytes() == bad
        history_path.write_bytes(valid)
    finally:
        close(process)


def main():
    jar = Path(sys.argv[1] if len(sys.argv) > 1 else "target/codeclarity-mcp.jar").resolve()
    with TemporaryDirectory(prefix="codeclarity-history-") as directory:
        project = Path(__file__).resolve().parents[1]
        proposal_schema = json.loads((project / "plugin/contracts/rule-candidate.schema.json").read_text(encoding="utf-8"))
        history_schema = json.loads((project / "plugin/contracts/review-history.schema.json").read_text(encoding="utf-8"))
        assert all(history_schema["$defs"][key] == value for key, value in proposal_schema["$defs"].items())
        classes = Path(directory) / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-encoding", "UTF-8", "-cp", str(jar), "-d", str(classes),
                        str(project / "src/test/java/dev/codeclarity/history/HistoryProjectionTest.java")], check=True)
        subprocess.run(["java", "-cp", os.pathsep.join([str(classes), str(jar)]),
                        "dev.codeclarity.history.HistoryProjectionTest"], check=True)
        root = Path(directory) / "repo"
        root.mkdir()
        git(root, "init", "-b", "main")
        history_path = root / ".codeclarity/review-history.json"
        process, client = connect(jar, root)
        try:
            tools = {t["name"]: t for t in client.send("tools/list")["tools"]}
            assert tools["get_review_history"]["annotations"]["readOnlyHint"] is True
            assert tools["update_review_history"]["annotations"]["readOnlyHint"] is False
            assert tools["update_review_history"]["inputSchema"]["anyOf"] == [{"required": ["review"]}, {"required": ["categories"]}]
            empty = client.tool("get_review_history", {})
            assert empty["revision"] == 0 and empty["statistics"]["fixedCount"] == 0 and not history_path.parent.exists()
            first = review_fixture(root)
            payload = {"review": first, "categories": [{"categoryId": "naming", "name": "Именование"}]}
            saved = client.tool("update_review_history", payload)
            assert saved["status"] == "saved" and saved["revision"] == 1 and history_path.exists(), saved
            before = history_path.read_bytes()
            stamp = history_path.stat().st_mtime_ns
            repeat = client.tool("update_review_history", json.loads(json.dumps(payload, sort_keys=True)))
            assert repeat["status"] == "unchanged" and repeat["revision"] == 1, repeat
            assert history_path.read_bytes() == before and history_path.stat().st_mtime_ns == stamp
            data = client.tool("get_review_history", {})
            assert data["statistics"]["reviewCount"] == 1 and data["statistics"]["detectedCount"] == 1
            assert data["statistics"]["fixedCount"] == 0 and data["findings"][0]["status"] == "DETECTED"
            assert data["categories"][0]["examples"][0]["findingId"] == "storage-finding-1"

            conflicting = copy.deepcopy(payload)
            conflicting["review"]["findings"][0]["description"] = "conflicting replay"
            conflicting["categories"][0]["name"] = "must not partially apply"
            bad_scope = copy.deepcopy(first)
            bad_scope["reviewId"] = "different-id-same-scope"
            for f in bad_scope["findings"]: f["reviewId"] = bad_scope["reviewId"]
            malformed = copy.deepcopy(first)
            malformed["findings"][0]["location"]["path"] = "../outside.py"
            fixed = copy.deepcopy(first)
            fixed["findings"][0]["reviewStatus"] = "FIXED"
            status_fixed = copy.deepcopy(first)
            status_fixed["findings"][0]["status"] = "FIXED"
            duplicate_id = review_fixture(root, 2)
            duplicate_id["findings"][0]["findingId"] = "storage-finding-1"
            wrong_root = review_fixture(root, 2)
            wrong_root["scope"]["repoRoot"] = str(root.parent)
            for invalid in ({}, conflicting, {"review": bad_scope}, {"review": malformed}, {"review": fixed},
                            {"review": status_fixed}, {"review": duplicate_id}, {"review": wrong_root},
                            {"feedback": [{"decision": "FIXED", "confirmed": True}]}, {"review": {"reviewId": "invalid"}},
                            {"categories": [{"categoryId": "naming", "name": "a", "fixedCount": 99}]},
                            {"categories": [{"categoryId": "x", "name": "a"}, {"categoryId": "x", "name": "b"}]}):
                client.tool("update_review_history", invalid, error=True)
                assert history_path.read_bytes() == before, invalid
            categories = {"categories": [{"categoryId": "naming", "name": "Readable names", "description": "Domain naming"},
                                         {"categoryId": "unused", "name": "Unused category"}]}
            client.tool("update_review_history", categories)
            assert client.tool("update_review_history", categories)["status"] == "unchanged"
            for index, category in ((2, "naming"), (3, "complexity")):
                client.tool("update_review_history", {"review": review_fixture(root, index, category)})
            data = client.tool("get_review_history", {})
            assert data["statistics"]["reviewCount"] == 3 and data["statistics"]["fixedCount"] == 0
            by_category = {c["categoryId"]: c for c in data["categories"]}
            assert by_category["naming"]["name"] == "Readable names" and by_category["naming"]["statistics"]["occurrenceCount"] == 2
            assert len(by_category["naming"]["examples"]) == 2 and by_category["unused"]["statistics"]["occurrenceCount"] == 0

            receipt = feedback(jar, root)
            assert receipt["statistics"]["fixedCount"] == 1, receipt
            assert feedback(jar, root)["status"] == "unchanged"
            assert client.tool("update_review_history", payload)["statistics"]["fixedCount"] == 1
            data = client.tool("get_review_history", {})
            assert len(data["feedback"]) == 1 and data["feedback"][0]["authority"] == "LOCAL_CLI"
            assert data["reviews"][0]["findings"][0]["reviewStatus"] == "PENDING_FEEDBACK"
            assert data["findings"][0]["status"] == "FIXED" and data["categories"][0]["examples"][0]["feedbackIds"]
            feedback(jar, root, "REJECTED", "Explicit rejection fixture")
            assert client.tool("get_review_history", {})["statistics"]["fixedCount"] == 0
            feedback(jar, root, evidence="New explicit fix confirmation")
            assert client.tool("get_review_history", {})["statistics"]["fixedCount"] == 1
            feedback(jar, root, evidence="", error=True)
            feedback(jar, root, actor="", error=True)
            feedback(jar, root, finding_id="unknown", error=True)
        finally:
            close(process)

        process, client = connect(jar, root)
        try:
            persisted = client.tool("get_review_history", {})
            assert persisted["statistics"]["fixedCount"] == 1 and persisted["statistics"]["reviewCount"] == 3
            valid_bytes = history_path.read_bytes()
            corrupt = copy.deepcopy(persisted)
            corrupt["statistics"]["fixedCount"] = 999
            duplicate = valid_bytes.decode().replace('"schemaVersion" : 1', '"schemaVersion" : 1, "schemaVersion" : 1', 1)
            assert duplicate != valid_bytes.decode()
            for bad in (b"{broken json", json.dumps(corrupt).encode(), duplicate.encode(), valid_bytes + b" {}"):
                history_path.write_bytes(bad)
                client.tool("get_review_history", {}, error=True)
                client.tool("update_review_history", {"review": review_fixture(root, 4)}, error=True)
                assert history_path.read_bytes() == bad, "Corrupt history must not be overwritten"
            history_path.write_bytes(valid_bytes)

            # Public reads take the storage lock. A raw Windows file handle can deny atomic replacement.
            done, reader_errors = Event(), []
            reader_process, reader_client = connect(jar, root)
            def reader():
                while not done.is_set():
                    try:
                        snapshot = reader_client.tool("get_review_history", {})
                        assert snapshot["statistics"]["reviewCount"] == len(snapshot["reviews"])
                        assert snapshot["statistics"]["occurrenceCount"] == len(snapshot["findings"])
                    except Exception as error:
                        reader_errors.append(str(error))
                    time.sleep(0.002)
            thread = Thread(target=reader)
            thread.start()
            def writer(worker):
                worker_process, worker_client = connect(jar, root)
                try:
                    for offset in range(2):
                        review = review_fixture(root, 100 + worker * 2 + offset)
                        worker_client.tool("update_review_history", {"review": review})
                        assert worker_client.tool("update_review_history", {"review": review})["status"] == "unchanged"
                finally:
                    close(worker_process)
            try:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(writer, range(4)))
            finally:
                done.set()
                thread.join()
                close(reader_process)
            assert not reader_errors, reader_errors
            final = client.tool("get_review_history", {})
            assert final["statistics"]["reviewCount"] == 11 and final["statistics"]["occurrenceCount"] == 11
            assert final["statistics"]["fixedCount"] == 1 and final["statistics"]["detectedCount"] == 10
            assert not list(history_path.parent.glob("review-history-*.tmp"))
        finally:
            close(process)
        candidate_checks(jar, Path(directory) / "candidate-repo")
    print("Passed: first-save creation, category merges, review/scope idempotency, conflict/JSON rejection, "
          "explicit feedback, restart persistence, concurrent MCP readers, four JVM writers, "
          "evidence-backed PROPOSED candidates, candidate replay/conflicts and no lost updates.")


if __name__ == "__main__":
    main()
