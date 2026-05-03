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

    def test_expand_publication_citations_adds_edges_from_provider_results(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "doi": "10.1000/target",
                    "unique_ids": {"DOI": "10.1000/target"},
                }
            ],
            "citation_edges": [],
            "statistics": {},
        }
        citation_result = {
            "ok": True,
            "data_provider": "Scopus",
            "papers": [
                {
                    "paperId": "scopus-citing-001",
                    "title": "Citing Paper",
                    "year": 2025,
                    "venue": "ACM MobiCom",
                    "externalIds": {"DOI": "10.1000/citing"},
                    "authors": ["Fellow A"],
                    "source_url": "https://example.test/citing",
                }
            ],
        }

        with mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
            return_value=citation_result,
        ) as list_all_citations:
            expanded = self.pipeline.expand_publication_citations(
                session,
                limit_per_publication=10,
            )

        list_all_citations.assert_called_once_with("10.1000/target", limit=10)
        self.assertEqual(len(expanded["citation_edges"]), 1)
        edge = expanded["citation_edges"][0]
        self.assertEqual(edge["source_publication_id"], "S001")
        self.assertEqual(edge["citing_paper_id"], "scopus-citing-001")
        self.assertEqual(edge["citing_title"], "Citing Paper")
        self.assertEqual(edge["cited_publication_title"], "Target Paper")
        self.assertEqual(edge["citing_doi"], "10.1000/citing")
        self.assertEqual(edge["citing_year"], 2025)
        self.assertEqual(edge["citing_venue"], "ACM MobiCom")
        self.assertEqual(edge["citing_authors"], ["Fellow A"])
        self.assertEqual(edge["provider"], "Scopus")
        self.assertEqual(edge["source_url"], "https://example.test/citing")
        self.assertEqual(expanded["statistics"]["citation_edge_count"], 1)

    def test_expand_publication_citations_records_provider_errors_and_continues(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Broken Paper",
                    "doi": "10.1000/broken",
                    "unique_ids": {"DOI": "10.1000/broken"},
                },
                {
                    "id": "S002",
                    "title": "Recoverable Paper",
                    "doi": "10.1000/recoverable",
                    "unique_ids": {"DOI": "10.1000/recoverable"},
                },
            ],
            "citation_edges": [],
            "statistics": {},
        }
        citation_result = {
            "ok": True,
            "data_provider": "OpenAlex",
            "papers": [
                {
                    "title": "Later Citing Paper",
                    "year": 2026,
                    "venue": "USENIX ATC",
                    "externalIds": {"OpenAlex": "W123"},
                    "authors": [{"name": "Fellow B"}],
                    "source_url": "https://example.test/later-citing",
                }
            ],
        }

        with mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
            side_effect=[RuntimeError("boom"), citation_result],
        ):
            expanded = self.pipeline.expand_publication_citations(
                session,
                limit_per_publication=10,
            )

        self.assertEqual(len(expanded["citation_edges"]), 1)
        edge = expanded["citation_edges"][0]
        self.assertEqual(edge["source_publication_id"], "S002")
        self.assertEqual(edge["citing_paper_id"], "W123")
        self.assertEqual(expanded["statistics"]["citation_edge_count"], 1)
        self.assertEqual(
            expanded["citation_expansion_errors"],
            [
                {
                    "source_publication_id": "S001",
                    "query": "10.1000/broken",
                    "error": "boom",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
