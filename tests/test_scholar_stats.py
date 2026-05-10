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


class VenueTierMatchingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCHOLAR_STATS_PATH, "test_scholar_stats_module")

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.tempdir.name) / "venue_tiers.json"
        self.registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "_comment": "fixture venue tiers",
                    "ccf_import_plan": {
                        "status": "planned",
                        "upstream": "CCF official list",
                    },
                    "items": [
                        {
                            "name": "International Conference on Machine Learning",
                            "tier": "CCF-A",
                            "category": "conference",
                            "source": "ccf_seed",
                            "aliases": ["ICML"],
                        },
                        {
                            "name": "IEEE International Conference on Software Maintenance and Evolution",
                            "tier": "CCF-B",
                            "category": "conference",
                            "source": "ccf_seed",
                            "aliases": ["ICSME"],
                        },
                        {
                            "name": "International Conference on Web Engineering",
                            "tier": "CCF-C",
                            "category": "conference",
                            "source": "ccf_seed",
                            "aliases": ["ICWE"],
                        },
                        {
                            "name": "Advances in Neural Information Processing Systems",
                            "tier": "Top",
                            "category": "conference",
                            "source": "top_seed",
                            "aliases": ["NeurIPS", "NIPS"],
                        },
                        {
                            "name": "International Symposium on Software Testing and Analysis",
                            "tier": "CCF-A",
                            "category": "conference",
                            "source": "ccf_seed",
                            "aliases": ["ISSTA"],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_matches_ccf_a_b_c_and_top_seed(self):
        icml = self.module.match_venue_tier("ICML", registry_path=str(self.registry_path))
        icsme = self.module.match_venue_tier(
            "IEEE International Conference on Software Maintenance and Evolution",
            registry_path=str(self.registry_path),
        )
        icwe = self.module.match_venue_tier("ICWE", registry_path=str(self.registry_path))
        neurips = self.module.match_venue_tier("NeurIPS", registry_path=str(self.registry_path))

        self.assertTrue(icml["matched"])
        self.assertEqual(icml["tier"], "CCF-A")
        self.assertEqual(icsme["tier"], "CCF-B")
        self.assertEqual(icwe["tier"], "CCF-C")
        self.assertEqual(neurips["tier"], "Top")

    def test_marks_unmatched_venues(self):
        match = self.module.match_venue_tier("Workshop on Tiny Datasets", registry_path=str(self.registry_path))

        self.assertFalse(match["matched"])
        self.assertEqual(match["tier"], "Unmatched")
        self.assertEqual(match["canonical_name"], "")

    def test_matches_long_proceedings_name_via_normalized_aliases(self):
        match = self.module.match_venue_tier(
            "Proceedings of the 31st ACM SIGSOFT International Symposium on Software Testing and Analysis",
            registry_path=str(self.registry_path),
        )

        self.assertTrue(match["matched"])
        self.assertEqual(match["tier"], "CCF-A")
        self.assertEqual(match["canonical_name"], "International Symposium on Software Testing and Analysis")
        self.assertIn(match["matched_by"], {"normalized_exact", "normalized_contains"})


class PersonRegistryMatchingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(PERSON_CANDIDATES_PATH, "test_person_candidates_module")
        cls.stats_module = load_module(SCHOLAR_STATS_PATH, "test_scholar_stats_for_people")

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.tempdir.name) / "person_tag_registry.json"
        self.registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "_comment": "fixture person registry",
                    "items": [
                        {
                            "name": "Grace Hopper",
                            "aliases": ["Rear Admiral Grace Hopper"],
                            "tags": [
                                {
                                    "type": "ieee_fellow",
                                    "source_links": ["https://example.com/grace-hopper"],
                                }
                            ],
                        },
                        {
                            "name": "Andrew Yao",
                            "aliases": ["Andrew Chi-Chih Yao", "姚期智"],
                            "matched_affiliations": ["tsinghua university", "清华大学"],
                            "tags": [
                                {
                                    "type": "acm_fellow",
                                    "source_links": ["https://example.com/acm-yao"],
                                },
                                {
                                    "type": "godel_prize",
                                    "source_links": ["https://example.com/godel-yao"],
                                },
                            ],
                        },
                        {
                            "name": "John Smith",
                            "aliases": ["J. Smith"],
                            "tags": [
                                {
                                    "type": "aaai_fellow",
                                    "source_links": ["https://example.com/john-smith"],
                                }
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_matches_exact_name_as_pending_candidate(self):
        candidates = self.module.build_candidates(
            [
                {
                    "id": "P001",
                    "title": "Compilers in Practice",
                    "authors": ["Grace Hopper", "Alan Turing"],
                }
            ],
            registry_path=str(self.registry_path),
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["name"], "Grace Hopper")
        self.assertEqual(candidate["tag_type"], "ieee_fellow")
        self.assertEqual(candidate["status"], "pending")
        self.assertEqual(candidate["evidence"][0]["match_type"], "exact_name")

    def test_matches_alias_and_emits_multiple_tag_candidates(self):
        candidates = self.module.build_candidates(
            [
                {
                    "id": "P002",
                    "title": "Theory Builders",
                    "authors": ["Andrew Chi-Chih Yao"],
                }
            ],
            registry_path=str(self.registry_path),
        )

        tag_types = {candidate["tag_type"] for candidate in candidates}
        match_types = {candidate["evidence"][0]["match_type"] for candidate in candidates}

        self.assertEqual(tag_types, {"acm_fellow", "godel_prize"})
        self.assertEqual(match_types, {"alias"})
        self.assertTrue(all(candidate["status"] == "pending" for candidate in candidates))

    def test_marks_name_only_matches_as_homonym_risk(self):
        candidates = self.module.build_candidates(
            [
                {
                    "id": "P003",
                    "title": "Agents Everywhere",
                    "authors": ["John Smith"],
                }
            ],
            registry_path=str(self.registry_path),
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["status"], "pending")
        self.assertTrue(candidate["homonym_risk"])
        self.assertIn("name_only_match", candidate["risk_flags"])

    def test_counts_pending_confirmed_rejected_in_quick_stats(self):
        session = {
            "query": "Test Scholar",
            "target": {"citationCount": 99},
            "papers": [
                {"id": "P001", "title": "A", "venue": "ICML", "year": 2024, "context_confidence": "high"},
                {"id": "P002", "title": "B", "venue": "Unknown Venue", "year": 2023, "context_confidence": "medium"},
                {"id": "P003", "title": "C", "venue": "NeurIPS", "year": 2022, "context_confidence": "low"},
            ],
            "person_candidates": [
                {"candidate_id": "c1", "status": "pending", "matched_paper_ids": ["P001"]},
                {"candidate_id": "c2", "status": "confirmed", "matched_paper_ids": ["P002"]},
                {"candidate_id": "c3", "status": "rejected", "matched_paper_ids": ["P003"]},
            ],
        }

        venue_registry_path = Path(self.tempdir.name) / "venue_tiers.json"
        venue_registry_path.write_text(
            json.dumps(
                {
                    "items": [
                        {"name": "International Conference on Machine Learning", "tier": "CCF-A", "aliases": ["ICML"]},
                        {"name": "Advances in Neural Information Processing Systems", "tier": "Top", "aliases": ["NeurIPS"]},
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        quick_stats = self.stats_module.build_quick_stats(
            session,
            venue_registry_path=str(venue_registry_path),
        )

        self.assertEqual(quick_stats["publication_statistics"]["matched_venue_count"], 2)
        self.assertEqual(quick_stats["publication_statistics"]["unmatched_venue_count"], 1)
        self.assertEqual(quick_stats["citation_statistics"]["person_status_counts"]["pending"], 1)
        self.assertEqual(quick_stats["citation_statistics"]["person_status_counts"]["confirmed"], 1)
        self.assertEqual(quick_stats["citation_statistics"]["person_status_counts"]["rejected"], 1)


if __name__ == "__main__":
    unittest.main()
