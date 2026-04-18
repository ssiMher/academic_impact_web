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

    def test_scopus_entry_mapping_handles_common_fields(self):
        entry = {
            "dc:title": "Adult cardiac-resident MSC-like stem cells with a proepicardial origin",
            "prism:doi": "10.1016/j.stem.2011.10.002",
            "prism:coverDate": "2011-11-04",
            "prism:publicationName": "Cell Stem Cell",
            "dc:identifier": "SCOPUS_ID:82755170946",
            "eid": "2-s2.0-82755170946",
            "dc:creator": "Smith J.",
            "citedby-count": "349",
            "link": [
                {"@ref": "scopus", "@href": "https://www.scopus.com/inward/record.uri?eid=2-s2.0-82755170946"}
            ],
        }

        paper = self.list_papers.normalize_scopus_entry(entry)

        self.assertEqual(paper["title"], entry["dc:title"])
        self.assertEqual(paper["year"], 2011)
        self.assertEqual(paper["venue"], "Cell Stem Cell")
        self.assertEqual(paper["externalIds"]["DOI"], "10.1016/j.stem.2011.10.002")
        self.assertEqual(paper["externalIds"]["Scopus"], "82755170946")
        self.assertEqual(paper["externalIds"]["EID"], "2-s2.0-82755170946")
        self.assertEqual(paper["authors"], [{"name": "Smith J."}])
        self.assertEqual(paper["citedby_count"], 349)

    def test_scopus_source_preference_uses_elsevier_provider(self):
        target = {
            "paperId": "2-s2.0-1",
            "title": "Target",
            "year": 2024,
            "venue": "Venue",
            "externalIds": {"DOI": "10.1000/demo", "EID": "2-s2.0-1"},
            "citationCount": 12,
            "source_url": "https://www.scopus.com/record/display.uri?eid=2-s2.0-1",
        }
        rows = [
            {
                "citingPaper": {
                    "title": "Scopus Citing Paper",
                    "year": 2025,
                    "venue": "Scopus Journal",
                    "externalIds": {"DOI": "10.1000/citing", "EID": "2-s2.0-2"},
                    "authors": [{"name": "Grace Hopper"}],
                    "source_url": "https://www.scopus.com/record/display.uri?eid=2-s2.0-2",
                    "citedby_count": 3,
                }
            }
        ]

        with mock.patch.dict(os.environ, {"ACADEMIC_IMPACT_CITATION_SOURCE": "scopus"}), \
                mock.patch.object(self.list_papers, "resolve_paper", side_effect=AssertionError("semantic should be bypassed")), \
                mock.patch.object(self.list_papers, "resolve_paper_openalex", side_effect=AssertionError("openalex should be bypassed")), \
                mock.patch.object(self.list_papers, "resolve_paper_scopus", return_value=target), \
                mock.patch.object(self.list_papers, "fetch_citations_scopus", return_value=rows):
            payload = self.list_papers.list_all_citations("Target", limit=1)

        self.assertEqual(payload["data_provider"], "Scopus")
        self.assertEqual(payload["total_citation_count"], 12)
        self.assertEqual(payload["source_url"], target["source_url"])
        self.assertEqual(payload["papers"][0]["title"], "Scopus Citing Paper")
        self.assertEqual(payload["papers"][0]["author_details"][0]["name"], "Grace Hopper")

    def test_scopus_fetch_tries_reference_queries_until_results(self):
        target = {
            "paperId": "2-s2.0-1",
            "title": "Target Paper",
            "externalIds": {"DOI": "10.1000/demo", "EID": "2-s2.0-1"},
        }
        calls = []
        empty = {"entry": []}
        hit = {
            "entry": [
                {
                    "dc:title": "Citing",
                    "prism:coverDate": "2025-01-01",
                    "prism:publicationName": "Journal",
                    "dc:creator": "Ada",
                    "eid": "2-s2.0-2",
                }
            ]
        }

        def fake_search(query, *, count, start, field):
            calls.append(query)
            return hit if query.startswith("REFDOI(") else empty

        with mock.patch.object(self.list_papers, "scopus_search", side_effect=fake_search):
            rows = self.list_papers.fetch_citations_scopus(target, fetch_limit=10)

        self.assertEqual(calls[:3], ["REFEID(2-s2.0-1)", "REFEID(1)", "REFDOI(10.1000/demo)"])
        self.assertEqual(rows[0]["citingPaper"]["title"], "Citing")

    def test_scopus_source_requires_elsevier_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ELSEVIER_API_KEY"):
                self.list_papers.elsevier_headers()


if __name__ == "__main__":
    unittest.main()
