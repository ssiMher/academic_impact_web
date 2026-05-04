from __future__ import annotations

import json
import shutil
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


if __name__ == "__main__":
    unittest.main()
