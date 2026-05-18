from __future__ import annotations

import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app
from app.services import impact_core, scholar_core


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

    def test_scholar_route_renders_local_pdf_index_controls(self):
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
                    "deep_analysis_queue": [
                        {
                            "queue_id": "Q001",
                            "citing_title": "Library Paper",
                            "library_pdf": {"status": "local_library_matched"},
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        with mock.patch.object(
            scholar_core,
            "load_local_pdf_index_status",
            return_value={
                "exists": True,
                "entry_count": 128,
                "scanned_pdf_count": 128,
                "build_elapsed_ms": 240,
                "refresh_total_ms": 840,
                "queue_rematch_elapsed_ms": 600,
                "generated_at": "2026-05-18T10:00:00",
                "index_path": "/tmp/local_pdf_index.json",
                "search_dirs": ["/papers"],
            },
        ):
            response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("刷新本地 PDF 索引", response.text)
        self.assertIn("当前索引条目：128", response.text)
        self.assertIn("上次扫描 PDF：128", response.text)
        self.assertIn("队列命中本地 PDF：1", response.text)
        self.assertIn("构建耗时：0.24 秒", response.text)
        self.assertIn("本次刷新总耗时：0.84 秒", response.text)
        self.assertIn("队列重匹配耗时：0.6 秒", response.text)
        self.assertIn("/tmp/local_pdf_index.json", response.text)

    def test_scholar_route_renders_expansion_controls_and_queue(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [
                        {
                            "id": "S001",
                            "title": "Paper One",
                            "year": 2025,
                            "venue": "ACM MobiCom",
                            "unique_ids": {"DBLP": "conf/test/one"},
                        }
                    ],
                    "citation_edges": [{"citing_title": "Citing Paper"}],
                    "deep_analysis_queue": [
                        {
                            "citing_title": "Citing Paper",
                            "citing_venue": "ACM MobiCom",
                            "citing_year": 2026,
                            "citing_authors": ["Alice Fellow"],
                            "priority_score": 50,
                            "reasons": ["person_tag:ACM Fellow"],
                        }
                    ],
                    "statistics": {
                        "publication_count": 1,
                        "citation_edge_count": 1,
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
        self.assertIn("展开引用论文", response.text)
        self.assertIn("高价值引用队列", response.text)
        self.assertIn('name="queue_ids"', response.text)
        self.assertIn("分析所选引用论文", response.text)
        self.assertIn("person_tag:ACM Fellow", response.text)
        self.assertIn("CCF A", response.text)

    def test_scholar_route_separates_publication_and_citation_statistics(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [],
                    "citation_edges": [{"citing_title": "Citing Paper"}],
                    "deep_analysis_queue": [],
                    "person_candidates": [],
                    "statistics": {
                        "publication_count": 190,
                        "citation_edge_count": 3450,
                        "publication_tiers": [
                            {"tier_label": "未匹配等级", "count": 175},
                            {"tier_label": "Top venue seed", "count": 15},
                        ],
                        "citing_venue_tiers": [
                            {"tier_label": "CCF A", "count": 211},
                            {"tier_label": "未匹配等级", "count": 3239},
                        ],
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
        self.assertIn("本人论文 venue 分级", response.text)
        self.assertIn("引用论文 venue 分级", response.text)
        self.assertIn("已展开 3450 条引用边", response.text)
        self.assertIn("CCF A: 211", response.text)
        self.assertIn("本地人物 registry 暂未命中", response.text)

    def test_scholar_route_filters_high_value_queue_by_reason(self):
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
                    "deep_analysis_queue": [
                        {
                            "citing_title": "Venue Citing Paper",
                            "citing_venue": "ACM MobiCom",
                            "citing_authors": ["Regular Author"],
                            "priority_score": 25,
                            "reasons": ["venue:CCF A"],
                        },
                        {
                            "citing_title": "Fellow Citing Paper",
                            "citing_venue": "Unknown Venue",
                            "citing_authors": ["Alice Fellow"],
                            "priority_score": 50,
                            "reasons": ["person_tag:ACM Fellow"],
                        },
                    ],
                    "statistics": {
                        "publication_count": 0,
                        "citation_edge_count": 0,
                        "person_tag_statistics": [],
                    },
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(
            f"/scholars/{TEST_SESSION_ID}",
            params={
                "queue_reason": "person_tag:ACM Fellow",
                "queue_page_size": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Fellow Citing Paper", response.text)
        self.assertNotIn("Venue Citing Paper</td>", response.text)
        self.assertIn("当前显示 1 / 2 篇高价值引用论文", response.text)

    def test_scholar_route_renders_queue_analysis_readiness(self):
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
                    "deep_analysis_queue": [
                        {
                            "queue_id": "Q001",
                            "citing_title": "Missing PDF Paper",
                            "citing_doi": "10.1000/missing",
                            "priority_score": 25,
                            "reasons": ["venue:CCF A"],
                        }
                    ],
                    "scholar_fulltext_results": [
                        {
                            "queue_id": "Q001",
                            "status": "context_only",
                            "download": {
                                "source": "manual_required",
                                "error": "未找到合法开源 PDF 链接。",
                            },
                            "analysis": {"error_type": "download_failed"},
                        }
                    ],
                    "statistics": {
                        "publication_count": 0,
                        "citation_edge_count": 0,
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
        self.assertIn("准备状态", response.text)
        self.assertIn("DOI: 10.1000/missing", response.text)
        self.assertIn("context_only", response.text)
        self.assertIn("manual_required", response.text)
        self.assertIn("建议先上传 PDF", response.text)
        self.assertIn("未找到合法开源 PDF 链接。", response.text)
        self.assertIn("分析会先尝试自动下载 PDF", response.text)
        self.assertIn(
            f'action="/scholars/{TEST_SESSION_ID}/attach-queue-pdf"',
            response.text,
        )
        self.assertIn('name="pdf_file"', response.text)

    def test_scholar_route_renders_local_library_ready_queue_item(self):
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
                    "deep_analysis_queue": [
                        {
                            "queue_id": "Q001",
                            "citing_title": "Library Paper",
                            "citing_doi": "10.1000/library",
                            "priority_score": 25,
                            "reasons": ["venue:CCF A"],
                            "library_pdf": {
                                "status": "local_library_matched",
                                "source": "local_pdf_library",
                                "local_file_path": "/tmp/library.pdf",
                            },
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("已命中本地论文库，可直接分析", response.text)
        self.assertIn("本地库 PDF：/tmp/library.pdf", response.text)

    def test_scholar_attach_queue_pdf_route_updates_queue_item(self):
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
                    "deep_analysis_queue": [
                        {
                            "queue_id": "Q001",
                            "citing_title": "Missing PDF Paper",
                            "priority_score": 25,
                            "reasons": ["venue:CCF A"],
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.post(
            f"/scholars/{TEST_SESSION_ID}/attach-queue-pdf",
            data={"queue_id": "Q001"},
            files={"pdf_file": ("manual.pdf", b"%PDF-1.4\n% test pdf\n", "application/pdf")},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/scholars/{TEST_SESSION_ID}#deep-analysis-queue",
        )
        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)
        manual_pdf = payload["deep_analysis_queue"][0]["manual_pdf"]
        self.assertEqual(manual_pdf["status"], "manual_pdf_attached")
        self.assertEqual(manual_pdf["source"], "manual_upload")
        self.assertTrue(Path(manual_pdf["local_file_path"]).exists())

        page = client.get(f"/scholars/{TEST_SESSION_ID}")
        self.assertIn("manual_pdf_attached", page.text)

    def test_build_deep_analysis_queue_view_paginates(self):
        session = {
            "deep_analysis_queue": [
                {
                    "citing_title": f"Citing {index}",
                    "reasons": ["venue:CCF A"],
                }
                for index in range(3)
            ]
        }

        view = scholar_core.build_deep_analysis_queue_view(
            session,
            page=2,
            page_size=2,
        )

        self.assertEqual(view["total_count"], 3)
        self.assertEqual(view["items"][0]["citing_title"], "Citing 2")
        self.assertEqual(view["pagination"]["page"], 2)
        self.assertFalse(view["pagination"]["has_next"])
        self.assertTrue(view["pagination"]["has_previous"])

    def test_build_deep_analysis_queue_view_adds_analysis_readiness(self):
        session = {
            "deep_analysis_queue": [
                {
                    "queue_id": "Q001",
                    "citing_title": "Failed Citing Paper",
                    "citing_doi": "10.1000/failed",
                    "citing_scopus_id": "2-s2.0-123",
                    "reasons": ["venue:CCF A"],
                    "manual_pdf": {
                        "status": "manual_pdf_attached",
                        "local_file_path": "/tmp/manual.pdf",
                    },
                },
                {
                    "queue_id": "Q002",
                    "citing_title": "Fresh Citing Paper",
                    "citing_openalex_id": "W123",
                    "reasons": ["venue:CCF A"],
                    "library_pdf": {
                        "status": "local_library_matched",
                        "source": "local_pdf_library",
                        "local_file_path": "/tmp/library.pdf",
                    },
                },
                {
                    "queue_id": "Q003",
                    "citing_title": "No Identifier Paper",
                    "reasons": ["venue:CCF A"],
                },
            ],
            "scholar_fulltext_results": [
                {
                    "queue_id": "Q001",
                    "status": "context_only",
                    "download": {
                        "source": "manual_required",
                        "error": "未找到合法开源 PDF 链接。",
                    },
                    "analysis": {"error_type": "download_failed"},
                }
            ],
        }

        view = scholar_core.build_deep_analysis_queue_view(session)

        failed = view["items"][0]
        fresh = view["items"][1]
        missing_id = view["items"][2]
        self.assertEqual(failed["analysis_status"], "context_only")
        self.assertEqual(failed["analysis_failure_message"], "未找到合法开源 PDF 链接。")
        self.assertEqual(failed["download_source"], "manual_pdf_attached")
        self.assertEqual(failed["manual_pdf_path"], "/tmp/manual.pdf")
        self.assertEqual(failed["citing_identifier"], "DOI: 10.1000/failed")
        self.assertEqual(failed["readiness_label"], "已上传 PDF，可重试")
        self.assertEqual(failed["readiness_status"], "manual_pdf_ready")
        self.assertEqual(fresh["analysis_status"], "local_library_matched")
        self.assertEqual(fresh["download_source"], "local_library_matched")
        self.assertEqual(fresh["citing_identifier"], "OpenAlex: W123")
        self.assertEqual(fresh["library_pdf_path"], "/tmp/library.pdf")
        self.assertEqual(fresh["readiness_label"], "已命中本地论文库，可直接分析")
        self.assertEqual(fresh["readiness_status"], "local_library_ready")
        self.assertEqual(missing_id["citing_identifier"], "-")
        self.assertEqual(missing_id["readiness_label"], "缺少 DOI/ID，可能失败")
        self.assertEqual(missing_id["readiness_status"], "missing_identifier")

    def test_build_strong_evidence_view_filters_and_paginates(self):
        session = {
            "strong_evidence": [
                {
                    "citing_title": "Fellow Method Paper",
                    "aspect": "method",
                    "stance": "positive",
                    "fellow_strong_citation": True,
                    "positive_evaluation": True,
                    "long_context_100_chars": True,
                },
                {
                    "citing_title": "Neutral Baseline Paper",
                    "aspect": "baseline",
                    "stance": "neutral",
                    "fellow_strong_citation": False,
                },
                {
                    "citing_title": "Second Method Paper",
                    "aspect": "method",
                    "stance": "positive",
                    "positive_evaluation": True,
                },
            ]
        }

        view = scholar_core.build_strong_evidence_view(
            session,
            active_aspect="method",
            active_stance="positive",
            active_flag="positive",
            page=2,
            page_size=1,
        )

        self.assertEqual(view["total_count"], 2)
        self.assertEqual(view["unfiltered_count"], 3)
        self.assertEqual(view["items"][0]["citing_title"], "Second Method Paper")
        self.assertEqual(view["aspect_counts"]["method"], 2)
        self.assertEqual(view["stance_counts"]["positive"], 2)
        self.assertEqual(view["flag_counts"]["positive"], 2)
        self.assertTrue(view["pagination"]["has_previous"])
        self.assertIn("strong_page=1", view["pagination"]["previous_url"])
        self.assertIn("strong_aspect=method", view["pagination"]["previous_url"])

    def test_build_strong_evidence_view_deduplicates_same_citation(self):
        citation_text = "Partition-based methods cite several target papers together."
        session = {
            "strong_evidence": [
                {
                    "queue_id": "Q001",
                    "citing_title": "A Survey of Distributed Graph Algorithms on Massive Graphs",
                    "cited_publication_title": "Trust: Triangle Counting Reloaded on GPUs.",
                    "citation_text": citation_text,
                    "aspect": "background",
                    "stance": "neutral",
                    "page": 10,
                    "span_index": 6,
                },
                {
                    "queue_id": "Q001",
                    "citing_title": "A Survey of Distributed Graph Algorithms on Massive Graphs",
                    "cited_publication_title": "TRUST: Triangle Counting Reloaded on GPUs.",
                    "citation_text": citation_text,
                    "aspect": "background",
                    "stance": "neutral",
                    "page": 10,
                    "span_index": 6,
                },
            ]
        }

        view = scholar_core.build_strong_evidence_view(session)

        self.assertEqual(view["total_count"], 1)
        self.assertEqual(view["unfiltered_count"], 1)
        self.assertEqual(view["aspect_counts"]["background"], 1)
        self.assertEqual(view["items"][0]["cited_publication_title"], "Trust: Triangle Counting Reloaded on GPUs.")

    def test_build_person_candidate_view_filters_and_paginates(self):
        session = {
            "person_candidates": [
                {
                    "name": "Alice Fellow",
                    "tag_type": "acm_fellow",
                    "tag_label": "ACM Fellow",
                    "status": "pending",
                },
                {
                    "name": "Bob Fellow",
                    "tag_type": "ieee_fellow",
                    "tag_label": "IEEE Fellow",
                    "status": "confirmed",
                },
                {
                    "name": "Carol Fellow",
                    "tag_type": "ieee_fellow",
                    "tag_label": "IEEE Fellow",
                    "status": "confirmed",
                },
            ]
        }

        view = scholar_core.build_person_candidate_view(
            session,
            active_status="confirmed",
            active_tag_type="ieee_fellow",
            page=2,
            page_size=1,
        )

        self.assertEqual(view["total_count"], 2)
        self.assertEqual(view["unfiltered_count"], 3)
        self.assertEqual(view["items"][0]["name"], "Carol Fellow")
        self.assertEqual(view["pagination"]["page"], 2)
        self.assertTrue(view["pagination"]["has_previous"])
        self.assertFalse(view["pagination"]["has_next"])
        self.assertEqual(view["status_counts"]["pending"], 1)
        self.assertEqual(view["status_counts"]["confirmed"], 2)
        self.assertEqual(view["tag_options"][0]["tag_type"], "ieee_fellow")

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

    def test_home_recent_sessions_includes_scholar_sessions(self):
        client = TestClient(app)
        with mock.patch.object(impact_core, "list_sessions", return_value=[]), mock.patch.object(
            scholar_core,
            "list_scholar_sessions",
            return_value=[
                {
                    "id": TEST_SESSION_ID,
                    "query": "Chen Tian",
                    "updated_at": "2026-05-18T12:00:00",
                    "paper_count": 12,
                    "session_type": "scholar_impact",
                    "detail_url": f"/scholars/{TEST_SESSION_ID}",
                }
            ],
        ):
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(TEST_SESSION_ID, response.text)
        self.assertIn("/scholars/test_scholar_session", response.text)
        self.assertIn("Chen Tian", response.text)

    def test_make_scholar_session_id_avoids_fast_duplicate(self):
        first = scholar_core.make_scholar_session_id("Chen Tian")
        second = scholar_core.make_scholar_session_id("Chen Tian")

        self.assertNotEqual(first, second)
        self.assertIn("_scholar_chen_tian", first)

    def test_expand_scholar_citations_task_updates_session(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [{"id": "S001", "title": "Paper One"}],
                    "citation_edges": [],
                    "deep_analysis_queue": [],
                    "statistics": {"publication_count": 1},
                    "task_state": scholar_core.default_task_state(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class FakePipeline:
            @staticmethod
            def expand_publication_citations(session, limit_per_publication=100, progress_callback=None):
                time.sleep(0.05)
                session["citation_edges"] = [
                    {
                        "source_publication_id": "S001",
                        "citing_title": "Citing Paper",
                        "citing_venue": "ACM MobiCom",
                    }
                ]
                session["deep_analysis_queue"] = [
                    {"citing_title": "Citing Paper", "priority_score": 25, "reasons": ["venue:Top venue seed"]}
                ]
                session["statistics"] = {"publication_count": 1, "citation_edge_count": 1}
                if progress_callback:
                    progress_callback(
                        {
                            "processed_count": 1,
                            "total_count": 1,
                            "citation_edge_count": 1,
                            "error_count": 0,
                        }
                    )
                return session

        with mock.patch.object(scholar_core, "_decorate_publication_venue_tiers"), \
             mock.patch.object(scholar_core, "scholar_pipeline", return_value=FakePipeline()):
            started, state = scholar_core.start_expand_citations_task(TEST_SESSION_ID, limit_per_publication=10)
            self.assertTrue(started)
            self.assertTrue(state["active"])
            self.assertEqual(state["task_type"], "expand_citations")

            started_again, duplicate_state = scholar_core.start_expand_citations_task(TEST_SESSION_ID, limit_per_publication=10)
            self.assertFalse(started_again)
            self.assertTrue(duplicate_state["active"])

            deadline = time.time() + 2
            final_status = None
            while time.time() < deadline:
                final_status = scholar_core.get_scholar_task_status(TEST_SESSION_ID)
                if not final_status["task_state"]["active"]:
                    break
                time.sleep(0.05)

        self.assertIsNotNone(final_status)
        self.assertEqual(final_status["task_state"]["status"], "succeeded")
        self.assertEqual(final_status["citation_edge_count"], 1)
        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)
        self.assertEqual(payload["deep_analysis_queue"][0]["citing_title"], "Citing Paper")

    def test_refresh_scholar_local_pdf_index_rebuilds_session_queue(self):
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
                    "deep_analysis_queue": [{"queue_id": "Q001"}],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class FakeDownloadPdf:
            DEFAULT_LOCAL_PDF_INDEX_PATH = "/tmp/local_pdf_index.json"

            @staticmethod
            def build_local_pdf_index(search_dirs, index_path=""):
                return {
                    "search_dirs": list(search_dirs),
                    "entry_count": 42,
                    "scanned_pdf_count": 42,
                    "build_elapsed_ms": 180,
                    "generated_at": "2026-05-18T11:00:00",
                }

            @staticmethod
            def load_local_pdf_index(index_path=""):
                return {
                    "entry_count": 42,
                    "scanned_pdf_count": 42,
                    "build_elapsed_ms": 180,
                    "generated_at": "2026-05-18T11:00:00",
                    "search_dirs": ["/papers"],
                }

        class FakePipeline:
            RUN_PIPELINE = type("RunPipeline", (), {"DOWNLOAD_PDF": FakeDownloadPdf})()

            @staticmethod
            def configured_local_pdf_library_dirs(download_pdf_module):
                return ["/papers"]

            @staticmethod
            def match_queue_item_local_pdf(
                queue_item,
                download_pdf_module,
                *,
                search_dirs=None,
                index_data=None,
            ):
                if queue_item.get("queue_id") == "Q001":
                    return {
                        "status": "local_library_matched",
                        "local_file_path": "/papers/matched.pdf",
                    }
                return {}

            @staticmethod
            def rebuild_scholar_derived_outputs(session, queue_limit=300):
                raise AssertionError("refresh_local_pdf_index should not rebuild scholar derived outputs")

        with mock.patch.object(
            scholar_core,
            "scholar_pipeline",
            return_value=FakePipeline(),
        ), mock.patch.object(
            scholar_core,
            "_decorate_publication_venue_tiers",
        ):
            result = scholar_core.refresh_scholar_local_pdf_index(TEST_SESSION_ID)

        self.assertEqual(result["entry_count"], 42)
        self.assertEqual(result["scanned_pdf_count"], 42)
        self.assertEqual(result["build_elapsed_ms"], 180)
        self.assertIn("refresh_total_ms", result)
        self.assertIn("queue_rematch_elapsed_ms", result)
        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)
        self.assertEqual(payload["deep_analysis_queue"][0]["queue_id"], "Q001")
        self.assertEqual(
            payload["deep_analysis_queue"][0]["library_pdf"]["status"],
            "local_library_matched",
        )

    def test_expand_scholar_citations_route_redirects(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "start_expand_citations_task", return_value=(True, {})) as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/expand-citations",
                data={"limit_per_publication": "12"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/scholars/{TEST_SESSION_ID}")
        start_task.assert_called_once_with(TEST_SESSION_ID, limit_per_publication=12)

    def test_expand_scholar_citations_route_rejects_invalid_limit(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "start_expand_citations_task") as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/expand-citations",
                data={"limit_per_publication": "1000"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        start_task.assert_not_called()

    def test_rebuild_scholar_derived_outputs_route_redirects(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "rebuild_scholar_derived_outputs",
            return_value={},
        ) as rebuild:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/rebuild-derived",
                data={"queue_limit": "250"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/scholars/{TEST_SESSION_ID}#deep-analysis-queue",
        )
        rebuild.assert_called_once_with(TEST_SESSION_ID, queue_limit=250)

    def test_rebuild_scholar_derived_outputs_route_rejects_invalid_limit(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "rebuild_scholar_derived_outputs",
        ) as rebuild:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/rebuild-derived",
                data={"queue_limit": "5000"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        rebuild.assert_not_called()

    def test_refresh_scholar_local_pdf_index_route_redirects(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "refresh_scholar_local_pdf_index",
            return_value={},
        ) as refresh_index:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/refresh-local-pdf-index",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/scholars/{TEST_SESSION_ID}#scholar-actions",
        )
        refresh_index.assert_called_once_with(TEST_SESSION_ID)

    def test_analyze_scholar_queue_route_redirects(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "start_analyze_queue_task",
            return_value=(True, {}),
        ) as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/analyze-queue",
                data={
                    "queue_ids": ["Q001", "Q002"],
                    "top_k_spans": "8",
                    "analysis_scope": "fulltext_direct",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/scholars/{TEST_SESSION_ID}",
        )
        start_task.assert_called_once_with(
            TEST_SESSION_ID,
            queue_ids=["Q001", "Q002"],
            top_k_spans=8,
            analysis_scope="fulltext_direct",
        )

    def test_analyze_scholar_queue_route_uses_default_span_count_when_hidden(self):
        client = TestClient(app)
        with mock.patch.object(
            scholar_core,
            "start_analyze_queue_task",
            return_value=(True, {}),
        ) as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/analyze-queue",
                data={
                    "queue_ids": ["Q001"],
                    "analysis_scope": "fulltext_direct",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        start_task.assert_called_once_with(
            TEST_SESSION_ID,
            queue_ids=["Q001"],
            top_k_spans=8,
            analysis_scope="fulltext_direct",
        )

    def test_analyze_scholar_queue_route_rejects_empty_selection(self):
        client = TestClient(app)
        with mock.patch.object(scholar_core, "start_analyze_queue_task") as start_task:
            response = client.post(
                f"/scholars/{TEST_SESSION_ID}/analyze-queue",
                data={"top_k_spans": "8"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        start_task.assert_not_called()

    def test_scholar_route_renders_strong_evidence_details(self):
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
                    "deep_analysis_queue": [],
                    "strong_evidence": [
                        {
                            "queue_id": "Q001",
                            "citing_title": "Fellow Citing Paper",
                            "cited_publication_title": "Target Paper",
                            "citing_authors": ["Alice Fellow"],
                            "person_tag_labels": ["ACM Fellow"],
                            "citation_text": "The target method is directly adopted in our system.",
                            "citation_char_count": 53,
                            "aspect": "method",
                            "stance": "positive",
                            "mention_type": "explicit_citation",
                            "page": 4,
                            "span_index": 2,
                            "confidence": 0.92,
                            "function": "引用论文采用目标方法。",
                            "reason": "正文明确说明采用目标论文的方法组件。",
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("命中目标：Target Paper", response.text)
        self.assertIn("页码：4", response.text)
        self.assertIn("段落：2", response.text)
        self.assertIn("态度：positive", response.text)
        self.assertIn("类型：explicit_citation", response.text)
        self.assertIn("置信度：0.92", response.text)
        self.assertIn("正文明确说明采用目标论文的方法组件。", response.text)

    def test_scholar_route_filters_strong_evidence(self):
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
                    "deep_analysis_queue": [],
                    "strong_evidence": [
                        {
                            "citing_title": "Fellow Method Paper",
                            "citation_text": "Long positive method citation. " * 5,
                            "aspect": "method",
                            "stance": "positive",
                            "fellow_strong_citation": True,
                            "positive_evaluation": True,
                            "long_context_100_chars": True,
                        },
                        {
                            "citing_title": "Neutral Baseline Paper",
                            "citation_text": "Used as a baseline.",
                            "aspect": "baseline",
                            "stance": "neutral",
                            "fellow_strong_citation": False,
                        },
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(
            f"/scholars/{TEST_SESSION_ID}",
            params={
                "strong_aspect": "method",
                "strong_flag": "fellow_strong",
                "strong_page_size": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("筛选证据", response.text)
        self.assertIn("当前显示 1 / 2 条强引用证据", response.text)
        self.assertIn("method: 1", response.text)
        self.assertIn("positive: 1", response.text)
        self.assertIn("Fellow 强引用: 1", response.text)
        self.assertIn("Fellow Method Paper", response.text)
        self.assertNotIn("Neutral Baseline Paper</strong>", response.text)
        self.assertIn('name="strong_aspect"', response.text)
        self.assertIn('name="strong_flag"', response.text)

    def test_scholar_route_renders_failed_analysis_retry_form(self):
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
                    "deep_analysis_queue": [],
                    "scholar_fulltext_results": [
                        {
                            "queue_id": "Q003",
                            "cited_publication_title": "Target Paper",
                            "citing_paper": {"title": "Missing PDF Paper"},
                            "status": "context_only",
                            "download": {
                                "source": "manual_required",
                                "error": "未找到合法开源 PDF 链接。",
                            },
                            "status_note": {
                                "message": "未获得全文 PDF，当前结果仅基于 citation contexts。",
                            },
                            "analysis": {
                                "error_type": "download_failed",
                                "error": "未找到合法开源 PDF 链接。",
                            },
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("全文分析状态", response.text)
        self.assertIn("失败/待补全文：1", response.text)
        self.assertIn("Missing PDF Paper", response.text)
        self.assertIn("未找到合法开源 PDF 链接。", response.text)
        self.assertIn('name="queue_ids" value="Q003"', response.text)
        self.assertIn("重试失败项", response.text)
        self.assertIn("建议动作", response.text)
        self.assertIn("上传该引用论文 PDF", response.text)

    def test_build_scholar_demo_guidance_recommends_next_actions(self):
        session = {
            "statistics": {"publication_count": 2, "citation_edge_count": 0},
            "citation_edges": [],
            "deep_analysis_queue": [
                {"queue_id": "Q001", "citing_title": "Missing PDF Paper"},
                {"queue_id": "Q002", "citing_title": "Fresh Paper"},
            ],
            "scholar_fulltext_results": [
                {
                    "queue_id": "Q001",
                    "status": "context_only",
                    "download": {"source": "manual_required"},
                    "analysis": {"ok": False, "error_type": "download_failed"},
                }
            ],
            "strong_evidence": [
                {
                    "citing_title": "Fellow Method Paper",
                    "citation_text": "A strong citation.",
                }
            ],
            "person_candidates": [
                {"candidate_id": "P001", "status": "pending"},
                {"candidate_id": "P002", "status": "pending"},
                {"candidate_id": "P003", "status": "confirmed"},
            ],
        }

        guidance = scholar_core.build_scholar_demo_guidance(session)

        titles = [step["title"] for step in guidance["steps"]]
        self.assertIn("先展开引用网络", titles)
        self.assertIn("审核人物标签候选", titles)
        self.assertIn("分析高价值引用队列", titles)
        self.assertIn("补 PDF 并重试失败项", titles)
        self.assertIn("下载报告并核对强引用证据", titles)
        self.assertEqual(guidance["completeness"]["queue_count"], 2)
        self.assertEqual(guidance["completeness"]["analyzed_queue_count"], 1)
        self.assertEqual(guidance["completeness"]["remaining_queue_count"], 1)
        self.assertEqual(guidance["completeness"]["failure_count"], 1)
        self.assertEqual(guidance["completeness"]["pending_person_count"], 2)

    def test_scholar_route_renders_demo_guidance(self):
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
                    "deep_analysis_queue": [
                        {"queue_id": "Q001", "citing_title": "Missing PDF Paper"},
                        {"queue_id": "Q002", "citing_title": "Fresh Paper"},
                    ],
                    "scholar_fulltext_results": [
                        {
                            "queue_id": "Q001",
                            "status": "context_only",
                            "citing_paper": {"title": "Missing PDF Paper"},
                            "download": {"source": "manual_required"},
                            "analysis": {"ok": False, "error_type": "download_failed"},
                        }
                    ],
                    "strong_evidence": [
                        {
                            "citing_title": "Fellow Method Paper",
                            "citation_text": "A strong citation.",
                        }
                    ],
                    "person_candidates": [
                        {"candidate_id": "P001", "status": "pending"},
                        {"candidate_id": "P002", "status": "pending"},
                    ],
                    "statistics": {
                        "publication_count": 2,
                        "citation_edge_count": 0,
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
        self.assertIn("下一步操作建议", response.text)
        self.assertIn("高价值队列：已分析 1/2", response.text)
        self.assertIn("待分析：1", response.text)
        self.assertIn("待补全文/失败项：1", response.text)
        self.assertIn("人物待确认：2", response.text)
        self.assertIn("补 PDF 并重试失败项", response.text)

    def test_scholar_route_renders_target_impact_summary(self):
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
                    "deep_analysis_queue": [],
                    "strong_evidence": [
                        {
                            "source_publication_id": "S001",
                            "citing_title": "Fellow Citing Paper",
                            "cited_publication_title": "Target Paper",
                            "citation_text": "A long positive citation. " * 6,
                            "citation_char_count": 150,
                            "aspect": "method",
                            "stance": "positive",
                            "positive_evaluation": True,
                            "fellow_strong_citation": True,
                            "long_context_100_chars": True,
                        },
                        {
                            "source_publication_id": "S001",
                            "citing_title": "Venue Citing Paper",
                            "cited_publication_title": "Target Paper",
                            "citation_text": "Used as a baseline.",
                            "citation_char_count": 19,
                            "aspect": "baseline",
                            "stance": "neutral",
                        },
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("目标论文影响力摘要", response.text)
        self.assertIn("Target Paper", response.text)
        self.assertIn("强引用：2", response.text)
        self.assertIn("引用论文：2", response.text)
        self.assertIn("Fellow 强引用：1", response.text)
        self.assertIn("method / baseline", response.text)

    def test_scholar_route_renders_impact_overview(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [{"id": "S001", "title": "Target Paper", "unique_ids": {}}],
                    "citation_edges": [],
                    "deep_analysis_queue": [
                        {"queue_id": "Q001", "citing_title": "Queued Citing Paper"}
                    ],
                    "scholar_fulltext_results": [
                        {
                            "queue_id": "Q001",
                            "status": "fulltext_analyzed",
                            "cited_publication_title": "Target Paper",
                            "citing_paper": {"title": "Fellow Citing Paper"},
                            "analysis": {"ok": True},
                        },
                        {
                            "queue_id": "Q002",
                            "status": "context_only",
                            "cited_publication_title": "Other Target",
                            "citing_paper": {"title": "Missing PDF Paper"},
                            "download": {"error": "未找到合法开源 PDF 链接。"},
                            "analysis": {"ok": False},
                        },
                    ],
                    "strong_evidence": [
                        {
                            "source_publication_id": "S001",
                            "citing_title": "Fellow Citing Paper",
                            "cited_publication_title": "Target Paper",
                            "citation_text": "A long positive citation. " * 6,
                            "citation_char_count": 150,
                            "aspect": "method",
                            "stance": "positive",
                            "positive_evaluation": True,
                            "fellow_strong_citation": True,
                            "long_context_100_chars": True,
                        }
                    ],
                    "statistics": {"publication_count": 1},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("学者影响力速览", response.text)
        self.assertIn("有强证据论文", response.text)
        self.assertIn("<strong>1</strong>", response.text)
        self.assertIn("Fellow 强引用", response.text)
        self.assertIn("待补全文", response.text)
        self.assertIn("当前最强目标论文：Target Paper", response.text)
        self.assertIn("建议先重试失败项或补充 PDF。", response.text)

    def test_scholar_route_renders_person_candidate_details(self):
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
                    "deep_analysis_queue": [],
                    "person_candidates": [
                        {
                            "candidate_id": "acm_fellow::alice-fellow",
                            "name": "Alice Fellow",
                            "tag_type": "acm_fellow",
                            "tag_label": "ACM Fellow",
                            "status": "pending",
                            "matched_paper_ids": ["C001"],
                            "matched_paper_titles": ["Fellow Citing Paper"],
                            "source_links": ["https://example.test/alice"],
                            "matched_affiliations": ["Example University"],
                            "note": "ACM Fellow registry seed",
                            "evidence": [
                                {
                                    "paper_id": "C001",
                                    "matched_author": "Alice Fellow",
                                    "paper_title": "Fellow Citing Paper",
                                    "match_type": "exact_name",
                                }
                            ],
                        }
                    ],
                    "statistics": {
                        "publication_count": 0,
                        "person_tag_statistics": [
                            {
                                "tag_type": "acm_fellow",
                                "tag_label": "ACM Fellow",
                                "count": 1,
                                "confirmed_count": 0,
                                "pending_count": 1,
                                "rejected_count": 0,
                                "source_complete_count": 1,
                                "matched_paper_count": 1,
                            }
                        ],
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
        self.assertIn("人物标签候选区", response.text)
        self.assertIn("待处理：1", response.text)
        self.assertIn("Alice Fellow", response.text)
        self.assertIn("ACM Fellow · pending", response.text)
        self.assertIn("Example University", response.text)
        self.assertIn("https://example.test/alice", response.text)
        self.assertIn("C001 · Alice Fellow · Fellow Citing Paper", response.text)
        self.assertIn('action="/scholars/test_scholar_session/candidates/review"', response.text)

    def test_scholar_route_filters_person_candidates(self):
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
                    "deep_analysis_queue": [],
                    "person_candidates": [
                        {
                            "candidate_id": "acm_fellow::alice",
                            "name": "Alice Fellow",
                            "tag_type": "acm_fellow",
                            "tag_label": "ACM Fellow",
                            "status": "pending",
                        },
                        {
                            "candidate_id": "ieee_fellow::bob",
                            "name": "Bob Fellow",
                            "tag_type": "ieee_fellow",
                            "tag_label": "IEEE Fellow",
                            "status": "confirmed",
                            "evidence": [
                                {
                                    "paper_id": "C002",
                                    "matched_author": "Bob Fellow",
                                    "paper_title": "Confirmed Citation",
                                    "match_type": "registry_exact",
                                }
                            ],
                        },
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(
            f"/scholars/{TEST_SESSION_ID}",
            params={
                "person_status": "confirmed",
                "person_tag_type": "ieee_fellow",
                "person_page_size": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("当前显示 1 / 2 位人物候选", response.text)
        self.assertIn("Bob Fellow", response.text)
        self.assertIn("registry_exact", response.text)
        self.assertNotIn("Alice Fellow</strong>", response.text)

    def test_scholar_candidate_review_route_updates_status(self):
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
                    "deep_analysis_queue": [],
                    "person_candidates": [
                        {
                            "candidate_id": "acm_fellow::alice-fellow",
                            "name": "Alice Fellow",
                            "tag_type": "acm_fellow",
                            "tag_label": "ACM Fellow",
                            "status": "pending",
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.post(
            f"/scholars/{TEST_SESSION_ID}/candidates/review",
            data={
                "candidate_id": "acm_fellow::alice-fellow",
                "action": "confirm",
                "note": "verified",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/scholars/{TEST_SESSION_ID}#person-candidates")
        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)
        candidate = payload["person_candidates"][0]
        self.assertEqual(candidate["status"], "confirmed")
        self.assertEqual(candidate["review_note"], "verified")
        self.assertTrue(candidate.get("reviewed_at"))
        self.assertEqual(payload["statistics"]["person_tag_statistics"][0]["confirmed_count"], 1)

    def test_scholar_task_status_route_returns_counts(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [{"id": "S001", "title": "Paper One"}],
                    "citation_edges": [{"citing_title": "Citing Paper"}],
                    "deep_analysis_queue": [{"citing_title": "Citing Paper"}],
                    "statistics": {"publication_count": 1, "citation_edge_count": 1},
                    "task_state": scholar_core.default_task_state(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}/task-status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["publication_count"], 1)
        self.assertEqual(payload["citation_edge_count"], 1)
        self.assertEqual(payload["deep_analysis_queue_count"], 1)

    def test_analyze_scholar_queue_progress_records_stage_details(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [{"id": "S001", "title": "Target Paper"}],
                    "citation_edges": [],
                    "deep_analysis_queue": [
                        {
                            "queue_id": "Q001",
                            "source_publication_ids": ["S001"],
                            "citing_title": "Citing Paper",
                        }
                    ],
                    "statistics": {"publication_count": 1},
                    "task_state": scholar_core.default_task_state(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        real_scholar_stats = scholar_core.scholar_pipeline().SCHOLAR_STATS

        class FakePipeline:
            SCHOLAR_STATS = real_scholar_stats

            @staticmethod
            def analyze_scholar_queue(
                session,
                session_dir,
                queue_ids,
                top_k_spans=8,
                analysis_scope="fulltext_direct",
                progress_callback=None,
            ):
                if progress_callback:
                    progress_callback(
                        {
                            "processed_count": 0,
                            "total_count": 1,
                            "queue_id": "Q001",
                            "current_title": "Citing Paper",
                            "current_index": 1,
                            "stage": "downloading_pdf",
                            "stage_message": "正在下载 PDF",
                        }
                    )
                session["scholar_fulltext_results"] = []
                session["strong_evidence"] = []
                return session

        with mock.patch.object(scholar_core, "scholar_pipeline", return_value=FakePipeline()):
            scholar_core.analyze_scholar_queue(
                TEST_SESSION_ID,
                queue_ids=["Q001"],
                top_k_spans=8,
                analysis_scope="fulltext_direct",
            )

        task_state = scholar_core.load_scholar_status(TEST_SESSION_ID)["task_state"]
        self.assertEqual(task_state["stage"], "downloading_pdf")
        self.assertEqual(task_state["stage_message"], "正在下载 PDF")
        self.assertEqual(task_state["current_queue_id"], "Q001")
        self.assertEqual(task_state["current_title"], "Citing Paper")
        self.assertEqual(task_state["current_index"], 1)

    def test_build_scholar_report_payload_summarizes_session(self):
        session = {
            "selected_author": {"display_name": "Chen Tian"},
            "statistics": {
                "publication_count": 189,
                "citation_edge_count": 3450,
                "first_author_publication_count": 18,
            },
            "deep_analysis_queue": [{"queue_id": "Q001"}, {"queue_id": "Q002"}, {"queue_id": "Q003"}],
            "person_candidates": [
                {"name": "Alice Fellow", "status": "pending"},
                {"name": "Bob Fellow", "status": "pending"},
            ],
            "scholar_fulltext_results": [
                {"queue_id": "Q001", "status": "fulltext_analyzed", "analysis": {"ok": True}},
                {"queue_id": "Q002", "status": "context_only", "analysis": {"ok": False}},
            ],
            "strong_evidence": [
                {
                    "citing_title": "Fellow Method Paper",
                    "cited_publication_title": "Target Paper",
                    "citation_text": "Long positive method citation. " * 5,
                    "aspect": "method",
                    "stance": "positive",
                    "fellow_strong_citation": True,
                    "positive_evaluation": True,
                    "long_context_100_chars": True,
                    "citation_char_count": 150,
                },
                {
                    "citing_title": "Baseline Paper",
                    "cited_publication_title": "Target Paper",
                    "citation_text": "Used as a baseline.",
                    "aspect": "baseline",
                    "stance": "neutral",
                },
                {
                    "citing_title": "Application Paper",
                    "cited_publication_title": "Applied Target",
                    "citation_text": "Applied to a new scenario.",
                    "aspect": "application",
                    "stance": "positive",
                    "positive_evaluation": True,
                }
            ],
        }

        payload = scholar_core.build_scholar_report_payload(session)

        self.assertIn("Chen Tian", payload["summary_text"])
        self.assertIn("189 篇论文", payload["summary_text"])
        self.assertIn("3450 条引用边", payload["summary_text"])
        self.assertIn("强引用证据 3 条", payload["summary_text"])
        self.assertIn("Fellow 强引用 1 条", payload["summary_text"])
        self.assertIn("当前最强目标论文：Target Paper", payload["bullets"])
        self.assertTrue(
            any("方法采用类证据 1 条" in item for item in payload["narrative_bullets"])
        )
        self.assertTrue(
            any("应用拓展类证据 1 条" in item for item in payload["narrative_bullets"])
        )
        self.assertEqual(payload["top_evidence"][0]["citing_title"], "Fellow Method Paper")
        self.assertIn("待分析高价值引用 1 篇", payload["limitations"])
        self.assertIn("待补全文/失败项 1 条", payload["limitations"])
        self.assertIn("人物标签待确认 2 人", payload["limitations"])
        self.assertIn("# Chen Tian 学者影响力报告", payload["markdown"])
        self.assertIn("## 证据解读", payload["markdown"])
        self.assertIn("## Top 强引用证据", payload["markdown"])
        self.assertIn("## 当前不足", payload["markdown"])

    def test_scholar_route_renders_report_summary_and_export_link(self):
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
                    "deep_analysis_queue": [{"queue_id": "Q001"}],
                    "strong_evidence": [
                        {
                            "citing_title": "Fellow Method Paper",
                            "cited_publication_title": "Target Paper",
                            "citation_text": "Long positive method citation. " * 5,
                            "aspect": "method",
                            "stance": "positive",
                            "fellow_strong_citation": True,
                            "positive_evaluation": True,
                            "long_context_100_chars": True,
                        }
                    ],
                    "statistics": {"publication_count": 1, "citation_edge_count": 2},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("报告摘要", response.text)
        self.assertIn("可复制结论", response.text)
        self.assertIn("Chen Tian", response.text)
        self.assertIn("强引用证据 1 条", response.text)
        self.assertIn(f"/scholars/{TEST_SESSION_ID}/exports/report.md", response.text)
        self.assertIn(
            f"/scholars/{TEST_SESSION_ID}/exports/citation_statistics.csv",
            response.text,
        )
        self.assertIn(
            f"/scholars/{TEST_SESSION_ID}/exports/raw_citing_authors.csv",
            response.text,
        )

    def test_scholar_route_hides_candidate_span_control_for_fulltext_analysis(self):
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
                    "deep_analysis_queue": [
                        {
                            "queue_id": "Q001",
                            "citing_title": "Citing Paper",
                            "citing_doi": "10.1000/citing",
                        }
                    ],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("候选段落数", response.text)
        self.assertIn('type="hidden" name="top_k_spans" value="8"', response.text)

    def test_scholar_report_markdown_export_route(self):
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
                    "deep_analysis_queue": [],
                    "strong_evidence": [],
                    "statistics": {"publication_count": 1, "citation_edge_count": 2},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}/exports/report.md")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers["content-type"])
        self.assertIn("# Chen Tian 学者影响力报告", response.text)
        self.assertIn("## 可复制结论", response.text)

    def test_scholar_citation_statistics_csv_export_route(self):
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
                    "deep_analysis_queue": [],
                    "person_candidates": [
                        {
                            "candidate_id": "acm_fellow::alice-fellow",
                            "name": "Alice Fellow",
                            "tag_type": "acm_fellow",
                            "tag_label": "ACM Fellow",
                            "status": "pending",
                            "matched_paper_ids": ["C001", "C002"],
                            "matched_paper_titles": ["Paper One", "Paper Two"],
                            "matched_affiliations": ["Example University"],
                            "source_links": ["https://example.test/alice"],
                            "homonym_risk": True,
                            "risk_flags": ["name_only_match"],
                            "resolved_matched_authors": [],
                            "auto_match_status": "not_matched",
                            "auto_match_score": 1,
                            "auto_match_confidence": "low",
                            "auto_match_reasons": ["ambiguous_name_collision"],
                            "note": "registry seed",
                            "evidence": [
                                {
                                    "paper_id": "C001",
                                    "paper_title": "Paper One",
                                    "matched_author": "Shared Author",
                                    "match_type": "alias",
                                }
                            ],
                        },
                        {
                            "candidate_id": "acm_fellow::bob-fellow",
                            "name": "Bob Fellow",
                            "tag_type": "acm_fellow",
                            "tag_label": "ACM Fellow",
                            "status": "confirmed",
                            "matched_paper_ids": ["C002"],
                            "matched_paper_titles": ["Paper Two"],
                            "matched_affiliations": [],
                            "source_links": [],
                            "resolved_matched_authors": ["Shared Author"],
                            "auto_match_status": "matched",
                            "auto_match_score": 9,
                            "auto_match_confidence": "medium",
                            "auto_match_reasons": ["unique_exact_name"],
                            "evidence": [
                                {
                                    "paper_id": "C002",
                                    "paper_title": "Paper Two",
                                    "matched_author": "Shared Author",
                                    "match_type": "exact_name",
                                }
                            ],
                        },
                    ],
                    "statistics": {
                        "publication_count": 1,
                        "citation_edge_count": 2,
                        "person_tag_statistics": [
                            {
                                "tag_type": "acm_fellow",
                                "tag_label": "ACM Fellow",
                                "count": 1,
                                "matched_author_count": 1,
                                "candidate_count": 2,
                                "ambiguous_author_count": 1,
                                "high_risk_author_count": 1,
                                "confirmed_count": 1,
                                "pending_count": 1,
                                "rejected_count": 0,
                                "source_complete_count": 1,
                                "matched_paper_count": 2,
                            }
                        ],
                    },
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(
            f"/scholars/{TEST_SESSION_ID}/exports/citation_statistics.csv"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("candidate_id,tag_type,tag_label", response.text)
        self.assertIn("Alice Fellow", response.text)
        self.assertIn("Bob Fellow", response.text)
        self.assertIn("Shared Author", response.text)
        self.assertIn("ambiguous_author_count", response.text)
        self.assertIn("auto_match_status", response.text)
        self.assertIn("resolved_matched_authors", response.text)
        self.assertIn("not_matched", response.text)
        self.assertIn("matched", response.text)

    def test_scholar_raw_citing_authors_csv_export_route(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [],
                    "citation_edges": [
                        {
                            "source_publication_id": "S001",
                            "citing_paper_id": "C001",
                            "citing_title": "Paper One",
                            "citing_year": 2025,
                            "citing_venue": "SIGCOMM",
                            "citing_doi": "10.1000/paper1",
                            "provider": "openalex",
                            "citing_authors": ["A. One", "B. Two"],
                            "citing_author_details": [
                                {
                                    "name": "Alice One",
                                    "institutions": ["Example U"],
                                    "source_url": "https://example.test/alice",
                                },
                                {
                                    "name": "Bob Two",
                                    "institutions": ["Second U"],
                                    "source_url": "https://example.test/bob",
                                },
                            ],
                            "cited_publication_title": "Target Paper",
                        },
                        {
                            "source_publication_id": "S002",
                            "citing_paper_id": "C002",
                            "citing_title": "Paper Two",
                            "citing_year": 2024,
                            "citing_venue": "NSDI",
                            "citing_doi": "10.1000/paper2",
                            "provider": "semanticscholar",
                            "citing_authors": ["Carol Three"],
                            "cited_publication_title": "Target Paper Two",
                        },
                    ],
                    "statistics": {"publication_count": 1, "citation_edge_count": 2},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(
            f"/scholars/{TEST_SESSION_ID}/exports/raw_citing_authors.csv"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn(
            "source_publication_id,citing_paper_id,citing_title,citing_year,citing_venue,citing_doi,provider,cited_publication_title,author_position,author_name,raw_author_name,author_institutions,author_source_url",
            response.text,
        )
        self.assertIn("Alice One", response.text)
        self.assertIn("Bob Two", response.text)
        self.assertIn("Carol Three", response.text)
        self.assertIn("A. One", response.text)
        self.assertIn("Example U", response.text)


if __name__ == "__main__":
    unittest.main()
