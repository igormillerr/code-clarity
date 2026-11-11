"""Verify review artifact invariants; fixtures are synthetic, not analyzer results."""

import copy
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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
            ARTIFACTS.write_new(root / "discovery.json", ARTIFACTS.canonical(final["ruleDiscovery"]))
            ARTIFACTS.write_new(root / "report.final.json", final_json)
            ARTIFACTS.write_new(root / "report.final.md", final_markdown)
            with self.assertRaises(ValueError):
                ARTIFACTS.write_new(root / "report.main.md", final_markdown)
            self.assertEqual(main_json, (root / "report.main.json").read_bytes())
            self.assertEqual(main_markdown, (root / "report.main.md").read_bytes())
            self.assertEqual(final_json, (root / "report.final.json").read_bytes())
            self.assertEqual(final_markdown, (root / "report.final.md").read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
