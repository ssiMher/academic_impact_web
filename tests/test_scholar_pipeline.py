from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_pipeline.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarPipelineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_module(PIPELINE_PATH, "test_scholar_pipeline")

    def test_build_scholar_session_from_dblp_author(self):
        author = {
            "display_name": "Chen Tian",
            "dblp_id": "94/1247-1",
            "affiliations": ["Nanjing University"],
            "source": "DBLP",
        }
        publications = [
            {
                "title": "Paper One",
                "year": 2024,
                "venue": "EuroSys",
                "doi": "10.1000/one",
                "unique_ids": {"DBLP": "conf/test/one", "DOI": "10.1000/one"},
                "authors": ["Chen Tian", "A. Coauthor"],
                "author_position": "first_author",
                "citation_count": 0,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            self.pipeline.AUTHOR_SOURCES,
            "fetch_dblp_publications",
            return_value=publications,
        ):
            session = self.pipeline.build_scholar_session(author, Path(tmpdir))

        self.assertEqual(session["session_type"], "scholar_impact")
        self.assertEqual(session["selected_author"]["display_name"], "Chen Tian")
        self.assertEqual(session["publications"][0]["id"], "S001")
        self.assertEqual(session["publications"][0]["title"], "Paper One")
        self.assertEqual(session["statistics"]["publication_count"], 1)
        self.assertEqual(session["statistics"]["strong_evidence_count"], 0)

    def test_save_scholar_session_writes_json(self):
        session = {
            "schema_version": "1.0",
            "session_type": "scholar_impact",
            "session_id": "test_scholar",
            "selected_author": {"display_name": "Chen Tian"},
            "publications": [],
            "citation_edges": [],
            "statistics": {},
            "task_state": {"active": False},
            "updated_at": "old",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            self.pipeline.save_scholar_session(session_dir, session)
            loaded = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))

        self.assertEqual(loaded["session_id"], "test_scholar")
        self.assertIn("updated_at", loaded)
        self.assertNotEqual(loaded["updated_at"], "old")


if __name__ == "__main__":
    unittest.main()
