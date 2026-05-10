from __future__ import annotations

import importlib.util
import json
import tempfile
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

    def test_normalize_venue_key_removes_proceedings_prefix_and_ordinals(self):
        normalized = self.impact_cli.normalize_venue_key(
            "Proceedings of the Fifteenth ACM International Conference on Web Search and Data Mining"
        )

        self.assertEqual(normalized, "acm international web search and data mining")
        self.assertEqual(
            self.impact_cli.normalize_venue_key("Proceedings of the AAAI Conference on Artificial Intelligence"),
            self.impact_cli.normalize_venue_key("AAAI Conference on Artificial Intelligence"),
        )

    def test_project_registry_matches_common_openalex_and_s2_venue_names(self):
        tier_index = self.impact_cli.build_venue_tier_index()

        cases = [
            (
                "Proceedings of the AAAI Conference on Artificial Intelligence",
                "AAAI Conference on Artificial Intelligence",
                "conference",
            ),
            (
                "Proceedings of the Fifteenth ACM International Conference on Web Search and Data Mining",
                "ACM International Conference on Web Search and Data Mining",
                "conference",
            ),
            ("ACM Computing Surveys", "ACM Computing Surveys", "journal"),
            ("Digital Signal Processing", "Digital Signal Processing", "journal"),
            (
                "ACM Mobicom 2024 Proceedings of the 30th International Conference on Mobile Computing and Networking",
                "ACM International Conference on Mobile Computing and Networking",
                "conference",
            ),
            (
                "ACM Sensys 2025 23 rd ACM Conference on Embedded Networked Sensor Systems",
                "ACM Conference on Embedded Networked Sensor Systems",
                "conference",
            ),
            (
                "IEEE Journal on Selected Areas in Communications",
                "IEEE Journal on Selected Areas in Communications",
                "journal",
            ),
            (
                "IEEE Transactions on Mobile Computing",
                "IEEE Transactions on Mobile Computing",
                "journal",
            ),
            (
                "IEEE Trans. Netw.",
                "IEEE/ACM Transactions on Networking",
                "journal",
            ),
            (
                "IEEE Transactions on Instrumentation and Measurement",
                "IEEE Transactions on Instrumentation and Measurement",
                "journal",
            ),
        ]
        for venue, expected_name, expected_type in cases:
            with self.subTest(venue=venue):
                matched = self.impact_cli.classify_venue_tier(venue, tier_index)
                self.assertTrue(matched["matched"])
                self.assertEqual(matched["matched_name"], expected_name)
                self.assertEqual(matched["venue_type"], expected_type)

    def test_project_registry_marks_confirmed_ccf_network_venues(self):
        tier_index = self.impact_cli.build_venue_tier_index()

        cases = [
            (
                "ACM Mobicom 2024 Proceedings of the 30th International Conference on Mobile Computing and Networking",
                "CCF A",
                "CCF",
            ),
            ("ACM SenSys", "CCF B", "CCF"),
            ("IEEE Journal on Selected Areas in Communications", "CCF A", "CCF"),
            ("IEEE Transactions on Mobile Computing", "CCF A", "CCF"),
            ("IEEE Trans. Netw.", "Tracked venue seed", "project_seed"),
            ("IEEE Transactions on Instrumentation and Measurement", "Tracked venue seed", "project_seed"),
        ]
        for venue, expected_label, expected_system in cases:
            with self.subTest(venue=venue):
                matched = self.impact_cli.classify_venue_tier(venue, tier_index)
                self.assertTrue(matched["matched"])
                self.assertEqual(matched["tier_label"], expected_label)
                self.assertEqual(matched["tier_system"], expected_system)

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

    def test_session_detail_payload_includes_person_tag_statistics(self):
        session = {
            "ok": True,
            "query": "Target",
            "target": {"title": "Target", "year": 2024, "venue": "NeurIPS"},
            "papers": [],
            "person_candidates": [
                {
                    "candidate_id": "acm_fellow::alice",
                    "name": "Alice",
                    "tag_type": "acm_fellow",
                    "tag_label": "ACM Fellow",
                    "matched_paper_ids": ["P001", "P002"],
                    "source_links": ["https://example.test/alice"],
                    "status": "pending",
                },
                {
                    "candidate_id": "acm_fellow::bob",
                    "name": "Bob",
                    "tag_type": "acm_fellow",
                    "tag_label": "ACM Fellow",
                    "matched_paper_ids": ["P002"],
                    "source_links": [],
                    "status": "confirmed",
                },
                {
                    "candidate_id": "ieee_fellow::carol",
                    "name": "Carol",
                    "tag_type": "ieee_fellow",
                    "tag_label": "IEEE Fellow",
                    "matched_paper_ids": ["P003"],
                    "source_links": ["https://example.test/carol"],
                    "status": "rejected",
                },
            ],
            "overview_stats": self.impact_cli.default_overview_stats(),
        }

        payload = self.impact_cli.build_session_detail_payload(session)
        stats = payload["person_tag_statistics"]
        acm_group = next(group for group in stats["groups"] if group["tag_type"] == "acm_fellow")
        ieee_group = next(group for group in stats["groups"] if group["tag_type"] == "ieee_fellow")

        self.assertEqual(stats["total_candidate_count"], 3)
        self.assertEqual(stats["pending_count"], 1)
        self.assertEqual(stats["confirmed_count"], 1)
        self.assertEqual(stats["rejected_count"], 1)
        self.assertEqual(acm_group["candidate_count"], 2)
        self.assertEqual(acm_group["source_complete_count"], 1)
        self.assertEqual(acm_group["matched_paper_count"], 2)
        self.assertEqual(ieee_group["candidate_count"], 1)

    def test_session_detail_payload_exposes_structured_finding_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            analysis_path = tmp_path / "fulltext_analysis.json"
            candidate_path = tmp_path / "candidate_spans.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "findings": [
                            {
                                "page": 4,
                                "span_index": 2,
                                "citation_text": "We compare against the target model as a baseline.",
                                "keep": True,
                                "aspect": "comparison",
                                "stance": "neutral",
                                "function": "将目标论文作为实验比较对象。",
                                "reason": "正文明确说明与目标模型进行对比。",
                                "confidence": 0.87,
                                "mention_type": "explicit_citation",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "spans": [
                            {
                                "page": 4,
                                "span_index": 2,
                                "text": "We compare against the target model as a baseline.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
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
                        "download_probe": {"status": "downloaded"},
                        "analysis_result": {
                            "status": "fulltext_analyzed",
                            "paths": {
                                "analysis": str(analysis_path),
                                "candidate_spans": str(candidate_path),
                            },
                        },
                    }
                ],
                "person_candidates": [],
                "overview_stats": self.impact_cli.default_overview_stats(),
            }

            paper = self.impact_cli.build_session_detail_payload(session)["papers"][0]
            summary = paper["citation_method_summary"]

            self.assertEqual(summary["primary_aspect_label"], "比较对象")
            self.assertEqual(summary["primary_mention_type_label"], "明确引用")
            self.assertEqual(summary["primary_stance_label"], "中性")
            self.assertEqual(summary["primary_function"], "将目标论文作为实验比较对象。")
            self.assertEqual(summary["primary_reason"], "正文明确说明与目标模型进行对比。")
            self.assertEqual(summary["finding_count"], 1)
            self.assertEqual(summary["kept_finding_count"], 1)
            self.assertEqual(summary["finding_preview"][0]["citation_excerpt"], "We compare against the target model as a baseline.")

    def test_session_detail_payload_paginates_after_filters(self):
        session = {
            "ok": True,
            "query": "Target",
            "target": {"title": "Target", "year": 2024, "venue": "NeurIPS"},
            "papers": [
                {
                    "id": f"P{index:03d}",
                    "title": f"Paper {index}",
                    "year": 2020 + index,
                    "venue": "ICRA",
                    "download_probe": {"status": "downloaded"},
                    "analysis_result": {"status": None, "paths": {}},
                }
                for index in range(1, 13)
            ],
            "person_candidates": [],
            "overview_stats": self.impact_cli.default_overview_stats(),
        }

        payload = self.impact_cli.build_session_detail_payload(session, {"page": "2", "page_size": "5"})

        self.assertEqual([paper["id"] for paper in payload["papers"]], ["P006", "P007", "P008", "P009", "P010"])
        self.assertEqual(
            payload["pagination"],
            {
                "page": 2,
                "page_size": 5,
                "total": 12,
                "total_pages": 3,
                "start": 6,
                "end": 10,
                "has_previous": True,
                "has_next": True,
                "previous_page": 1,
                "next_page": 3,
                "previous_query": "page_size=5&page=1",
                "next_query": "page_size=5&page=3",
            },
        )


if __name__ == "__main__":
    unittest.main()
