# Highlight Evidence Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade scholar impact analysis from a strong-citation list into a PPT-ready third-party highlight evidence workflow, including custom analysis templates, collaborator exclusion, finer evidence labels, and highlight-card exports.

**Architecture:** Keep the existing scholar session, high-value queue, fulltext analyzer, and strong evidence page. Add a small evidence-template layer, extend self-citation into exclusion-aware third-party citation classification, refine evidence labels in the existing `scholar_evidence.py`, and generate highlight cards from normalized strong evidence rather than inventing a separate result store.

**Tech Stack:** FastAPI, Jinja templates, Python JSON session files, existing scholar impact analyzer modules, existing fulltext LLM analyzer, existing local PDF workflow, `unittest`.

---

## 1. Background And Mentor Acceptance Target

The mentor's feedback and Ning teacher's reference PPT point to one product target:

> The system should discover high-quality third-party evaluations that can be used in group reports or PPTs, not merely count citations or chase perfect name disambiguation.

The expected output should read like the reference PPT:

- an important scholar/team cites the target work;
- the citation is positive, representative, first/pioneering, state-of-the-art, large-context, baseline/comparison, theory/model adoption, method extension, or sustained follow-up;
- the system shows the original text evidence and highlights decisive words;
- self-citations, close collaborators, and group authors are excluded or clearly marked;
- users can ask for a specific evidence pattern, such as "find first evaluations" or "find detailed comparisons".

## 2. Scope

### In Scope

- Refine evidence labels to match report/PPT categories.
- Add custom analysis templates and built-in presets.
- Add session-level collaborator/group exclusion configuration.
- Make high-value queue and strong evidence aware of third-party vs self/collaborator status.
- Generate PPT-ready highlight evidence cards.
- Export highlight cards as CSV and Markdown.
- Add tests for label normalization, template compilation, exclusion classification, queue ranking, strong evidence filtering, and exports.

### Out Of Scope

- Perfect global scholar disambiguation.
- Automatic university account login or cookie-based publisher downloads.
- Full PowerPoint generation.
- Replacing DBLP as the publication source.
- Rebuilding all person-tag external IDs.

## 3. Current Code Map

### Files To Modify

- `skills/scholar_impact_analyzer/scholar_evidence.py`
  - evidence labels, display names, keyword patterns, exclusion-aware citation classification, scoring.
- `skills/scholar_impact_analyzer/scholar_stats.py`
  - high-value queue ranking and reasons using third-party/excluded status.
- `skills/scholar_impact_analyzer/scholar_pipeline.py`
  - pass analysis templates and exclusion config into fulltext analysis and strong evidence normalization.
- `skills/analyze_fulltext_citation/analyze_fulltext.py`
  - prompt/schema update for refined labels and custom evidence templates.
- `app/services/scholar_core.py`
  - session defaults, template/exclusion update handlers, strong evidence view, highlight card builder, exports.
- `app/main.py`
  - routes for updating templates/exclusion settings and downloading highlight-card exports.
- `app/templates/scholar_session.html`
  - UI for template selection, custom template input, exclusion author list, highlight cards, export links.
- `tests/test_scholar_evidence.py`
  - label, scoring, keyword, exclusion tests.
- `tests/test_scholar_stats.py`
  - queue ranking and collaborator exclusion tests.
- `tests/test_scholar_pipeline.py`
  - analyzer template propagation and strong evidence normalization tests.
- `tests/test_scholar_web.py`
  - route rendering, form updates, filters, exports.
- `tests/test_analyze_fulltext.py`
  - refined label schema and prompt preservation tests.
- `docs/devlog.md`
  - implementation note after each completed feature slice.

### Files To Create

- `skills/scholar_impact_analyzer/evidence_templates.py`
  - built-in templates, natural-language template compilation, template prompt fragment generation.
- `data/reference/scholar_evidence_templates.json`
  - editable built-in presets used by the web UI and analyzer.
- `tests/test_scholar_evidence_templates.py`
  - deterministic tests for template loading and compilation.

## 4. Session Schema Additions

Add these optional fields to scholar sessions. Existing sessions must load with defaults.

```json
{
  "analysis_templates": {
    "active_template_ids": ["ppt_highlight_default"],
    "custom_requests": [
      "找首次评价",
      "找大量实验比较",
      "找作为理论基础的引用"
    ],
    "compiled_templates": [
      {
        "id": "custom_first_evaluation",
        "name": "首次评价",
        "description": "寻找 first、首次、pioneering、开创性等首创评价",
        "target_labels": ["first_or_pioneering"],
        "positive_keywords": ["first", "首次", "pioneering", "开创"],
        "negative_keywords": ["one of", "related work"],
        "prompt_instruction": "优先寻找原文明确称目标工作 first、首次、pioneering、开创性或 seminal 的证据。"
      }
    ]
  },
  "exclusion_profile": {
    "exclude_selected_author": true,
    "exclude_source_paper_authors": true,
    "extra_excluded_authors": ["Lei Xie", "Chuyu Wang"],
    "extra_excluded_affiliations": ["Nanjing University", "State Key Laboratory for Novel Software Technology"],
    "notes": "本组/长期合作者列表"
  },
  "highlight_cards": []
}
```

## 5. Refined Evidence Labels

The label set should support old labels for backward compatibility, but the UI should present the refined labels below.

