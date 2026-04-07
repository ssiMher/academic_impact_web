from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIND_CANDIDATE_SPANS_PATH = ROOT / 'skills' / 'analyze_fulltext_citation' / 'find_candidate_spans.py'


def load_find_candidate_spans_module():
    spec = importlib.util.spec_from_file_location('test_find_candidate_spans_module', FIND_CANDIDATE_SPANS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FindCandidateSpansAliasTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_find_candidate_spans_module()

    def test_generate_target_aliases_is_generic_not_paper_specific(self):
        aliases = self.module.generate_target_aliases('Training-Free Group Relative Policy Optimization')
        normalized = {alias.lower() for alias in aliases}
        self.assertIn('tf-grpo', normalized)
        self.assertIn('tfgrpo', normalized)

        lora_aliases = self.module.generate_target_aliases('LoRA: Low-Rank Adaptation of Large Language Models')
        self.assertIn('lora', {alias.lower() for alias in lora_aliases})

    def test_paragraph_score_fallback_recognizes_generated_aliases(self):
        title = 'Training-Free Group Relative Policy Optimization'
        aliases = self.module.generate_target_aliases(title)
        score, hits = self.module.paragraph_score_fallback(
            'TF-GRPO [14] simply mimics the GRPO procedure to compute semantic advantages.',
            target_title=title,
            target_aliases=aliases,
        )
        self.assertGreaterEqual(score, 3)
        self.assertIn('TF-GRPO', {hit.upper() for hit in hits})


if __name__ == '__main__':
    unittest.main()
