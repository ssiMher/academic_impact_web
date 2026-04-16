from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import main
from skills.academic_impact_analyzer import impact_cli


class DiscoverLimitTestCase(unittest.TestCase):
    def test_web_discover_clamps_large_form_values(self):
        with mock.patch.object(main.impact_core, "start_discover_task", return_value="session-1") as start:
            response = asyncio.run(
                main.discover(
                    query="Target",
                    limit=9999,
                    probe_downloads=False,
                    auto_refresh_top=999,
                    sort_preference="recent",
                )
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(start.call_args.kwargs["limit"], 500)
        self.assertEqual(start.call_args.kwargs["auto_refresh_top"], 100)

    def test_web_extend_discover_clamps_large_form_value(self):
        with mock.patch.object(main.impact_core, "start_extend_discover_task") as start:
            response = asyncio.run(
                main.extend_discover_session(
                    session_id="session-1",
                    target_limit=999999,
                )
            )

        self.assertEqual(response.status_code, 303)
        start.assert_called_once_with("session-1", 10000)

    def test_large_discover_request_prefetches_more_than_legacy_cap(self):
        fake_papers = [
            {
                "title": f"Citing Paper {index}",
                "year": 2024,
                "venue": "Venue",
                "authors": [f"Author {index}"],
                "author_details": [],
                "externalIds": {},
            }
            for index in range(3)
        ]
        list_result = {
            "ok": True,
            "target": {"title": "Target", "citationCount": 5001},
            "papers": fake_papers,
            "warnings": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch.object(impact_cli.LIST_PAPERS, "list_all_citations", return_value=list_result) as list_all, \
                mock.patch.object(impact_cli.FETCH_CONTEXTS, "get_citation_contexts", return_value={"ok": True, "results": []}):
            session = impact_cli.build_discover_session(
                query="Target",
                session_dir=Path(tmpdir),
                limit=500,
                probe_downloads=False,
                auto_refresh_count=0,
                sort_preference="recent",
            )

        self.assertTrue(session["ok"])
        self.assertEqual(list_all.call_args.kwargs["limit"], 500)
        self.assertEqual(list_all.call_args.kwargs["fetch_limit"], 2500)

    def test_full_citation_discover_request_can_cover_five_thousand_rows(self):
        list_result = {
            "ok": True,
            "target": {"title": "Target", "citationCount": 5001},
            "papers": [],
            "warnings": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch.object(impact_cli.LIST_PAPERS, "list_all_citations", return_value=list_result) as list_all, \
                mock.patch.object(impact_cli.FETCH_CONTEXTS, "get_citation_contexts", return_value={"ok": True, "results": []}):
            impact_cli.build_discover_session(
                query="Target",
                session_dir=Path(tmpdir),
                limit=5001,
                probe_downloads=False,
                auto_refresh_count=0,
                sort_preference="recent",
            )

        self.assertEqual(list_all.call_args.kwargs["limit"], 5001)
        self.assertEqual(list_all.call_args.kwargs["fetch_limit"], 10000)

    def test_extend_discover_preserves_existing_paper_state(self):
        prior_session = {
            "ok": True,
            "query": "Target",
            "created_at": "2099-01-01T00:00:00",
            "papers": [
                {
                    "id": "P001",
                    "title": "Existing Paper",
                    "externalIds": {"DOI": "10.1234/existing"},
                    "download_probe": {"status": "local_available", "local_file_path": "/tmp/existing.pdf"},
                    "analysis_result": {"status": "fulltext_analyzed", "paths": {"analysis": "/tmp/analysis.json"}},
                    "selection": {"selected_for_download": True, "selected_for_analysis": True},
                    "paper": {
                        "title": "Existing Paper",
                        "externalIds": {"DOI": "10.1234/existing"},
                    },
                }
            ],
            "task_state": {},
            "list_preferences": {"sort_preference": "recent"},
        }
        list_result = {
            "ok": True,
            "target": {"title": "Target", "citationCount": 5001},
            "papers": [
                {
                    "title": "Existing Paper",
                    "year": 2024,
                    "venue": "Venue",
                    "authors": ["Author One"],
                    "author_details": [],
                    "externalIds": {"DOI": "10.1234/existing"},
                },
                {
                    "title": "New Paper",
                    "year": 2023,
                    "venue": "Venue",
                    "authors": ["Author Two"],
                    "author_details": [],
                    "externalIds": {"DOI": "10.1234/new"},
                },
            ],
            "warnings": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch.object(impact_cli.LIST_PAPERS, "list_all_citations", return_value=list_result), \
                mock.patch.object(impact_cli.FETCH_CONTEXTS, "get_citation_contexts", return_value={"ok": True, "results": []}):
            session_dir = Path(tmpdir)
            impact_cli.write_json(session_dir / "session.json", prior_session)
            session = impact_cli.build_discover_session(
                query="Target",
                session_dir=session_dir,
                limit=2,
                probe_downloads=False,
                auto_refresh_count=0,
                sort_preference="recent",
            )

        self.assertEqual(session["created_at"], "2099-01-01T00:00:00")
        self.assertEqual(session["papers"][0]["download_probe"]["status"], "local_available")
        self.assertEqual(session["papers"][0]["analysis_result"]["status"], "fulltext_analyzed")
        self.assertTrue(session["papers"][0]["selection"]["selected_for_download"])
        self.assertEqual(session["papers"][1]["download_probe"]["status"], "not_probed")


if __name__ == "__main__":
    unittest.main()