| Label | Chinese Display | Meaning | Report Value |
| --- | --- | --- | --- |
| `positive_evaluation` | 正向评价 | Original text clearly praises the target work or result. | Supports "highly evaluated by peers". |
| `sota_evaluation` | 最先进 / SOTA | Text says state-of-the-art, best, advanced, leading, superior. | Supports "recognized as advanced work". |
| `first_or_pioneering` | 首次 / 开创性 | Text says first, pioneering, seminal, first use, first work. | Supports "pioneering contribution". |
| `representative_work` | 代表性工作 | Text presents target as representative, canonical, unique, only example. | Matches MoirePose PPT style. |
| `large_context` | 大篇幅引用 | The citing paper spends a long paragraph, multiple sentences, or figure/table context on target. | Supports "substantive citation". |
| `detailed_comparison` | 详细对比 | Citing paper compares with target in experiments, evaluation, table, or system discussion. | Stronger than generic comparison. |
| `baseline` | 作为 Baseline | Target is used as a baseline method/system/model. | Direct experimental impact. |
| `method_foundation` | 方法来源 | Citing paper uses, follows, adopts, builds on, or is inspired by target method. | Shows method transfer. |
| `method_extension` | 方法拓展 | Citing paper extends, adapts, modifies, or generalizes target method. | Shows follow-on research. |
| `theory_foundation` | 理论 / 公式基础 | Citing paper adopts target theory, model, derivation, equation, proof, framework. | Matches Jiwu Huang TDSC example. |
| `sustained_followup` | 持续跟踪引用 | Same author/team cites target across multiple papers. | Matches Wolfgang Heidrich example. |
| `important_person` | 重要人物引用 | Citing author/team has Fellow/academician/award/top-school tag. | Supports "cited by important peers". |
| `review_comment_praise` | 审稿意见亮评 | Imported review comments praise the work. | Matches PPT review-comment slide. |
| `negative_or_limitation` | 负面或局限评价 | Text criticizes limitations or failure. | Needed for completeness and filtering. |
| `survey_or_related_work` | 综述 / 相关工作 | Mostly background or grouped related-work mention. | Usually lower report priority. |

## 6. Built-In Analysis Templates

Create presets in `data/reference/scholar_evidence_templates.json`.

```json
[
  {
    "id": "ppt_highlight_default",
    "name": "PPT 亮点评价",
    "description": "优先寻找可直接写进汇报的第三方正向评价、代表性评价、SOTA、重要人物引用和大篇幅引用。",
    "target_labels": [
      "positive_evaluation",
      "sota_evaluation",
      "representative_work",
      "large_context",
      "important_person"
    ],
    "positive_keywords": [
      "state-of-the-art",
      "first",
      "pioneering",
      "representative",
      "only",
      "advanced",
      "leading",
      "首次",
      "开创",
      "代表性",
      "最先进"
    ],
    "prompt_instruction": "优先寻找能够支撑汇报/PPT亮点评价的第三方原文证据，尤其是正向评价、SOTA、唯一代表性工作、大篇幅引用和重要人物引用。"
  },
  {
    "id": "first_evaluation",
    "name": "首次 / 开创性评价",
    "description": "寻找 first、first work、pioneering、seminal、首次、开创性等表达。",
    "target_labels": ["first_or_pioneering"],
    "positive_keywords": ["first", "first work", "pioneering", "seminal", "首次", "开创"],
    "prompt_instruction": "只在原文明确表达 first、首次、pioneering、开创性或 seminal 时标注首次/开创性。"
  },
  {
    "id": "detailed_comparison",
    "name": "大量 / 详细实验比较",
    "description": "寻找 compare、baseline、table、evaluation、outperform、实验对比等证据。",
    "target_labels": ["detailed_comparison", "baseline"],
    "positive_keywords": ["compare", "comparison", "baseline", "evaluation", "outperform", "Table", "对比", "基线"],
    "prompt_instruction": "优先寻找引用论文把目标工作作为 baseline 或在实验、表格、评估章节中详细比较的证据。"
  },
  {
    "id": "theory_foundation",
    "name": "理论 / 模型基础",
    "description": "寻找公式、理论、模型、推导、framework 被采用或拓展的证据。",
    "target_labels": ["theory_foundation", "method_extension"],
    "positive_keywords": ["derive", "equation", "model", "framework", "theory", "extend", "formula", "公式", "理论", "模型", "推导"],
    "prompt_instruction": "优先寻找引用论文在理论推导、公式建模、框架构建中采用或拓展目标工作的证据。"
  },
  {
    "id": "method_source",
    "name": "方法来源 / 方法拓展",
    "description": "寻找 based on、inspired by、adopt、extend、follow 等方法继承证据。",
    "target_labels": ["method_foundation", "method_extension"],
    "positive_keywords": ["based on", "inspired by", "adopt", "extend", "follow", "build on", "基于", "采用", "拓展"],
    "prompt_instruction": "优先寻找引用论文的方法设计明确基于、采用、借鉴、拓展目标工作的证据。"
  }
]
```

## 7. Implementation Tasks

### Task 1: Add Evidence Template Loader And Compiler

**Files:**

- Create: `skills/scholar_impact_analyzer/evidence_templates.py`
- Create: `data/reference/scholar_evidence_templates.json`
- Test: `tests/test_scholar_evidence_templates.py`

- [ ] **Step 1: Write tests for loading presets and compiling natural-language requests**

Create `tests/test_scholar_evidence_templates.py`:

```python
from __future__ import annotations

import importlib.util
import json
import tempfile
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
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python3 -m unittest tests.test_scholar_evidence_templates -q
```

Expected: fail because `evidence_templates.py` does not exist.

