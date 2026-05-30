from __future__ import annotations

import re
from typing import Any


VALID_EVIDENCE_LABELS = (
    "positive_evaluation",
    "sota_evaluation",
    "first_or_pioneering",
    "representative_work",
    "large_context",
    "detailed_comparison",
    "baseline",
    "comparison",
    "method_foundation",
    "method_extension",
    "theory_foundation",
    "sustained_followup",
    "important_person",
    "review_comment_praise",
    "survey_or_related_work",
    "negative_or_limitation",
)

LABEL_DISPLAY_NAMES = {
    "positive_evaluation": "正向评价",
    "sota_evaluation": "最先进 / SOTA",
    "first_or_pioneering": "首次 / 开创性",
    "representative_work": "代表性工作",
    "large_context": "大篇幅引用",
    "detailed_comparison": "详细对比",
    "baseline": "作为 Baseline",
    "comparison": "实验对比",
    "method_foundation": "方法来源",
    "method_extension": "方法拓展",
    "theory_foundation": "理论 / 公式基础",
    "sustained_followup": "持续跟踪引用",
    "important_person": "重要人物引用",
    "review_comment_praise": "审稿意见亮评",
    "survey_or_related_work": "综述/相关工作",
    "negative_or_limitation": "负面或局限评价",
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
    "sota_evaluation": [
        "state-of-the-art",
        "state of the art",
        "sota",
        "best",
        "advanced",
        "leading",
        "superior",
        "outperform",
        "outperforms",
        "最先进",
        "领先",
        "优越",
    ],
    "first_or_pioneering": [
        "first",
        "first work",
        "first use",
        "pioneer",
        "pioneering",
        "seminal",
        "original",
        "首次",
        "开创",
        "奠基",
    ],
    "representative_work": [
        "representative",
        "canonical",
        "typical",
        "unique",
        "only",
        "exemplar",
        "代表性",
        "典型",
        "唯一",
    ],
    "baseline": ["baseline", "baselines", "compare against", "compared with", "基线"],
    "comparison": ["compare", "comparison", "compared", "versus", "vs.", "对比", "比较"],
    "detailed_comparison": [
        "detailed comparison",
        "compare against",
        "compared with",
        "comparison",
        "evaluation",
        "experiment",
        "table",
        "ablation",
        "benchmark",
        "详细对比",
        "实验对比",
        "评估",
        "表",
    ],
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
    "method_extension": [
        "extend",
        "extends",
        "extended",
        "extension",
        "adapt",
        "adapts",
        "modified",
        "generalize",
        "generalizes",
        "拓展",
        "扩展",
        "改造",
        "泛化",
    ],
    "theory_foundation": ["theory", "theoretical", "proof", "lemma", "定理", "理论", "证明"],
    "sustained_followup": [
        "follow-up",
        "follow up",
        "subsequent work",
        "continued",
        "series of work",
        "持续",
        "后续工作",
        "跟踪",
    ],
    "review_comment_praise": [
        "reviewer",
        "review comment",
        "praised",
        "excellent",
        "highly novel",
        "审稿",
        "评审",
        "高度评价",
    ],
    "negative_or_limitation": ["limitation", "limited", "fail", "worse", "不足", "局限", "失败"],
}

AUTHOR_LIST_SEPARATOR_PATTERN = re.compile(r"\s*(?:;|；|\||、|\band\b)\s*")


def normalize_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def name_without_numeric_suffix(value: str) -> str:
    return re.sub(r"\s+\d{4}$", "", str(value or "").strip())


def name_signatures(value: str) -> set[str]:
    text = name_without_numeric_suffix(value).lower()
    direct = normalize_name(text)
    tokens = [token for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if token]
    signatures = {direct} if direct else set()
    if len(tokens) > 1:
        signatures.add("".join(sorted(tokens)))
    latin_tokens = [
        token
        for token in tokens
        if token.isascii() and token.isalpha()
    ]
    if len(latin_tokens) >= 2:
        given = latin_tokens[0]
        surname = latin_tokens[-1]
        if len(surname) > 1:
            signatures.add(f"{surname}{given[0]}")
            signatures.add(f"{given[0]}{surname}")
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


