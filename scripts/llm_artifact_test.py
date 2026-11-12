"""Verify review artifact invariants; fixtures are synthetic, not analyzer results."""

import copy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from llm_evals import check_report, git
from llm_java_skill_e2e import discovery_errors

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review_artifacts", PROJECT / "plugin/scripts/review_artifacts.py")
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)


def fixture():
    scope = {"repoRoot": str(PROJECT), "baseSha": "a" * 40, "headSha": "b" * 40,
             "snapshotId": "b" * 40, "languages": ["python"], "paths": ["sample.py"]}
    independent = {"reviewId": "synthetic-artifact-review", "scope": scope, "status": "COMPLETE",
                   "coverage": {"filesExpected": 1, "filesReviewed": 1, "entitiesExpected": 1, "entitiesReviewed": 1},
                   "findings": []}
    measurements = []
    for metric_id in ARTIFACTS.METRICS:
        definition = {"id": metric_id, "language": "python", "analyzer": "synthetic-unit-fixture/1", "algorithm": "synthetic/1"}
        measurements.append({"path": "sample.py", "entity": "sample(value)", "metric": metric_id, "status": "COMPARED",
                             "before": {"definition": definition, "status": "AVAILABLE", "value": 1},
                             "after": {"definition": definition, "status": "AVAILABLE", "value": 2}, "delta": 1})
    report = {"schemaVersion": 1, "reviewId": independent["reviewId"], "scope": copy.deepcopy(scope),
              "independentReview": {"artifact": "synthetic-independent.json", "status": "COMPLETE",
                                    "coverage": copy.deepcopy(independent["coverage"]), "findings": []},
              "metrics": measurements, "findings": [],
              "coverage": {"filesExpected": 1, "filesAnalyzed": 1, "entitiesExpected": 1, "entitiesAnalyzed": 1},
              "skips": [], "verdict": "PASS", "ruleDiscovery": {"status": "NO_SUGGESTION"}}
    return report, independent


def finding(report, finding_id="synthetic-finding"):
    return {"findingId": finding_id, "reviewId": report["reviewId"], "snapshotId": report["scope"]["headSha"],
            "source": "AI_REVIEW", "categoryId": "opaque_names", "location": {"path": "sample.py", "startLine": 1, "endLine": 2},
            "evidence": ["Synthetic unit fixture: def sample(a): return a"],
            "description": "Synthetic unit-test observation.", "recommendation": "Use a domain-specific name.",
            "metricRelation": "INSUFFICIENT_DATA", "reviewStatus": "PENDING_FEEDBACK"}