- [ ] **Step 3: Add preset JSON**

Create `data/reference/scholar_evidence_templates.json` with the JSON array from section 6.

- [ ] **Step 4: Implement `evidence_templates.py`**

The module should expose:

```python
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_PATH = ROOT / "data" / "reference" / "scholar_evidence_templates.json"


def unique_strings(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def load_builtin_templates(path: Path | str = DEFAULT_TEMPLATE_PATH) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [normalize_template(item) for item in data if isinstance(item, dict)]


def normalize_template(item: dict[str, Any]) -> dict[str, Any]:
    template_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or template_id).strip()
    return {
        "id": template_id,
        "name": name,
        "description": str(item.get("description") or "").strip(),
        "target_labels": unique_strings(item.get("target_labels") or []),
        "positive_keywords": unique_strings(item.get("positive_keywords") or []),
        "negative_keywords": unique_strings(item.get("negative_keywords") or []),
        "prompt_instruction": str(item.get("prompt_instruction") or "").strip(),
    }


def compile_custom_request(request: str) -> dict[str, Any]:
    text = str(request or "").strip()
    lower = text.lower()
    labels = []
    keywords = []
    instructions = []
    if any(token in lower for token in ["首次", "first", "开创", "pioneer"]):
        labels.append("first_or_pioneering")
        keywords.extend(["first", "first work", "pioneering", "首次", "开创"])
        instructions.append("寻找原文明确表达 first、首次、pioneering、开创性或 seminal 的证据。")
    if any(token in lower for token in ["比较", "对比", "baseline", "实验", "compare"]):
        labels.extend(["detailed_comparison", "baseline"])
        keywords.extend(["compare", "comparison", "baseline", "evaluation", "对比", "基线"])
        instructions.append("寻找实验、表格、评估章节中把目标工作作为 baseline 或比较对象的证据。")
    if any(token in lower for token in ["理论", "公式", "模型", "推导", "foundation", "framework"]):
        labels.extend(["theory_foundation", "method_extension"])
        keywords.extend(["theory", "equation", "model", "framework", "derive", "理论", "公式", "模型"])
        instructions.append("寻找理论推导、公式建模或框架构建中采用或拓展目标工作的证据。")
    if any(token in lower for token in ["方法", "来源", "拓展", "inspired", "based on", "采用"]):
        labels.extend(["method_foundation", "method_extension"])
        keywords.extend(["based on", "inspired by", "adopt", "extend", "基于", "采用", "拓展"])
        instructions.append("寻找引用论文的方法设计明确基于、采用、借鉴、拓展目标工作的证据。")
    if any(token in lower for token in ["正向", "好评", "评价", "先进", "sota", "state-of-the-art"]):
        labels.extend(["positive_evaluation", "sota_evaluation"])
        keywords.extend(["state-of-the-art", "advanced", "outperform", "正向", "最先进"])
        instructions.append("寻找明确正向评价、state-of-the-art、advanced、outperform 等证据。")
    if not labels:
        labels = ["positive_evaluation", "large_context"]
        keywords = [text] if text else []
        instructions = [f"根据用户需求“{text}”寻找可用于汇报的强引用证据。"]
    primary = labels[0]
    return normalize_template({
        "id": f"custom_{primary}",
        "name": text or "自定义模板",
        "description": f"用户自定义需求：{text}",
        "target_labels": labels,
        "positive_keywords": keywords,
        "prompt_instruction": " ".join(instructions),
    })


def build_template_prompt_fragment(templates: list[dict[str, Any]]) -> str:
    normalized = [normalize_template(item) for item in templates if item]
    if not normalized:
        return ""
    lines = ["用户本次特别关注以下引用证据模板："]
    for item in normalized:
        labels = ", ".join(item["target_labels"]) or "-"
        keywords = ", ".join(item["positive_keywords"][:12]) or "-"
        lines.append(f"- {item['name']}：标签={labels}；关键词={keywords}；要求={item['prompt_instruction']}")
    return "\n".join(lines)
```

- [ ] **Step 5: Run template tests**

Run:

```bash
python3 -m unittest tests.test_scholar_evidence_templates -q
```

Expected: pass.

### Task 2: Refine Evidence Labels, Keywords, And Scoring

**Files:**

- Modify: `skills/scholar_impact_analyzer/scholar_evidence.py`
- Test: `tests/test_scholar_evidence.py`

- [ ] **Step 1: Add failing tests for refined labels**

Extend `tests/test_scholar_evidence.py` with:

```python
    def test_derive_labels_detects_ppt_highlight_categories(self):
        finding = {
            "citation_text": (
                "Ning et al. is the state-of-the-art Moire-guided method. "
                "We compare our system with their representative 6-DoF pose estimation work."
            ),
            "stance": "positive",
            "aspect": "comparison",
            "evidence_labels": [],
        }

        labels = self.evidence.derive_evidence_labels(
            finding,
            citation_char_count=len(finding["citation_text"]),
            person_tag_labels=["IEEE Fellow"],
        )

        self.assertIn("positive_evaluation", labels)
        self.assertIn("sota_evaluation", labels)
        self.assertIn("representative_work", labels)
        self.assertIn("detailed_comparison", labels)
        self.assertIn("important_person", labels)

    def test_score_prioritizes_non_self_ppt_highlight(self):
        score = self.evidence.score_strong_evidence(
            labels=[
                "sota_evaluation",
                "representative_work",
                "detailed_comparison",
                "important_person",
            ],
            confidence=0.9,
            citation_char_count=420,
            person_tag_labels=["IEEE Fellow"],
            self_citation_status="non_self_citation",
        )

        self.assertGreaterEqual(score, 85)
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
python3 -m unittest tests.test_scholar_evidence -q
```

