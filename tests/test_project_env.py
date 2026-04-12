from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / '.env'
ENV_LOCAL_PATH = ROOT / '.env.local'
ANALYZE_FULLTEXT_PATH = ROOT / 'skills' / 'analyze_fulltext_citation' / 'analyze_fulltext.py'


class ProjectEnvTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env_backup = ENV_PATH.read_text(encoding='utf-8') if ENV_PATH.exists() else None
        cls._env_local_backup = ENV_LOCAL_PATH.read_text(encoding='utf-8') if ENV_LOCAL_PATH.exists() else None

    @classmethod
    def tearDownClass(cls):
        if cls._env_backup is None:
            if ENV_PATH.exists():
                ENV_PATH.unlink()
        else:
            ENV_PATH.write_text(cls._env_backup, encoding='utf-8')

        if cls._env_local_backup is None:
            if ENV_LOCAL_PATH.exists():
                ENV_LOCAL_PATH.unlink()
        else:
            ENV_LOCAL_PATH.write_text(cls._env_local_backup, encoding='utf-8')

    def setUp(self):
        for path in [ENV_PATH, ENV_LOCAL_PATH]:
            if path.exists():
                path.unlink()
        for key in [
            'ACADEMIC_IMPACT_ANALYSIS_MODE',
            'ACADEMIC_IMPACT_LLM_URL',
            'ACADEMIC_IMPACT_LLM_MODEL',
            'ACADEMIC_IMPACT_LLM_API_KEY',
            'DEEPSEEK_API_KEY',
            'ACADEMIC_IMPACT_LOCAL_LLM_URL',
            'ACADEMIC_IMPACT_LOCAL_MODEL',
        ]:
            os.environ.pop(key, None)

    def load_analyze_fulltext_module(self):
        spec = importlib.util.spec_from_file_location('test_analyze_fulltext_env', ANALYZE_FULLTEXT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_analyze_fulltext_reads_single_model_project_env(self):
        ENV_PATH.write_text(
            '\n'.join(
                [
                    'ACADEMIC_IMPACT_ANALYSIS_MODE=single_model',
                    'ACADEMIC_IMPACT_LLM_URL=http://127.0.0.1:9999/v1/chat/completions',
                    'ACADEMIC_IMPACT_LLM_MODEL=test-single-model',
                    'ACADEMIC_IMPACT_LLM_API_KEY=project-key',
                ]
            ),
            encoding='utf-8',
        )

        module = self.load_analyze_fulltext_module()

        self.assertEqual(module.normalized_analysis_mode(), 'single_model')
        self.assertEqual(module.LLM_URL, 'http://127.0.0.1:9999/v1/chat/completions')
        self.assertEqual(module.LLM_MODEL, 'test-single-model')
        self.assertEqual(module.load_analysis_api_key(module.LLM_URL), 'project-key')

    def test_analyze_fulltext_falls_back_to_legacy_local_vars(self):
        ENV_PATH.write_text(
            '\n'.join(
                [
                    'ACADEMIC_IMPACT_LOCAL_LLM_URL=http://127.0.0.1:9998/v1/chat/completions',
                    'ACADEMIC_IMPACT_LOCAL_MODEL=test-local-model',
                ]
            ),
            encoding='utf-8',
        )

        module = self.load_analyze_fulltext_module()

        self.assertEqual(module.normalized_analysis_mode(), 'single_model')
        self.assertEqual(module.LLM_URL, 'http://127.0.0.1:9998/v1/chat/completions')
        self.assertEqual(module.LLM_MODEL, 'test-local-model')

    def test_analyze_fulltext_legacy_two_stage_reads_old_vars(self):
        ENV_PATH.write_text(
            '\n'.join(
                [
                    'ACADEMIC_IMPACT_ANALYSIS_MODE=legacy_two_stage',
                    'DEEPSEEK_API_KEY=project-key',
                    'ACADEMIC_IMPACT_LOCAL_LLM_URL=http://127.0.0.1:9999/v1/chat/completions',
                    'ACADEMIC_IMPACT_LOCAL_MODEL=test-local-model',
                ]
            ),
            encoding='utf-8',
        )

        module = self.load_analyze_fulltext_module()

        self.assertEqual(module.normalized_analysis_mode(), 'legacy_two_stage')
        self.assertEqual(module.LOCAL_VLLM_URL, 'http://127.0.0.1:9999/v1/chat/completions')
        self.assertEqual(module.LOCAL_MODEL, 'test-local-model')
        self.assertEqual(module.load_deepseek_key(), 'project-key')


if __name__ == '__main__':
    unittest.main()
