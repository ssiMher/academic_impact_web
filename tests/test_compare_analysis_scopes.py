from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "compare_analysis_scopes.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CompareAnalysisScopesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = load_module(SCRIPT_PATH, "test_compare_analysis_scopes_module")

    def write_session(self, session_dir: Path) -> None:
        session_dir.mkdir(parents=True)
        payload = {
            "session_id": "session-demo",
            "query": "target paper",
            "target": {"title": "Target Paper", "year": 2024, "externalIds": {}},
            "papers": [
                {
                    "id": "P001",
                    "title": "Citing Paper 1",
                    "paper": {"title": "Citing Paper 1", "year": 2025},
                    "download_probe": {"local_file_path": str(session_dir / "p001.pdf")},
                },
                {
                    "id": "P002",
                    "title": "Citing Paper 2",
                    "paper": {"title": "Citing Paper 2", "year": 2025},
                    "download_probe": {"local_file_path": str(session_dir / "p002.pdf")},
                },
            ],
        }
        (session_dir / "session.json").write_text(json.dumps(payload), encoding="utf-8")
        (session_dir / "contexts.json").write_text("{}", encoding="utf-8")

    def test_select_paper_ids_validates_ids(self):
        session = {
            "papers": [
                {"id": "P001"},
                {"id": "P002"},
                {"id": "P003"},
            ]
        }
        self.assertEqual(self.benchmark.select_paper_ids(session, [], 2), ["P001", "P002"])
        self.assertEqual(self.benchmark.select_paper_ids(session, ["P003"], 2), ["P003"])

        with self.assertRaises(ValueError):
            self.benchmark.select_paper_ids(session, ["P004"], 2)

    def test_run_benchmark_copies_session_and_compares_scopes(self):
        def fake_run_analysis(session_dir: Path, ids: list[str], top_k_spans: int, analysis_scope: str):
            session_path = session_dir / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            for item in session["papers"]:
                if item["id"] not in ids:
                    continue
                analysis_dir = session_dir / "analysis" / f"{item['id']}_{analysis_scope}"
                analysis_dir.mkdir(parents=True, exist_ok=True)
                analysis_path = analysis_dir / "fulltext_analysis.json"
                candidate_path = analysis_dir / "candidate_spans.json"
                finding_count = 1 if analysis_scope == "candidate_spans" else 2
                analysis_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "analysis_scope": analysis_scope,
                            "findings": [{"aspect": "baseline"} for _ in range(finding_count)],
                            "_debug": {"analysis_scope": analysis_scope, "prompt_chars": 1000 + finding_count},
                        }
                    ),
                    encoding="utf-8",
                )
                candidate_path.write_text(
                    json.dumps({"ok": True, "spans": [{"page": 1}, {"page": 2}]}),
                    encoding="utf-8",
                )
                item["analysis_result"] = {
                    "status": "fulltext_analyzed",
                    "paths": {
                        "analysis": str(analysis_path),
                        "candidate_spans": str(candidate_path),
                    },
                }
            session_path.write_text(json.dumps(session), encoding="utf-8")
            return {"ok": True, "processed_papers": len(ids), "analysis_scope": analysis_scope}

        def fake_detail_for_paper(session: dict, paper_id: str):
            item = next(item for item in session["papers"] if item["id"] == paper_id)
            analysis_path = Path(item["analysis_result"]["paths"]["analysis"])
            analysis_data = json.loads(analysis_path.read_text(encoding="utf-8"))
            finding_count = len(analysis_data["findings"])
            return {
                "id": paper_id,
                "analysis_status": item["analysis_result"]["status"],
                "citation_method_summary": {
                    "labels": ["baseline"],
                    "evidence_excerpt": "The target is used as a baseline.",
                },
                "citation_trace": {
                    "finding_count": finding_count,
                    "candidate_span_count": 2,
                    "debug": analysis_data["_debug"],
                },
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            source_session_dir = Path(tmpdir) / "source"
            output_dir = Path(tmpdir) / "benchmark"
            self.write_session(source_session_dir)

            with mock.patch.object(self.benchmark.impact_cli, "run_analysis", side_effect=fake_run_analysis), \
                    mock.patch.object(self.benchmark, "detail_for_paper", side_effect=fake_detail_for_paper):
                payload = self.benchmark.run_benchmark(
                    session_dir=source_session_dir,
                    paper_ids=["P001"],
                    scopes=["candidate_spans", "fulltext_direct"],
                    top_k_spans=8,
                    concurrency=2,
                    output_dir=output_dir,
                    gold_path=None,
                )

            original_session = json.loads((source_session_dir / "session.json").read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["paper_count"], 1)
        self.assertEqual(len(payload["runs"]), 2)
        self.assertIn("candidate_spans", payload["scope_summary"])
        self.assertIn("fulltext_direct", payload["scope_summary"])
        self.assertEqual(payload["comparisons"][0]["finding_count_delta"], 1)
        self.assertNotIn("analysis_result", original_session["papers"][0])

    def test_gold_evaluator_uses_raw_findings_not_summary_excerpt(self):
        detail = {
            "analysis_status": "reference_only",
            "citation_method_summary": {
                "labels": ["reference_only"],
                "evidence_excerpt": "Vaswani et al. appears only in References.",
            },
            "citation_trace": {"finding_count": 0},
        }
        expected = {
            "final_status": "fulltext_no_finding",
            "has_findings": False,
            "min_labels": [],
        }

        result = self.benchmark.evaluate_against_gold(detail, expected, {"findings": []})

        self.assertTrue(result["passed"])
        self.assertEqual(result["actual"]["final_status"], "reference_only")
        self.assertEqual(result["actual"]["normalized_status"], "fulltext_no_finding")
        self.assertFalse(result["actual"]["has_findings"])

    def test_gold_evaluator_ignores_keep_false_aspect_labels(self):
        detail = {
            "analysis_status": "mention_only",
            "citation_method_summary": {
                "labels": ["method", "grouped_literature_mention"],
                "evidence_excerpt": "Grouped literature mention.",
            },
            "citation_trace": {"finding_count": 1},
        }
        analysis = {
            "findings": [
                {
                    "keep": False,
                    "aspect": "method",
                    "mention_type": "grouped_literature_mention",
                }
            ]
        }
        expected = {
            "final_status": "mention_only",
            "has_findings": True,
            "min_labels": ["method"],
        }

        result = self.benchmark.evaluate_against_gold(detail, expected, analysis)

        self.assertFalse(result["passed"])
        self.assertEqual(result["missing_labels"], ["method"])
        self.assertEqual(result["actual"]["labels"], ["grouped_literature_mention"])


if __name__ == "__main__":
    unittest.main()