Expected: fail because refined labels are not recognized.

- [ ] **Step 3: Update label constants**

Add the refined labels from section 5 to `VALID_EVIDENCE_LABELS`, `LABEL_DISPLAY_NAMES`, and `KEYWORD_PATTERNS`. Keep old labels.

- [ ] **Step 4: Update label derivation**

Update `derive_evidence_labels()` so that:

- `aspect == "comparison"` adds `comparison` and `detailed_comparison`;
- text containing `state-of-the-art`, `sota`, `advanced`, `leading`, `最先进` adds `sota_evaluation`;
- text containing `representative`, `only`, `unique`, `canonical`, `代表性`, `唯一` adds `representative_work`;
- text containing `extend`, `adapt`, `generalize`, `拓展`, `迁移` adds `method_extension`;
- long citation remains `large_context`;
- important person logic remains intact.

- [ ] **Step 5: Update score weights**

Use weights that favor reportable third-party evidence:

```python
weights = {
    "sota_evaluation": 24,
    "representative_work": 22,
    "first_or_pioneering": 24,
    "detailed_comparison": 22,
    "baseline": 18,
    "theory_foundation": 18,
    "method_foundation": 16,
    "method_extension": 16,
    "large_context": 12,
    "important_person": 18,
    "positive_evaluation": 18,
    "review_comment_praise": 16,
    "negative_or_limitation": 8,
    "survey_or_related_work": 4,
}
```

- [ ] **Step 6: Run evidence tests**

Run:

```bash
python3 -m unittest tests.test_scholar_evidence -q
```

Expected: pass.

### Task 3: Add Collaborator And Group Exclusion Profile

**Files:**

- Modify: `skills/scholar_impact_analyzer/scholar_evidence.py`
- Modify: `skills/scholar_impact_analyzer/scholar_stats.py`
- Modify: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Modify: `app/services/scholar_core.py`
- Modify: `app/main.py`
- Modify: `app/templates/scholar_session.html`
- Test: `tests/test_scholar_evidence.py`
- Test: `tests/test_scholar_stats.py`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Add tests for exclusion-aware citation classification**

Add to `tests/test_scholar_evidence.py`:

```python
    def test_classify_third_party_citation_marks_extra_excluded_author(self):
        result = self.evidence.classify_third_party_citation(
            source_authors=["Jingyi Ning"],
            citing_authors=["Lei Xie", "External Author"],
            selected_author_names=["Jingyi Ning"],
            extra_excluded_authors=["Lei Xie"],
            extra_excluded_affiliations=[],
            citing_affiliations=[],
        )

        self.assertEqual(result["status"], "excluded_collaborator")
        self.assertEqual(result["overlap_authors"], ["Lei Xie"])

    def test_classify_third_party_citation_marks_non_self_when_no_exclusion_matches(self):
        result = self.evidence.classify_third_party_citation(
            source_authors=["Jingyi Ning"],
            citing_authors=["External Author"],
            selected_author_names=["Jingyi Ning"],
            extra_excluded_authors=["Lei Xie"],
            extra_excluded_affiliations=["Nanjing University"],
            citing_affiliations=["University of Example"],
        )

        self.assertEqual(result["status"], "non_self_citation")
```

- [ ] **Step 2: Implement `classify_third_party_citation()`**

In `scholar_evidence.py`, add:

```python
def classify_third_party_citation(
    *,
    source_authors: list[Any] | None,
    citing_authors: list[Any] | None,
    selected_author_names: list[Any] | None = None,
    extra_excluded_authors: list[Any] | None = None,
    extra_excluded_affiliations: list[Any] | None = None,
    citing_affiliations: list[Any] | None = None,
) -> dict[str, Any]:
    source_names = expand_author_names(source_authors)
    selected_names = expand_author_names(selected_author_names)
    extra_names = expand_author_names(extra_excluded_authors)
    citing_names = expand_author_names(citing_authors)
    if not citing_names:
        return {"status": "unknown", "overlap_authors": [], "overlap_affiliations": []}

    selected_or_source_signatures = set()
    for author in source_names + selected_names:
        selected_or_source_signatures.update(name_signatures(author))
    extra_signatures = set()
    for author in extra_names:
        extra_signatures.update(name_signatures(author))

    self_hits = []
    collaborator_hits = []
    for author in citing_names:
        signatures = name_signatures(author)
        if selected_or_source_signatures and signatures & selected_or_source_signatures:
            self_hits.append(author)
        elif extra_signatures and signatures & extra_signatures:
            collaborator_hits.append(author)

    if self_hits:
        return {
            "status": "self_citation",
            "overlap_authors": unique_nonempty_strings(self_hits),
            "overlap_affiliations": [],
        }
    if collaborator_hits:
        return {
            "status": "excluded_collaborator",
            "overlap_authors": unique_nonempty_strings(collaborator_hits),
            "overlap_affiliations": [],
        }

    excluded_affiliations = [
        normalize_name(value) for value in (extra_excluded_affiliations or []) if normalize_name(value)
    ]
    citing_affiliation_hits = []
    for affiliation in citing_affiliations or []:
        normalized = normalize_name(str(affiliation or ""))
        if normalized and any(item and item in normalized for item in excluded_affiliations):
            citing_affiliation_hits.append(str(affiliation))
    if citing_affiliation_hits:
        return {
            "status": "excluded_collaborator",
            "overlap_authors": [],
            "overlap_affiliations": unique_nonempty_strings(citing_affiliation_hits),
        }
    return {"status": "non_self_citation", "overlap_authors": [], "overlap_affiliations": []}
```

