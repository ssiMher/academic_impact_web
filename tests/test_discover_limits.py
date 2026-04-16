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
        self.assertEqual(list_all.call_args.kwargs["fetch_limit"], 1000)


if __name__ == "__main__":
    unittest.main()
