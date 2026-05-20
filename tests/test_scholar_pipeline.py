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
        self.assertEqual(edge["source_publication_authors"], [])
        self.assertEqual(edge["citing_doi"], "10.1000/citing")
        self.assertEqual(edge["citing_year"], 2025)
        self.assertEqual(edge["citing_venue"], "ACM MobiCom")
        self.assertEqual(edge["citing_authors"], ["Fellow A"])
        self.assertEqual(edge["provider"], "Scopus")
        self.assertEqual(edge["source_url"], "https://example.test/citing")
        self.assertEqual(expanded["statistics"]["citation_edge_count"], 1)

    def test_expand_publication_citations_preserves_author_details(self):
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
            "data_provider": "OpenAlex",
            "papers": [
                {
                    "paperId": "openalex-citing-001",
                    "title": "Citing Paper",
                    "year": 2025,
                    "venue": "ACM MobiCom",
                    "externalIds": {"DOI": "10.1000/citing"},
                    "authors": ["Meng L."],
                    "author_details": [
                        {
                            "name": "Lingkai Meng",
                            "author_id": "https://openalex.org/A123",
                            "source_url": "https://openalex.org/A123",
                            "institutions": ["Nanjing University"],
                        }
                    ],
                }
            ],
        }

        with mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
            return_value=citation_result,
        ):
            expanded = self.pipeline.expand_publication_citations(
                session,
                limit_per_publication=10,
            )

        edge = expanded["citation_edges"][0]
        self.assertEqual(edge["citing_authors"], ["Lingkai Meng"])
        self.assertEqual(edge["citing_author_details"][0]["name"], "Lingkai Meng")
        self.assertEqual(edge["citing_author_details"][0]["institutions"], ["Nanjing University"])

    def test_expand_publication_citations_builds_person_candidates_from_citing_authors(self):
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
                    "title": "Fellow Citing Paper",
                    "year": 2025,
                    "venue": "ACM MobiCom",
                    "externalIds": {"DOI": "10.1000/citing"},
                    "authors": ["Alice Fellow"],
                }
            ],
        }
        registry_entries = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "aliases": [],
                "source_links": ["https://example.test/alice"],
                "matched_affiliations": [],
                "note": "",
            }
        ]

        with mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
            return_value=citation_result,
        ), mock.patch.object(
            self.pipeline.SCHOLAR_STATS.PERSON_CANDIDATES,
            "load_registry",
            return_value=registry_entries,
        ):
            expanded = self.pipeline.expand_publication_citations(
                session,
                limit_per_publication=10,
            )

        self.assertEqual(len(expanded["person_candidates"]), 1)
        self.assertEqual(expanded["person_candidates"][0]["name"], "Alice Fellow")
        self.assertEqual(
            expanded["statistics"]["person_tag_statistics"][0]["tag_label"],
            "ACM Fellow",
        )
        self.assertIn(
            "person_tag:ACM Fellow",
            expanded["deep_analysis_queue"][0]["reasons"],
        )

    def test_expand_publication_citations_preserves_strong_evidence_count(self):
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
            "statistics": {"strong_evidence_count": 7},
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
                }
            ],
        }

        with mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
            return_value=citation_result,
        ):
            expanded = self.pipeline.expand_publication_citations(
                session,
                limit_per_publication=10,
            )

        self.assertEqual(expanded["statistics"]["strong_evidence_count"], 7)

    def test_rebuild_scholar_derived_outputs_uses_existing_edges_without_provider_calls(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "citation_count": 12,
                }
            ],
            "citation_edges": [
                {
                    "source_publication_id": "S001",
                    "cited_publication_title": "Target Paper",
                    "citing_paper_id": "C001",
                    "citing_title": "Top Venue Citation",
                    "citing_year": 2025,
                    "citing_venue": "ACM MobiCom",
                    "citing_authors": ["Alice Fellow"],
                }
            ],
            "person_candidates": [],
            "deep_analysis_queue": [],
            "statistics": {"strong_evidence_count": 3},
        }
        registry_entries = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "aliases": [],
                "source_links": ["https://example.test/alice"],
                "matched_affiliations": [],
                "note": "",
            }
        ]

        with mock.patch.object(
            self.pipeline.SCHOLAR_STATS.PERSON_CANDIDATES,
            "load_registry",
            return_value=registry_entries,
        ), mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
        ) as list_all_citations:
            rebuilt = self.pipeline.rebuild_scholar_derived_outputs(
                session,
                queue_limit=10,
            )

        list_all_citations.assert_not_called()
        self.assertEqual(rebuilt["statistics"]["citation_edge_count"], 1)
        self.assertEqual(rebuilt["statistics"]["strong_evidence_count"], 3)
        self.assertEqual(rebuilt["person_candidates"][0]["name"], "Alice Fellow")
        self.assertEqual(len(rebuilt["deep_analysis_queue"]), 1)
        self.assertIn(
            "person_tag:ACM Fellow",
            rebuilt["deep_analysis_queue"][0]["reasons"],
        )

    def test_rebuild_scholar_derived_outputs_preserves_manual_queue_pdf(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "citation_count": 12,
                }
            ],
            "citation_edges": [
                {
                    "source_publication_id": "S001",
                    "cited_publication_title": "Target Paper",
                    "citing_paper_id": "C001",
                    "citing_title": "Top Venue Citation",
                    "citing_year": 2025,
                    "citing_venue": "ACM MobiCom",
                    "citing_authors": ["Regular Author"],
                }
            ],
            "person_candidates": [],
            "deep_analysis_queue": [
                {
                    "queue_id": "Q009",
                    "source_publication_ids": ["S001"],
                    "citing_paper_id": "C001",
                    "citing_title": "Top Venue Citation",
                    "citing_year": 2025,
                    "citing_venue": "ACM MobiCom",
                    "citing_authors": ["Regular Author"],
                    "manual_pdf": {
                        "status": "manual_pdf_attached",
                        "local_file_path": "/tmp/top-venue.pdf",
                    },
                }
            ],
            "statistics": {},
        }

        rebuilt = self.pipeline.rebuild_scholar_derived_outputs(
            session,
            queue_limit=10,
        )

        self.assertEqual(
            rebuilt["deep_analysis_queue"][0]["manual_pdf"]["local_file_path"],
            "/tmp/top-venue.pdf",
        )

    def test_rebuild_scholar_derived_outputs_attaches_local_library_pdf(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "citation_count": 12,
                }
            ],
            "citation_edges": [
                {
                    "source_publication_id": "S001",
                    "cited_publication_title": "Target Paper",
                    "citing_paper_id": "C001",
                    "citing_title": "Top Venue Citation",
                    "citing_doi": "10.1000/citing",
                    "citing_year": 2025,
                    "citing_venue": "ACM MobiCom",
                    "citing_authors": ["Regular Author"],
                }
            ],
            "person_candidates": [],
            "deep_analysis_queue": [],
            "statistics": {},
        }

        with mock.patch.object(
            self.pipeline.RUN_PIPELINE.DOWNLOAD_PDF,
            "find_local_pdf_with_metadata",
            return_value={
                "local_file_path": "/tmp/library/top-venue.pdf",
                "matched_dir": "/tmp/library",
                "match_source": "index_cache",
            },
        ) as find_local_pdf_with_metadata:
            rebuilt = self.pipeline.rebuild_scholar_derived_outputs(
                session,
                queue_limit=10,
            )

        find_local_pdf_with_metadata.assert_called_once()
        library_pdf = rebuilt["deep_analysis_queue"][0]["library_pdf"]
        self.assertEqual(library_pdf["status"], "local_library_matched")
        self.assertEqual(library_pdf["source"], "local_pdf_library")
        self.assertEqual(library_pdf["local_file_path"], "/tmp/library/top-venue.pdf")

    def test_analyze_scholar_queue_records_strong_evidence_for_selected_items(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "year": 2024,
                    "venue": "ACM MobiCom",
                    "doi": "10.1000/target",
                    "citation_count": 12,
                }
            ],
            "citation_edges": [],
            "person_candidates": [
                {
                    "name": "Alice Fellow",
                    "tag_type": "acm_fellow",
                    "tag_label": "ACM Fellow",
                    "status": "pending",
                }
            ],
            "deep_analysis_queue": [
                {
                    "queue_id": "Q001",
                    "source_publication_ids": ["S001"],
                    "citing_paper_id": "C001",
                    "citing_title": "Fellow Citing Paper",
                    "citing_year": 2025,
                    "citing_venue": "ACM MobiCom",
                    "citing_doi": "10.1000/citing",
                    "citing_authors": ["Alice Fellow"],
                    "source_url": "https://example.test/citing",
                },
                {
                    "queue_id": "Q002",
                    "source_publication_ids": ["S001"],
                    "citing_paper_id": "C002",
                    "citing_title": "Unselected Paper",
                    "citing_authors": ["Regular Author"],
                },
            ],
            "statistics": {"strong_evidence_count": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)

            def fake_process_citing_paper(**kwargs):
                item_dir = kwargs["item_dir"]
                item_dir.mkdir(parents=True, exist_ok=True)
                analysis_path = item_dir / "fulltext_analysis.json"
                analysis_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "findings": [
                                {
                                    "citation_text": "This influential work is important. " * 4,
                                    "aspect": "method",
                                    "stance": "positive",
                                    "function": "引用者正向采用目标工作。",
                                    "reason": "正文给出正向评价并采用。",
                                    "confidence": 0.92,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return {
                    "status": "fulltext_analyzed",
                    "paths": {"analysis": str(analysis_path)},
                    "analysis": {"findings_count": 1},
                }

            with mock.patch.object(
                self.pipeline.RUN_PIPELINE,
                "process_citing_paper",
                side_effect=fake_process_citing_paper,
            ) as process_citing_paper:
                analyzed = self.pipeline.analyze_scholar_queue(
                    session,
                    session_dir,
                    queue_ids=["Q001"],
                    top_k_spans=8,
                    analysis_scope="fulltext_direct",
                )

        process_citing_paper.assert_called_once()
        self.assertEqual(len(analyzed["scholar_fulltext_results"]), 1)
        self.assertEqual(analyzed["scholar_fulltext_results"][0]["queue_id"], "Q001")
        self.assertEqual(len(analyzed["strong_evidence"]), 1)
        self.assertTrue(analyzed["strong_evidence"][0]["fellow_strong_citation"])
        self.assertEqual(analyzed["statistics"]["strong_evidence_count"], 1)

    def test_analyze_scholar_queue_passes_attached_pdf_path(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "year": 2024,
                    "venue": "ACM MobiCom",
                    "doi": "10.1000/target",
                }
            ],
            "citation_edges": [],
            "deep_analysis_queue": [
                {
                    "queue_id": "Q001",
                    "source_publication_ids": ["S001"],
                    "citing_paper_id": "C001",
                    "citing_title": "Manual PDF Citing Paper",
                    "manual_pdf": {
                        "status": "manual_pdf_attached",
                        "local_file_path": "/tmp/manual-citing.pdf",
                    },
                }
            ],
            "statistics": {},
        }
        observed_paths = []

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)

            def fake_process_citing_paper(**kwargs):
                observed_paths.append(kwargs.get("local_pdf_path"))
                item_dir = kwargs["item_dir"]
                item_dir.mkdir(parents=True, exist_ok=True)
                analysis_path = item_dir / "fulltext_analysis.json"
                analysis_path.write_text(
                    json.dumps({"ok": True, "findings": []}),
                    encoding="utf-8",
                )
                return {
                    "status": "fulltext_analyzed",
                    "paths": {"analysis": str(analysis_path)},
                    "analysis": {"findings_count": 0},
                }

            with mock.patch.object(
                self.pipeline.RUN_PIPELINE,
                "process_citing_paper",
                side_effect=fake_process_citing_paper,
            ):
                self.pipeline.analyze_scholar_queue(
                    session,
                    session_dir,
                    queue_ids=["Q001"],
                    analysis_scope="fulltext_direct",
                )

        self.assertEqual(observed_paths, ["/tmp/manual-citing.pdf"])

    def test_analyze_scholar_queue_uses_library_pdf_when_manual_missing(self):
        observed_paths = []

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            library_pdf_path = session_dir / "library-citing.pdf"
            library_pdf_path.write_bytes(b"%PDF-1.4\n% local library pdf\n")
            session = {
                "publications": [
                    {
                        "id": "S001",
                        "title": "Target Paper",
                        "year": 2024,
                        "venue": "ACM MobiCom",
                        "doi": "10.1000/target",
                    }
                ],
                "citation_edges": [],
                "deep_analysis_queue": [
                    {
                        "queue_id": "Q001",
                        "source_publication_ids": ["S001"],
                        "citing_paper_id": "C001",
                        "citing_title": "Library PDF Citing Paper",
                        "library_pdf": {
                            "status": "local_library_matched",
                            "local_file_path": str(library_pdf_path),
                        },
                    }
                ],
                "statistics": {},
            }

            def fake_process_citing_paper(**kwargs):
                observed_paths.append(kwargs.get("local_pdf_path"))
                item_dir = kwargs["item_dir"]
                item_dir.mkdir(parents=True, exist_ok=True)
                analysis_path = item_dir / "fulltext_analysis.json"
                analysis_path.write_text(
                    json.dumps({"ok": True, "findings": []}),
                    encoding="utf-8",
                )
                return {
                    "status": "fulltext_analyzed",
                    "paths": {"analysis": str(analysis_path)},
                    "analysis": {"findings_count": 0},
                }

            with mock.patch.object(
                self.pipeline.RUN_PIPELINE,
                "process_citing_paper",
                side_effect=fake_process_citing_paper,
            ):
                self.pipeline.analyze_scholar_queue(
                    session,
                    session_dir,
                    queue_ids=["Q001"],
                    analysis_scope="fulltext_direct",
                )

        self.assertEqual(observed_paths, [str(library_pdf_path)])

    def test_analyze_scholar_queue_emits_stage_progress(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "doi": "10.1000/target",
                }
            ],
            "citation_edges": [],
            "deep_analysis_queue": [
                {
                    "queue_id": "Q001",
                    "source_publication_ids": ["S001"],
                    "citing_paper_id": "C001",
                    "citing_title": "Citing Paper",
                    "citing_doi": "10.1000/citing",
                }
            ],
            "person_candidates": [],
            "statistics": {},
        }
        progress_events = []

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)

            def fake_process_citing_paper(**kwargs):
                progress_callback = kwargs.get("progress_callback")
                if progress_callback:
                    progress_callback(
                        {
                            "stage": "downloading_pdf",
                            "stage_message": "正在下载 PDF",
                        }
                    )
                    progress_callback(
                        {
                            "stage": "analyzing_fulltext",
                            "stage_message": "正在调用模型分析全文",
                        }
                    )
                item_dir = kwargs["item_dir"]
                item_dir.mkdir(parents=True, exist_ok=True)
                analysis_path = item_dir / "fulltext_analysis.json"
                analysis_path.write_text(
                    json.dumps({"ok": True, "findings": []}),
                    encoding="utf-8",
                )
                return {
                    "status": "fulltext_analyzed",
                    "paths": {"analysis": str(analysis_path)},
                    "analysis": {"findings_count": 0},
                }

            with mock.patch.object(
                self.pipeline.RUN_PIPELINE,
                "process_citing_paper",
                side_effect=fake_process_citing_paper,
            ):
                self.pipeline.analyze_scholar_queue(
                    session,
                    session_dir,
                    queue_ids=["Q001"],
                    progress_callback=progress_events.append,
                )

        stages = [event.get("stage") for event in progress_events]
        self.assertIn("preparing_item", stages)
        self.assertIn("downloading_pdf", stages)
        self.assertIn("analyzing_fulltext", stages)
        self.assertIn("writing_results", stages)
        self.assertEqual(progress_events[0]["current_title"], "Citing Paper")
        self.assertEqual(progress_events[0]["current_index"], 1)

    def test_analyze_scholar_queue_deduplicates_same_evidence_for_duplicate_targets(self):
        session = {
            "publications": [
                {"id": "S001", "title": "Trust: Triangle Counting Reloaded on GPUs."},
                {"id": "S002", "title": "TRUST: Triangle Counting Reloaded on GPUs."},
            ],
            "citation_edges": [],
            "deep_analysis_queue": [
                {
                    "queue_id": "Q001",
                    "source_publication_ids": ["S001", "S002"],
                    "citing_paper_id": "C001",
                    "citing_title": "A Survey of Distributed Graph Algorithms on Massive Graphs",
                }
            ],
            "person_candidates": [],
            "statistics": {},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)

            def fake_process_citing_paper(**kwargs):
                item_dir = kwargs["item_dir"]
                item_dir.mkdir(parents=True, exist_ok=True)
                analysis_path = item_dir / "fulltext_analysis.json"
                analysis_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "findings": [
                                {
                                    "citation_text": "Partition-based methods cite several target papers together.",
                                    "aspect": "background",
                                    "stance": "neutral",
                                    "mention_type": "grouped_literature_mention",
                                    "page": 10,
                                    "span_index": 6,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return {
                    "status": "fulltext_analyzed",
                    "paths": {"analysis": str(analysis_path)},
                    "analysis": {"findings_count": 1},
                }

            with mock.patch.object(
                self.pipeline.RUN_PIPELINE,
                "process_citing_paper",
                side_effect=fake_process_citing_paper,
            ):
                analyzed = self.pipeline.analyze_scholar_queue(
                    session,
                    session_dir,
                    queue_ids=["Q001"],
                )

        self.assertEqual(len(analyzed["scholar_fulltext_results"]), 2)
        self.assertEqual(len(analyzed["strong_evidence"]), 1)
        self.assertEqual(analyzed["statistics"]["strong_evidence_count"], 1)

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

    def test_expand_publication_citations_reports_progress(self):
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
            "data_provider": "OpenAlex",
            "papers": [
                {
                    "title": "Citing Paper",
                    "year": 2025,
                    "venue": "ACM MobiCom",
                    "externalIds": {"OpenAlex": "W123"},
                    "authors": [{"name": "Fellow B"}],
                }
            ],
        }
        progress_events = []

        with mock.patch.object(
            self.pipeline.LIST_PAPERS,
            "list_all_citations",
            return_value=citation_result,
        ):
            self.pipeline.expand_publication_citations(
                session,
                limit_per_publication=10,
                progress_callback=progress_events.append,
            )

        self.assertEqual(progress_events[-1]["processed_count"], 1)
        self.assertEqual(progress_events[-1]["total_count"], 1)
        self.assertEqual(progress_events[-1]["citation_edge_count"], 1)

    def test_normalize_deep_analysis_finding_marks_long_positive_fellow_citation(self):
        edge = {
            "source_publication_id": "S001",
            "citing_title": "Fellow Citation",
            "citing_authors": ["Alice Fellow"],
        }
        finding = {
            "citation_text": "This influential system changed the way we build network simulators. " * 3,
            "aspect": "method",
            "stance": "positive",
            "function": "引用者采用了目标工作的核心方法。",
            "reason": "正文明确肯定并采用该方法。",
            "confidence": 0.91,
        }

        evidence = self.pipeline.normalize_strong_evidence(edge, finding, person_tag_labels=["ACM Fellow"])

        self.assertTrue(evidence["long_context_100_chars"])
        self.assertTrue(evidence["positive_evaluation"])
        self.assertTrue(evidence["fellow_strong_citation"])
        self.assertEqual(evidence["aspect"], "method")
        self.assertIn("positive_evaluation", evidence["evidence_labels"])
        self.assertIn("method_foundation", evidence["evidence_labels"])
        self.assertIn("important_person", evidence["evidence_labels"])
        self.assertGreaterEqual(evidence["strong_citation_score"], 75)
        self.assertEqual(evidence["evidence_strength"], "high")

    def test_normalize_strong_evidence_marks_self_citation(self):
        edge = {
            "source_publication_id": "S001",
            "source_publication_authors": ["Chen Tian"],
            "citing_title": "Self Citation",
            "citing_authors": ["Tian Chen"],
        }
        finding = {
            "citation_text": "This work is used as a baseline.",
            "aspect": "baseline",
            "stance": "positive",
            "confidence": 0.9,
        }

        evidence = self.pipeline.normalize_strong_evidence(edge, finding, person_tag_labels=[])

        self.assertEqual(evidence["self_citation_status"], "self_citation")
        self.assertEqual(evidence["self_citation_overlap_authors"], ["Tian Chen"])
        self.assertIn("baseline", evidence["evidence_labels"])


if __name__ == "__main__":
    unittest.main()
