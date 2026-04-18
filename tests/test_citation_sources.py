from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LIST_PAPERS_PATH = ROOT / "skills" / "list_all_citations" / "list_papers.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CitationSourcesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.list_papers = load_module(LIST_PAPERS_PATH, "test_list_papers_sources")

    def test_semantic_scholar_title_search_url_is_not_duplicated(self):
        requested_urls = []

        class FakeResponse:
            def json(self):
                return {
                    "data": [
                        {
                            "paperId": "S2-1",
                            "title": "Target",
                            "year": 2024,
                            "venue": "Venue",
                            "externalIds": {},
                            "citationCount": 1,
                            "influentialCitationCount": 0,
                        }
                    ]
                }

        def fake_get(url):
            requested_urls.append(url)
            return FakeResponse()

        with mock.patch.object(self.list_papers, "safe_get", side_effect=fake_get):
            resolved = self.list_papers.resolve_paper("A title only target")

        self.assertEqual(resolved["paperId"], "S2-1")
        self.assertEqual(len(requested_urls), 1)
        self.assertEqual(requested_urls[0].count("/paper/search"), 1)

    def test_openalex_source_preference_bypasses_semantic_scholar(self):
        target = {
            "paperId": "https://openalex.org/W1",
            "title": "Target",
            "year": 2024,
            "venue": "Venue",
            "externalIds": {},
            "citationCount": 1,
        }
        rows = [
            {
                "citingPaper": {
                    "title": "Citing Paper",
                    "year": 2025,
                    "venue": "Journal",
                    "externalIds": {},
                    "authors": [{"name": "Ada", "id": "https://openalex.org/A1"}],
                }
            }
        ]

        with mock.patch.dict(os.environ, {"ACADEMIC_IMPACT_CITATION_SOURCE": "openalex"}), \
                mock.patch.object(self.list_papers, "resolve_paper", side_effect=AssertionError("semantic should be bypassed")), \
                mock.patch.object(self.list_papers, "resolve_paper_openalex", return_value=target), \
                mock.patch.object(self.list_papers, "fetch_citations_openalex", return_value=rows):
            payload = self.list_papers.list_all_citations("Target", limit=1)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data_provider"], "OpenAlex")
        self.assertEqual(payload["papers"][0]["title"], "Citing Paper")


if __name__ == "__main__":
    unittest.main()
