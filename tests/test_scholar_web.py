from __future__ import annotations

import json
import shutil
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app
from app.services import scholar_core


TEST_SESSION_ID = "test_scholar_session"
TEST_SESSION_DIR = scholar_core.SCHOLAR_SESSIONS_ROOT / TEST_SESSION_ID


class ScholarWebTestCase(unittest.TestCase):
    def tearDown(self):
        if TEST_SESSION_DIR.exists():
            shutil.rmtree(TEST_SESSION_DIR)

    def test_load_scholar_status(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [],
                    "citation_edges": [],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)

        self.assertEqual(payload["session_id"], TEST_SESSION_ID)
        self.assertEqual(payload["selected_author"]["display_name"], "Chen Tian")

    def test_scholar_route_renders(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {
                        "display_name": "Chen Tian",
                        "affiliations": ["Nanjing University"],
                    },
                    "publications": [],
                    "citation_edges": [],
                    "statistics": {
                        "publication_count": 0,
                        "person_tag_statistics": [],
                    },
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Chen Tian", response.text)

    def test_scholar_route_renders_expansion_controls_and_queue(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [
                        {
                            "id": "S001",
                            "title": "Paper One",
                            "year": 2025,
                            "venue": "ACM MobiCom",
                            "unique_ids": {"DBLP": "conf/test/one"},
                        }
                    ],
                    "citation_edges": [{"citing_title": "Citing Paper"}],
                    "deep_analysis_queue": [
                        {
                            "citing_title": "Citing Paper",
                            "citing_venue": "ACM MobiCom",
                            "citing_year": 2026,
                            "citing_authors": ["Alice Fellow"],
                            "priority_score": 50,
                            "reasons": ["person_tag:ACM Fellow"],
                        }
                    ],
                    "statistics": {
                        "publication_count": 1,
                        "citation_edge_count": 1,
                        "person_tag_statistics": [],
                    },
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("展开引用论文", response.text)
        self.assertIn("高价值引用队列", response.text)
        self.assertIn("person_tag:ACM Fellow", response.text)
        self.assertIn("CCF A", response.text)

    def test_scholar_route_filters_high_value_queue_by_reason(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [],
                    "citation_edges": [],
                    "deep_analysis_queue": [
                        {
                            "citing_title": "Venue Citing Paper",
                            "citing_venue": "ACM MobiCom",
                            "citing_authors": ["Regular Author"],
                            "priority_score": 25,
                            "reasons": ["venue:CCF A"],
                        },
                        {
                            "citing_title": "Fellow Citing Paper",
                            "citing_venue": "Unknown Venue",
                            "citing_authors": ["Alice Fellow"],
                            "priority_score": 50,
                            "reasons": ["person_tag:ACM Fellow"],
                        },
                    ],
                    "statistics": {
                        "publication_count": 0,
                        "citation_edge_count": 0,
                        "person_tag_statistics": [],
                    },
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(
            f"/scholars/{TEST_SESSION_ID}",
            params={
                "queue_reason": "person_tag:ACM Fellow",
                "queue_page_size": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Fellow Citing Paper", response.text)
        self.assertNotIn("Venue Citing Paper</td>", response.text)
        self.assertIn("当前显示 1 / 2 篇高价值引用论文", response.text)

    def test_build_deep_analysis_queue_view_paginates(self):
        session = {
            "deep_analysis_queue": [
                {
                    "citing_title": f"Citing {index}",
                    "reasons": ["venue:CCF A"],
                }
                for index in range(3)
            ]
        }

        view = scholar_core.build_deep_analysis_queue_view(
            session,
            page=2,
            page_size=2,
        )

        self.assertEqual(view["total_count"], 3)
        self.assertEqual(view["items"][0]["citing_title"], "Citing 2")
        self.assertEqual(view["pagination"]["page"], 2)
        self.assertFalse(view["pagination"]["has_next"])
        self.assertTrue(view["pagination"]["has_previous"])

    def test_create_scholar_session_from_author_payload(self):
        author = {
            "display_name": "Chen Tian",
            "dblp_id": "94/1247-1",
            "affiliations": ["Nanjing University"],
        }
        fake_session = {
            "session_id": TEST_SESSION_ID,
            "session_type": "scholar_impact",
            "selected_author": author,
            "publications": [],
            "citation_edges": [],
            "statistics": {"publication_count": 0},
            "task_state": {"active": False},
        }

        with mock.patch.object(scholar_core, "make_scholar_session_id", return_value=TEST_SESSION_ID), \
             mock.patch.object(scholar_core.scholar_pipeline(), "build_scholar_session", return_value=fake_session):
            session_id = scholar_core.create_scholar_session(author)

        self.assertEqual(session_id, TEST_SESSION_ID)
        self.assertTrue((TEST_SESSION_DIR / "session.json").exists())

    def test_create_scholar_route_redirects_to_session(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "create_scholar_session", return_value=TEST_SESSION_ID) as create_session:
            response = client.post(
                "/scholars/create",
                data={
                    "display_name": "Chen Tian",
                    "dblp_id": "94/1247-1",
                    "affiliations": "Nanjing University|Test Lab",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/scholars/{TEST_SESSION_ID}")
        create_session.assert_called_once_with(
            {
                "display_name": "Chen Tian",
                "dblp_id": "94/1247-1",
                "openalex_id": "",
                "scopus_author_id": "",
                "affiliations": ["Nanjing University", "Test Lab"],
            }
        )

    def test_create_scholar_route_requires_dblp_id(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "create_scholar_session") as create_session:
            response = client.post(
                "/scholars/create",
                data={
                    "display_name": "Chen Tian",
                    "dblp_id": "",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        create_session.assert_not_called()

    def test_make_scholar_session_id_avoids_fast_duplicate(self):
        first = scholar_core.make_scholar_session_id("Chen Tian")
        second = scholar_core.make_scholar_session_id("Chen Tian")

        self.assertNotEqual(first, second)
        self.assertIn("_scholar_chen_tian", first)

    def test_expand_scholar_citations_task_updates_session(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [{"id": "S001", "title": "Paper One"}],
                    "citation_edges": [],
                    "deep_analysis_queue": [],
                    "statistics": {"publication_count": 1},
                    "task_state": scholar_core.default_task_state(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class FakePipeline:
            @staticmethod
            def expand_publication_citations(session, limit_per_publication=100, progress_callback=None):
                time.sleep(0.05)
                session["citation_edges"] = [
                    {
                        "source_publication_id": "S001",
                        "citing_title": "Citing Paper",
                        "citing_venue": "ACM MobiCom",
                    }
                ]
                session["deep_analysis_queue"] = [
                    {"citing_title": "Citing Paper", "priority_score": 25, "reasons": ["venue:Top venue seed"]}
                ]
                session["statistics"] = {"publication_count": 1, "citation_edge_count": 1}
                if progress_callback:
                    progress_callback(
                        {
                            "processed_count": 1,
                            "total_count": 1,
                            "citation_edge_count": 1,
                            "error_count": 0,
                        }
                    )
                return session

        with mock.patch.object(scholar_core, "_decorate_publication_venue_tiers"), \
             mock.patch.object(scholar_core, "scholar_pipeline", return_value=FakePipeline()):
            started, state = scholar_core.start_expand_citations_task(TEST_SESSION_ID, limit_per_publication=10)
            self.assertTrue(started)
            self.assertTrue(state["active"])
            self.assertEqual(state["task_type"], "expand_citations")

            started_again, duplicate_state = scholar_core.start_expand_citations_task(TEST_SESSION_ID, limit_per_publication=10)
            self.assertFalse(started_again)
            self.assertTrue(duplicate_state["active"])

            deadline = time.time() + 2
            final_status = None
            while time.time() < deadline:
                final_status = scholar_core.get_scholar_task_status(TEST_SESSION_ID)
                if not final_status["task_state"]["active"]:
                    break
                time.sleep(0.05)

        self.assertIsNotNone(final_status)
        self.assertEqual(final_status["task_state"]["status"], "succeeded")
        self.assertEqual(final_status["citation_edge_count"], 1)
        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)
        self.assertEqual(payload["deep_analysis_queue"][0]["citing_title"], "Citing Paper")

    def test_expand_scholar_citations_route_redirects(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "start_expand_citations_task", return_value=(True, {})) as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/expand-citations",
                data={"limit_per_publication": "12"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/scholars/{TEST_SESSION_ID}")
        start_task.assert_called_once_with(TEST_SESSION_ID, limit_per_publication=12)

    def test_expand_scholar_citations_route_rejects_invalid_limit(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "start_expand_citations_task") as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/expand-citations",
                data={"limit_per_publication": "1000"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        start_task.assert_not_called()

    def test_rebuild_scholar_derived_outputs_route_redirects(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "rebuild_scholar_derived_outputs",
            return_value={},
        ) as rebuild:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/rebuild-derived",
                data={"queue_limit": "250"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/scholars/{TEST_SESSION_ID}#deep-analysis-queue",
        )
        rebuild.assert_called_once_with(TEST_SESSION_ID, queue_limit=250)

    def test_rebuild_scholar_derived_outputs_route_rejects_invalid_limit(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "rebuild_scholar_derived_outputs",
        ) as rebuild:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/rebuild-derived",
                data={"queue_limit": "5000"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        rebuild.assert_not_called()

    def test_scholar_task_status_route_returns_counts(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [{"id": "S001", "title": "Paper One"}],
                    "citation_edges": [{"citing_title": "Citing Paper"}],
                    "deep_analysis_queue": [{"citing_title": "Citing Paper"}],
                    "statistics": {"publication_count": 1, "citation_edge_count": 1},
                    "task_state": scholar_core.default_task_state(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}/task-status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["publication_count"], 1)
        self.assertEqual(payload["citation_edge_count"], 1)
        self.assertEqual(payload["deep_analysis_queue_count"], 1)


if __name__ == "__main__":
    unittest.main()