def _signature_index(values: list[Any] | None) -> set[str]:
    signatures: set[str] = set()
    for author in expand_author_names(values):
        signatures.update(name_signatures(author))
    return signatures


def classify_third_party_citation(
    *,
    source_authors: list[Any] | None,
    citing_authors: list[Any] | None,
    selected_author_names: list[Any] | None = None,
    extra_excluded_authors: list[Any] | None = None,
    extra_excluded_affiliations: list[Any] | None = None,
    citing_affiliations: list[Any] | None = None,
) -> dict[str, Any]:
    citing_names = expand_author_names(citing_authors)
    if not citing_names:
        return {
            "status": "unknown",
            "overlap_authors": [],
            "overlap_affiliations": [],
        }

    self_signatures = _signature_index(
        (source_authors or []) + (selected_author_names or [])
    )
    collaborator_signatures = _signature_index(extra_excluded_authors)

    self_hits = []
    collaborator_hits = []
    for author in citing_names:
        signatures = name_signatures(author)
        if self_signatures and signatures & self_signatures:
            self_hits.append(author)
        elif collaborator_signatures and signatures & collaborator_signatures:
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
        normalize_name(str(value or ""))
        for value in (extra_excluded_affiliations or [])
        if normalize_name(str(value or ""))
    ]
    affiliation_hits = []
    for affiliation in citing_affiliations or []:
        text = str(affiliation or "").strip()
        normalized = normalize_name(text)
        if normalized and any(excluded in normalized for excluded in excluded_affiliations):
            affiliation_hits.append(text)
    if affiliation_hits:
        return {
            "status": "excluded_collaborator",
            "overlap_authors": [],
            "overlap_affiliations": unique_nonempty_strings(affiliation_hits),
        }

    return {
        "status": "non_self_citation",
        "overlap_authors": [],
        "overlap_affiliations": [],
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
        labels.append("detailed_comparison")
    if aspect in {"method", "application"}:
        labels.append("method_foundation")
    if aspect == "extension":
        labels.append("method_extension")
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


def is_reportable_strong_evidence(item: dict[str, Any]) -> bool:
    """Return whether a finding belongs in the strong-evidence surface."""
    if item.get("keep") is False:
        return False
    if (item.get("mention_type") or "") in {
        "grouped_literature_mention",
        "weak_body_mention",
    }:
        return False
    score = item.get("strong_citation_score")
    labels = set(coerce_labels(item.get("evidence_labels")))
    if score is None:
        aspect = item.get("aspect") or ""
        stance = (item.get("stance") or "").lower()
        has_legacy_strong_signal = bool(
            item.get("fellow_strong_citation")
            or item.get("positive_evaluation")
            or item.get("long_context_100_chars")
            or stance == "positive"
            or aspect in {"method", "baseline", "comparison", "extension", "application"}
            or labels.difference({"survey_or_related_work"})
        )
        if not has_legacy_strong_signal:
            return False
        if aspect == "background" and not (
            item.get("fellow_strong_citation")
            or item.get("positive_evaluation")
            or stance == "positive"
            or labels.difference({"survey_or_related_work", "large_context"})
        ):
            return False
        return True
    try:
        score_value = int(score)
    except (TypeError, ValueError):
        score_value = 0
    if score_value < 45:
        return False
    if (item.get("evidence_strength") or "").lower() == "low":
        return False
    if labels and labels <= {"survey_or_related_work"}:
        return False
    if (
        (item.get("aspect") or "") == "background"
        and (item.get("stance") or "").lower() != "positive"
        and not labels.difference({"survey_or_related_work", "large_context"})
    ):
        return False
    return True


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
        "sota_evaluation": 24,
        "first_or_pioneering": 24,
        "representative_work": 18,
        "detailed_comparison": 22,
        "baseline": 18,
        "comparison": 18,
        "method_foundation": 14,
        "method_extension": 18,
        "theory_foundation": 14,
        "large_context": 10,
        "sustained_followup": 16,
        "important_person": 18,
        "review_comment_praise": 18,
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
    elif self_citation_status == "excluded_collaborator":
        score -= 12
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
