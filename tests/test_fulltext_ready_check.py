from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts.fulltext_ready_check import candidate_probe_urls, env_status, overall_summary, service_status


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
            {'missing_keys': ['ACADEMIC_IMPACT_LLM_URL']},
            {'status': 'service_unreachable'},
            {'blockers': ['pdf_missing', 'context_only']},
        )
        self.assertEqual(summary['blockers'], ['配置缺失', '服务不可达', 'PDF 缺失', '只能 context_only'])
        self.assertFalse(summary['ok'])

    def test_env_status_legacy_config_passes(self):
        env = {
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'legacy_two_stage',
            'ACADEMIC_IMPACT_LOCAL_LLM_URL': 'http://127.0.0.1:8002/v1/chat/completions',
            'ACADEMIC_IMPACT_LOCAL_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
            'DEEPSEEK_API_KEY': 'deepseek-key',
        }
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}), \
                mock.patch.dict(os.environ, env, clear=True):
            status = env_status()

        self.assertEqual(status['missing_keys'], [])
        self.assertEqual(status['effective']['analysis_mode'], 'legacy_two_stage')
        self.assertEqual(status['effective']['url'], env['ACADEMIC_IMPACT_LOCAL_LLM_URL'])
        self.assertEqual(status['effective']['model'], env['ACADEMIC_IMPACT_LOCAL_MODEL'])
        self.assertEqual(status['effective']['api_key_source'], 'DEEPSEEK_API_KEY')

    def test_env_status_legacy_requires_deepseek_api_key(self):
        env = {
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'legacy_two_stage',
            'ACADEMIC_IMPACT_LLM_URL': 'https://api.deepseek.com/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'deepseek-chat',
            'ACADEMIC_IMPACT_LOCAL_LLM_URL': 'http://127.0.0.1:8002/v1/chat/completions',
            'ACADEMIC_IMPACT_LOCAL_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        }
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}), \
                mock.patch.dict(os.environ, env, clear=True):
            status = env_status()

        self.assertEqual(status['missing_keys'], ['DEEPSEEK_API_KEY'])
        self.assertFalse(status['effective']['api_key_configured'])

    def test_env_status_invalid_mode_fails(self):
        env = {
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'surprise_me',
            'ACADEMIC_IMPACT_LLM_URL': 'http://127.0.0.1:8002/v1/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        }
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}), \
                mock.patch.dict(os.environ, env, clear=True):
            status = env_status()

        self.assertEqual(status['missing_keys'], ['ACADEMIC_IMPACT_ANALYSIS_MODE'])
        self.assertFalse(status['effective']['analysis_mode_valid'])

    def test_env_status_accepts_deepseek_legacy_key_for_deepseek_url(self):
        env = {
            'ACADEMIC_IMPACT_LLM_URL': 'https://api.deepseek.com/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'deepseek-chat',
            'DEEPSEEK_API_KEY': 'legacy-key',
        }
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}), \
                mock.patch.dict(os.environ, env, clear=True):
            status = env_status()

        self.assertEqual(status['missing_keys'], [])
        self.assertTrue(status['effective']['api_key_configured'])
        self.assertEqual(status['effective']['api_key_source'], 'DEEPSEEK_API_KEY')

    def test_env_status_single_model_allows_local_model_without_api_key(self):
        env = {
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'single_model',
            'ACADEMIC_IMPACT_LLM_URL': 'http://127.0.0.1:8002/v1/chat/completions',
            'ACADEMIC_IMPACT_LLM_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        }
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}), \
                mock.patch.dict(os.environ, env, clear=True):
            status = env_status()

        self.assertEqual(status['missing_keys'], [])
        self.assertFalse(status['effective']['api_key_required'])

    def test_env_status_single_model_accepts_legacy_local_key_fallback(self):
        env = {
            'ACADEMIC_IMPACT_ANALYSIS_MODE': 'single_model',
            'ACADEMIC_IMPACT_LOCAL_LLM_URL': 'http://127.0.0.1:8002/v1/chat/completions',
            'ACADEMIC_IMPACT_LOCAL_MODEL': 'Qwen3.5-27B-Q4_K_M.gguf',
        }
        with mock.patch('scripts.fulltext_ready_check.load_project_env', return_value={}), \
                mock.patch.dict(os.environ, env, clear=True):
            status = env_status()

        self.assertEqual(status['missing_keys'], [])
        self.assertEqual(status['effective']['url_source'], 'ACADEMIC_IMPACT_LOCAL_LLM_URL')
        self.assertEqual(status['effective']['model_source'], 'ACADEMIC_IMPACT_LOCAL_MODEL')


if __name__ == '__main__':
    unittest.main()
