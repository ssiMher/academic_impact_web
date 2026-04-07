from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from app.services import impact_core


ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = ROOT / "data" / "sessions"
TEST_SESSION_ID = "20990101_000000_test_attach_pdf"
TEST_SESSION_DIR = SESSIONS_ROOT / TEST_SESSION_ID


class WebAttachPdfTestCase(unittest.TestCase):
    def setUp(self):
        if TEST_SESSION_DIR.exists():
            shutil.rmtree(TEST_SESSION_DIR)
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "query": "Test Query",
                    "papers": [
                        {
                            "id": "P001",
                            "title": "Test Paper",
                            "download_probe": {"status": "not_probed"},
                            "analysis_result": {"status": None, "paths": {}},
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        if TEST_SESSION_DIR.exists():
            shutil.rmtree(TEST_SESSION_DIR)

    def test_attach_uploaded_pdf_uses_temp_file_and_cleans_it_up(self):
        observed = {}

        class FakeCli:
            @staticmethod
            def attach_local_pdf(session_dir, paper_id, file_path):
                path = Path(file_path)
                observed["session_dir"] = session_dir
                observed["paper_id"] = paper_id
                observed["file_path"] = file_path
                observed["exists_during_call"] = path.exists()
                observed["suffix"] = path.suffix
                observed["parent_name"] = path.parent.name
                return {"ok": True, "file_path": str(path)}

        with mock.patch.object(impact_core, "impact_cli", return_value=FakeCli()):
            result = impact_core.attach_uploaded_pdf(
                TEST_SESSION_ID,
                "P001",
                "evidence.pdf",
                b"%PDF-1.4 test",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(observed["paper_id"], "P001")
        self.assertEqual(observed["suffix"], ".pdf")
        self.assertEqual(observed["parent_name"], "uploads")
        self.assertTrue(observed["exists_during_call"])
        self.assertFalse(Path(observed["file_path"]).exists())


if __name__ == "__main__":
    unittest.main()
