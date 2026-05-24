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

    def test_classify_self_citation_detects_inverted_initial_name(self):
        result = self.evidence.classify_self_citation(
            ["Jingyi Ning", "Lei Xie 0004"],
            ["Ning J."],
        )

        self.assertEqual(result["status"], "self_citation")
        self.assertEqual(result["overlap_authors"], ["Ning J."])

    def test_classify_self_citation_marks_non_self(self):
        result = self.evidence.classify_self_citation(
            ["Chen Tian"],
            ["Grace Hopper"],
        )

        self.assertEqual(result["status"], "non_self_citation")

    def test_classify_third_party_citation_marks_extra_excluded_author(self):
        result = self.evidence.classify_third_party_citation(
            source_authors=["Jingyi Ning"],
            citing_authors=["Lei Xie", "External Author"],
            selected_author_names=["Jingyi Ning"],
            extra_excluded_authors=["Lei Xie"],
            extra_excluded_affiliations=[],
            citing_affiliations=[],
        )

        self.assertEqual(result["status"], "excluded_collaborator")
        self.assertEqual(result["overlap_authors"], ["Lei Xie"])

    def test_classify_third_party_citation_marks_excluded_affiliation(self):
        result = self.evidence.classify_third_party_citation(
            source_authors=["Jingyi Ning"],
            citing_authors=["External Author"],
            selected_author_names=["Jingyi Ning"],
            extra_excluded_authors=[],
            extra_excluded_affiliations=["Nanjing University"],
            citing_affiliations=["State Key Laboratory, Nanjing University"],
        )

        self.assertEqual(result["status"], "excluded_collaborator")
        self.assertEqual(
            result["overlap_affiliations"],
            ["State Key Laboratory, Nanjing University"],
        )

    def test_classify_third_party_citation_marks_non_self_when_no_exclusion_matches(self):
        result = self.evidence.classify_third_party_citation(
            source_authors=["Jingyi Ning"],
            citing_authors=["External Author"],
            selected_author_names=["Jingyi Ning"],
            extra_excluded_authors=["Lei Xie"],
            extra_excluded_affiliations=["Nanjing University"],
            citing_affiliations=["University of Example"],
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

    def test_refined_labels_are_derived_displayed_and_scored(self):
        finding = {
            "citation_text": (
                "This state-of-the-art method is a representative work. "
                "We extend it and provide a detailed comparison in Table 2, "
                "showing superior results."
            ),
            "aspect": "extension",
            "stance": "positive",
            "confidence": 0.88,
        }

        labels = self.evidence.derive_evidence_labels(
            finding,
            citation_char_count=420,
            person_tag_labels=[],
        )
        keywords = self.evidence.derive_highlight_keywords(finding, labels)
        score = self.evidence.score_strong_evidence(
            labels=labels,
            confidence=finding["confidence"],
            citation_char_count=420,
            person_tag_labels=[],
            self_citation_status="non_self_citation",
        )

        self.assertIn("sota_evaluation", labels)
        self.assertIn("representative_work", labels)
        self.assertIn("detailed_comparison", labels)
        self.assertIn("method_extension", labels)
        self.assertIn("large_context", labels)
        self.assertIn("state-of-the-art", keywords)
        self.assertEqual(self.evidence.evidence_label_display("sota_evaluation"), "最先进 / SOTA")
        self.assertEqual(self.evidence.evidence_label_display("comparison"), "实验对比")
        self.assertGreaterEqual(score, 75)

    def test_review_comment_praise_label_is_supported(self):
        finding = {
            "citation_text": "Reviewer 2 praised the work as excellent and highly novel.",
            "evidence_labels": ["review_comment_praise", "positive_evaluation"],
            "stance": "positive",
        }

        labels = self.evidence.derive_evidence_labels(
            finding,
            citation_char_count=len(finding["citation_text"]),
            person_tag_labels=[],
        )

        self.assertIn("review_comment_praise", labels)
        self.assertEqual(self.evidence.evidence_label_display("review_comment_praise"), "审稿意见亮评")


if __name__ == "__main__":
    unittest.main()
