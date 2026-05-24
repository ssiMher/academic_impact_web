from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "evidence_templates.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EvidenceTemplatesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(MODULE_PATH, "test_evidence_templates")

    def test_load_builtin_templates(self):
        templates = self.module.load_builtin_templates()
        ids = {item["id"] for item in templates}
        self.assertIn("ppt_highlight_default", ids)
        self.assertIn("first_evaluation", ids)

    def test_compile_custom_request_first_evaluation(self):
        compiled = self.module.compile_custom_request("找首次评价")
        self.assertEqual(compiled["id"], "custom_first_or_pioneering")
        self.assertIn("first_or_pioneering", compiled["target_labels"])
        self.assertIn("首次", compiled["positive_keywords"])

    def test_compile_custom_request_detailed_comparison(self):
        compiled = self.module.compile_custom_request("找大量实验比较")
        self.assertIn("detailed_comparison", compiled["target_labels"])
        self.assertIn("baseline", compiled["target_labels"])

    def test_prompt_fragment_mentions_target_labels(self):
        fragment = self.module.build_template_prompt_fragment([
            self.module.compile_custom_request("找作为理论基础的引用")
        ])
        self.assertIn("theory_foundation", fragment)
        self.assertIn("理论", fragment)


if __name__ == "__main__":
    unittest.main()