def matched_fixture():
    """Synthetic Core receipts: two logical groups and four snapshot entities."""
    report, independent = fixture()
    report["scope"]["paths"] = ["sample.py", "other.py"]
    independent["scope"] = copy.deepcopy(report["scope"])
    independent["coverage"] = {"filesExpected": 2, "filesReviewed": 2, "entitiesExpected": 4,
                               "entitiesReviewed": 4, "entityUnit": "SNAPSHOT_ENTITY"}
    report["independentReview"]["coverage"] = copy.deepcopy(independent["coverage"])
    report["coverage"] = {"filesExpected": 2, "filesAnalyzed": 2, "entitiesExpected": 2,
                          "entitiesAnalyzed": 2, "entityUnit": "MATCH_GROUP"}
    original_metrics = report["metrics"]
    report["metrics"], report["entityMatches"], files = [], [], []
    for name in ("sample", "other"):
        path = name + ".py"
        def entity(parameter):
            return {"signature": f"{name}({parameter})", "lines": {"startLine": 1, "endLine": 3},
                    "matchingKey": name, "matchingAmbiguous": False}
        match = {"key": name, "status": "MATCHED", "before": [entity("value")], "after": [entity("renamed")]}
        report["entityMatches"].append({"path": path, "oldPath": path, "newPath": path, **copy.deepcopy(match)})
        rows = []
        for original in original_metrics:
            metric = copy.deepcopy(original)
            metric.update(path=path, entity=f"{name}(renamed)")
            report["metrics"].append(metric)
            rows.append({key: copy.deepcopy(value) for key, value in metric.items() if key != "path"})
        files.append({"oldPath": path, "newPath": path, "changedMethods": [f"{name}(renamed)"],
                      "metrics": rows, "matches": [match]})
    receipt = {"baseSha": report["scope"]["baseSha"], "headSha": report["scope"]["headSha"],
               "status": "ok", "warnings": [], "files": files}
    trace = [{"event": "independent_review_frozen", "findings": []},
             {"event": "tool_call", "tool": "analyze_python_changes", "result": receipt}]
    return report, independent, trace


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.report, self.independent = fixture()

    def test_complete_synthetic_report_is_valid(self):
        self.assertIs(self.report, ARTIFACTS.validate(self.report, self.independent))

    def test_final_file_denominator_cannot_shrink_selected_scope(self):
        self.report["coverage"].update(filesExpected=0, filesAnalyzed=0)
        with self.assertRaisesRegex(ValueError, "denominator"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_independent_file_denominator_cannot_shrink_selected_scope(self):
        self.independent["coverage"].update(filesExpected=0, filesReviewed=0)
        self.report["independentReview"]["coverage"].update(filesExpected=0, filesReviewed=0)
        with self.assertRaisesRegex(ValueError, "denominator"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_unknown_counts_are_accepted_as_incomplete(self):
        self.report["coverage"].update(entitiesExpected=None, entitiesAnalyzed=None)
        self.report["independentReview"]["coverage"].update(entitiesExpected=None, entitiesReviewed=None)
        self.independent["coverage"].update(entitiesExpected=None, entitiesReviewed=None)
        self.report["independentReview"]["status"] = self.independent["status"] = "INCOMPLETE"
        self.report["verdict"] = "INCOMPLETE"
        ARTIFACTS.validate(self.report, self.independent)
        self.report["verdict"] = "PASS"
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)

    def test_omitted_required_metric_rejects_complete_verdict(self):
        self.report["metrics"].pop()
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)
        self.report["verdict"] = "INCOMPLETE"
        self.report["skips"] = [{"stage": "metrics", "reason": "Synthetic analyzer omitted return_count."}]
        ARTIFACTS.validate(self.report, self.independent)

    def test_frozen_artifact_is_idempotent_but_not_replaceable(self):
        with TemporaryDirectory(prefix="codeclarity-artifact-test-") as directory:
            path = Path(directory) / "independent.json"
            payload = ARTIFACTS.canonical(self.independent)
            ARTIFACTS.write_new(path, payload)
            ARTIFACTS.write_new(path, payload)
            changed = copy.deepcopy(self.independent)
            changed["status"] = "INCOMPLETE"
            with self.assertRaises(ValueError):
                ARTIFACTS.write_new(path, ARTIFACTS.canonical(changed))
            self.assertEqual(payload, path.read_bytes())

    def test_final_alias_preserves_original_independent_finding(self):
        original = finding(self.report)
        self.independent["findings"] = [original]
        self.report["independentReview"]["findings"] = [copy.deepcopy(original)]
        final = copy.deepcopy(original)
        final.update(findingId="canonical-finding", categoryId="domain_naming", originFindingIds=[original["findingId"]])
        self.report["findings"] = [final]
        self.report["verdict"] = "WARN"
        ARTIFACTS.validate(self.report, self.independent)
        final.pop("originFindingIds")
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)

    def test_frozen_observation_cannot_be_rewritten(self):
        original = finding(self.report)
        self.independent["findings"] = [copy.deepcopy(original)]
        self.report["independentReview"]["findings"] = [original]
        self.report["findings"] = [copy.deepcopy(original)]
        self.report["verdict"] = "WARN"
        self.report["independentReview"]["findings"][0]["description"] = "Rewritten after seeing metrics"
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)

    def test_no_changes_requires_empty_scope_and_results(self):
        self.report["scope"]["paths"] = []
        self.report["scope"]["languages"] = []
        self.independent["scope"] = copy.deepcopy(self.report["scope"])
        self.report["metrics"] = []
        self.report["coverage"] = {"filesExpected": 0, "filesAnalyzed": 0, "entitiesExpected": 0, "entitiesAnalyzed": 0}
        empty_independent = {"filesExpected": 0, "filesReviewed": 0, "entitiesExpected": 0, "entitiesReviewed": 0}
        self.independent["coverage"] = copy.deepcopy(empty_independent)
        self.report["independentReview"]["coverage"] = empty_independent
        self.report["verdict"] = "NO_CHANGES"
        ARTIFACTS.validate(self.report, self.independent)
        self.report["scope"]["paths"] = ["sample.py"]
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report)

    def test_unsupported_value_never_gets_numeric_delta(self):
        metric = self.report["metrics"][0]
        metric["before"].update(status="UNSUPPORTED", value=None, reason="Synthetic unsupported entity")
        metric.update(status="UNAVAILABLE", delta=None)
        self.report["verdict"] = "INCOMPLETE"
        ARTIFACTS.validate(self.report, self.independent)
        metric["delta"] = 0
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)
        metric["delta"] = None
        metric["before"]["value"] = 0
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)

    def test_new_finding_cannot_claim_human_fix(self):
        self.report["findings"] = [finding(self.report)]
        self.report["verdict"] = "WARN"
        ARTIFACTS.validate(self.report, self.independent)
        self.report["findings"][0]["reviewStatus"] = "FIXED"
        with self.assertRaises(ValueError):
            ARTIFACTS.validate(self.report, self.independent)

    def test_independent_artifact_rejects_current_metric_payload(self):
        self.independent["currentMetrics"] = {"cyclomatic_complexity": 2}
        with self.assertRaises(ValueError):
            ARTIFACTS.check_independent(self.independent)

    def test_no_suggestion_is_silent_in_rendered_markdown(self):
        markdown = ARTIFACTS.render(self.report)
        self.assertNotIn("NO_SUGGESTION", markdown)
        self.assertNotIn("Proposed rule", markdown)

    def test_not_run_main_and_discovery_final_keep_distinct_artifacts(self):
        self.report["ruleDiscovery"] = {"status": "NOT_RUN"}
        ARTIFACTS.validate(self.report, self.independent)
        main_json = ARTIFACTS.canonical(self.report)
        main_markdown = ARTIFACTS.render(self.report).encode("utf-8")
        self.assertNotIn(b"NOT_RUN", main_markdown)
        self.assertNotIn(b"Proposed rule", main_markdown)
        final = copy.deepcopy(self.report)
        # A synthetic unit payload tests artifact separation, not production persistence.
        final["ruleDiscovery"] = {"status": "RULE_SUGGESTED", "candidate": {
            "status": "PROPOSED", "title": "Prefer domain names", "synthetic": True}}
        ARTIFACTS.validate(final, self.independent)
        final_json = ARTIFACTS.canonical(final)
        final_markdown = ARTIFACTS.render(final).encode("utf-8")
        self.assertIn(b"Proposed rule", final_markdown)
        with TemporaryDirectory(prefix="codeclarity-discovery-artifact-test-") as directory:
            root = Path(directory)
            ARTIFACTS.write_new(root / "report.main.json", main_json)
            ARTIFACTS.write_new(root / "report.main.md", main_markdown)
            ARTIFACTS.write_new(root / "review.history-input.json", main_json)
            ARTIFACTS.write_new(root / "discovery.json", ARTIFACTS.canonical(final["ruleDiscovery"]))
            ARTIFACTS.write_new(root / "report.final.json", final_json)
            ARTIFACTS.write_new(root / "report.final.md", final_markdown)
            with self.assertRaises(ValueError):
                ARTIFACTS.write_new(root / "report.main.md", final_markdown)
            with self.assertRaises(ValueError):
                ARTIFACTS.write_new(root / "review.history-input.json", final_json)
            ARTIFACTS.write_new(root / "review.history-input.json", main_json)
            self.assertEqual("NOT_RUN", ARTIFACTS.load(root / "review.history-input.json")["ruleDiscovery"]["status"])
            self.assertEqual(main_json, (root / "report.main.json").read_bytes())
            self.assertEqual(main_markdown, (root / "report.main.md").read_bytes())
            self.assertEqual(final_json, (root / "report.final.json").read_bytes())
            self.assertEqual(final_markdown, (root / "report.final.md").read_bytes())


