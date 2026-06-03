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

    def test_normalize_model_finding_preserves_evidence_metadata(self):
        finding = {
            "page": 4,
            "span_index": 2,
            "citation_text": "We compare against the pioneering baseline.",
            "keep": True,
            "aspect": "baseline",
            "stance": "positive",
            "evidence_labels": [
                "baseline",
                "first_or_pioneering",
                "sota_evaluation",
                "representative_work",
                "detailed_comparison",
                "method_extension",
                "sustained_followup",
                "review_comment_praise",
                "not_valid",
            ],
            "highlight_keywords": ["compare", "pioneering"],
            "evidence_strength": "high",
            "is_self_citation": True,
            "why_valuable": "可用于说明目标工作被作为开创性基线比较。",
            "confidence": 0.91,
        }

        result = self.module.normalize_model_finding(finding, 0)

        self.assertEqual(
            result["evidence_labels"],
            [
                "baseline",
                "first_or_pioneering",
                "sota_evaluation",
                "representative_work",
                "detailed_comparison",
                "method_extension",
                "sustained_followup",
                "review_comment_praise",
            ],
        )
        self.assertEqual(result["highlight_keywords"], ["compare", "pioneering"])
        self.assertEqual(result["evidence_strength"], "high")
        self.assertIs(result["is_self_citation"], True)
        self.assertEqual(result["why_valuable"], "可用于说明目标工作被作为开创性基线比较。")

    def test_prompts_describe_refined_evidence_label_schema(self):
        system_prompt = self.module.SINGLE_MODEL_SYSTEM_PROMPT
        deepseek_prompt = self.module.DEEPSEEK_SYSTEM_PROMPT
        user_prompt = self.module.build_single_model_prompt(
            {
                "target_title": "Target Paper",
                "target_year": 2024,
                "citing_title": "Citing Paper",
                "candidate_spans": [
                    {
                        "page": 1,
                        "span_index": 1,
                        "text": "Target Paper is a state-of-the-art representative work.",
                    }
                ],
            }
        )

        for label in [
            "sota_evaluation",
            "representative_work",
            "detailed_comparison",
            "method_extension",
            "sustained_followup",
            "review_comment_praise",
        ]:
            self.assertIn(label, system_prompt)
            self.assertIn(label, deepseek_prompt)

        self.assertIn("SOTA", system_prompt)
        self.assertIn("representative", system_prompt)
        self.assertIn("detailed comparison", system_prompt)
        self.assertIn("template priority", system_prompt)
        self.assertIn("优先级", user_prompt)

    def test_template_prompt_fragment_is_included_in_candidate_and_fulltext_prompts(self):
        fragment = "用户本次特别关注以下引用证据模板：详细对比；要求=寻找 baseline。"
        candidate_prompt = self.module.build_single_model_prompt(
            {
                "target_title": "Target Paper",
                "citing_title": "Citing Paper",
                "template_prompt_fragment": fragment,
                "candidate_spans": [
                    {
                        "page": 1,
                        "span_index": 1,
                        "text": "We compare against Target Paper.",
                    }
                ],
            }
        )
        fulltext_prompt = self.module.build_fulltext_direct_prompt(
            {
                "target_title": "Target Paper",
                "citing_title": "Citing Paper",
                "template_prompt_fragment": fragment,
                "fulltext_pages": [
                    {"page": 2, "text": "Target Paper is a baseline."},
                ],
            }
        )

        self.assertIn(fragment, candidate_prompt)
        self.assertIn(fragment, fulltext_prompt)

    def test_prompt_includes_target_citation_anchor_metadata(self):
        payload = {
            "target_title": "MoiréTracker: Continuous Camera-to-Screen 6-DoF Pose Tracking Based on Moiré Pattern",
            "target_year": 2024,
            "citing_title": "Visual-Based Out-of-Plane Rotation Measurement",
            "target_citation_index": "16",
            "target_reference_text": "[16] J. Ning et al., MoiréTracker: Continuous camera-to-screen 6-DoF pose tracking based on Moiré pattern.",
            "candidate_spans": [
                {
                    "page": 2,
                    "span_index": 1,
                    "text": "Some methods leverage the aliasing effect [15], [16], [17]. Other methods achieved high accuracy [18].",
                    "citation_index": "16",
                    "match_type": "citation_index_grouped",
                }
            ],
        }

        prompt = self.module.build_single_model_prompt(payload)

        self.assertIn("目标论文引用编号/锚点：16", prompt)
        self.assertIn("目标论文参考文献条目", prompt)
        self.assertIn("MoiréTracker", prompt)
        self.assertIn("不能把其他编号", prompt)

    def test_fulltext_prompt_includes_citation_anchor_rules(self):
        prompt = self.module.build_fulltext_direct_prompt(
            {
                "target_title": "Target Paper",
                "citing_title": "Citing Paper",
                "target_citation_index": "9",
                "fulltext_pages": [
                    {"page": 1, "text": "Related work cites Target Paper [9]."},
                ],
            }
        )

        self.assertIn("目标论文引用编号/锚点：9", prompt)
        self.assertIn("同一句、同一子句或明确承接", prompt)
        self.assertIn("不能把其他编号", prompt)

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

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='legacy_two_stage'), \
                mock.patch.object(self.module, 'load_deepseek_key', return_value='test-key'), \
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

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='legacy_two_stage'), \
                mock.patch.object(self.module, 'load_deepseek_key', return_value='test-key'), \
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

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='legacy_two_stage'), \
                mock.patch.object(self.module, 'load_deepseek_key', return_value='test-key'), \
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

    def test_analyze_payload_single_model_direct_json(self):
        payload = {
            'target_title': 'LoRA: Low-Rank Adaptation of Large Language Models',
            'target_year': 2021,
            'citing_title': 'Single Model Test',
            'candidate_spans': [{'page': 5, 'span_index': 2, 'text': 'LoRA [9] is a baseline.'}],
        }
        model_result = {
            'analysis_text': (
                '{"ok": true, "citing_title": "Single Model Test", "findings": ['
                '{"page": 5, "span_index": 2, "citation_text": "LoRA [9]", '
                '"keep": true, "aspect": "baseline", "stance": "neutral", '
                '"function": "作为基线比较", "reason": "明确点名 LoRA", '
                '"confidence": 0.86, "mention_type": "explicit_citation"}]}'
            ),
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 250,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(result['_debug']['analysis_mode'], 'single_model')
        self.assertEqual(result['findings'][0]['page'], 5)
        self.assertTrue(result['findings'][0]['keep'])

    def test_analyze_payload_supports_fulltext_direct_scope(self):
        payload = {
            'analysis_scope': 'fulltext_direct',
            'target_title': 'Optimizing generative AI by backpropagating language model feedback',
            'target_year': 2025,
            'citing_title': 'Direct Fulltext Test',
            'candidate_spans': [],
            'fulltext_pages': [
                {'page': 1, 'text': 'Introduction without the target paper.'},
                {'page': 3, 'text': 'We compare against Chen et al. (2025) as a baseline.'},
            ],
        }
        model_result = {
            'analysis_text': (
                '{"ok": true, "citing_title": "Direct Fulltext Test", "findings": ['
                '{"page": 3, "span_index": 1, "citation_text": "Chen et al. (2025)", '
                '"keep": true, "aspect": "baseline", "stance": "neutral"}]}'
            ),
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 210,
            'reasoning_len': 0,
        }

        captured_messages = []

        def fake_chat(messages, **kwargs):
            captured_messages.extend(messages)
            return model_result

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', side_effect=fake_chat):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(result['_debug']['analysis_scope'], 'fulltext_direct')
        self.assertEqual(result['_debug']['candidate_span_count'], 0)
        self.assertEqual(result['_debug']['fulltext_page_count'], 2)
        self.assertEqual(result['findings'][0]['page'], 3)
        self.assertIn('分析范围：fulltext_direct', captured_messages[1]['content'])
        self.assertIn('[Page 3]', captured_messages[1]['content'])
        self.assertIn('主要贡献类型', self.module.SINGLE_MODEL_SYSTEM_PROMPT)
        self.assertIn('Transformer encoder', self.module.SINGLE_MODEL_SYSTEM_PROMPT)
        self.assertIn('不要降级为 mention_only', captured_messages[1]['content'])

    def test_analyze_payload_uses_deepseek_profile_when_requested(self):
        payload = {
            'analysis_scope': 'fulltext_direct',
            'analysis_model_profile': 'deepseek',
            'target_title': 'Target Paper',
            'citing_title': 'DeepSeek Profile Test',
            'candidate_spans': [],
            'fulltext_pages': [
                {'page': 1, 'text': 'We build on Target Paper as a baseline.'},
            ],
        }
        model_result = {
            'analysis_text': '{"ok": true, "citing_title": "DeepSeek Profile Test", "findings": []}',
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 72,
            'reasoning_len': 0,
        }
        captured_kwargs = {}

        def fake_chat(_messages, **kwargs):
            captured_kwargs.update(kwargs)
            return model_result

        with mock.patch.object(self.module, 'call_openai_compatible_chat', side_effect=fake_chat), \
                mock.patch.object(self.module, 'load_analysis_api_key', return_value='deepseek-key'):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(captured_kwargs['url'], 'https://api.deepseek.com/chat/completions')
        self.assertEqual(captured_kwargs['model'], 'deepseek-chat')
        self.assertEqual(captured_kwargs['api_key'], 'deepseek-key')
        self.assertEqual(result['_debug']['analysis_model_profile'], 'deepseek')

    def test_resolve_analysis_model_profile_supports_local_and_default_profiles(self):
        default_profile = self.module.resolve_analysis_model_profile('')
        local_profile = self.module.resolve_analysis_model_profile('local')

        self.assertEqual(default_profile['profile'], 'default')
        self.assertEqual(default_profile['mode'], 'single_model')
        self.assertEqual(local_profile['profile'], 'local')
        self.assertEqual(local_profile['mode'], 'single_model')
        self.assertEqual(local_profile['url'], self.module.LOCAL_VLLM_URL)
        self.assertEqual(local_profile['model'], self.module.LOCAL_MODEL)

    def test_fulltext_direct_prompt_uses_configurable_default_budget(self):
        self.assertEqual(self.module.MAX_FULLTEXT_DIRECT_CHARS, 90000)

        prompt = self.module.build_fulltext_direct_prompt(
            {
                'analysis_scope': 'fulltext_direct',
                'target_title': 'Target Paper',
                'citing_title': 'Long Citing Paper',
                'fulltext_pages': [
                    {'page': 1, 'text': 'A' * (self.module.MAX_FULLTEXT_DIRECT_CHARS + 1000)},
                    {'page': 2, 'text': 'This page should not fit under the direct prompt budget.'},
                ],
            }
        )

        self.assertIn('全文文本已按字符预算截断', prompt)
        self.assertNotIn('This page should not fit', prompt)

    def test_fulltext_direct_requires_fulltext_text(self):
        payload = {
            'analysis_scope': 'fulltext_direct',
            'citing_title': 'Empty Direct Test',
            'candidate_spans': [],
            'fulltext_pages': [],
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat') as mock_chat:
            result = self.module.analyze_payload(payload)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'fulltext_direct_empty_text')
        self.assertEqual(result['_debug']['analysis_scope'], 'fulltext_direct')
        mock_chat.assert_not_called()

    def test_single_model_rejects_non_object_json(self):
        payload = {
            'citing_title': 'Schema Test',
            'candidate_spans': [{'page': 1, 'span_index': 1, 'text': 'dummy'}],
        }
        model_result = {
            'analysis_text': '[]',
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 2,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'single_model_schema_invalid')

    def test_single_model_rejects_non_object_finding(self):
        payload = {
            'citing_title': 'Finding Schema Test',
            'candidate_spans': [{'page': 1, 'span_index': 1, 'text': 'dummy'}],
        }
        model_result = {
            'analysis_text': '{"ok": true, "findings": ["bad"]}',
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 35,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'single_model_schema_invalid')

    def test_single_model_normalizes_partial_finding_defaults(self):
        payload = {
            'citing_title': 'Partial Finding Test',
            'candidate_spans': [{'page': 2, 'span_index': 4, 'text': 'LoRA [9]'}],
        }
        model_result = {
            'analysis_text': (
                '{"ok": true, "findings": ['
                '{"page": "2", "span_index": "4", "keep": "yes", '
                '"aspect": "unexpected", "stance": "mixed"}]}'
            ),
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 120,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        finding = result['findings'][0]
        self.assertTrue(finding['keep'])
        self.assertEqual(finding['page'], 2)
        self.assertEqual(finding['span_index'], 4)
        self.assertEqual(finding['aspect'], 'other')
        self.assertEqual(finding['stance'], 'neutral')
        self.assertEqual(finding['confidence'], 0.6)
        self.assertEqual(finding['mention_type'], 'explicit_citation')

    def test_single_model_extracts_fenced_json_from_content(self):
        payload = {
            'citing_title': 'Fenced JSON Test',
            'candidate_spans': [{'page': 6, 'span_index': 1, 'text': 'dummy'}],
        }
        model_result = {
            'analysis_text': (
                '<think>{"ok": true, "findings": [{"page": 99, "span_index": 99}]}</think>\n'
                '```json\n'
                '{"ok": true, "citing_title": "Fenced JSON Test", "findings": ['
                '{"page": 6, "span_index": 1, "citation_text": "real", "keep": true}'
                ']}\n'
                '```'
            ),
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 180,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(result['findings'][0]['page'], 6)
        self.assertEqual(result['findings'][0]['span_index'], 1)

    def test_single_model_extracts_prefixed_json_from_content(self):
        payload = {
            'citing_title': 'Prefixed JSON Test',
            'candidate_spans': [{'page': 7, 'span_index': 3, 'text': 'dummy'}],
        }
        model_result = {
            'analysis_text': (
                'Here is the JSON:\n'
                '{"ok": true, "citing_title": "Prefixed JSON Test", "findings": ['
                '{"page": 7, "span_index": 3, "citation_text": "real", "keep": false}'
                ']}'
            ),
            'output_source': 'content',
            'finish_reason': 'stop',
            'content_len': 160,
            'reasoning_len': 0,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        self.assertTrue(result['ok'])
        self.assertEqual(result['findings'][0]['page'], 7)
        self.assertFalse(result['findings'][0]['keep'])

    def test_single_model_does_not_parse_thinking_trace_as_final_json(self):
        payload = {
            'citing_title': 'Reasoning Only Test',
            'candidate_spans': [{'page': 8, 'span_index': 1, 'text': 'dummy'}],
        }
        model_result = {
            'analysis_text': '',
            'content': '',
            'reasoning_content': (
                'Thinking Process:\n'
                '1. Analyze the request.\n'
                '{"ok": true, "citing_title": "schema echo", "findings": []}'
            ),
            'output_source': 'reasoning_content_ignored',
            'finish_reason': 'length',
            'content_len': 0,
            'reasoning_len': 96,
        }

        with mock.patch.object(self.module, 'normalized_analysis_mode', return_value='single_model'), \
                mock.patch.object(self.module, 'call_openai_compatible_chat', return_value=model_result):
            result = self.module.analyze_payload(payload)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'blank_model_output')
        self.assertEqual(result['_debug']['output_source'], 'reasoning_content_ignored')
        self.assertIn('Thinking Process', result['_debug']['reasoning_preview'])

    def test_openai_compatible_chat_retries_without_response_format_on_400(self):
        http_error = self.module.requests.HTTPError

        class FakeResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    exc = http_error(f'{self.status_code} Client Error')
                    exc.response = self
                    raise exc

            def json(self):
                return self._payload

        posts = []
        success_payload = {
            'choices': [
                {
                    'message': {'content': '{"ok": true, "findings": []}'},
                    'finish_reason': 'stop',
                }
            ]
        }

        def fake_post(url, headers, json, timeout):
            posts.append(json)
            if len(posts) == 1:
                return FakeResponse(400, {})
            return FakeResponse(200, success_payload)

        with mock.patch.object(self.module.requests, 'post', side_effect=fake_post):
            result = self.module.call_openai_compatible_chat(
                [{'role': 'user', 'content': 'hi'}],
                url='http://127.0.0.1:18002/v1/chat/completions',
                model='test-model',
                use_reasoning_fallback=False,
            )

        self.assertEqual(result['analysis_text'], '{"ok": true, "findings": []}')
        self.assertIn('response_format', posts[0])
        self.assertNotIn('response_format', posts[1])

    def test_request_exception_classification_uses_response_body(self):
        class FakeResponse:
            text = 'request (43127 tokens) exceeds the available context size (32768 tokens)'

        exc = self.module.requests.HTTPError('400 Client Error')
        exc.response = FakeResponse()

        detail_type, message = self.module.classify_request_exception(exc)

        self.assertEqual(detail_type, 'context_length_exceeded')
        self.assertIn('上下文上限', message)

    def test_openai_compatible_chat_sends_disable_thinking_flag(self):
        payload = {
            'choices': [
                {
                    'message': {'content': '{"ok": true, "findings": []}'},
                    'finish_reason': 'stop',
                }
            ]
        }
        posts = []

        def fake_post(url, headers, json, timeout):
            posts.append(json)
            return mock.Mock(raise_for_status=lambda: None, json=lambda: payload)

        with mock.patch.object(self.module.requests, 'post', side_effect=fake_post):
            result = self.module.call_openai_compatible_chat(
                [{'role': 'user', 'content': 'hi'}],
                url='http://127.0.0.1:18002/v1/chat/completions',
                model='test-model',
                use_reasoning_fallback=False,
                disable_thinking=True,
            )

        self.assertEqual(result['analysis_text'], '{"ok": true, "findings": []}')
        self.assertEqual(posts[0]['chat_template_kwargs'], {'enable_thinking': False})

    def test_openai_compatible_chat_falls_back_if_disable_thinking_is_unsupported(self):
        http_error = self.module.requests.HTTPError

        class FakeResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    exc = http_error(f'{self.status_code} Client Error')
                    exc.response = self
                    raise exc

            def json(self):
                return self._payload

        posts = []
        success_payload = {
            'choices': [
                {
                    'message': {'content': '{"ok": true, "findings": []}'},
                    'finish_reason': 'stop',
                }
            ]
        }

        def fake_post(url, headers, json, timeout):
            posts.append(dict(json))
            if len(posts) < 3:
                return FakeResponse(400, {})
            return FakeResponse(200, success_payload)

        with mock.patch.object(self.module.requests, 'post', side_effect=fake_post):
            result = self.module.call_openai_compatible_chat(
                [{'role': 'user', 'content': 'hi'}],
                url='http://127.0.0.1:18002/v1/chat/completions',
                model='test-model',
                use_reasoning_fallback=False,
                disable_thinking=True,
            )

        self.assertEqual(result['analysis_text'], '{"ok": true, "findings": []}')
        self.assertIn('response_format', posts[0])
        self.assertIn('chat_template_kwargs', posts[0])
        self.assertNotIn('response_format', posts[1])
        self.assertIn('chat_template_kwargs', posts[1])
        self.assertNotIn('response_format', posts[2])
        self.assertNotIn('chat_template_kwargs', posts[2])

    def test_openai_compatible_chat_can_ignore_reasoning_fallback(self):
        payload = {
            'choices': [
                {
                    'message': {
                        'content': '',
                        'reasoning_content': 'Thinking Process: not final JSON',
                    },
                    'finish_reason': 'length',
                }
            ]
        }

        with mock.patch.object(
            self.module.requests,
            'post',
            return_value=mock.Mock(raise_for_status=lambda: None, json=lambda: payload),
        ):
            result = self.module.call_openai_compatible_chat(
                [{'role': 'user', 'content': 'hi'}],
                url='http://127.0.0.1:18002/v1/chat/completions',
                model='test-model',
                use_reasoning_fallback=False,
            )

        self.assertEqual(result['analysis_text'], '')
        self.assertEqual(result['output_source'], 'reasoning_content_ignored')
        self.assertEqual(result['reasoning_len'], len('Thinking Process: not final JSON'))

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

    def test_keep_true_findings_are_normalized_to_explicit_citation(self):
        finding = self.module.normalize_model_finding(
            {
                'page': 2,
                'span_index': 1,
                'citation_text': 'We use the Transformer encoder [42].',
                'keep': True,
                'aspect': 'method',
                'mention_type': 'weak_body_mention',
            },
            0,
        )

        self.assertEqual(finding['mention_type'], 'explicit_citation')


if __name__ == '__main__':
    unittest.main()
