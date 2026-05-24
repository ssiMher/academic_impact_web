from __future__ import annotations

import json
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


def load_builtin_templates(path: Path | str = DEFAULT_TEMPLATE_PATH) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [normalize_template(item) for item in data if isinstance(item, dict)]


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
        lines.append(
            f"- {item['name']}：标签={labels}；关键词={keywords}；要求={item['prompt_instruction']}"
        )
    return "\n".join(lines)
