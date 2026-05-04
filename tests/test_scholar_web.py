from __future__ import annotations

import json
import shutil
import unittest

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


if __name__ == "__main__":
    unittest.main()
