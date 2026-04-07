from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ANALYZE_FULLTEXT_PATH = ROOT / 'skills' / 'analyze_fulltext_citation' / 'analyze_fulltext.py'


def load_analyze_fulltext_module():
    spec = importlib.util.spec_from_file_location('test_analyze_fulltext_module', ANALYZE_FULLTEXT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AnalyzeFulltextResponseHandlingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_analyze_fulltext_module()

    def test_analyze_payload_prefers_message_content(self):
        payload = {
            'target_title': 'LoRA: Low-Rank Adaptation of Large Language Models',
            'target_year': 2021,
            'citing_title': 'Test Content Preferred',
            'candidate_spans': [{'page': 2, 'span_index': 3, 'text': 'dummy text'}],
        }
        local_result = {
            'analysis_text': '引用论文标题：Test Content Preferred\n候选结论：\n1. 页码：2',
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 42,
            'reasoning_len': 18,
        }

        with mock.patch.object(self.module, 'load_deepseek_key', return_value='test-key'), \
                mock.patch.object(self.module, 'call_local_27b', return_value=local_result), \
                mock.patch.object(
                    self.module,
                    'call_deepseek',
                    return_value='{"ok": true, "citing_title": "Test Content Preferred", "findings": []}',
                ):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(result['_debug']['output_source'], 'content')
        self.assertEqual(result['_debug']['finish_reason'], 'stop')
        self.assertEqual(result['_debug']['content_len'], 42)
        self.assertEqual(result['_debug']['reasoning_len'], 18)
        self.assertIn('引用论文标题：Test Content Preferred', result['_debug']['local_analysis_preview'])

    def test_analyze_payload_falls_back_to_reasoning_content(self):
        payload = {
            'target_title': 'LoRA: Low-Rank Adaptation of Large Language Models',
            'target_year': 2021,
            'citing_title': 'Test Reasoning Fallback',
            'candidate_spans': [{'page': 3, 'span_index': 7, 'text': 'dummy text'}],
        }
        local_result = {
            'analysis_text': '引用论文标题：Test Reasoning Fallback\n候选结论：\n1. 页码：3',
            'output_source': 'reasoning_content',
            'finish_reason': 'length',
            'content_len': 0,
            'reasoning_len': 61,
        }

        def fake_call_deepseek(messages, api_key, max_tokens=800):
            self.assertIn('Test Reasoning Fallback', messages[1]['content'])
            self.assertIn('页码：3', messages[1]['content'])
            return '{"ok": true, "citing_title": "Test Reasoning Fallback", "findings": []}'

        with mock.patch.object(self.module, 'load_deepseek_key', return_value='test-key'), \
                mock.patch.object(self.module, 'call_local_27b', return_value=local_result), \
                mock.patch.object(self.module, 'call_deepseek', side_effect=fake_call_deepseek):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(result['_debug']['output_source'], 'reasoning_content')
        self.assertEqual(result['_debug']['finish_reason'], 'length')
        self.assertEqual(result['_debug']['content_len'], 0)
        self.assertEqual(result['_debug']['reasoning_len'], 61)
        self.assertIn('Test Reasoning Fallback', result['_debug']['local_analysis_preview'])

    def test_analyze_payload_returns_blank_model_output_when_both_fields_empty(self):
        payload = {
            'target_title': 'LoRA: Low-Rank Adaptation of Large Language Models',
            'target_year': 2021,
            'citing_title': 'Test Blank Output',
            'candidate_spans': [{'page': 4, 'span_index': 1, 'text': 'dummy text'}],
        }
        local_result = {
            'analysis_text': '',
            'output_source': 'blank',
            'finish_reason': 'length',
            'content_len': 0,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'load_deepseek_key', return_value='test-key'), \
                mock.patch.object(self.module, 'call_local_27b', return_value=local_result), \
                mock.patch.object(self.module, 'call_deepseek') as mock_deepseek:
            result = self.module.analyze_payload(payload)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'blank_model_output')
        self.assertEqual(result['_debug']['output_source'], 'blank')
        self.assertEqual(result['_debug']['content_len'], 0)
        self.assertEqual(result['_debug']['reasoning_len'], 0)
        self.assertEqual(result['_debug']['local_analysis_preview'], '')
        mock_deepseek.assert_not_called()

    def test_normalize_finding_consistency_removes_explicit_citation_when_keep_false(self):
        parsed = {
            'ok': True,
            'citing_title': 'Consistency Test',
            'findings': [
                {
                    'page': 2,
                    'span_index': 1,
                    'citation_text': 'Recent studies [9,13,2] have explored various PEFT techniques.',
                    'keep': False,
                    'aspect': 'background',
                    'stance': 'neutral',
                    'function': 'test',
                    'reason': 'test',
                    'confidence': 0.6,
                    'mention_type': 'explicit_citation',
                },
                {
                    'page': 3,
                    'span_index': 7,
                    'citation_text': 'Low-rank re-parameterization further improves efficiency [9].',
                    'keep': False,
                    'aspect': 'background',
                    'stance': 'neutral',
                    'function': 'test',
                    'reason': 'test',
                    'confidence': 0.6,
                    'mention_type': 'explicit_citation',
                },
            ],
        }

        result = self.module.normalize_finding_consistency(parsed)

        self.assertEqual(result['findings'][0]['mention_type'], 'grouped_literature_mention')
        self.assertEqual(result['findings'][1]['mention_type'], 'weak_body_mention')


if __name__ == '__main__':
    unittest.main()
