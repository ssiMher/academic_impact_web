from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts.fulltext_ready_check import candidate_probe_urls, env_status, overall_summary, service_status


class FulltextReadyCheckTestCase(unittest.TestCase):
    ENV_KEYS = [
        'ACADEMIC_IMPACT_ANALYSIS_MODE',
        'ACADEMIC_IMPACT_LLM_URL',
        'ACADEMIC_IMPACT_LLM_MODEL',
        'ACADEMIC_IMPACT_LLM_API_KEY',
        'ACADEMIC_IMPACT_LOCAL_LLM_URL',
        'ACADEMIC_IMPACT_LOCAL_MODEL',
        'DEEPSEEK_API_KEY',
    ]

    def setUp(self):
        self._env_backup = {key: os.environ.get(key) for key in self.ENV_KEYS}
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in self._env_backup.items():
            if value is not None:
                os.environ[key] = value

    def checked_env_status(self, values):
        os.environ.update(values)
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}):
            return env_status()

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

    def test_env_status_accepts_single_model_local_without_api_key(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'single_model',
            'ACADEMIC_IMPACT_LLM_URL': 'http://127.0.0.1:18002/v1/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        })

        self.assertEqual(status['missing_keys'], [])
        self.assertEqual(status['effective']['analysis_mode'], 'single_model')
        self.assertFalse(status['effective']['api_key_required'])

    def test_env_status_accepts_single_model_legacy_local_fallback(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_LOCAL_LLM_URL': 'http://127.0.0.1:18002/v1/chat/completions',
            'ACADEMIC_IMPACT_LOCAL_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        })

        self.assertEqual(status['missing_keys'], [])
        self.assertEqual(status['effective']['url_source'], 'ACADEMIC_IMPACT_LOCAL_LLM_URL')
        self.assertEqual(status['effective']['model_source'], 'ACADEMIC_IMPACT_LOCAL_MODEL')

    def test_env_status_accepts_deepseek_key_fallback_for_single_model(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'single_model',
            'ACADEMIC_IMPACT_LLM_URL': 'https://api.deepseek.com/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'deepseek-chat',
            'DEEPSEEK_API_KEY': 'legacy-key',
        })

        self.assertEqual(status['missing_keys'], [])
        self.assertTrue(status['effective']['api_key_required'])
        self.assertEqual(status['effective']['api_key_source'], 'DEEPSEEK_API_KEY')

    def test_env_status_requires_deepseek_key_for_single_model(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'single_model',
            'ACADEMIC_IMPACT_LLM_URL': 'https://api.deepseek.com/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'deepseek-chat',
        })

        self.assertEqual(status['missing_keys'], ['ACADEMIC_IMPACT_LLM_API_KEY'])

    def test_env_status_legacy_two_stage_requires_deepseek(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'legacy_two_stage',
            'ACADEMIC_IMPACT_LOCAL_LLM_URL': 'http://127.0.0.1:18002/v1/chat/completions',
            'ACADEMIC_IMPACT_LOCAL_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        })

        self.assertEqual(status['missing_keys'], ['DEEPSEEK_API_KEY'])

    def test_env_status_accepts_legacy_two_stage_config(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'legacy_two_stage',
            'ACADEMIC_IMPACT_LOCAL_LLM_URL': 'http://127.0.0.1:18002/v1/chat/completions',
            'ACADEMIC_IMPACT_LOCAL_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
            'DEEPSEEK_API_KEY': 'legacy-key',
        })

        self.assertEqual(status['missing_keys'], [])
        self.assertEqual(status['effective']['analysis_mode'], 'legacy_two_stage')

    def test_env_status_rejects_invalid_mode(self):
        status = self.checked_env_status({
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'two_models_forever',
            'ACADEMIC_IMPACT_LLM_URL': 'http://127.0.0.1:18002/v1/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        })

        self.assertEqual(status['missing_keys'], ['ACADEMIC_IMPACT_ANALYSIS_MODE'])


if __name__ == '__main__':
    unittest.main()
