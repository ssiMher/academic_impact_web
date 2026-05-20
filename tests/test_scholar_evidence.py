from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_evidence.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarEvidenceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = load_module(EVIDENCE_PATH, "test_scholar_evidence")

    def test_classify_self_citation_detects_overlap(self):
        result = self.evidence.classify_self_citation(
            ["Chen Tian", "Alice"],
            ["Bob", "Tian Chen", "Carol"],
        )

        self.assertEqual(result["status"], "self_citation")
        self.assertEqual(result["overlap_authors"], ["Tian Chen"])

    def test_classify_self_citation_marks_non_self(self):
        result = self.evidence.classify_self_citation(
            ["Chen Tian"],
            ["Grace Hopper"],
        )

        self.assertEqual(result["status"], "non_self_citation")
        self.assertEqual(result["overlap_authors"], [])

    def test_derive_labels_and_score_high_value_evidence(self):
        finding = {
            "citation_text": (
                "This pioneering system is used as a baseline and compared with "
                "our approach because it is effective."
            ),
            "aspect": "baseline",
            "stance": "positive",
            "confidence": 0.9,
        }

        labels = self.evidence.derive_evidence_labels(
            finding,
            citation_char_count=len(finding["citation_text"]),
            person_tag_labels=["ACM Fellow"],
        )
        keywords = self.evidence.derive_highlight_keywords(finding, labels)
        score = self.evidence.score_strong_evidence(
            labels=labels,
            confidence=finding["confidence"],
            citation_char_count=len(finding["citation_text"]),
            person_tag_labels=["ACM Fellow"],
            self_citation_status="non_self_citation",
        )

        self.assertIn("positive_evaluation", labels)
        self.assertIn("first_or_pioneering", labels)
        self.assertIn("baseline", labels)
        self.assertIn("important_person", labels)
        self.assertIn("pioneering", keywords)
        self.assertGreaterEqual(score, 75)
        self.assertEqual(self.evidence.evidence_strength(score), "high")


if __name__ == "__main__":
    unittest.main()