class MatchCoverageTests(unittest.TestCase):
    def setUp(self):
        self.report, self.independent, self.trace = matched_fixture()

    def test_two_core_groups_allow_four_independent_snapshot_entities(self):
        ARTIFACTS.validate(self.report, self.independent)
        self.assertEqual([], check_report(self.report, self.trace))
        markdown = ARTIFACTS.render(self.report)
        self.assertIn("sample(value)", markdown)
        self.assertIn("sample(renamed)", markdown)
        self.assertIn("SNAPSHOT_ENTITY", markdown)
        self.assertIn("MATCH_GROUP", markdown)

    def test_complete_python_can_pass_and_naming_can_warn(self):
        ARTIFACTS.validate(self.report, self.independent)
        self.assertEqual("PASS", self.report["verdict"])
        self.report["findings"] = [finding(self.report)]
        self.report["findings"][0]["metricRelation"] = "UNRELATED"
        self.report["verdict"] = "WARN"
        ARTIFACTS.validate(self.report, self.independent)
        self.assertEqual([], check_report(self.report, self.trace))

    def test_unverified_identity_keeps_raw_values_without_manufacturing_delta(self):
        match = self.report["entityMatches"][0]
        match["status"] = "UNVERIFIED"
        for side in ("before", "after"):
            match[side][0]["matchingWarning"] = "Synthetic positional owner: cross-snapshot identity unverified"
        raw = []
        for row in self.report["metrics"]:
            if row["path"] == match["path"]:
                raw.append(copy.deepcopy((row["before"], row["after"])))
                row.update(status="UNAVAILABLE", delta=None)
        self.report["verdict"] = "INCOMPLETE"
        self.report["skips"] = [{"stage": "matching", "path": match["path"],
                                 "reason": match["after"][0]["matchingWarning"]}]
        ARTIFACTS.validate(self.report, self.independent)
        self.assertEqual(raw, [(row["before"], row["after"]) for row in self.report["metrics"] if row["path"] == match["path"]])
        self.assertIn("UNAVAILABLE", ARTIFACTS.render(self.report))
        self.report["verdict"] = "PASS"
        with self.assertRaisesRegex(ValueError, "Complete verdict"):
            ARTIFACTS.validate(self.report, self.independent)
        self.report["verdict"] = "INCOMPLETE"
        self.report["metrics"][0]["delta"] = 1
        with self.assertRaisesRegex(ValueError, "Delta contradicts"):
            ARTIFACTS.validate(self.report, self.independent)
        self.report["metrics"][0].update(status="COMPARED", delta=1)
        with self.assertRaisesRegex(ValueError, "comparison status"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_matching_warning_cannot_be_presented_as_a_matched_pair(self):
        self.report["entityMatches"][0]["before"][0]["matchingWarning"] = "Synthetic identity warning"
        with self.assertRaisesRegex(ValueError, "unverified identity"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_outside_or_unknown_core_line_coverage_cannot_be_pass(self):
        complete = {"status": "COMPLETE", "outsideEntityLines": [], "reason": None}
        self.report["fileCoverage"] = [{"path": path, "oldPath": path, "newPath": path,
                                        "base": copy.deepcopy(complete), "head": copy.deepcopy(complete)}
                                       for path in self.report["scope"]["paths"]]
        ARTIFACTS.validate(self.report, self.independent)
        for status, spans in (("OUTSIDE_SUPPORTED_ENTITIES", [{"startLine": 4, "endLine": 5}]), ("UNKNOWN", [])):
            with self.subTest(status=status):
                self.report["fileCoverage"][0]["head"] = {"status": status, "outsideEntityLines": spans,
                                                          "reason": "Synthetic field-only or failed coverage"}
                retained = copy.deepcopy(self.report["fileCoverage"])
                self.report["verdict"] = "INCOMPLETE"
                self.report["skips"] = [{"stage": "coverage", "path": "sample.py", "reason": retained[0]["head"]["reason"]}]
                ARTIFACTS.validate(self.report, self.independent)
                self.assertEqual(retained, self.report["fileCoverage"])
                self.assertIn(status, ARTIFACTS.render(self.report))
                self.report["verdict"] = "PASS"
                with self.assertRaisesRegex(ValueError, "Complete verdict"):
                    ARTIFACTS.validate(self.report, self.independent)

    def test_file_coverage_cannot_omit_a_selected_path_and_claim_complete(self):
        complete = {"status": "COMPLETE", "outsideEntityLines": [], "reason": None}
        self.report["fileCoverage"] = [{"path": "sample.py", "oldPath": "sample.py", "newPath": "sample.py",
                                        "base": complete, "head": complete}]
        self.report["verdict"] = "INCOMPLETE"
        ARTIFACTS.validate(self.report, self.independent)
        self.report["verdict"] = "PASS"
        with self.assertRaisesRegex(ValueError, "Complete verdict"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_final_group_denominator_cannot_use_union_of_signatures(self):
        self.report["coverage"].update(entitiesExpected=4, entitiesAnalyzed=4)
        self.report["verdict"] = "INCOMPLETE"
        with self.assertRaisesRegex(ValueError, "match groups"):
            ARTIFACTS.validate(self.report, self.independent)
        self.assertTrue(any("Core match groups" in error for error in check_report(self.report, self.trace)))

    def test_modified_or_omitted_core_pair_is_rejected(self):
        self.report["entityMatches"][0]["before"][0]["lines"]["endLine"] = 2
        self.assertTrue(any("exact Core receipts" in error for error in check_report(self.report, self.trace)))
        self.report.pop("entityMatches")
        self.assertTrue(any("omitted" in error for error in check_report(self.report, self.trace)))

    def test_invalid_matched_candidates_or_source_ranges_are_rejected(self):
        self.report["entityMatches"][0]["after"][0]["lines"]["startLine"] = 0
        with self.assertRaisesRegex(ValueError, "line range"):
            ARTIFACTS.validate(self.report, self.independent)
        self.report["entityMatches"][0]["after"][0]["lines"]["startLine"] = 1
        self.report["entityMatches"][0]["before"].append(copy.deepcopy(self.report["entityMatches"][0]["before"][0]))
        with self.assertRaisesRegex(ValueError, "one entity"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_metrics_cannot_relabel_a_matched_group_to_old_signature(self):
        self.report["metrics"][0]["entity"] = "sample(value)"
        with self.assertRaisesRegex(ValueError, "no supplied Core match"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_cognitive_error_preserves_five_other_values(self):
        for row in self.report["metrics"]:
            if row["metric"] == "cognitive_complexity":
                row["before"].update(status="ERROR", value=None, reason="Synthetic missing dependency")
                row["after"].update(status="ERROR", value=None, reason="Synthetic missing dependency")
                row.update(status="UNAVAILABLE", delta=None)
        self.report["verdict"] = "INCOMPLETE"
        ARTIFACTS.validate(self.report, self.independent)
        self.assertEqual(10, sum(row["after"]["status"] == "AVAILABLE" for row in self.report["metrics"]))
        self.report["verdict"] = "PASS"
        with self.assertRaisesRegex(ValueError, "Complete verdict"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_frozen_snapshot_entity_denominator_remains_separate_and_verifiable(self):
        self.report["independentReview"]["coverage"].update(entitiesExpected=2, entitiesReviewed=2)
        self.independent["coverage"].update(entitiesExpected=2, entitiesReviewed=2)
        self.assertTrue(any("snapshot occurrences" in error for error in check_report(self.report, self.trace)))

    def test_mixed_scope_with_missing_java_metrics_is_incomplete(self):
        # The shape is a supplied synthetic receipt; no Java metric is calculated here.
        self.report["scope"]["languages"] = ["java", "python"]
        self.report["scope"]["paths"][1] = "Other.java"
        self.independent["scope"] = copy.deepcopy(self.report["scope"])
        match = self.report["entityMatches"][1]
        match.update(path="Other.java", oldPath="Other.java", newPath="Other.java", key="Other#other()")
        for side in ("before", "after"):
            match[side][0].update(signature="Other#other()", matchingKey="Other#other()")
        self.report["metrics"] = [row for row in self.report["metrics"] if row["path"] != "other.py"
                                  or row["metric"] in ("cyclomatic_complexity", "cognitive_complexity")]
        for row in self.report["metrics"]:
            if row["path"] == "other.py":
                row.update(path="Other.java", entity="Other#other()")
                for side in ("before", "after"):
                    row[side]["definition"].update(language="java", analyzer="synthetic-java-unit-fixture/1", algorithm="synthetic-java/1")
        self.report["skips"] = [{"stage": "metrics", "path": "Other.java", "reason": "Synthetic Java adapter has two metrics only"}]
        self.report["verdict"] = "INCOMPLETE"
        ARTIFACTS.validate(self.report, self.independent)
        self.report["verdict"] = "PASS"
        with self.assertRaisesRegex(ValueError, "Complete verdict"):
            ARTIFACTS.validate(self.report, self.independent)

    def test_committed_source_range_preserves_leading_blank_lines(self):
        with TemporaryDirectory(prefix="codeclarity-range-check-") as directory:
            root = Path(directory)
            git(root, "init", "-b", "main")
            hooks = root / "empty-hooks"
            hooks.mkdir()
            for key, value in (("user.name", "Synthetic range test"), ("user.email", "range@example.invalid"),
                               ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks)), ("core.autocrlf", "false")):
                git(root, "config", key, value)
            for name in ("sample", "other"):
                (root / (name + ".py")).write_text(f"\n\n\ndef {name}(value):\n    return value\n\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "Synthetic line range fixture")
            sha = git(root, "rev-parse", "HEAD")
            self.report["scope"].update(baseSha=sha, headSha=sha, snapshotId=sha)
            self.independent["scope"] = copy.deepcopy(self.report["scope"])
            receipt = self.trace[1]["result"]
            receipt.update(baseSha=sha, headSha=sha)
            for normalized, file in zip(self.report["entityMatches"], receipt["files"]):
                for side in ("before", "after"):
                    normalized[side][0]["lines"].update(startLine=4, endLine=5)
                    file["matches"][0][side][0]["lines"].update(startLine=4, endLine=5)
            self.assertEqual([], check_report(self.report, self.trace, root))


class DiscoveryRecordTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="codeclarity-discovery-record-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "discovery.json"
        self.review_id = "synthetic-discovery-link-review"
        self.rules = {"status": "NO_SUGGESTION", "reason": "Synthetic history has no confirmed fixes"}
        self.record = {"reviewId": self.review_id, **self.rules}
        self.path.write_text(json.dumps(self.record), encoding="utf-8")

    def test_relative_and_absolute_artifact_links_do_not_require_record_self_reference(self):
        self.assertNotIn("artifact", self.record)
        for link in (self.path.name, str(self.path.resolve())):
            with self.subTest(link=link):
                rules = {**self.rules, "artifact": link}
                self.assertEqual([], discovery_errors(rules, self.record, self.review_id, self.path))

    def test_link_to_another_discovery_file_is_rejected(self):
        wrong = self.path.with_name("different-discovery.json")
        wrong.write_text(json.dumps(self.record), encoding="utf-8")
        for link in (wrong.name, str(wrong.resolve())):
            with self.subTest(link=link):
                errors = discovery_errors({**self.rules, "artifact": link}, self.record, self.review_id, self.path)
                self.assertTrue(any("different file" in error for error in errors), errors)

    def test_link_does_not_hide_changed_status_reason_or_review_identity(self):
        rules = {**self.rules, "artifact": self.path.name}
        for key, value in (("status", "ERROR"), ("reason", "Altered decision rationale"),
                           ("reviewId", "another-review")):
            with self.subTest(field=key):
                record = {**self.record, key: value}
                errors = discovery_errors(rules, record, self.review_id, self.path)
                self.assertTrue(any("differs" in error for error in errors), errors)

    def test_legacy_decision_without_artifact_link_remains_valid(self):
        self.assertEqual([], discovery_errors(self.rules, self.record, self.review_id, self.path))
        self.assertEqual([], discovery_errors(self.rules, self.rules, self.review_id, self.path))

    def test_empty_or_non_string_artifact_link_is_rejected(self):
        for link in ("", None, 3):
            with self.subTest(link=link):
                errors = discovery_errors({**self.rules, "artifact": link}, self.record, self.review_id, self.path)
                self.assertIn("Invalid discovery artifact link", errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