When implementing, simplify the signature-set logic if needed, but keep the output contract:

- `self_citation`
- `excluded_collaborator`
- `non_self_citation`
- `unknown`

- [ ] **Step 3: Wire exclusion profile into queue building**

In `scholar_stats.build_deep_analysis_queue()`, read:

```python
exclusion_profile = session.get("exclusion_profile") or {}
extra_excluded_authors = exclusion_profile.get("extra_excluded_authors") or []
extra_excluded_affiliations = exclusion_profile.get("extra_excluded_affiliations") or []
```

Use `classify_third_party_citation()` instead of `classify_edge_self_citation()` for queue items. Keep old self-citation fields but add:

```json
{
  "third_party_status": "non_self_citation",
  "excluded_overlap_authors": [],
  "excluded_overlap_affiliations": []
}
```

Ranking rule:

- `third_party_status == "non_self_citation"`: add 6 points.
- `third_party_status == "self_citation"`: subtract 18 points.
- `third_party_status == "excluded_collaborator"`: subtract 12 points.
- `third_party_status == "unknown"`: no bonus.

Reasons:

- `third_party:non_self`
- `third_party:self`
- `third_party:excluded_collaborator`
- `third_party:unknown`

- [ ] **Step 4: Add session update service**

In `app/services/scholar_core.py`, add:

```python
def update_scholar_exclusion_profile(
    session_id: str,
    *,
    extra_excluded_authors_text: str,
    extra_excluded_affiliations_text: str,
    exclude_selected_author: bool = True,
    exclude_source_paper_authors: bool = True,
) -> dict[str, Any]:
    session = load_scholar_session(session_id)
    session["exclusion_profile"] = {
        "exclude_selected_author": bool(exclude_selected_author),
        "exclude_source_paper_authors": bool(exclude_source_paper_authors),
        "extra_excluded_authors": parse_multiline_values(extra_excluded_authors_text),
        "extra_excluded_affiliations": parse_multiline_values(extra_excluded_affiliations_text),
    }
    rebuilt = scholar_pipeline().rebuild_scholar_derived_outputs(session)
    write_scholar_session(session_id, rebuilt)
    return rebuilt
```

If helper names differ, use existing session read/write helpers in `scholar_core.py`.

- [ ] **Step 5: Add web route and form**

In `app/main.py`, add POST route:

```python
@app.post("/scholars/{session_id}/exclusion-profile")
def update_scholar_exclusion_profile_route(
    session_id: str,
    extra_excluded_authors: str = Form(""),
    extra_excluded_affiliations: str = Form(""),
    exclude_selected_author: str | None = Form(None),
    exclude_source_paper_authors: str | None = Form(None),
):
    scholar_core.update_scholar_exclusion_profile(
        session_id,
        extra_excluded_authors_text=extra_excluded_authors,
        extra_excluded_affiliations_text=extra_excluded_affiliations,
        exclude_selected_author=exclude_selected_author == "on",
        exclude_source_paper_authors=exclude_source_paper_authors == "on",
    )
    return RedirectResponse(f"/scholars/{session_id}#exclusion-profile", status_code=303)
```

In `app/templates/scholar_session.html`, add an "排除作者/本组作者" section with:

- checkbox: exclude selected scholar;
- checkbox: exclude source paper authors;
- textarea: collaborator/group authors, one per line;
- textarea: group affiliations, one per line;
- submit button: "保存排除配置并重建队列".

- [ ] **Step 6: Add web tests**

Add to `tests/test_scholar_web.py`:

```python
def test_scholar_route_renders_exclusion_profile_form(self):
    response = client.get(f"/scholars/{session_id}")
    self.assertIn("排除作者", response.text)
    self.assertIn("本组作者", response.text)

def test_update_exclusion_profile_redirects_to_section(self):
    response = client.post(
        f"/scholars/{session_id}/exclusion-profile",
        data={
            "exclude_selected_author": "on",
            "exclude_source_paper_authors": "on",
            "extra_excluded_authors": "Lei Xie\nChuyu Wang",
            "extra_excluded_affiliations": "Nanjing University",
        },
        follow_redirects=False,
    )
    self.assertEqual(response.status_code, 303)
    self.assertIn("#exclusion-profile", response.headers["location"])
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_scholar_evidence tests.test_scholar_stats tests.test_scholar_web -q
```

Expected: pass.

### Task 4: Pass Custom Templates Into Fulltext Analysis

**Files:**

- Modify: `skills/analyze_fulltext_citation/analyze_fulltext.py`
- Modify: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Test: `tests/test_analyze_fulltext.py`
- Test: `tests/test_scholar_pipeline.py`

- [ ] **Step 1: Update fulltext analyzer API tests**

Add a test in `tests/test_analyze_fulltext.py` that calls the analyzer prompt builder or request builder with a template prompt fragment and asserts the final prompt contains:

```text
用户本次特别关注以下引用证据模板
first_or_pioneering
detailed_comparison
```

If there is no public prompt-builder function, add a small helper function first:

```python
def build_analysis_instruction(template_prompt_fragment: str = "") -> str:
    if not template_prompt_fragment:
        return SINGLE_MODEL_SYSTEM_PROMPT
    return SINGLE_MODEL_SYSTEM_PROMPT + "\n\n" + template_prompt_fragment
```

