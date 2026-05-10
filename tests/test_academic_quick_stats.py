from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHOLAR_STATS_PATH = ROOT / "skills" / "academic_impact_analyzer" / "scholar_stats.py"
PERSON_CANDIDATES_PATH = ROOT / "skills" / "academic_impact_analyzer" / "person_candidates.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcademicQuickStatsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = load_module(SCHOLAR_STATS_PATH, "test_academic_quick_stats_module")
        cls.people = load_module(PERSON_CANDIDATES_PATH, "test_academic_person_candidates_module")

    def test_matches_ccf_top_unmatched_and_long_proceedings_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "venue_tiers.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "name": "International Conference on Machine Learning",
                                "tier": "A",
                                "tier_system": "CCF",
                                "aliases": ["ICML"],
                            },
                            {
                                "name": "IEEE International Conference on Software Maintenance and Evolution",
                                "tier": "B",
                                "tier_system": "CCF",
                                "aliases": ["ICSME"],
                            },
                            {
                                "name": "International Conference on Web Engineering",
                                "tier": "C",
                                "tier_system": "CCF",
                                "aliases": ["ICWE"],
                            },
                            {
                                "name": "International Symposium on Software Testing and Analysis",
                                "tier": "A",
                                "tier_system": "CCF",
                                "aliases": ["ISSTA"],
                            },
                            {
                                "name": "Advances in Neural Information Processing Systems",
                                "tier": "top",
                                "tier_label": "Top venue seed",
                                "aliases": ["NeurIPS"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                self.stats.match_venue_tier("ICML", registry_path=str(registry_path))["tier"],
                "CCF-A",
            )
            self.assertEqual(
                self.stats.match_venue_tier("ICSME", registry_path=str(registry_path))["tier"],
                "CCF-B",
            )
            self.assertEqual(
                self.stats.match_venue_tier("ICWE", registry_path=str(registry_path))["tier"],
                "CCF-C",
            )
            self.assertEqual(
                self.stats.match_venue_tier("NeurIPS", registry_path=str(registry_path))["tier"],
                "Top",
            )
            self.assertFalse(
                self.stats.match_venue_tier("Workshop on Tiny Datasets", registry_path=str(registry_path))["matched"]
            )
            long_name = "Proceedings of the 31st ACM SIGSOFT International Symposium on Software Testing and Analysis"
            self.assertEqual(
                self.stats.match_venue_tier(long_name, registry_path=str(registry_path))["canonical_name"],
                "International Symposium on Software Testing and Analysis",
            )

    def test_person_registry_matches_aliases_as_pending_and_marks_homonym_risk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "person_tag_registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "name": "Andrew Yao",
                                "aliases": ["Andrew Chi-Chih Yao"],
                                "tags": [
                                    {"type": "acm_fellow", "source_links": ["https://example.com/acm"]},
                                    {"type": "godel_prize", "source_links": ["https://example.com/godel"]},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidates = self.people.build_candidates(
                [{"id": "P001", "title": "Theory Builders", "authors": ["Andrew Chi-Chih Yao"]}],
                registry_path=str(registry_path),
            )

            self.assertEqual({candidate["tag_type"] for candidate in candidates}, {"acm_fellow", "godel_prize"})
            self.assertTrue(all(candidate["status"] == "pending" for candidate in candidates))
            self.assertTrue(all(candidate["evidence"][0]["match_type"] == "alias" for candidate in candidates))
            self.assertTrue(all(candidate["homonym_risk"] for candidate in candidates))

    def test_quick_stats_counts_person_review_statuses(self):
        session = {
            "target": {"citationCount": 99},
            "papers": [
                {"id": "P001", "title": "A", "venue": "NeurIPS", "year": 2024, "context_confidence": "high"},
                {"id": "P002", "title": "B", "venue": "Unknown Venue", "year": 2023, "context_confidence": "medium"},
            ],
            "person_candidates": [
                {"status": "pending", "matched_paper_ids": ["P001"]},
                {"status": "confirmed", "matched_paper_ids": ["P002"]},
                {"status": "rejected", "matched_paper_ids": ["P002"]},
            ],
        }

        quick_stats = self.stats.build_quick_stats(session)

        self.assertEqual(quick_stats["publication_statistics"]["paper_count"], 2)
        self.assertEqual(quick_stats["citation_statistics"]["person_status_counts"]["pending"], 1)
        self.assertEqual(quick_stats["citation_statistics"]["person_status_counts"]["confirmed"], 1)
        self.assertEqual(quick_stats["citation_statistics"]["person_status_counts"]["rejected"], 1)


if __name__ == "__main__":
    unittest.main()
