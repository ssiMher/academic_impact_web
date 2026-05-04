from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_stats.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarStatsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = load_module(STATS_PATH, "test_scholar_stats")

    def test_build_scholar_statistics(self):
        publications = [
            {
                "id": "S001",
                "title": "Paper One",
                "year": 2024,
                "venue": "ACM MobiCom",
                "author_position": "first_author",
                "citation_count": 10,
            },
            {
                "id": "S002",
                "title": "Paper Two",
                "year": 2023,
                "venue": "IEEE Transactions on Mobile Computing",
                "author_position": "middle_author",
                "citation_count": 5,
            },
        ]
        citation_edges = [
            {
                "source_publication_id": "S001",
                "citing_title": "Citing One",
                "citing_venue": "ACM MobiCom",
                "citing_year": 2025,
                "citing_authors": ["Alice Fellow"],
            },
            {
                "source_publication_id": "S002",
                "citing_title": "Citing Two",
                "citing_venue": "Unknown Venue",
                "citing_year": 2025,
                "citing_authors": ["Bob"],
            },
        ]
        person_candidates = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "matched_paper_ids": ["C000001"],
                "status": "pending",
            }
        ]

        result = self.stats.build_scholar_statistics(
            publications, citation_edges, person_candidates
        )

        self.assertEqual(result["publication_count"], 2)
        self.assertEqual(result["first_author_publication_count"], 1)
        self.assertEqual(result["total_citation_count"], 15)
        self.assertEqual(result["citation_edge_count"], 2)
        self.assertEqual(result["top_publications"][0]["title"], "Paper One")
        self.assertEqual(result["person_tag_statistics"][0]["tag_label"], "ACM Fellow")
        self.assertEqual(result["strong_evidence_count"], 0)

    def test_person_tag_statistics_omits_empty_groups(self):
        self.assertEqual(self.stats.person_tag_statistics([]), [])

    def test_person_tag_statistics_groups_present_candidates_with_counts(self):
        candidates = [
            {
                "candidate_id": "acm_fellow::alice",
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "status": "pending",
                "matched_paper_ids": ["C001", "C002"],
                "source_links": ["https://example.test/alice"],
            },
            {
                "candidate_id": "acm_fellow::bob",
                "name": "Bob Fellow",
                "tag_type": "acm_fellow",
                "status": "confirmed",
                "matched_paper_ids": ["C002", "C003"],
                "source_links": [],
            },
            {
                "candidate_id": "acm_fellow::carol",
                "name": "Carol Fellow",
                "tag_type": "acm_fellow",
                "status": "rejected",
                "matched_paper_ids": ["C004"],
                "source_links": ["https://example.test/carol"],
            },
            {
                "candidate_id": "acm_fellow::dana",
                "name": "Dana Fellow",
                "tag_type": "acm_fellow",
                "status": "source_complete",
                "matched_paper_ids": ["C005"],
                "source_links": ["https://example.test/dana"],
            },
            {
                "candidate_id": "acm_fellow::erin",
                "name": "Erin Fellow",
                "tag_type": "acm_fellow",
                "status": "pending",
                "matched_paper_ids": ["C006"],
                "source_links": [],
            },
            {
                "candidate_id": "acm_fellow::frank",
                "name": "Frank Fellow",
                "tag_type": "acm_fellow",
                "status": "pending",
                "matched_paper_ids": ["C007"],
                "source_links": [],
            },
        ]

        result = self.stats.person_tag_statistics(candidates)

        self.assertEqual(len(result), 1)
        group = result[0]
        self.assertEqual(group["tag_type"], "acm_fellow")
        self.assertEqual(group["tag_label"], "ACM Fellow")
        self.assertEqual(group["count"], 6)
        self.assertEqual(group["confirmed_count"], 1)
        self.assertEqual(group["pending_count"], 3)
        self.assertEqual(group["rejected_count"], 1)
        self.assertEqual(group["source_complete_count"], 3)
        self.assertEqual(group["matched_paper_count"], 7)
        self.assertEqual(len(group["candidates"]), 5)

    def test_build_person_candidates_from_citation_edges_uses_citing_authors(self):
        citation_edges = [
            {
                "citing_paper_id": "C001",
                "citing_title": "Fellow Citation",
                "citing_authors": ["Alice Fellow", "Regular Author"],
            },
            {
                "citing_paper_id": "C001",
                "citing_title": "Fellow Citation",
                "citing_authors": ["Alice Fellow"],
            },
        ]
        registry = {
            "items": [
                {
                    "name": "Alice Fellow",
                    "tag_type": "acm_fellow",
                    "source_links": ["https://example.test/alice"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            candidates = self.stats.build_person_candidates_from_citation_edges(
                citation_edges,
                registry_path=str(registry_path),
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "Alice Fellow")
        self.assertEqual(candidates[0]["tag_label"], "ACM Fellow")
        self.assertEqual(candidates[0]["matched_paper_ids"], ["C001"])
        self.assertEqual(candidates[0]["matched_paper_titles"], ["Fellow Citation"])

    def test_build_deep_analysis_queue_prioritizes_fellow_and_top_venue(self):
        citation_edges = [
            {
                "source_publication_id": "S001",
                "citing_title": "Fellow Citation",
                "citing_venue": "Unknown Venue",
                "citing_authors": ["Alice Fellow"],
            },
            {
                "source_publication_id": "S002",
                "citing_title": "Top Venue Citation",
                "citing_venue": "ACM MobiCom",
                "citing_authors": ["Regular Author"],
            },
        ]
        person_candidates = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "matched_paper_ids": [],
                "status": "pending",
            }
        ]

        queue = self.stats.build_deep_analysis_queue(
            citation_edges, person_candidates, limit=10
        )

        self.assertEqual(queue[0]["citing_title"], "Fellow Citation")
        self.assertIn("person_tag:ACM Fellow", queue[0]["reasons"])
        self.assertTrue(
            any(item["citing_title"] == "Top Venue Citation" for item in queue)
        )

    def test_build_deep_analysis_queue_ignores_rejected_person_tags(self):
        citation_edges = [
            {
                "source_publication_id": "S001",
                "citing_title": "Rejected Fellow Citation",
                "citing_venue": "Unknown Venue",
                "citing_authors": ["Alice Fellow"],
            }
        ]
        person_candidates = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "status": "rejected",
            }
        ]

        queue = self.stats.build_deep_analysis_queue(
            citation_edges, person_candidates, limit=10
        )

        self.assertEqual(queue, [])

    def test_build_deep_analysis_queue_groups_duplicate_citing_papers(self):
        citation_edges = [
            {
                "source_publication_id": "S001",
                "cited_publication_title": "Target One",
                "citing_paper_id": "C001",
                "citing_title": "Shared Citing Paper",
                "citing_venue": "ACM MobiCom",
                "citing_authors": ["Regular Author"],
            },
            {
                "source_publication_id": "S002",
                "cited_publication_title": "Target Two",
                "citing_paper_id": "C001",
                "citing_title": "Shared Citing Paper",
                "citing_venue": "ACM MobiCom",
                "citing_authors": ["Regular Author"],
            },
        ]

        queue = self.stats.build_deep_analysis_queue(
            citation_edges,
            person_candidates=[],
            limit=10,
        )

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["citing_title"], "Shared Citing Paper")
        self.assertEqual(queue[0]["cited_publication_count"], 2)
        self.assertEqual(queue[0]["source_publication_ids"], ["S001", "S002"])
        self.assertEqual(
            queue[0]["cited_publication_titles"],
            ["Target One", "Target Two"],
        )
        self.assertEqual(queue[0]["reasons"], ["venue:CCF A"])


if __name__ == "__main__":
    unittest.main()