- [ ] **Step 2: Extend analyzer schema**

Update prompt JSON schema labels to include:

```text
sota_evaluation
representative_work
detailed_comparison
method_extension
sustained_followup
review_comment_praise
```

Update rules so the model knows:

- SOTA requires explicit original text.
- Representative work requires "representative", "only", "unique", or equivalent.
- Detailed comparison requires experiment/table/evaluation comparison, not a single related-work sentence.
- Template requests are priority signals; they do not override evidence quality.

- [ ] **Step 3: Pass templates from scholar session**

In `scholar_pipeline.analyze_scholar_queue()`, load active templates from session:

```python
template_prompt_fragment = EVIDENCE_TEMPLATES.build_template_prompt_fragment(
    session.get("analysis_templates", {}).get("compiled_templates") or []
)
```

Pass this into the fulltext analyzer call using a new optional argument, for example:

```python
analysis = RUN_PIPELINE.ANALYZE_FULLTEXT.analyze_pdf_citation(
    ...,
    template_prompt_fragment=template_prompt_fragment,
)
```

If the existing analyzer function names differ, add the optional parameter at the narrowest wrapper layer used by scholar analysis.

- [ ] **Step 4: Update strong evidence normalization**

Ensure new evidence labels survive `normalize_model_finding()` and `normalize_strong_evidence()`.

- [ ] **Step 5: Run analyzer and pipeline tests**

Run:

```bash
python3 -m unittest tests.test_analyze_fulltext tests.test_scholar_pipeline -q
```

Expected: pass.

### Task 5: Add Template Configuration UI

**Files:**

- Modify: `app/services/scholar_core.py`
- Modify: `app/main.py`
- Modify: `app/templates/scholar_session.html`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Add service for template updates**

In `scholar_core.py`, add:

```python
def update_scholar_analysis_templates(
    session_id: str,
    *,
    active_template_ids: list[str],
    custom_requests_text: str,
) -> dict[str, Any]:
    templates_module = scholar_pipeline().EVIDENCE_TEMPLATES
    session = load_scholar_session(session_id)
    builtin = templates_module.load_builtin_templates()
    builtin_by_id = {item["id"]: item for item in builtin}
    custom_requests = parse_multiline_values(custom_requests_text)
    compiled = [
        builtin_by_id[item]
        for item in active_template_ids
        if item in builtin_by_id
    ]
    compiled.extend(
        templates_module.compile_custom_request(item)
        for item in custom_requests
    )
    session["analysis_templates"] = {
        "active_template_ids": active_template_ids,
        "custom_requests": custom_requests,
        "compiled_templates": compiled,
    }
    write_scholar_session(session_id, session)
    return session
```

- [ ] **Step 2: Add POST route**

In `app/main.py`, add:

```python
@app.post("/scholars/{session_id}/analysis-templates")
def update_scholar_analysis_templates_route(
    session_id: str,
    template_ids: list[str] = Form([]),
    custom_requests: str = Form(""),
):
    scholar_core.update_scholar_analysis_templates(
        session_id,
        active_template_ids=template_ids,
        custom_requests_text=custom_requests,
    )
    return RedirectResponse(f"/scholars/{session_id}#analysis-templates", status_code=303)
```

- [ ] **Step 3: Render template UI**

In `scholar_session.html`, add section "分析模板":

- preset checkboxes:
  - PPT 亮点评价;
  - 首次 / 开创性评价;
  - 大量 / 详细实验比较;
  - 理论 / 模型基础;
  - 方法来源 / 方法拓展;
- textarea for one custom request per line;
- compiled template preview showing target labels and keywords;
- note: "模板会影响后续全文分析，不会改写已完成的强引用证据；如需重跑，请重新分析对应队列项。"

- [ ] **Step 4: Add web tests**

Add tests asserting:

- page renders "分析模板";
- posting selected template IDs stores them in session;
- posting custom text compiles labels.

- [ ] **Step 5: Run web tests**

Run:

```bash
python3 -m unittest tests.test_scholar_web -q
```

Expected: pass.

### Task 6: Generate PPT-Ready Highlight Cards

**Files:**

- Modify: `app/services/scholar_core.py`
- Modify: `app/templates/scholar_session.html`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Add card builder tests**

Add tests for `build_highlight_cards(session)`:

```python
def test_build_highlight_cards_groups_reportable_evidence(self):
    session = {
        "selected_author": {"display_name": "Jingyi Ning"},
        "strong_evidence": [
            {
                "citing_title": "MoiréTag",
                "citing_venue": "SIGGRAPH",
                "citing_year": 2023,
                "cited_publication_title": "MoiréPose",
                "citation_text": "the state-of-the-art Moiré-guided method [Ning et al. 2022]",
                "evidence_labels": ["sota_evaluation", "detailed_comparison", "important_person"],
                "evidence_label_names": ["最先进 / SOTA", "详细对比", "重要人物引用"],
                "highlight_keywords": ["state-of-the-art"],
                "person_tag_labels": ["IEEE Fellow"],
                "self_citation_status": "non_self_citation",
                "strong_citation_score": 94,
                "why_valuable": "可作为高水平同行正向评价。",
            }
        ],
    }

    cards = scholar_core.build_highlight_cards(session)

    self.assertEqual(len(cards), 1)
    self.assertIn("IEEE Fellow", cards[0]["headline"])
    self.assertIn("state-of-the-art", cards[0]["evidence_excerpt"])
    self.assertIn("汇报句", cards[0]["report_sentence_label"])
```

