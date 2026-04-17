from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "fulltext_gold_workflow.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FulltextGoldWorkflowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_module(SCRIPT_PATH, "test_fulltext_gold_workflow_module")

    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def make_benchmark_report(self, root: Path) -> Path:
        candidate_analysis = root / "candidate" / "fulltext_analysis.json"
        fulltext_analysis = root / "fulltext" / "fulltext_analysis.json"
        self.write_json(
            candidate_analysis,
            {
                "findings": [
                    {
                        "aspect": "background",
                        "evidence_excerpt": "The target work is introduced as background.",
                        "confidence": 0.8,
                    }
                ]
            },
        )
        self.write_json(
            fulltext_analysis,
            {
                "findings": [
                    {
                        "aspect": "method",
                        "evidence_excerpt": "The target architecture is used in the method.",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        report_path = root / "report.json"
        self.write_json(
            report_path,
            {
                "session_id": "session-demo",
                "paper_ids": ["P001"],
                "runs": [
                    {
                        "paper_id": "P001",
                        "title": "Citing Paper",
                        "scope": "candidate_spans",
                        "ok": True,
                        "wall_seconds": 10.5,
                        "actual": {
                            "analysis_status": "mention_only",
                            "labels": ["background"],
                            "has_findings": True,
                            "finding_count": 1,
                        },
                        "paths": {"analysis": str(candidate_analysis)},
                    },
                    {
                        "paper_id": "P001",
                        "title": "Citing Paper",
                        "scope": "fulltext_direct",
                        "ok": True,
                        "wall_seconds": 22.0,
                        "actual": {
                            "analysis_status": "fulltext_analyzed",
                            "labels": ["method"],
                            "has_findings": True,
                            "finding_count": 1,
                        },
                        "paths": {"analysis": str(fulltext_analysis)},
                    },
                ],
            },
        )
        return report_path

    def fill_expected(self, template: dict) -> dict:
        payload = json.loads(json.dumps(template))
        payload["samples"][0]["expected"] = {
            "final_status": "fulltext_analyzed",
            "has_findings": True,
            "min_labels": ["method"],
        }
        return payload

    def test_build_template_from_benchmark_report_includes_both_scopes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report_path = self.make_benchmark_report(tmp)

            payload = self.workflow.build_template_from_benchmark(report_path, ids=[], top_n=0)

        self.assertEqual(payload["source"]["type"], "benchmark_report")
        self.assertEqual(len(payload["samples"]), 1)
        sample = payload["samples"][0]
        self.assertEqual(sample["session_id"], "session-demo")
        self.assertEqual(sample["paper_id"], "P001")
        self.assertEqual(sample["candidate_spans"]["analysis_status"], "mention_only")
        self.assertEqual(sample["candidate_spans"]["labels"], ["background"])
        self.assertEqual(sample["candidate_spans"]["findings"][0]["aspect"], "background")
        self.assertEqual(sample["fulltext_direct"]["analysis_status"], "fulltext_analyzed")
        self.assertEqual(sample["fulltext_direct"]["labels"], ["method"])
        self.assertEqual(sample["fulltext_direct"]["findings"][0]["aspect"], "method")
        self.assertEqual(
            sample["expected"],
            {"final_status": "", "has_findings": None, "min_labels": []},
        )

    def test_validate_requires_human_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self.workflow.build_template_from_benchmark(self.make_benchmark_report(Path(tmpdir)), [], 0)
            samples, errors = self.workflow.validate_review_template(payload)
            self.assertEqual(samples, [])
            self.assertTrue(any("expected.final_status" in item for item in errors))
            self.assertTrue(any("expected.has_findings" in item for item in errors))

            filled = self.fill_expected(payload)
            samples, errors = self.workflow.validate_review_template(filled)

        self.assertEqual(errors, [])
        self.assertEqual(
            samples,
            [
                {
                    "target_query": "",
                    "session_id": "session-demo",
                    "paper_id": "P001",
                    "title": "Citing Paper",
                    "expected": {
                        "final_status": "fulltext_analyzed",
                        "has_findings": True,
                        "min_labels": ["method"],
                    },
                }
            ],
        )

    def test_validate_accepts_pipeline_failure_statuses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self.workflow.build_template_from_benchmark(self.make_benchmark_report(Path(tmpdir)), [], 0)
            payload["samples"][0]["expected"] = {
                "final_status": "fulltext_extract_failed",
                "has_findings": False,
                "min_labels": [],
            }

            samples, errors = self.workflow.validate_review_template(payload)

        self.assertEqual(errors, [])
        self.assertEqual(samples[0]["expected"]["final_status"], "fulltext_extract_failed")

    def test_append_skips_duplicates_and_keeps_stable_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self.fill_expected(
                self.workflow.build_template_from_benchmark(self.make_benchmark_report(tmp), [], 0)
            )
            review_path = tmp / "review.json"
            gold_path = tmp / "gold.json"
            self.write_json(review_path, payload)
            self.write_json(
                gold_path,
                {
                    "schema_version": "1.0",
                    "description": "demo",
                    "samples": [
                        {
                            "target_query": "Existing",
                            "session_id": "session-existing",
                            "paper_id": "P009",
                            "title": "Existing Paper",
                            "expected": {
                                "final_status": "mention_only",
                                "has_findings": True,
                                "min_labels": ["weak_body_mention"],
                            },
                        }
                    ],
                },
            )

            first = self.workflow.append_review_samples(
                review_path=review_path,
                gold_path=gold_path,
                output_path=None,
                replace_existing=False,
                dry_run=False,
            )
            second = self.workflow.append_review_samples(
                review_path=review_path,
                gold_path=gold_path,
                output_path=None,
                replace_existing=False,
                dry_run=False,
            )
            written = json.loads(gold_path.read_text(encoding="utf-8"))

        self.assertTrue(first["ok"])
        self.assertEqual(first["appended_count"], 1)
        self.assertEqual(first["skipped_duplicate_count"], 0)
        self.assertTrue(second["ok"])
        self.assertEqual(second["appended_count"], 0)
        self.assertEqual(second["skipped_duplicate_count"], 1)
        self.assertEqual(written["schema_version"], "1.0")
        self.assertEqual(written["description"], "demo")
        self.assertEqual(len(written["samples"]), 2)
        self.assertEqual(
            [(item["session_id"], item["paper_id"]) for item in written["samples"]],
            [("session-existing", "P009"), ("session-demo", "P001")],
        )

    def test_append_reports_template_duplicate_samples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self.fill_expected(
                self.workflow.build_template_from_benchmark(self.make_benchmark_report(tmp), [], 0)
            )
            payload["samples"].append(json.loads(json.dumps(payload["samples"][0])))
            review_path = tmp / "review.json"
            gold_path = tmp / "gold.json"
            self.write_json(review_path, payload)

            result = self.workflow.append_review_samples(
                review_path=review_path,
                gold_path=gold_path,
                output_path=None,
                replace_existing=False,
                dry_run=False,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(any("重复样本" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
