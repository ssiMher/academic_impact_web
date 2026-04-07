from __future__ import annotations

import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from app.services import impact_core


ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = ROOT / "data" / "sessions"
TEST_ANALYZE_SESSION_ID = "20990101_000000_test_background_analyze"


class BackgroundTasksTestCase(unittest.TestCase):
    def setUp(self):
        self.session_dir = SESSIONS_ROOT / TEST_ANALYZE_SESSION_ID
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "session.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "query": "Test Query",
                    "target": {"title": "Test Target"},
                    "papers": [
                        {
                            "id": "P001",
                            "title": "Test Paper",
                            "download_probe": {"status": "local_available"},
                            "analysis_result": {"status": None, "paths": {}},
                        }
                    ],
                    "task_state": impact_core.default_task_state(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir)

    def test_start_analyze_task_blocks_duplicates_and_completes(self):
        class FakeCli:
            @staticmethod
            def run_analysis(session_dir: Path, ids: list[str], top_k_spans: int):
                time.sleep(0.05)
                session = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
                session["papers"][0]["analysis_result"] = {
                    "status": "fulltext_analyzed",
                    "paths": {"analysis": "fake.json"},
                }
                (session_dir / "session.json").write_text(
                    json.dumps(session, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return {"ok": True}

            @staticmethod
            def load_session(session_dir: Path):
                return json.loads((session_dir / "session.json").read_text(encoding="utf-8"))

        with mock.patch.object(impact_core, "impact_cli", return_value=FakeCli()):
            started, state = impact_core.start_analyze_task(TEST_ANALYZE_SESSION_ID, ["P001"], top_k_spans=8)
            self.assertTrue(started)
            self.assertTrue(state["active"])
            self.assertEqual(state["task_type"], "analyze")

            started_again, duplicate_state = impact_core.start_analyze_task(TEST_ANALYZE_SESSION_ID, ["P001"], top_k_spans=8)
            self.assertFalse(started_again)
            self.assertTrue(duplicate_state["active"])

            deadline = time.time() + 2
            final_status = None
            while time.time() < deadline:
                final_status = impact_core.get_task_status(TEST_ANALYZE_SESSION_ID)
                if not final_status["task_state"]["active"]:
                    break
                time.sleep(0.05)

        self.assertIsNotNone(final_status)
        self.assertFalse(final_status["task_state"]["active"])
        self.assertEqual(final_status["task_state"]["status"], "succeeded")

    def test_start_discover_task_creates_placeholder_session(self):
        class FakeRunPipeline:
            @staticmethod
            def slugify(query: str, limit: int = 50):
                return "test_discover"

        class FakeCli:
            @staticmethod
            def build_discover_session(query, session_dir, limit, probe_downloads, auto_refresh_count=0, sort_preference="context"):
                time.sleep(0.05)
                payload = {
                    "ok": True,
                    "query": query,
                    "target": {"title": query},
                    "papers": [],
                }
                (session_dir / "session.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return payload

        with mock.patch.object(impact_core, "run_pipeline", return_value=FakeRunPipeline()), \
                mock.patch.object(impact_core, "impact_cli", return_value=FakeCli()):
            session_id = impact_core.start_discover_task("Background Discover Query", limit=5)

        status = impact_core.get_task_status(session_id)
        self.assertIn("task_state", status)
        self.assertEqual(status["session_id"], session_id)
        self.assertTrue((SESSIONS_ROOT / session_id / "session.json").exists())


if __name__ == "__main__":
    unittest.main()
