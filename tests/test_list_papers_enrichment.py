import unittest
from unittest.mock import patch

from skills.list_all_citations import list_papers


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class ListPapersOpenAlexEnrichmentTest(unittest.TestCase):
    def semantic_target(self):
        return {
            "paperId": "S2TARGET",
            "title": "Target Paper",
            "year": 2025,
            "venue": "Conference",
            "externalIds": {"DOI": "10.0000/target"},
            "citationCount": 3,
            "influentialCitationCount": 0,
        }

    def semantic_citation_rows(self):
        return [
            {
                "citingPaper": {
                    "title": "Citing Paper",
                    "year": 2026,
                    "venue": "arXiv.org",
                    "externalIds": {"DOI": "10.1234/citing"},
                    "authors": [
                        {"name": "Jane Doe", "authorId": "S2A1"},
                        {"name": "John Smith", "authorId": "S2A2"},
                    ],
                }
            }
        ]

    def openalex_work(self):
        return {
            "title": "Citing Paper",
            "doi": "https://doi.org/10.1234/citing",
            "authorships": [
                {
                    "author": {"display_name": "Jane Doe", "id": "https://openalex.org/A1"},
                    "institutions": [
                        {"display_name": "Massachusetts Institute of Technology", "id": "https://openalex.org/I63966007"}
                    ],
                },
                {
                    "author": {"display_name": "John Smith", "id": "https://openalex.org/A2"},
                    "institutions": [
                        {"display_name": "Carnegie Mellon University", "id": "https://openalex.org/I74973139"}
                    ],
                },
            ],
        }

    @patch.object(list_papers, "safe_get_openalex")
    @patch.object(list_papers, "fetch_citations")
    @patch.object(list_papers, "resolve_paper")
    def test_semantic_scholar_results_are_enriched_with_openalex_institutions(
        self,
        resolve_paper,
        fetch_citations,
        safe_get_openalex,
    ):
        resolve_paper.return_value = self.semantic_target()
        fetch_citations.return_value = self.semantic_citation_rows()
        safe_get_openalex.return_value = FakeResponse(self.openalex_work())

        result = list_papers.list_all_citations(
            "Target Paper",
            limit=1,
            fetch_limit=1,
            enrich_openalex=True,
            openalex_enrichment_limit=1,
        )

        self.assertEqual(result["data_provider"], "Semantic Scholar")
        self.assertEqual(result["openalex_enrichment"]["attempted"], 1)
        self.assertEqual(result["openalex_enrichment"]["enriched"], 1)
        details = result["papers"][0]["author_details"]
        self.assertEqual(details[0]["name"], "Jane Doe")
        self.assertEqual(details[0]["institutions"], ["Massachusetts Institute of Technology"])
        self.assertEqual(details[0]["openalex_author_id"], "https://openalex.org/A1")
        self.assertEqual(details[1]["institutions"], ["Carnegie Mellon University"])

    @patch.object(list_papers, "resolve_openalex_work_for_paper")
    @patch.object(list_papers, "fetch_citations")
    @patch.object(list_papers, "resolve_paper")
    def test_openalex_enrichment_failure_keeps_semantic_scholar_result_successful(
        self,
        resolve_paper,
        fetch_citations,
        resolve_openalex_work_for_paper,
    ):
        resolve_paper.return_value = self.semantic_target()
        fetch_citations.return_value = self.semantic_citation_rows()
        resolve_openalex_work_for_paper.side_effect = RuntimeError("rate limited")

        result = list_papers.list_all_citations(
            "Target Paper",
            limit=1,
            fetch_limit=1,
            enrich_openalex=True,
            openalex_enrichment_limit=1,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data_provider"], "Semantic Scholar")
        self.assertEqual(result["openalex_enrichment"]["attempted"], 1)
        self.assertEqual(result["openalex_enrichment"]["enriched"], 0)
        self.assertIn("OpenAlex affiliation enrichment skipped", result["warnings"][0])
        self.assertEqual(result["papers"][0]["author_details"][0]["institutions"], [])

    @patch.object(list_papers, "resolve_openalex_work_for_paper")
    @patch.object(list_papers, "fetch_citations_openalex")
    @patch.object(list_papers, "resolve_paper_openalex")
    @patch.object(list_papers, "resolve_paper")
    def test_openalex_fallback_path_is_not_re_enriched(
        self,
        resolve_paper,
        resolve_paper_openalex,
        fetch_citations_openalex,
        resolve_openalex_work_for_paper,
    ):
        resolve_paper.side_effect = RuntimeError("semantic scholar unavailable")
        resolve_paper_openalex.return_value = {
            "paperId": "https://openalex.org/W1",
            "title": "Target Paper",
            "year": 2025,
            "venue": "OpenAlex Venue",
            "externalIds": {"DOI": "10.0000/target"},
            "citationCount": 1,
        }
        fetch_citations_openalex.return_value = [
            {
                "citingPaper": {
                    "title": "Fallback Citing Paper",
                    "year": 2024,
                    "venue": "OpenAlex Venue",
                    "externalIds": {"DOI": "10.1234/fallback"},
                    "authors": [
                        {
                            "name": "Ada Lovelace",
                            "id": "https://openalex.org/Ada",
                            "institutions": [
                                {"display_name": "Stanford University", "id": "https://openalex.org/I97018004"}
                            ],
                        }
                    ],
                }
            }
        ]

        result = list_papers.list_all_citations(
            "Target Paper",
            limit=1,
            fetch_limit=1,
            enrich_openalex=True,
            openalex_enrichment_limit=1,
        )

        self.assertEqual(result["data_provider"], "OpenAlex (Fallback)")
        self.assertFalse(result["openalex_enrichment"]["enabled"])
        resolve_openalex_work_for_paper.assert_not_called()
        self.assertEqual(result["papers"][0]["author_details"][0]["institutions"], ["Stanford University"])

    def test_work_match_accepts_doi_urls_and_rejects_short_title_substrings(self):
        paper = {"title": "AI", "externalIds": {"DOI": "https://doi.org/10.1234/citing"}}
        self.assertTrue(list_papers.work_matches_paper({"doi": "10.1234/citing", "title": "Other"}, paper))
        self.assertFalse(list_papers.work_matches_paper({"title": "Mainstream Brain Study"}, {"title": "AI"}))


if __name__ == "__main__":
    unittest.main()
