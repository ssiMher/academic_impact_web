from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPACT_CLI_PATH = ROOT / "skills" / "academic_impact_analyzer" / "impact_cli.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VenueStatisticsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.impact_cli = load_module(IMPACT_CLI_PATH, "test_impact_cli_venue_statistics")

    def test_classify_venue_tier_uses_alias_registry(self):
        tier_index = self.impact_cli.build_venue_tier_index({
            "entries": [
                {
                    "name": "IEEE International Conference on Robotics and Automation",
                    "aliases": ["ICRA"],
                    "tier": "A",
                    "tier_label": "CCF A",
                    "tier_system": "CCF",
                    "venue_type": "conference",
                    "source": "fixture",
                }
            ]
        })

        matched = self.impact_cli.classify_venue_tier("ICRA", tier_index)
        unmatched = self.impact_cli.classify_venue_tier("AI Survey", tier_index)

        self.assertTrue(matched["matched"])
        self.assertEqual(matched["matched_name"], "IEEE International Conference on Robotics and Automation")
        self.assertEqual(matched["tier_label"], "CCF A")
        self.assertFalse(unmatched["matched"])
        self.assertEqual(unmatched["tier"], "unmatched")

    def test_build_venue_statistics_counts_venues_and_tiers(self):
        tier_index = self.impact_cli.build_venue_tier_index({
            "entries": [
                {
                    "name": "IEEE International Conference on Robotics and Automation",
                    "aliases": ["ICRA"],
                    "tier": "top",
                    "tier_label": "Top venue seed",
                    "tier_system": "project_seed",
                    "venue_type": "conference",
                    "source": "fixture",
                }
            ]
        })
        papers = [
            {"id": "P001", "title": "Robotics", "venue": "ICRA", "year": 2025},
            {"id": "P002", "title": "Survey", "venue": "AI Survey", "year": 2024},
            {"id": "P003", "title": "Missing", "venue": "", "year": 2023},
        ]

        stats = self.impact_cli.build_venue_statistics(papers, tier_index)

        self.assertEqual(stats["paper_count"], 3)
        self.assertEqual(stats["known_venue_count"], 2)
        self.assertEqual(stats["matched_tier_count"], 1)
        self.assertEqual(stats["unmatched_tier_count"], 2)
        self.assertEqual(stats["top_venues"][0]["venue"], "AI Survey")
        self.assertEqual(
            {group["tier"]: group["count"] for group in stats["tier_distribution"]},
            {"top": 1, "unmatched": 1, "unknown": 1},
        )

    def test_session_detail_payload_includes_venue_statistics(self):
        session = {
            "ok": True,
            "query": "Target",
            "target": {"title": "Target", "year": 2024, "venue": "NeurIPS"},
            "papers": [
                {
                    "id": "P001",
                    "title": "Robotics",
                    "year": 2025,
                    "venue": "ICRA",
                    "download_probe": {"status": "not_probed"},
                    "analysis_result": {"status": None, "paths": {}},
                },
                {
                    "id": "P002",
                    "title": "Survey",
                    "year": 2024,
                    "venue": "AI Survey",
                    "download_probe": {"status": "not_probed"},
                    "analysis_result": {"status": None, "paths": {}},
                },
            ],
            "person_candidates": [],
            "overview_stats": self.impact_cli.default_overview_stats(),
        }

        payload = self.impact_cli.build_session_detail_payload(session)

        self.assertIn("venue_statistics", payload)
        self.assertEqual(payload["venue_statistics"]["paper_count"], 2)
        self.assertEqual(payload["venue_statistics"]["matched_tier_count"], 1)
        self.assertEqual(payload["papers"][0]["venue_tier"]["tier_label"], "Top venue seed")
        self.assertEqual(payload["papers"][1]["venue_tier"]["tier"], "unmatched")


if __name__ == "__main__":
    unittest.main()