- [ ] **Step 2: Implement card builder**

In `scholar_core.py`, add:

```python
def build_highlight_cards(session: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    evidence_items = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    reportable = [
        item for item in evidence_items
        if (item.get("self_citation_status") or "unknown") == "non_self_citation"
        and (item.get("strong_citation_score") or 0) >= 45
    ]
    reportable = sorted(
        reportable,
        key=lambda item: (
            -(item.get("strong_citation_score") or 0),
            -len(item.get("evidence_labels") or []),
            item.get("citing_title") or "",
        ),
    )
    cards = []
    for index, item in enumerate(reportable[:limit], 1):
        labels = item.get("evidence_label_names") or item.get("evidence_labels") or []
        important = ", ".join(item.get("person_tag_labels") or [])
        citing_title = item.get("citing_title") or "未知引用论文"
        target_title = item.get("cited_publication_title") or "目标论文"
        label_text = "、".join(labels[:4]) or "强引用证据"
        if important:
            headline = f"{important} 团队引用并评价 {target_title}"
        else:
            headline = f"{citing_title} 引用并评价 {target_title}"
        report_sentence = (
            f"{citing_title} 将 {target_title} 作为{label_text}证据，"
            f"原文显示：{str(item.get('citation_text') or '').strip()[:160]}"
        )
        cards.append({
            "index": index,
            "headline": headline,
            "citing_title": citing_title,
            "citing_venue": item.get("citing_venue") or "",
            "citing_year": item.get("citing_year") or "",
            "target_title": target_title,
            "labels": labels,
            "score": item.get("strong_citation_score") or 0,
            "self_citation_status": item.get("self_citation_status") or "unknown",
            "important_person": important,
            "evidence_excerpt": item.get("citation_text") or "",
            "highlight_keywords": item.get("highlight_keywords") or [],
            "why_valuable": item.get("why_valuable") or item.get("valuable_reason") or "",
            "report_sentence_label": "汇报句",
            "report_sentence": report_sentence,
        })
    return cards
```

- [ ] **Step 3: Render cards in page**

Add "亮点评价卡片" section before or after "强引用证据":

- show headline;
- show chips for labels and important-person tags;
- show original excerpt with highlights;
- show generated Chinese report sentence;
- show source paper and target paper.

- [ ] **Step 4: Run web tests**

Run:

```bash
python3 -m unittest tests.test_scholar_web -q
```

Expected: pass.

### Task 7: Export Highlight Cards CSV And Markdown

**Files:**

- Modify: `app/services/scholar_core.py`
- Modify: `app/main.py`
- Modify: `app/templates/scholar_session.html`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Add export service tests**

Add tests asserting CSV includes columns:

```text
index,headline,citing_title,citing_venue,citing_year,target_title,labels,score,self_citation_status,important_person,evidence_excerpt,highlight_keywords,why_valuable,report_sentence
```

And Markdown includes:

```text
## 亮点评价卡片
### 1.
原文证据
汇报句
```

- [ ] **Step 2: Implement export writers**

Add:

```python
def write_highlight_cards_csv(session_id: str) -> Path:
    session = load_scholar_session(session_id)
    cards = build_highlight_cards(session)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "highlight_cards.csv"
    # use csv.DictWriter with stable fieldnames
    return path


def write_highlight_cards_markdown(session_id: str) -> Path:
    session = load_scholar_session(session_id)
    cards = build_highlight_cards(session)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "highlight_cards.md"
    # write one card per section
    return path
```

- [ ] **Step 3: Add download routes**

Add:

```python
@app.get("/scholars/{session_id}/exports/highlight-cards.csv")
def download_highlight_cards_csv(session_id: str):
    path = scholar_core.write_highlight_cards_csv(session_id)
    return FileResponse(path, media_type="text/csv", filename="highlight_cards.csv")


@app.get("/scholars/{session_id}/exports/highlight-cards.md")
def download_highlight_cards_markdown(session_id: str):
    path = scholar_core.write_highlight_cards_markdown(session_id)
    return FileResponse(path, media_type="text/markdown", filename="highlight_cards.md")
```

- [ ] **Step 4: Add page links**

In `scholar_session.html`, add export links near report exports:

- "导出亮点评价 CSV"
- "导出亮点评价 Markdown"

- [ ] **Step 5: Run route tests**

Run:

```bash
python3 -m unittest tests.test_scholar_web -q
```

Expected: pass.

### Task 8: Add Sustained Follow-Up / Team Aggregation

**Files:**

- Modify: `app/services/scholar_core.py`
- Modify: `skills/scholar_impact_analyzer/scholar_evidence.py`
- Test: `tests/test_scholar_web.py`
- Test: `tests/test_scholar_evidence.py`

- [ ] **Step 1: Add tests for sustained follow-up**

Create a session with two or more strong evidence records sharing the same important author or same normalized first author, then assert the cards include `sustained_followup`.

- [ ] **Step 2: Implement grouping**

In `build_highlight_cards()`, before scoring cards:

- group evidence by `person_tag_matched_authors`, `citing_authors`, or normalized first important author;
- if the same group has at least 2 non-self strong evidence records, add `sustained_followup` to each card's labels;
- add a group summary field:

```json
{
  "followup_group": "Wolfgang Heidrich",
  "followup_count": 2,
  "followup_titles": ["MoiréTag", "QR-Tag"]
}
```

- [ ] **Step 3: Render group summary**

