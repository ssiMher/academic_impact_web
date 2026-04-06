from __future__ import annotations

import json
import shutil
import unittest
import asyncio
from pathlib import Path

from starlette.requests import Request

from app.main import session_detail
from app.services import impact_core


ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = ROOT / 'data' / 'sessions'
REFERENCE_ROOT = ROOT / 'data' / 'reference'
REGISTRY_PATH = REFERENCE_ROOT / 'person_tag_registry.json'
TEST_SESSION_ID = '20990101_000000_test_phase1_detail'
TEST_SESSION_DIR = SESSIONS_ROOT / TEST_SESSION_ID


class Phase1DetailTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._registry_backup = REGISTRY_PATH.read_text(encoding='utf-8') if REGISTRY_PATH.exists() else None
        REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
        REGISTRY_PATH.write_text(
            json.dumps(
                [
                    {
                        'name': 'Grace Hopper',
                        'tag_type': 'ieee_fellow',
                        'source_links': ['https://example.com/grace-hopper'],
                        'note': 'fixture candidate',
                    }
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )

    @classmethod
    def tearDownClass(cls):
        if cls._registry_backup is None:
            if REGISTRY_PATH.exists():
                REGISTRY_PATH.unlink()
        else:
            REGISTRY_PATH.write_text(cls._registry_backup, encoding='utf-8')

    def setUp(self):
        if TEST_SESSION_DIR.exists():
            shutil.rmtree(TEST_SESSION_DIR)
        (TEST_SESSION_DIR / 'analysis' / 'P001_test').mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / 'analysis').mkdir(parents=True, exist_ok=True)

        candidate_path = TEST_SESSION_DIR / 'analysis' / 'P001_test' / 'candidate_spans.json'
        analysis_path = TEST_SESSION_DIR / 'analysis' / 'P001_test' / 'fulltext_analysis.json'
        fallback_path = TEST_SESSION_DIR / 'analysis' / 'P002_test' / 'context_fallback.json'
        fallback_path.parent.mkdir(parents=True, exist_ok=True)

        candidate_path.write_text(
            json.dumps(
                {
                    'ok': True,
                    'count': 1,
                    'spans': [
                        {
                            'page': 4,
                            'span_index': 2,
                            'text': 'For the first time we extend Attention is All You Need to robotics.',
                            'match_type': 'citation_index_exact',
                            'score': 8,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )
        analysis_path.write_text(
            json.dumps(
                {
                    'ok': True,
                    'findings': [
                        {
                            'page': 4,
                            'span_index': 2,
                            'citation_text': 'For the first time we extend Attention is All You Need to robotics.',
                            'aspect': 'extension',
                            'stance': 'positive',
                            'function': '将目标论文扩展到机器人控制任务。',
                            'reason': '明确说明是在原方法基础上扩展。',
                            'confidence': 0.91,
                            'mention_type': 'explicit_citation',
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )
        fallback_path.write_text(
            json.dumps(
                {
                    'ok': True,
                    'fallback_contexts': [
                        {'text': 'This study cites the target work as background.'}
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )

        session_payload = {
            'ok': True,
            'query': 'Attention Is All You Need',
            'created_at': '2099-01-01T00:00:00',
            'target': {
                'title': 'Attention Is All You Need',
                'year': 2017,
                'venue': 'NeurIPS',
                'citationCount': 12345,
                'externalIds': {'DOI': '10.1234/attention'},
            },
            'paths': {
                'list_papers': str(TEST_SESSION_DIR / 'list_papers.json'),
                'contexts': str(TEST_SESSION_DIR / 'contexts.json'),
            },
            'papers': [
                {
                    'id': 'P001',
                    'title': 'Robotics Transformer Extensions',
                    'year': 2025,
                    'venue': 'ICRA',
                    'authors': ['Grace Hopper', 'Alan Turing'],
                    'externalIds': {'DOI': '10.1234/robotics'},
                    'download_queries': ['10.1234/robotics'],
                    'download_probe': {
                        'ok': True,
                        'status': 'local_available',
                        'local_file_path': '/tmp/fake.pdf',
                        'candidate_count': 1,
                        'pdf_candidates': ['/tmp/fake.pdf'],
                    },
                    'analysis_result': {
                        'status': 'fulltext_analyzed',
                        'paths': {
                            'candidate_spans': str(candidate_path),
                            'analysis': str(analysis_path),
                        },
                    },
                    'context_confidence': 'high',
                    'paper': {
                        'title': 'Robotics Transformer Extensions',
                        'year': 2025,
                        'venue': 'ICRA',
                        'authors': ['Grace Hopper', 'Alan Turing'],
                        'externalIds': {'DOI': '10.1234/robotics'},
                    },
                },
                {
                    'id': 'P002',
                    'title': 'Survey of Transformers',
                    'year': 2024,
                    'venue': 'AI Survey',
                    'authors': ['Ada Lovelace'],
                    'externalIds': {'DOI': '10.1234/survey'},
                    'download_queries': ['10.1234/survey'],
                    'download_probe': {
                        'ok': True,
                        'status': 'manual_required',
                        'local_file_path': None,
                        'candidate_count': 0,
                        'pdf_candidates': [],
                        'attempts': [
                            {
                                'ok': True,
                                'status': 'manual_required',
                                'requested_via': '10.1234/survey',
                                'candidate_count': 0,
                            },
                            {
                                'ok': False,
                                'requested_via': 'Survey of Transformers',
                                'error': '搜索失败，状态码: 429',
                            },
                        ],
                    },
                    'download_result': {
                        'ok': False,
                        'query': 'Survey of Transformers',
                        'requested_via': 'Survey of Transformers',
                        'error': '搜索失败，状态码: 429',
                        'attempts': [
                            {
                                'ok': False,
                                'query': '10.1234/survey',
                                'requested_via': '10.1234/survey',
                                'error': '未找到合法开源 PDF 链接。',
                            },
                            {
                                'ok': False,
                                'query': 'Survey of Transformers',
                                'requested_via': 'Survey of Transformers',
                                'error': '搜索失败，状态码: 429',
                            },
                        ],
                    },
                    'analysis_result': {
                        'status': 'context_only',
                        'paths': {
                            'fallback_analysis': str(fallback_path),
                        },
                    },
                    'context_confidence': 'medium',
                    'paper': {
                        'title': 'Survey of Transformers',
                        'year': 2024,
                        'venue': 'AI Survey',
                        'authors': ['Ada Lovelace'],
                        'externalIds': {'DOI': '10.1234/survey'},
                    },
                },
            ],
            'analysis': {
                'processed_papers': 1,
            },
        }
        (TEST_SESSION_DIR / 'session.json').write_text(
            json.dumps(session_payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        (TEST_SESSION_DIR / 'list_papers.json').write_text('{}', encoding='utf-8')
        (TEST_SESSION_DIR / 'contexts.json').write_text('{}', encoding='utf-8')

    def tearDown(self):
        if TEST_SESSION_DIR.exists():
            shutil.rmtree(TEST_SESSION_DIR)

    def test_load_status_builds_detail_payload_and_exports(self):
        session, status_payload, detail_payload, report_md = impact_core.load_status(TEST_SESSION_ID)

        self.assertEqual(status_payload['overview_stats']['candidate_people_count'], 1)
        self.assertEqual(detail_payload['person_summary']['pending_count'], 1)
        self.assertEqual(len(detail_payload['papers']), 2)
        first_paper = detail_payload['papers'][0]
        self.assertIn('extension', first_paper['citation_method_summary']['labels'])
        self.assertTrue(first_paper['citation_method_summary']['first_claim_hit'])
        self.assertTrue(detail_payload['exports']['report_md_path'])
        self.assertTrue(detail_payload['exports']['structured_json_path'])
        self.assertIn('单篇论文引用分析报告', report_md)

    def test_review_candidate_changes_summary_counts(self):
        _, _, detail_payload, _ = impact_core.load_status(TEST_SESSION_ID)
        candidate_id = detail_payload['person_candidates'][0]['candidate_id']

        impact_core.review_person_candidate(TEST_SESSION_ID, candidate_id, action='confirm', note='verified')
        _, _, after_confirm, _ = impact_core.load_status(TEST_SESSION_ID)
        self.assertEqual(after_confirm['person_summary']['confirmed_count'], 1)
        self.assertEqual(after_confirm['person_summary']['pending_count'], 0)

        impact_core.review_person_candidate(TEST_SESSION_ID, candidate_id, action='reset', note='re-opened')
        _, _, after_reset, _ = impact_core.load_status(TEST_SESSION_ID)
        self.assertEqual(after_reset['person_summary']['pending_count'], 1)
        self.assertEqual(after_reset['person_summary']['confirmed_count'], 0)

    def test_reject_candidate_changes_summary_counts(self):
        _, _, detail_payload, _ = impact_core.load_status(TEST_SESSION_ID)
        candidate_id = detail_payload['person_candidates'][0]['candidate_id']

        impact_core.review_person_candidate(TEST_SESSION_ID, candidate_id, action='reject', note='not a match')
        _, _, after_reject, _ = impact_core.load_status(TEST_SESSION_ID)
        self.assertEqual(after_reject['person_summary']['pending_count'], 0)
        self.assertEqual(after_reject['person_summary']['confirmed_count'], 0)
        self.assertEqual(after_reject['person_summary']['rejected_count'], 1)

    def test_export_file_includes_export_paths_on_first_generation(self):
        _, _, detail_payload, _ = impact_core.load_status(TEST_SESSION_ID)
        structured_path = Path(detail_payload['exports']['structured_json_path'])
        exported_payload = json.loads(structured_path.read_text(encoding='utf-8'))

        self.assertEqual(exported_payload['exports']['report_md_path'], detail_payload['exports']['report_md_path'])
        self.assertEqual(exported_payload['exports']['structured_json_path'], detail_payload['exports']['structured_json_path'])
        context_only_item = next(item for item in exported_payload['papers'] if item['id'] == 'P002')
        self.assertIn('未获得 PDF', context_only_item['analysis_reason']['tags'])
        self.assertIn('外部源限流', context_only_item['analysis_reason']['tags'])
        self.assertIn('未经全文验证', context_only_item['analysis_reason']['tags'])
        self.assertIn('citation contexts', context_only_item['analysis_reason']['message'])

    def test_review_candidate_refreshes_export_payload(self):
        _, _, detail_payload, _ = impact_core.load_status(TEST_SESSION_ID)
        candidate_id = detail_payload['person_candidates'][0]['candidate_id']

        impact_core.review_person_candidate(TEST_SESSION_ID, candidate_id, action='confirm', note='verified')
        exported_payload = json.loads(
            impact_core.resolve_export_path(TEST_SESSION_ID, 'structured.json').read_text(encoding='utf-8')
        )

        self.assertEqual(exported_payload['person_summary']['confirmed_count'], 1)
        self.assertEqual(exported_payload['person_summary']['pending_count'], 0)
        self.assertEqual(exported_payload['person_candidates'][0]['status'], 'confirmed')
        self.assertEqual(exported_payload['person_candidates'][0]['review_note'], 'verified')

    def test_context_only_reason_renders_in_page_and_report(self):
        _, _, detail_payload, report_md = impact_core.load_status(TEST_SESSION_ID)
        context_only_item = next(item for item in detail_payload['papers'] if item['id'] == 'P002')

        self.assertIn('未获得 PDF', context_only_item['analysis_reason']['tags'])
        self.assertIn('外部源限流', context_only_item['analysis_reason']['tags'])
        self.assertIn('仅 citation context', context_only_item['analysis_reason']['tags'])
        self.assertIn('未经全文验证', context_only_item['analysis_reason']['tags'])
        self.assertIn('HTTP 429', context_only_item['analysis_reason']['message'])
        self.assertIn('当前限制说明', report_md)
        self.assertIn('外部源限流', report_md)

    def test_session_detail_page_renders_phase1_sections(self):
        request = Request({'type': 'http', 'method': 'GET', 'path': f'/sessions/{TEST_SESSION_ID}', 'headers': []})
        response = asyncio.run(session_detail(request, TEST_SESSION_ID))
        body = response.body.decode('utf-8')
        self.assertIn('目标论文基本信息与总览统计', body)
        self.assertIn('引用论文列表与状态', body)
        self.assertIn('单篇引用方式分析结果', body)
        self.assertIn('人物标签候选区', body)
        self.assertIn('导出与汇总', body)
        self.assertIn('/exports/report.md', body)
        self.assertIn('Grace Hopper', body)
        self.assertIn('当前限制', body)
        self.assertIn('外部源限流', body)


if __name__ == '__main__':
    unittest.main()
