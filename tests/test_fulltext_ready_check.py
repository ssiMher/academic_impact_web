from __future__ import annotations

import os
import unittest

from scripts.fulltext_ready_check import candidate_probe_urls, overall_summary, service_status


class FulltextReadyCheckTestCase(unittest.TestCase):
    def test_candidate_probe_urls_prefers_models_endpoint(self):
        urls = candidate_probe_urls('http://127.0.0.1:8002/v1/chat/completions')
        self.assertEqual(urls[0], 'http://127.0.0.1:8002/v1/models')
        self.assertIn('http://127.0.0.1:8002', urls)

    def test_service_status_reports_missing_config(self):
        status = service_status('')
        self.assertEqual(status['status'], 'config_missing')
        self.assertFalse(status['reachable'])

    def test_overall_summary_collects_blockers(self):
        summary = overall_summary(
            {'missing_keys': ['DEEPSEEK_API_KEY']},
            {'status': 'service_unreachable'},
            {'blockers': ['pdf_missing', 'context_only']},
        )
        self.assertEqual(summary['blockers'], ['配置缺失', '服务不可达', 'PDF 缺失', '只能 context_only'])
        self.assertFalse(summary['ok'])


if __name__ == '__main__':
    unittest.main()