Page text:

```text
持续跟踪引用：Wolfgang Heidrich 团队共有 2 篇引用论文命中高质量证据。
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_scholar_web tests.test_scholar_evidence -q
```

Expected: pass.

### Task 9: Add Review Comment Import As Optional Evidence Source

**Files:**

- Modify: `app/services/scholar_core.py`
- Modify: `app/main.py`
- Modify: `app/templates/scholar_session.html`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Add service tests for review comment evidence**

Input:

```text
The state-of-the-art work in moiré pattern-based perception technology.
The first work to derive a fundamental and systematic framework.
```

Expected:

- creates strong evidence entries with `source_type == "review_comment"`;
- labels include `review_comment_praise`, `sota_evaluation`, `first_or_pioneering`;
- cards include these entries if score is high.

- [ ] **Step 2: Implement import service**

Add:

```python
def import_review_comment_evidence(session_id: str, text: str) -> dict[str, Any]:
    session = load_scholar_session(session_id)
    snippets = split_review_comment_snippets(text)
    evidence = []
    for snippet in snippets:
        labels = scholar_pipeline().SCHOLAR_EVIDENCE.derive_evidence_labels(
            {
                "citation_text": snippet,
                "stance": "positive",
                "aspect": "other",
                "evidence_labels": ["review_comment_praise"],
            },
            citation_char_count=len(snippet),
            person_tag_labels=[],
        )
        evidence.append({
            "source_type": "review_comment",
            "citing_title": "审稿意见",
            "cited_publication_title": session.get("selected_author", {}).get("display_name") or "目标工作",
            "citation_text": snippet,
            "evidence_labels": labels,
            "evidence_label_names": [scholar_pipeline().SCHOLAR_EVIDENCE.evidence_label_display(label) for label in labels],
            "highlight_keywords": scholar_pipeline().SCHOLAR_EVIDENCE.derive_highlight_keywords({"citation_text": snippet}, labels),
            "self_citation_status": "non_self_citation",
            "strong_citation_score": scholar_pipeline().SCHOLAR_EVIDENCE.score_strong_evidence(
                labels=labels,
                confidence=0.95,
                citation_char_count=len(snippet),
                person_tag_labels=[],
                self_citation_status="non_self_citation",
            ),
            "why_valuable": "审稿意见中的正向亮点评价，可作为补充评价材料。",
        })
    session["strong_evidence"] = scholar_pipeline().deduplicate_strong_evidence(
        (session.get("strong_evidence") or []) + evidence
    )
    write_scholar_session(session_id, session)
    return session
```

- [ ] **Step 3: Add route and UI**

Add section "审稿意见 / 外部评价导入":

- textarea;
- submit button;
- note: "该材料不是引用论文，系统会单独标注来源。"

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m unittest tests.test_scholar_web -q
```

Expected: pass.

## 8. Validation Plan

Run all focused tests after each task. After all tasks:

```bash
python3 -m unittest discover tests
```

Manual validation with a real scholar session:

1. Start server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

2. Open an existing scholar session for Jingyi Ning or create a fresh one.
3. Configure templates:
   - PPT 亮点评价
   - 大量 / 详细实验比较
   - 理论 / 模型基础
4. Configure exclusion authors:
   - Jingyi Ning
   - Lei Xie
   - Chuyu Wang
   - Yanling Bu
   - Baoliu Ye
   - Sanglu Lu
5. Rebuild queue.
6. Analyze several high-value queue items with PDFs.
7. Confirm strong evidence labels include:
   - SOTA;
   - 代表性工作;
   - 详细对比;
   - 方法/理论基础;
   - 重要人物引用.
8. Export `highlight_cards.csv` and `highlight_cards.md`.
9. Confirm exported cards are close to the reference PPT wording.

## 9. Rollout Order

Recommended implementation sequence:

1. Task 1: templates module.
2. Task 2: refined labels.
3. Task 3: exclusion profile.
4. Task 4: analyzer template propagation.
5. Task 5: template UI.
6. Task 6: highlight cards.
7. Task 7: exports.
8. Task 8: sustained follow-up aggregation.
9. Task 9: review comment import.

This order keeps every step independently testable. The first seven tasks deliver the main mentor-facing workflow. Tasks 8 and 9 are strong additions for matching the MoiréPose reference PPT, but can be postponed if the immediate goal is a demo.

## 10. Acceptance Criteria

The feature is complete when:

- Users can choose built-in templates and enter custom requests such as "找首次评价".
- Users can configure collaborator/group exclusion authors and affiliations.
- High-value queue marks third-party, self, collaborator-excluded, and unknown cases.
- Strong evidence supports refined PPT-oriented labels.
- Fulltext analysis prompt receives the active templates.
- The page shows highlight evidence cards with original evidence text and generated Chinese report sentences.
- Users can export highlight cards as CSV and Markdown.
- Existing sessions still load without migration errors.
- `python3 -m unittest discover tests` passes.

## 11. Remaining Risks

- Natural-language template compilation is deterministic and keyword-based in this plan. It will not understand every possible user request, but it avoids adding another LLM dependency to configure the analyzer.
- Collaborator exclusion by affiliation can over-filter if the affiliation string is broad. The UI must show what was excluded so users can tune the list.
- "首次评价" is still text-evidence based unless we add chronological validation. For this phase, the label means the citing paper says "first/pioneering"; it does not prove globally first.
- Sustained follow-up grouping is name-based unless external IDs are available. It should be treated as report guidance, not a formal bibliometric identity proof.
