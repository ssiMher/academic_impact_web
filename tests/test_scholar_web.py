from __future__ import annotations

import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertIn("未找到合法开源 PDF 链接。", response.text)
        self.assertIn("分析会先尝试自动下载 PDF", response.text)
        self.assertIn(
            f'action="/scholars/{TEST_SESSION_ID}/attach-queue-pdf"',
            response.text,
        )
        self.assertIn('name="pdf_file"', response.text)

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
        self.assertEqual(failed["analysis_status"], "context_only")
        self.assertEqual(failed["analysis_failure_message"], "未找到合法开源 PDF 链接。")
        self.assertEqual(failed["download_source"], "manual_pdf_attached")
        self.assertEqual(failed["manual_pdf_path"], "/tmp/manual.pdf")
        self.assertEqual(failed["citing_identifier"], "DOI: 10.1000/failed")
        self.assertEqual(fresh["analysis_status"], "not_analyzed")
        self.assertEqual(fresh["download_source"], "点击分析时自动尝试下载 PDF")
        self.assertEqual(fresh["citing_identifier"], "OpenAlex: W123")

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


if __name__ == "__main__":
    unittest.main()
