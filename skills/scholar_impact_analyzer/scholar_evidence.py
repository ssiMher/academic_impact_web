from __future__ import annotations

import re
from typing import Any


VALID_EVIDENCE_LABELS = {
    "positive_evaluation",
    "first_or_pioneering",
    "baseline",
    "comparison",
    "method_foundation",
    "theory_foundation",
    "large_context",
    "survey_or_related_work",
    "negative_or_limitation",
    "important_person",
}

LABEL_DISPLAY_NAMES = {
    "positive_evaluation": "正向评价",
    "first_or_pioneering": "首次/开创性评价",
    "baseline": "作为基线",
    "comparison": "实验对比",
    "method_foundation": "方法基础",
    "theory_foundation": "理论基础",
    "large_context": "大篇幅引用",
    "survey_or_related_work": "综述/相关工作",
    "negative_or_limitation": "负面或局限评价",
    "important_person": "重要人物引用",
}

KEYWORD_PATTERNS = {
    "positive_evaluation": [
        "outperform",
        "improve",
        "improves",
        "effective",
        "efficient",
        "influential",
        "important",
        "significant",
        "成功",
        "有效",
        "重要",
    ],
    "first_or_pioneering": [
        "first",
        "pioneer",
        "pioneering",
        "seminal",
        "original",
        "首次",
        "开创",
        "奠基",
    ],
    "baseline": ["baseline", "baselines", "compare against", "compared with", "基线"],
    "comparison": ["compare", "comparison", "compared", "versus", "vs.", "对比", "比较"],
    "method_foundation": [
        "based on",
        "build on",
        "builds on",
        "follow",
        "following",
        "adopt",
        "use",
        "inspired by",
        "基于",
        "采用",
        "借鉴",
    ],
    "theory_foundation": ["theory", "theoretical", "proof", "lemma", "定理", "理论", "证明"],
    "negative_or_limitation": ["limitation", "limited", "fail", "worse", "不足", "局限", "失败"],
}

AUTHOR_LIST_SEPARATOR_PATTERN = re.compile(r"\s*(?:;|；|\||、|\band\b)\s*")


def normalize_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def name_signatures(value: str) -> set[str]:
    text = str(value or "").strip().lower()
    direct = normalize_name(text)
    tokens = [token for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if token]
    signatures = {direct} if direct else set()
    if len(tokens) > 1:
        signatures.add("".join(sorted(tokens)))
    return signatures


def unique_nonempty_strings(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def author_text(value: Any) -> str:
    if isinstance(value, dict):
        return (
            value.get("name")
            or value.get("display_name")
            or value.get("text")
            or value.get("#text")
            or ""
        )
    return str(value or "")


def expand_author_names(values: Any) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, list) else [values]
    expanded = []
    for value in raw_values:
        text = author_text(value).strip()
        if not text:
            continue
        parts = [
            part.strip()
            for part in AUTHOR_LIST_SEPARATOR_PATTERN.split(text)
            if part.strip()
        ]
        expanded.extend(parts or [text])
    return unique_nonempty_strings(expanded)


def classify_self_citation(
    source_authors: list[Any] | None,
    citing_authors: list[Any] | None,
) -> dict[str, Any]:
    source_signatures = set()
    citing_signatures_by_author: dict[str, set[str]] = {}
    for author in expand_author_names(source_authors):
        source_signatures.update(name_signatures(str(author or "")))
    for author in expand_author_names(citing_authors):
        author_text = str(author or "")
        citing_signatures_by_author[author_text] = name_signatures(author_text)
    if not source_signatures or not citing_signatures_by_author:
        return {"status": "unknown", "overlap_authors": []}
    overlap_authors = [
        author
        for author, signatures in citing_signatures_by_author.items()
        if source_signatures & signatures
    ]
    if not overlap_authors:
        return {"status": "non_self_citation", "overlap_authors": []}
    return {
        "status": "self_citation",
        "overlap_authors": unique_nonempty_strings(overlap_authors),
    }


def coerce_labels(value: Any) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    labels = []
    for item in raw_values:
        label = str(item or "").strip()
        if label in VALID_EVIDENCE_LABELS and label not in labels:
            labels.append(label)
    return labels


def derive_evidence_labels(
    finding: dict[str, Any],
    *,
    citation_char_count: int,
    person_tag_labels: list[str] | None = None,
) -> list[str]:
    labels = coerce_labels(finding.get("evidence_labels"))
    aspect = str(finding.get("aspect") or "").strip()
    stance = str(finding.get("stance") or "").strip().lower()
    text = str(finding.get("citation_text") or "").lower()
    person_tags = person_tag_labels or []

    if stance == "positive":
        labels.append("positive_evaluation")
    if aspect == "baseline":
        labels.append("baseline")
    if aspect == "comparison":
        labels.append("comparison")
    if aspect in {"method", "extension", "application"}:
        labels.append("method_foundation")
    if aspect == "background":
        labels.append("survey_or_related_work")
    if stance == "negative":
        labels.append("negative_or_limitation")
    if citation_char_count >= 300:
        labels.append("large_context")
    if any("Fellow" in label or "院士" in label or "Turing" in label or "Prize" in label for label in person_tags):
        labels.append("important_person")

    for label, patterns in KEYWORD_PATTERNS.items():
        if any(pattern.lower() in text for pattern in patterns):
            labels.append(label)

    return [label for label in VALID_EVIDENCE_LABELS if label in set(labels)]


def derive_highlight_keywords(
    finding: dict[str, Any],
    labels: list[str],
) -> list[str]:
    keywords = unique_nonempty_strings(finding.get("highlight_keywords") or [])
    text = str(finding.get("citation_text") or "")
    lower_text = text.lower()
    for label in labels:
        for pattern in KEYWORD_PATTERNS.get(label, []):
            if pattern.lower() in lower_text:
                keywords.append(pattern)
    return unique_nonempty_strings(keywords)[:12]


def evidence_strength(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def score_strong_evidence(
    *,
    labels: list[str],
    confidence: Any,
    citation_char_count: int,
    person_tag_labels: list[str] | None,
    self_citation_status: str,
) -> int:
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.6
    confidence_value = min(max(confidence_value, 0.0), 1.0)
    score = int(round(confidence_value * 20))

    weights = {
        "positive_evaluation": 18,
        "first_or_pioneering": 24,
        "baseline": 18,
        "comparison": 18,
        "method_foundation": 14,
        "theory_foundation": 14,
        "large_context": 10,
        "important_person": 18,
        "negative_or_limitation": 8,
        "survey_or_related_work": 4,
    }
    for label in labels:
        score += weights.get(label, 0)
    if citation_char_count >= 100:
        score += 6
    if person_tag_labels:
        score += 4
    if self_citation_status == "non_self_citation":
        score += 6
    elif self_citation_status == "self_citation":
        score -= 18
    return min(max(score, 0), 100)


def evidence_label_display(label: str) -> str:
    return LABEL_DISPLAY_NAMES.get(label, label)


def highlight_excerpt_html(text: str, keywords: list[str]) -> str:
    escaped = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    for keyword in sorted(unique_nonempty_strings(keywords), key=len, reverse=True):
        if not keyword:
            continue
        pattern = re.compile(re.escape(keyword), flags=re.IGNORECASE)
        escaped = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", escaped)
    return escaped
