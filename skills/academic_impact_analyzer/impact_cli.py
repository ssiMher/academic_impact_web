import argparse
import csv
import importlib.util
import io
import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode


ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "skills"
DEFAULT_SESSIONS_DIR = ROOT / "data" / "sessions"
PERSON_TAG_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"
VENUE_TIER_REGISTRY_PATH = ROOT / "data" / "reference" / "venue_tiers.json"
SESSION_SCHEMA_VERSION = "1.0"
QUICK_ANALYSIS_VERSION = "1.0"
EVIDENCE_INDEX_VERSION = "1.0"
SESSION_DETAIL_PAYLOAD_VERSION = "1.0"

STOPWORD_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "using",
    "towards",
    "technical",
    "report",
    "analysis",
    "study",
    "paper",
    "papers",
    "model",
    "models",
    "approach",
    "method",
    "methods",
    "system",
    "systems",
    "ocr",
    "vl",
}

ANALYSIS_STATUS_LABELS = {
    "fulltext_analyzed": "全文分析完成",
    "mention_only": "弱提及",
    "reference_only": "仅参考文献命中",
    "fulltext_no_finding": "全文未发现可靠证据",
    "context_only": "仅上下文分析",
    "fulltext_extract_failed": "全文提取失败",
    "analysis_failed": "语义分析失败",
    "write_output_failed": "结果写出失败",
}

ASPECT_LABELS = {
    "background": "背景",
    "method": "方法采用",
    "baseline": "基线",
    "comparison": "比较对象",
    "extension": "扩展",
    "application": "应用",
    "other": "其他",
}

MENTION_TYPE_LABELS = {
    "explicit_citation": "明确引用",
    "grouped_literature_mention": "组引用/综述提及",
    "weak_body_mention": "弱正文提及",
}

STANCE_LABELS = {
    "positive": "正向",
    "neutral": "中性",
    "negative": "负向",
}

NUMBER_WORDS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

TOP_SCHOOL_RULES = [
    ("mit", "MIT", ["massachusetts institute of technology"]),
    ("cmu", "CMU", ["carnegie mellon university"]),
    ("stanford", "Stanford", ["stanford university"]),
    ("berkeley", "UC Berkeley", ["university of california berkeley", "uc berkeley", "berkeley"]),
    ("harvard", "Harvard", ["harvard university"]),
    ("princeton", "Princeton", ["princeton university"]),
    ("caltech", "Caltech", ["california institute of technology", "caltech"]),
    ("oxford", "Oxford", ["university of oxford", "oxford university"]),
    ("cambridge", "Cambridge", ["university of cambridge", "cambridge university"]),
    ("eth", "ETH Zurich", ["eth zurich", "swiss federal institute of technology zurich"]),
    ("epfl", "EPFL", ["epfl", "ecole polytechnique federale de lausanne"]),
]

STRONG_CLAIM_PATTERNS = [
    re.compile(pattern, flags=re.I)
    for pattern in [
        r"\bfor the first time\b",
        r"\bfirst\b",
        r"\bnovel\b",
        r"\bstate[- ]of[- ]the[- ]art\b",
        r"首次",
        r"首个",
        r"第一次",
    ]
]


def env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LIST_PAPERS = load_module(
    "impact_cli_list_papers",
    SKILLS_ROOT / "list_all_citations" / "list_papers.py"
)
FETCH_CONTEXTS = load_module(
    "impact_cli_fetch_contexts",
    SKILLS_ROOT / "academic_impact_analyzer" / "fetch_contexts.py"
)
DOWNLOAD_PDF = load_module(
    "impact_cli_download_pdf",
    SKILLS_ROOT / "download_paper_pdf" / "download_pdf.py"
)
RUN_PIPELINE = load_module(
    "impact_cli_run_pipeline",
    SKILLS_ROOT / "academic_impact_analyzer" / "run_pipeline.py"
)
AGGREGATE_REPORT = load_module(
    "impact_cli_aggregate_report",
    SKILLS_ROOT / "academic_impact_analyzer" / "aggregate_report.py"
)
PERSON_CANDIDATES = load_module(
    "impact_cli_person_candidates",
    SKILLS_ROOT / "academic_impact_analyzer" / "person_candidates.py"
)
SCHOLAR_STATS = load_module(
    "impact_cli_scholar_stats",
    SKILLS_ROOT / "academic_impact_analyzer" / "scholar_stats.py"
)
SCHOLAR_EVIDENCE = load_module(
    "impact_cli_scholar_evidence",
    SKILLS_ROOT / "scholar_impact_analyzer" / "scholar_evidence.py"
)
EVIDENCE_TEMPLATES = load_module(
    "impact_cli_evidence_templates",
    SKILLS_ROOT / "scholar_impact_analyzer" / "evidence_templates.py"
)


def sanitize_json_value(value):
    if isinstance(value, str):
        return re.sub(r"[\ud800-\udfff]", "", value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    return value


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_json_value(data)
    path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_ids(raw: str) -> List[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def chinese_number_to_int(text: str):
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    if len(text) == 2 and text[0] == "十" and text[1] in NUMBER_WORDS:
        return 10 + NUMBER_WORDS[text[1]]
    if len(text) == 2 and text[1] == "十" and text[0] in NUMBER_WORDS:
        return NUMBER_WORDS[text[0]] * 10
    if len(text) == 3 and text[1] == "十" and text[0] in NUMBER_WORDS and text[2] in NUMBER_WORDS:
        return NUMBER_WORDS[text[0]] * 10 + NUMBER_WORDS[text[2]]
    return None


def ids_from_message(message: str):
    matches = re.findall(r"第\s*([0-9一二两三四五六七八九十]+)\s*篇", message or "")
    ids = []
    for raw in matches:
        num = chinese_number_to_int(raw)
        if num is None:
            continue
        ids.append(f"P{num:03d}")
    return ids


def truncate_text(text: str, limit: int = 180):
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def sort_papers_by_recent(papers: List[dict]) -> List[dict]:
    return sorted(
        papers,
        key=lambda item: (
            item.get("year") is None,
            -(item.get("year") or -1),
            (item.get("title") or "").lower(),
        ),
    )


def normalize_reference_text(text: str):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize_reference_text(text: str) -> List[str]:
    normalized = normalize_reference_text(text)
    if not normalized:
        return []
    return [token for token in normalized.split(" ") if token]


def unique_strings(values: List[str]) -> List[str]:
    result = []
    seen = set()
    for value in values:
        normalized = (value or "").strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def parse_multiline_values(value: str) -> List[str]:
    parts = re.split(r"[\n\r;；|]+", str(value or ""))
    return unique_strings([part.strip() for part in parts if part.strip()])


def default_analysis_templates() -> dict:
    try:
        templates = EVIDENCE_TEMPLATES.load_builtin_templates()
    except Exception:
        templates = []
    return EVIDENCE_TEMPLATES.compile_template_state(
        active_template_ids=["ppt_highlight_default"],
        custom_requests=[],
        builtin_templates=templates,
    )


def ensure_analysis_templates(session: dict) -> dict:
    defaults = default_analysis_templates()
    template_state = session.get("analysis_templates")
    if not isinstance(template_state, dict):
        session["analysis_templates"] = defaults
        return defaults
    active_template_ids = (
        template_state["active_template_ids"]
        if "active_template_ids" in template_state
        else defaults["active_template_ids"]
    )
    synced = EVIDENCE_TEMPLATES.compile_template_state(
        active_template_ids=active_template_ids,
        custom_requests=template_state.get("custom_requests") or [],
        builtin_templates=defaults["builtin_templates"],
    )
    session["analysis_templates"] = synced
    return synced


ANALYSIS_MODEL_OPTIONS = [
    {
        "value": "default",
        "label": "跟随环境配置",
        "description": "使用当前 .env 中配置的分析模式、接口地址和模型名。",
    },
    {
        "value": "local",
        "label": "本地模型",
        "description": "使用 ACADEMIC_IMPACT_LOCAL_LLM_URL / ACADEMIC_IMPACT_LOCAL_MODEL。",
    },
    {
        "value": "deepseek",
        "label": "DeepSeek",
        "description": "使用 DeepSeek Chat，需要配置 DEEPSEEK_API_KEY。",
    },
]


def normalize_analysis_model_profile(value: str = "") -> str:
    profile = (value or "default").strip().lower().replace("-", "_")
    aliases = {
        "": "default",
        "env": "default",
        "current": "default",
        "local_model": "local",
        "local_llm": "local",
        "本地模型": "local",
        "deepseek_chat": "deepseek",
    }
    profile = aliases.get(profile, profile)
    if profile not in {item["value"] for item in ANALYSIS_MODEL_OPTIONS}:
        return "default"
    return profile


def analysis_model_options() -> List[dict]:
    return [dict(item) for item in ANALYSIS_MODEL_OPTIONS]


def session_analysis_model_profile(session: dict) -> str:
    value = ""
    analysis_model = session.get("analysis_model")
    if isinstance(analysis_model, dict):
        value = analysis_model.get("profile") or ""
    return normalize_analysis_model_profile(value)


def set_session_analysis_model_profile(session: dict, profile: str) -> str:
    normalized = normalize_analysis_model_profile(profile)
    session["analysis_model"] = {"profile": normalized}
    return normalized


def update_analysis_templates(
    session_dir: Path,
    active_template_ids: List[str],
    custom_requests_text: str,
) -> dict:
    session = load_session(session_dir)
    custom_requests = parse_multiline_values(custom_requests_text)
    session["analysis_templates"] = EVIDENCE_TEMPLATES.compile_template_state(
        active_template_ids=active_template_ids,
        custom_requests=custom_requests,
    )
    save_session(session_dir, session)
    return session


def count_sentences(text: str) -> int:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return 0
    parts = [part for part in re.split(r"[。！？!?；;]+", clean) if part.strip()]
    return max(1, len(parts))


def build_paper_alias_entry(item: dict):
    title = item.get("title", "")
    paper_id = item.get("id", "")
    normalized_title = normalize_reference_text(title)
    title_parts = [
        part.strip()
        for part in re.split(r"[:：\-|/]", title)
        if part and part.strip()
    ]
    aliases = [title]
    if title_parts:
        aliases.append(title_parts[0])
    normalized_aliases = unique_strings([normalize_reference_text(alias) for alias in aliases])
    tokens = []
    for token in tokenize_reference_text(title):
        if len(token) < 3 and not token.isdigit():
            continue
        if token in STOPWORD_TOKENS:
            continue
        tokens.append(token)
    keywords = unique_strings(tokens)[:8]
    return {
        "id": paper_id,
        "title": title,
        "normalized_title": normalized_title,
        "aliases": unique_strings(aliases),
        "normalized_aliases": normalized_aliases,
        "keywords": keywords,
    }


def build_session_paper_aliases(papers: List[dict]):
    return [build_paper_alias_entry(item) for item in papers]


def default_quick_analysis(session: dict = None):
    query = (session or {}).get("query", "")
    return {
        "schema_version": QUICK_ANALYSIS_VERSION,
        "status": "not_ready",
        "analysis_mode": "quick",
        "query": query,
        "impact_level": None,
        "impact_label": None,
        "summary": "",
        "highlights": [],
        "generated_at": None,
    }


def default_evidence_index():
    return {
        "schema_version": EVIDENCE_INDEX_VERSION,
        "status": "not_ready",
        "items": [],
        "qa_ready_count": 0,
        "generated_at": None,
    }


def default_overview_stats():
    return {
        "downloaded_count": 0,
        "analyzed_count": 0,
        "candidate_people_count": 0,
        "confirmed_people_count": 0,
    }


def default_quick_stats(session: dict = None):
    return SCHOLAR_STATS.default_quick_stats(session)


def default_exports():
    return {
        "report_md_path": "",
        "structured_json_path": "",
        "highlight_cards_csv_path": "",
        "highlight_cards_md_path": "",
    }


def merge_exports(value: Any = None) -> dict:
    exports = default_exports()
    if isinstance(value, dict):
        exports.update(value)
    return exports


def default_task_state():
    return {
        "active": False,
        "task_type": None,
        "status": "idle",
        "message": "",
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "error": "",
        "requested_ids": [],
        "top_k_spans": None,
        "analysis_model_profile": "default",
    }


def infer_impact_level(paper_count: int, medium_or_high_count: int, high_count: int) -> Tuple[str, str]:
    if paper_count >= 10 or high_count >= 2 or medium_or_high_count >= 4:
        return "high", "较高"
    if paper_count >= 5 or medium_or_high_count >= 2:
        return "medium", "中等"
    return "low", "初步"


def build_quick_analysis(session_dir: Path, session: dict):
    papers = session.get("papers", [])
    if not papers:
        result = default_quick_analysis(session)
        result["status"] = "empty"
        result["summary"] = "当前会话中还没有发现引用论文。"
        result["generated_at"] = datetime.now().isoformat(timespec="seconds")
        return result

    confidence_counts = Counter(item.get("context_confidence") or "unknown" for item in papers)
    high_count = confidence_counts.get("high", 0)
    medium_count = confidence_counts.get("medium", 0)
    medium_or_high_count = high_count + medium_count
    impact_level, impact_label = infer_impact_level(len(papers), medium_or_high_count, high_count)

    highlights = []
    for item in papers:
        best_context = item.get("best_context") or {}
        context_text = truncate_text(best_context.get("text") or "", limit=180)
        if not context_text:
            continue
        highlights.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "context_confidence": item.get("context_confidence"),
            "excerpt": context_text,
        })
    highlights = highlights[:3]

    total_citation_count = ((session.get("target") or {}).get("citationCount"))
    displayed_count = len(papers)
    if total_citation_count:
        count_intro = f"Semantic Scholar 当前记录总引用数约 {total_citation_count} 篇，本会话先展示其中 {displayed_count} 篇候选论文。"
    else:
        count_intro = f"当前会话先展示 {displayed_count} 篇引用论文候选。"

    summary_parts = [
        f"{count_intro} 其中 {medium_or_high_count} 篇在 citation contexts 中呈现出中高置信度引用信号。"
    ]
    if highlights:
        top_titles = "、".join(f"{entry['id']} {entry['title']}" for entry in highlights[:2])
        summary_parts.append(f"从现有上下文看，较值得优先关注的引用论文包括 {top_titles}。")
    summary_parts.append(
        f"基于现有 citation contexts 的初步判断，这篇目标论文的外部影响力处于{impact_label}水平；如果需要回答“具体怎么引用、引用了多长段落”，还需要继续做全文级全面分析。"
    )

    return {
        "schema_version": QUICK_ANALYSIS_VERSION,
        "status": "ready",
        "analysis_mode": "quick",
        "query": session.get("query", ""),
        "impact_level": impact_level,
        "impact_label": impact_label,
        "summary": " ".join(summary_parts),
        "highlights": highlights,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def load_json_if_exists(path_str: str):
    path = Path(path_str).expanduser()
    if not path_str or not path.exists():
        return None
    return read_json(path)


def build_primary_evidence(candidate_data: dict, analysis_data: dict):
    spans = candidate_data.get("spans", []) if isinstance(candidate_data, dict) else []
    findings = analysis_data.get("findings", []) if isinstance(analysis_data, dict) else []
    top_span = spans[0] if spans else {}
    matched_finding = None
    if top_span:
        for finding in findings:
            if (
                finding.get("page") == top_span.get("page")
                and finding.get("span_index") == top_span.get("span_index")
            ):
                matched_finding = finding
                break
    focus_text = top_span.get("text") or (matched_finding or {}).get("citation_text") or ""
    return {
        "page": top_span.get("page") or (matched_finding or {}).get("page"),
        "span_index": top_span.get("span_index") or (matched_finding or {}).get("span_index"),
        "char_length": len(re.sub(r"\s+", "", focus_text)),
        "sentence_count": count_sentences(focus_text),
        "excerpt": truncate_text(focus_text, limit=220),
        "text": focus_text,
        "match_type": top_span.get("match_type"),
        "citation_index": top_span.get("citation_index") or candidate_data.get("citation_index"),
        "score": top_span.get("score"),
        "context_window_text": top_span.get("context_window_text", ""),
        "finding": {
            "aspect": (matched_finding or {}).get("aspect"),
            "stance": (matched_finding or {}).get("stance"),
            "function": (matched_finding or {}).get("function"),
            "reason": (matched_finding or {}).get("reason"),
            "confidence": (matched_finding or {}).get("confidence"),
            "mention_type": (matched_finding or {}).get("mention_type"),
        },
    }


def _paper_authors(item: dict) -> List[Any]:
    paper = item.get("paper") if isinstance(item.get("paper"), dict) else {}
    return item.get("authors") or paper.get("authors") or []


def _target_authors(target: Optional[dict]) -> List[Any]:
    target = target or {}
    authors = target.get("authors") or target.get("author_names") or []
    if authors:
        return authors
    paper = target.get("paper") if isinstance(target.get("paper"), dict) else {}
    return paper.get("authors") or []


def _person_tag_labels_for_item(item: dict) -> List[str]:
    labels = []
    for hit in item.get("person_candidate_hits", []) or []:
        if hit.get("status") == "rejected":
            continue
        label = hit.get("tag_label") or hit.get("tag_type") or ""
        if label:
            labels.append(label)
    return unique_strings(labels)


def _exclusion_profile_value(profile: Optional[dict], key: str) -> List[str]:
    if not isinstance(profile, dict):
        return []
    return profile.get(key) or []


def build_template_match_spec(compiled_templates: Optional[List[dict]]) -> dict:
    labels = []
    keywords = []
    names = []
    for template in compiled_templates or []:
        if not isinstance(template, dict):
            continue
        names.append(template.get("name") or template.get("id") or "")
        labels.extend(template.get("target_labels") or [])
        keywords.extend(template.get("positive_keywords") or [])
    label_terms = unique_strings([str(label or "").strip() for label in labels])
    keyword_terms = unique_strings([str(keyword or "").strip() for keyword in keywords])
    available_terms = unique_strings(
        [SCHOLAR_EVIDENCE.evidence_label_display(label) for label in label_terms]
        + keyword_terms
    )
    return {
        "labels": set(label_terms),
        "label_terms": label_terms,
        "available_terms": available_terms,
        "keywords": [
            {"term": keyword, "lower": keyword.lower()}
            for keyword in keyword_terms
            if keyword
        ],
        "names": unique_strings([str(name or "").strip() for name in names]),
    }


def template_match_summary(detail: dict, template_spec: Optional[dict]) -> dict:
    available_terms = []
    if template_spec:
        available_terms.extend(template_spec.get("available_terms") or [])
    available_terms = unique_strings([term for term in available_terms if term])
    if not template_spec:
        return {
            "matched": False,
            "matched_terms": [],
            "available_terms": [],
            "label": "未配置分析模板",
        }
    if detail.get("keep") is False:
        return {
            "matched": False,
            "matched_terms": [],
            "available_terms": available_terms,
            "label": "当前模板检查：" + (" / ".join(available_terms[:4]) if available_terms else "-"),
        }
    if (detail.get("mention_type") or "") in {
        "grouped_literature_mention",
        "weak_body_mention",
    }:
        return {
            "matched": False,
            "matched_terms": [],
            "available_terms": available_terms,
            "label": "当前模板检查：" + (" / ".join(available_terms[:4]) if available_terms else "-"),
        }

    target_labels = template_spec.get("labels") or set()
    detail_labels = set(detail.get("evidence_labels") or [])
    matched_terms = []
    if target_labels and target_labels & detail_labels:
        matched_terms.extend(
            SCHOLAR_EVIDENCE.evidence_label_display(label)
            for label in template_spec.get("label_terms") or []
            if label in detail_labels
        )

    text = str(detail.get("citation_text") or "").lower()
    highlight_keywords = {
        str(keyword or "").strip().lower()
        for keyword in detail.get("highlight_keywords") or []
        if str(keyword or "").strip()
    }
    for keyword in template_spec.get("keywords") or []:
        keyword_lower = keyword.get("lower") or ""
        if keyword_lower in highlight_keywords or (keyword_lower and keyword_lower in text):
            matched_terms.append(keyword.get("term") or keyword_lower)
    matched_terms = unique_strings([term for term in matched_terms if term])
    return {
        "matched": bool(matched_terms),
        "matched_terms": matched_terms,
        "available_terms": available_terms,
        "label": (
            "模板命中词：" + " / ".join(matched_terms[:4])
            if matched_terms
            else "当前模板检查：" + (" / ".join(available_terms[:4]) if available_terms else "-")
        ),
    }


def finding_matches_template(detail: dict, template_spec: Optional[dict]) -> bool:
    return bool(template_match_summary(detail, template_spec).get("matched"))


def build_finding_detail(
    finding: dict,
    *,
    item: Optional[dict] = None,
    target: Optional[dict] = None,
    exclusion_profile: Optional[dict] = None,
    template_spec: Optional[dict] = None,
):
    if not isinstance(finding, dict):
        return None
    aspect = (finding.get("aspect") or "").strip()
    mention_type = (finding.get("mention_type") or "").strip()
    stance = (finding.get("stance") or "").strip()
    confidence = finding.get("confidence")
    citation_text = finding.get("citation_text") or ""
    citation_char_count = len(re.sub(r"\s+", "", citation_text))
    keep = bool(finding.get("keep", True))
    is_weak_mention = (not keep) or mention_type in {
        "grouped_literature_mention",
        "weak_body_mention",
    }
    item = item or {}
    person_tag_labels = _person_tag_labels_for_item(item)
    third_party = SCHOLAR_EVIDENCE.classify_third_party_citation(
        source_authors=_target_authors(target),
        citing_authors=_paper_authors(item),
        selected_author_names=[],
        extra_excluded_authors=_exclusion_profile_value(exclusion_profile, "extra_excluded_authors"),
        extra_excluded_affiliations=_exclusion_profile_value(exclusion_profile, "extra_excluded_affiliations"),
        citing_affiliations=item.get("affiliations") or (item.get("paper") or {}).get("affiliations") or [],
    )
    self_citation_status = third_party.get("status") or "unknown"
    evidence_labels = SCHOLAR_EVIDENCE.derive_evidence_labels(
        finding,
        citation_char_count=citation_char_count,
        person_tag_labels=person_tag_labels,
    )
    highlight_keywords = SCHOLAR_EVIDENCE.derive_highlight_keywords(finding, evidence_labels)
    strong_score = 0 if is_weak_mention else SCHOLAR_EVIDENCE.score_strong_evidence(
        labels=evidence_labels,
        confidence=confidence,
        citation_char_count=citation_char_count,
        person_tag_labels=person_tag_labels,
        self_citation_status=self_citation_status,
    )
    evidence_strength = SCHOLAR_EVIDENCE.evidence_strength(strong_score)
    reportable_probe = dict(finding)
    reportable_probe.update(
        {
            "keep": keep,
            "evidence_labels": evidence_labels,
            "strong_citation_score": strong_score,
            "evidence_strength": evidence_strength,
        }
    )
    reportable = SCHOLAR_EVIDENCE.is_reportable_strong_evidence(reportable_probe)
    if self_citation_status in {"self_citation", "excluded_collaborator"}:
        reportable = False
    detail = {
        "page": finding.get("page"),
        "span_index": finding.get("span_index"),
        "citation_text": citation_text,
        "citation_excerpt": truncate_text(citation_text, limit=360),
        "aspect": aspect,
        "aspect_label": ASPECT_LABELS.get(aspect, aspect or "-"),
        "mention_type": mention_type,
        "mention_type_label": MENTION_TYPE_LABELS.get(mention_type, mention_type or "-"),
        "stance": stance,
        "stance_label": STANCE_LABELS.get(stance, stance or "-"),
        "function": finding.get("function") or "",
        "reason": finding.get("reason") or "",
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
        "keep": keep,
        "evidence_labels": evidence_labels,
        "evidence_label_names": [
            SCHOLAR_EVIDENCE.evidence_label_display(label)
            for label in evidence_labels
        ],
        "highlight_keywords": highlight_keywords,
        "highlighted_citation_text": SCHOLAR_EVIDENCE.highlight_excerpt_html(
            citation_text,
            highlight_keywords,
        ),
        "strong_citation_score": strong_score,
        "evidence_strength": evidence_strength,
        "reportable_strong_evidence": reportable,
        "self_citation_status": self_citation_status,
        "self_citation_label": {
            "self_citation": "自引",
            "excluded_collaborator": "本组/合作者",
            "non_self_citation": "非自引",
            "unknown": "未知",
        }.get(self_citation_status, self_citation_status),
        "overlap_authors": third_party.get("overlap_authors", []),
        "overlap_affiliations": third_party.get("overlap_affiliations", []),
        "person_tag_labels": person_tag_labels,
        "valuable_reason": finding.get("valuable_reason") or finding.get("reason") or "",
    }
    template_match = template_match_summary(detail, template_spec)
    detail["template_matched"] = bool(template_match.get("matched"))
    detail["template_match_terms"] = template_match.get("matched_terms") or []
    detail["template_available_terms"] = template_match.get("available_terms") or []
    detail["template_match_label"] = template_match.get("label") or (
        "模板命中" if detail["template_matched"] else "模板未命中"
    )
    return detail


def build_evidence_index(session_dir: Path, session: dict):
    items = []
    for item in session.get("papers", []):
        analysis_paths = item.get("analysis_result", {}).get("paths", {})
        if not analysis_paths:
            continue
        candidate_data = load_json_if_exists(analysis_paths.get("candidate_spans", ""))
        analysis_data = load_json_if_exists(analysis_paths.get("analysis", ""))
        fallback_data = load_json_if_exists(analysis_paths.get("fallback_analysis", ""))
        status = item.get("analysis_result", {}).get("status")
        primary_evidence = build_primary_evidence(candidate_data or {}, analysis_data or {})
        qa_ready = bool(candidate_data and analysis_data and status in {
            "fulltext_analyzed",
            "mention_only",
            "reference_only",
            "fulltext_no_finding",
        })
        items.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "status": status,
            "status_label": ANALYSIS_STATUS_LABELS.get(status, status or "-"),
            "qa_ready": qa_ready,
            "candidate_span_count": len((candidate_data or {}).get("spans", [])),
            "findings_count": len((analysis_data or {}).get("findings", [])) if analysis_data else 0,
            "primary_evidence": primary_evidence,
            "fallback_contexts": (fallback_data or {}).get("fallback_contexts", [])[:2],
            "paths": analysis_paths,
        })

    qa_ready_count = sum(1 for item in items if item.get("qa_ready"))
    return {
        "schema_version": EVIDENCE_INDEX_VERSION,
        "status": "ready" if items else "not_ready",
        "items": items,
        "qa_ready_count": qa_ready_count,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_overview_stats(session: dict):
    papers = session.get("papers", [])
    person_candidates = session.get("person_candidates", [])
    downloaded_count = sum(
        1 for item in papers if item.get("download_probe", {}).get("status") == "local_available"
    )
    analyzed_count = sum(1 for item in papers if item.get("analysis_result", {}).get("status"))
    candidate_people_count = len(person_candidates)
    confirmed_people_count = sum(1 for item in person_candidates if item.get("status") == "confirmed")
    return {
        "downloaded_count": downloaded_count,
        "analyzed_count": analyzed_count,
        "candidate_people_count": candidate_people_count,
        "confirmed_people_count": confirmed_people_count,
    }


def build_person_tag_statistics(person_candidates: List[dict]):
    tag_labels = getattr(PERSON_CANDIDATES, "TAG_LABELS", {})
    ordered_tag_types = list(tag_labels.keys())
    for candidate in person_candidates:
        tag_type = candidate.get("tag_type") or ""
        if tag_type and tag_type not in ordered_tag_types:
            ordered_tag_types.append(tag_type)

    groups = []
    for tag_type in ordered_tag_types:
        candidates = [item for item in person_candidates if item.get("tag_type") == tag_type]
        summary = PERSON_CANDIDATES.summarize_candidates(candidates)
        paper_ids = set()
        for candidate in candidates:
            paper_ids.update(candidate.get("matched_paper_ids") or [])
        groups.append({
            "tag_type": tag_type,
            "tag_label": tag_labels.get(tag_type, tag_type or "-"),
            "count": summary["matched_author_count"],
            "matched_author_count": summary["matched_author_count"],
            "candidate_count": len(candidates),
            "ambiguous_author_count": summary["ambiguous_author_count"],
            "high_risk_author_count": summary["high_risk_author_count"],
            "matched_author_preview": summary["matched_author_preview"],
            "confirmed_count": sum(1 for item in candidates if item.get("status") == "confirmed"),
            "pending_count": sum(1 for item in candidates if item.get("status") == "pending"),
            "rejected_count": sum(1 for item in candidates if item.get("status") == "rejected"),
            "source_complete_count": sum(1 for item in candidates if item.get("source_links")),
            "matched_paper_count": len(paper_ids),
            "candidate_preview": candidates[:5],
        })

    return {
        "schema_version": "1.0",
        "total_candidate_count": len(person_candidates),
        "confirmed_count": sum(1 for item in person_candidates if item.get("status") == "confirmed"),
        "pending_count": sum(1 for item in person_candidates if item.get("status") == "pending"),
        "rejected_count": sum(1 for item in person_candidates if item.get("status") == "rejected"),
        "source_complete_count": sum(1 for item in person_candidates if item.get("source_links")),
        "groups": groups,
    }


def normalize_venue_key(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", text)
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    ordinal_words = (
        "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        "eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|"
        "seventeenth|eighteenth|nineteenth|twentieth|twenty first|"
        "twenty second|twenty third|twenty fourth|twenty fifth|twenty sixth|"
        "twenty seventh|twenty eighth|twenty ninth|thirtieth|thirty first"
    )
    text = re.sub(rf"\b({ordinal_words})\b", " ", text)
    text = re.sub(r"\b(proceedings|proceeding|proc|conference|conf|symposium|of|the|on)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_unknown_venue(value: str) -> bool:
    normalized = normalize_venue_key(value)
    return not normalized or normalized in {"unknown", "unknown venue", "none", "null", "arxiv org"}


def load_venue_tier_registry(path: Path = VENUE_TIER_REGISTRY_PATH) -> dict:
    if not path.exists():
        return {
            "schema_version": "1.0",
            "source_note": "missing venue tier registry",
            "entries": [],
        }
    try:
        payload = read_json(path)
    except Exception:
        return {
            "schema_version": "1.0",
            "source_note": "failed to read venue tier registry",
            "entries": [],
        }
    if isinstance(payload, list):
        return {"schema_version": "1.0", "entries": payload}
    if not isinstance(payload, dict):
        return {"schema_version": "1.0", "entries": []}
    payload.setdefault("entries", [])
    return payload


def build_venue_tier_index(registry: Optional[dict] = None) -> dict:
    registry = registry if isinstance(registry, dict) else load_venue_tier_registry()
    index = {}
    for entry in registry.get("entries", []) or []:
        if not isinstance(entry, dict):
            continue
        names = [entry.get("name", "")]
        names.extend(entry.get("aliases", []) or [])
        for name in names:
            key = normalize_venue_key(name)
            if key and key not in index:
                index[key] = entry
    return {
        "registry": registry,
        "by_key": index,
    }


def classify_venue_tier(venue: str, tier_index: Optional[dict] = None) -> dict:
    tier_index = tier_index if isinstance(tier_index, dict) else build_venue_tier_index()
    raw_venue = str(venue or "").strip()
    normalized = normalize_venue_key(raw_venue)
    if is_unknown_venue(raw_venue):
        return {
            "venue": raw_venue,
            "normalized_venue": normalized,
            "matched": False,
            "tier": "unknown",
            "tier_label": "未识别 venue",
            "tier_system": "",
            "venue_type": "",
            "matched_name": "",
            "source": "",
        }

    entry = (tier_index.get("by_key") or {}).get(normalized)
    if not entry:
        padded_normalized = f" {normalized} "
        substring_matches = []
        for key, candidate in (tier_index.get("by_key") or {}).items():
            if len(key) < 8:
                continue
            padded_key = f" {key} "
            if padded_key in padded_normalized or padded_normalized in padded_key:
                substring_matches.append((len(key), candidate))
        if substring_matches:
            entry = sorted(substring_matches, key=lambda item: item[0], reverse=True)[0][1]
    if not entry:
        return {
            "venue": raw_venue,
            "normalized_venue": normalized,
            "matched": False,
            "tier": "unmatched",
            "tier_label": "未匹配等级",
            "tier_system": "",
            "venue_type": "",
            "matched_name": "",
            "source": "",
        }

    tier = str(entry.get("tier") or "unrated").strip()
    tier_system = str(entry.get("tier_system") or entry.get("system") or "").strip()
    tier_label = str(entry.get("tier_label") or entry.get("label") or "").strip()
    if not tier_label:
        tier_label = f"{tier_system} {tier}".strip() or tier
    return {
        "venue": raw_venue,
        "normalized_venue": normalized,
        "matched": True,
        "tier": tier,
        "tier_label": tier_label,
        "tier_system": tier_system,
        "venue_type": entry.get("venue_type") or "",
        "matched_name": entry.get("name") or raw_venue,
        "source": entry.get("source") or "",
    }


def build_venue_statistics(papers: List[dict], tier_index: Optional[dict] = None) -> dict:
    tier_index = tier_index if isinstance(tier_index, dict) else build_venue_tier_index()
    venue_groups = {}
    tier_groups = {}
    paper_items = []

    for item in papers or []:
        paper_id = item.get("id")
        venue = item.get("venue") or (item.get("paper") or {}).get("venue") or ""
        classification = item.get("venue_tier") if isinstance(item.get("venue_tier"), dict) else classify_venue_tier(venue, tier_index)
        venue_key = classification.get("normalized_venue") or normalize_venue_key(venue) or "unknown"
        venue_label = venue if not is_unknown_venue(venue) else "Unknown Venue"
        venue_group = venue_groups.setdefault(venue_key, {
            "venue": venue_label,
            "normalized_venue": venue_key,
            "count": 0,
            "paper_ids": [],
            "tier": classification,
        })
        venue_group["count"] += 1
        if paper_id:
            venue_group["paper_ids"].append(paper_id)

        tier_key = classification.get("tier") or "unknown"
        tier_label = classification.get("tier_label") or tier_key
        tier_group = tier_groups.setdefault(tier_key, {
            "tier": tier_key,
            "tier_label": tier_label,
            "tier_system": classification.get("tier_system") or "",
            "count": 0,
            "paper_ids": [],
        })
        tier_group["count"] += 1
        if paper_id:
            tier_group["paper_ids"].append(paper_id)

        paper_items.append({
            "id": paper_id,
            "title": item.get("title"),
            "venue": venue,
            "year": item.get("year"),
            "venue_tier": classification,
        })

    top_venues = sorted(
        venue_groups.values(),
        key=lambda group: (-group["count"], group["venue"].lower()),
    )
    tier_distribution = sorted(
        tier_groups.values(),
        key=lambda group: (-group["count"], group["tier_label"].lower()),
    )
    matched_tier_count = sum(1 for item in paper_items if item["venue_tier"].get("matched"))
    known_venue_count = sum(1 for item in paper_items if not is_unknown_venue(item.get("venue", "")))

    return {
        "schema_version": "1.0",
        "registry_path": str(VENUE_TIER_REGISTRY_PATH),
        "registry_source_note": (tier_index.get("registry") or {}).get("source_note", ""),
        "paper_count": len(paper_items),
        "known_venue_count": known_venue_count,
        "unknown_venue_count": len(paper_items) - known_venue_count,
        "unique_venue_count": len([key for key in venue_groups if key != "unknown"]),
        "matched_tier_count": matched_tier_count,
        "unmatched_tier_count": len(paper_items) - matched_tier_count,
        "top_venues": top_venues[:12],
        "tier_distribution": tier_distribution,
        "papers": paper_items,
    }


def rebuild_person_candidates(session: dict):
    session["person_candidates"] = PERSON_CANDIDATES.build_candidates(
        session.get("papers", []),
        existing=session.get("person_candidates", []),
    )
    session["overview_stats"] = build_overview_stats(session)


FIRST_CLAIM_PATTERNS = [
    r"\bfor the first time\b",
    r"\bour work is the first\b",
    r"\bwe are the first\b",
    r"\bfirst to\b",
    r"\b首次\b",
    r"\b第一次\b",
]


def contains_first_claim(text: str):
    content = str(text or "")
    return any(re.search(pattern, content, flags=re.I) for pattern in FIRST_CLAIM_PATTERNS)


def is_rate_limited_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return "429" in lowered or "rate limited" in lowered or "rate limit" in lowered


def build_analysis_reason(item: dict, status: str, fallback_data: Optional[dict] = None):
    if not status:
        return None

    download_probe = item.get("download_probe", {}) or {}
    download_result = item.get("download_result", {}) or {}
    attempts = []
    for payload in [download_probe, download_result]:
        for attempt in payload.get("attempts", []) or []:
            if isinstance(attempt, dict):
                attempts.append(attempt)

    raw_errors = unique_strings(
        [
            download_probe.get("error", ""),
            download_result.get("error", ""),
            *[attempt.get("error", "") for attempt in attempts],
            *[
                entry.get("error", "")
                for payload in [download_probe, download_result]
                for entry in (payload.get("download_errors", []) or [])
                if isinstance(entry, dict)
            ],
        ]
    )
    download_error_types = unique_strings(
        [
            download_probe.get("error_type", ""),
            download_result.get("error_type", ""),
            *[attempt.get("error_type", "") for attempt in attempts],
            *[
                entry.get("error_type", "")
                for payload in [download_probe, download_result]
                for entry in (payload.get("download_errors", []) or [])
                if isinstance(entry, dict)
            ],
        ]
    )
    analysis_paths = item.get("analysis_result", {}).get("paths", {})
    analysis_data = load_json_if_exists(analysis_paths.get("analysis", ""))
    analysis_error_type = (analysis_data or {}).get("error_type", "") if isinstance(analysis_data, dict) else ""
    analysis_error = (analysis_data or {}).get("error", "") if isinstance(analysis_data, dict) else ""
    analysis_error_stage = (analysis_data or {}).get("error_stage", "") if isinstance(analysis_data, dict) else ""
    tags = []
    details = []

    if status == "context_only":
        tags.extend(["未获得 PDF", "仅 citation context", "未经全文验证"])
        details.append("未获得全文 PDF，当前结果仅基于 citation contexts，未经全文验证。")
        download_failure_map = {
            "fake_pdf_html_interstitial": (["fake_pdf_html_interstitial", "假 PDF / HTML 拦截页"], "这不是模型问题，而是下载到的文件实际上是 HTML/反爬页面，不是真正 PDF。"),
            "downloaded_non_pdf": (["downloaded_non_pdf", "无效 PDF / 假 PDF"], "这不是模型问题，而是下载到的文件并非真实 PDF。"),
        }
        for error_type in download_error_types:
            mapped = download_failure_map.get(error_type)
            if not mapped:
                continue
            tag_list, detail = mapped
            tags.extend(tag_list)
            details.append(detail)
        if any(is_rate_limited_error(error) for error in raw_errors):
            tags.append("外部源限流")
            details.append("下载阶段命中过外部源限流（HTTP 429）。")
        fallback_message = (fallback_data or {}).get("message", "")
        if fallback_message:
            details.append(fallback_message)
    elif status == "fulltext_extract_failed":
        extract_failure_map = {
            "extract_text_failed": (["extract_text_failed", "全文提取失败"], "已获得 PDF，但全文提取阶段失败，无法进入候选段落定位。"),
            "pdf_parse_failed": (["pdf_parse_failed", "PDF 解析失败"], "已获得 PDF，但 pypdf、PyMuPDF、pdfplumber 均未能稳定解析文本。"),
            "empty_text_pdf": (["empty_text_pdf", "文本几乎为空"], "PDF 可以打开，但提取到的文本几乎为空，暂时无法继续全文分析。"),
            "likely_scanned_pdf": (["likely_scanned_pdf", "疑似扫描版 PDF"], "PDF 可以打开，但更像扫描版/图片版，当前无 OCR 主路径，暂时无法继续全文分析。"),
        }
        mapped = extract_failure_map.get(analysis_error_type)
        if mapped:
            tag_list, detail = mapped
            tags.extend(tag_list)
            details.append(detail)
        else:
            tags.append("全文提取失败")
            details.append("已获得 PDF，但全文提取失败，无法继续做全文级语义分析。")
    elif status == "analysis_failed":
        tags.append("全文语义分析失败")
        stage_tag_map = {
            "candidate_span_failed": "candidate_span_failed",
            "single_model_request_failed": "single_model_request_failed",
            "single_model_json_parse_failed": "single_model_json_parse_failed",
            "single_model_schema_invalid": "single_model_schema_invalid",
            "local_model_request_failed": "local_model_request_failed",
            "blank_model_output": "blank_model_output",
            "deepseek_request_failed": "deepseek_request_failed",
            "deepseek_json_parse_failed": "deepseek_json_parse_failed",
            "write_output_failed": "write_output_failed",
        }
        stage_detail_map = {
            "candidate_span_failed": "候选段落定位阶段失败，未能生成可分析的正文候选。",
            "single_model_request_failed": "分析模型请求阶段失败，全文语义分析未能完成。",
            "single_model_json_parse_failed": "分析模型返回结果无法解析为 JSON，未能产出结构化分析结果。",
            "single_model_schema_invalid": "分析模型返回 JSON 结构不符合全文分析 schema，未能产出可靠结构化结果。",
            "local_model_request_failed": "本地模型请求阶段失败，全文语义分析未能完成。",
            "blank_model_output": "分析模型返回空输出，未能进入结构化结果处理阶段。",
            "deepseek_request_failed": "DeepSeek 整理阶段请求失败，未能产出结构化分析结果。",
            "deepseek_json_parse_failed": "DeepSeek 返回结果无法解析为 JSON，未能产出结构化分析结果。",
            "write_output_failed": "分析过程中的结果写出失败，请检查服务器目录权限或磁盘空间。",
        }
        if analysis_error_type in stage_tag_map:
            tags.append(stage_tag_map[analysis_error_type])
            details.append(stage_detail_map[analysis_error_type])
        else:
            details.append("已获得候选段落，但全文语义分析阶段失败。")
    elif status == "write_output_failed":
        tags.extend(["write_output_failed", "结果写出失败"])
        details.append("分析过程中的结果写出失败，请检查目录权限、磁盘空间或文件系统状态。")

    if analysis_error_stage and analysis_error_stage not in tags:
        tags.append(analysis_error_stage)
    if analysis_error:
        raw_errors.append(analysis_error)

    tags = unique_strings(tags)
    details = unique_strings(details)
    if not tags and not details and not raw_errors:
        return None
    return {
        "tags": tags,
        "message": "；".join(details),
        "errors": raw_errors,
    }


def summarize_citation_method(
    item: dict,
    *,
    target: Optional[dict] = None,
    exclusion_profile: Optional[dict] = None,
    compiled_templates: Optional[List[dict]] = None,
):
    analysis_paths = item.get("analysis_result", {}).get("paths", {})
    candidate_data = load_json_if_exists(analysis_paths.get("candidate_spans", ""))
    analysis_data = load_json_if_exists(analysis_paths.get("analysis", ""))
    fallback_data = load_json_if_exists(analysis_paths.get("fallback_analysis", ""))
    status = item.get("analysis_result", {}).get("status")
    primary_evidence = build_primary_evidence(candidate_data or {}, analysis_data or {})
    findings = (analysis_data or {}).get("findings", []) if isinstance(analysis_data, dict) else []
    pages = [finding.get("page") for finding in findings if finding.get("page") is not None]
    span_pairs = [
        (finding.get("page"), finding.get("span_index"))
        for finding in findings
        if finding.get("page") is not None and finding.get("span_index") is not None
    ]
    unique_pairs = []
    seen_pairs = set()
    for pair in span_pairs:
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        unique_pairs.append(pair)
    continuous_mention_count = 0
    if unique_pairs:
        continuous_mention_count = 1
        previous_page, previous_span = unique_pairs[0]
        for current_page, current_span in unique_pairs[1:]:
            if current_page == previous_page and current_span == previous_span + 1:
                pass
            else:
                continuous_mention_count += 1
            previous_page, previous_span = current_page, current_span

    labels = []
    finding_details = []
    template_spec = build_template_match_spec(compiled_templates)
    for finding in findings:
        aspect = (finding.get("aspect") or "").strip()
        mention_type = (finding.get("mention_type") or "").strip()
        if aspect:
            labels.append(aspect)
        if mention_type and mention_type != "explicit_citation":
            labels.append(mention_type)
        detail = build_finding_detail(
            finding,
            item=item,
            target=target,
            exclusion_profile=exclusion_profile,
            template_spec=template_spec,
        )
        if detail:
            finding_details.append(detail)
            labels.extend(detail.get("evidence_labels") or [])
    if status and status not in {"fulltext_analyzed", "mention_only"}:
        labels.append(status)

    evidence_excerpt = primary_evidence.get("excerpt") or ""
    if not evidence_excerpt and fallback_data:
        fallback_contexts = fallback_data.get("fallback_contexts", [])
        if fallback_contexts:
            evidence_excerpt = truncate_text((fallback_contexts[0] or {}).get("text", ""), limit=220)

    page_start = min(pages) if pages else primary_evidence.get("page")
    page_end = max(pages) if pages else primary_evidence.get("page")
    first_claim_hit = contains_first_claim(primary_evidence.get("text", "")) or any(
        contains_first_claim(finding.get("citation_text", "")) for finding in findings
    )
    confidence_values = [
        finding.get("confidence") for finding in findings if isinstance(finding.get("confidence"), (int, float))
    ]
    confidence = max(confidence_values) if confidence_values else primary_evidence.get("finding", {}).get("confidence")
    analysis_reason = build_analysis_reason(item, status, fallback_data)
    kept_findings = [finding for finding in finding_details if finding.get("keep")]
    reportable_findings = [
        finding for finding in finding_details if finding.get("reportable_strong_evidence")
    ]
    template_matched_findings = [
        finding for finding in finding_details if finding.get("template_matched")
    ]
    template_matched_terms = unique_strings(
        term
        for finding in template_matched_findings
        for term in (finding.get("template_match_terms") or [])
    )
    primary_finding = (
        reportable_findings[0]
        if reportable_findings
        else (kept_findings[0] if kept_findings else (finding_details[0] if finding_details else {}))
    )

    return {
        "labels": unique_strings(labels),
        "evidence_excerpt": evidence_excerpt,
        "page_start": page_start,
        "page_end": page_end,
        "citation_occurrence_count": len(unique_pairs),
        "continuous_mention_count": continuous_mention_count if unique_pairs else 0,
        "first_claim_hit": bool(first_claim_hit),
        "confidence": confidence,
        "status": status,
        "status_label": ANALYSIS_STATUS_LABELS.get(status, status or "-"),
        "finding_count": len(finding_details),
        "kept_finding_count": len(kept_findings),
        "reportable_strong_evidence_count": len(reportable_findings),
        "template_match_count": len(template_matched_findings),
        "template_names": template_spec.get("names") or [],
        "template_available_terms": template_spec.get("available_terms") or [],
        "template_matched_terms": template_matched_terms,
        "strong_evidence_score": max(
            [finding.get("strong_citation_score") or 0 for finding in reportable_findings] or [0]
        ),
        "finding_details": finding_details,
        "reportable_strong_evidence": reportable_findings,
        "template_matched_evidence": template_matched_findings,
        "finding_preview": (reportable_findings or finding_details)[:3],
        "extra_finding_count": max(0, len(finding_details) - 3),
        "primary_aspect_label": primary_finding.get("aspect_label") or "-",
        "primary_mention_type_label": primary_finding.get("mention_type_label") or "-",
        "primary_stance_label": primary_finding.get("stance_label") or "-",
        "primary_function": primary_finding.get("function") or "",
        "primary_reason": primary_finding.get("reason") or "",
        "primary_evidence": primary_evidence,
        "analysis_reason": analysis_reason,
    }


def enrich_papers_with_candidate_hits(session: dict):
    candidate_map: dict[str, list[dict]] = {}
    for candidate in session.get("person_candidates", []):
        for paper_id in candidate.get("matched_paper_ids", []):
            candidate_map.setdefault(paper_id, []).append(candidate)
    for item in session.get("papers", []):
        item["person_candidate_hits"] = [
            {
                "candidate_id": candidate.get("candidate_id"),
                "name": candidate.get("name"),
                "tag_label": candidate.get("tag_label"),
                "status": candidate.get("status"),
            }
            for candidate in candidate_map.get(item.get("id"), [])
        ]


def apply_qa_flags(session: dict):
    qa_ready_ids = {
        item.get("id")
        for item in session.get("evidence_index", {}).get("items", [])
        if item.get("qa_ready")
    }
    for item in session.get("papers", []):
        item["qa_ready"] = item.get("id") in qa_ready_ids


def sync_session_derivatives(session_dir: Path, session: dict, update_quick: bool = False, update_evidence: bool = False):
    session["paper_aliases"] = build_session_paper_aliases(session.get("papers", []))
    if update_evidence or (
        session.get("analysis", {}).get("processed_papers")
        and session.get("evidence_index", {}).get("status") != "ready"
    ):
        session["evidence_index"] = build_evidence_index(session_dir, session)
    else:
        session.setdefault("evidence_index", default_evidence_index())
    apply_qa_flags(session)
    rebuild_person_candidates(session)
    enrich_papers_with_candidate_hits(session)
    session["quick_stats"] = SCHOLAR_STATS.build_quick_stats(session)
    if update_quick:
        session["quick_analysis"] = build_quick_analysis(session_dir, session)
    else:
        session.setdefault("quick_analysis", default_quick_analysis(session))
    session.setdefault("quick_stats", default_quick_stats(session))
    return session


def query_matches_session(session: dict, query: str):
    normalized_query = normalize_reference_text(query)
    if not normalized_query:
        return False
    candidates = [
        session.get("query", ""),
        (session.get("target") or {}).get("title", ""),
        ((session.get("target") or {}).get("externalIds") or {}).get("DOI", ""),
        ((session.get("target") or {}).get("externalIds") or {}).get("ArXiv", ""),
    ]
    normalized_candidates = [normalize_reference_text(item) for item in candidates if item]
    for candidate in normalized_candidates:
        if not candidate:
            continue
        if normalized_query == candidate:
            return True
        if normalized_query in candidate or candidate in normalized_query:
            return True
    return False


def find_latest_session_dir_by_query(query: str):
    if not DEFAULT_SESSIONS_DIR.exists():
        return None
    candidates = sorted(
        [path for path in DEFAULT_SESSIONS_DIR.iterdir() if path.is_dir()],
        key=lambda path: path.name,
        reverse=True,
    )
    for session_dir in candidates:
        session_path = session_dir / "session.json"
        if not session_path.exists():
            continue
        try:
            session = read_json(session_path)
        except Exception:
            continue
        if query_matches_session(session, query):
            return session_dir
    return None


def message_has_multi_reference_cue(text: str):
    return bool(re.search(r"[、,/，]|以及|和|及|还有", text or ""))


def score_paper_alias_match(alias_entry: dict, message_text: str):
    normalized_message = normalize_reference_text(message_text)
    message_tokens = set(tokenize_reference_text(message_text))
    score = 0
    matched_keywords = []

    normalized_title = alias_entry.get("normalized_title", "")
    if normalized_title and len(normalized_title) >= 6 and normalized_title in normalized_message:
        score += 120

    for alias in alias_entry.get("normalized_aliases", []):
        if len(alias) < 5:
            continue
        if alias in normalized_message:
            score = max(score, 80 + min(len(alias), 30))

    for keyword in alias_entry.get("keywords", []):
        if keyword in message_tokens:
            matched_keywords.append(keyword)
        elif len(keyword) >= 5 and keyword in normalized_message:
            matched_keywords.append(keyword)

    if matched_keywords:
        matched_keywords = unique_strings(matched_keywords)
        score += len(matched_keywords) * 16
        score += min(max(len(token) for token in matched_keywords), 20)
        if len(matched_keywords) >= 2:
            score += 20

    return score, matched_keywords


def resolve_paper_selection(session: dict, raw_text: str = "", ids: List[str] = None, top_n: int = 0):
    papers = session.get("papers", [])
    paper_ids = {item.get("id") for item in papers}

    if ids:
        valid_ids = [paper_id for paper_id in ids if paper_id in paper_ids]
        return {
            "status": "ok" if valid_ids else "no_match",
            "ids": valid_ids,
            "matches": [item for item in papers if item.get("id") in valid_ids],
        }

    if top_n > 0:
        selected = papers[:top_n]
        return {
            "status": "ok" if selected else "no_match",
            "ids": [item.get("id") for item in selected if item.get("id")],
            "matches": selected,
        }

    alias_entries = session.get("paper_aliases") or build_session_paper_aliases(papers)
    scored = []
    for alias_entry in alias_entries:
        score, matched_keywords = score_paper_alias_match(alias_entry, raw_text)
        if score < 24:
            continue
        scored.append({
            "id": alias_entry.get("id"),
            "title": alias_entry.get("title"),
            "score": score,
            "matched_keywords": matched_keywords,
        })
    scored.sort(key=lambda item: (-item["score"], item["id"]))

    if not scored:
        relaxed_matches = []
        message_tokens = set(tokenize_reference_text(raw_text))
        for alias_entry in alias_entries:
            relaxed_hits = []
            for token in tokenize_reference_text(alias_entry.get("title", "")):
                if len(token) < 4:
                    continue
                if token in message_tokens:
                    relaxed_hits.append(token)
            relaxed_hits = unique_strings(relaxed_hits)
            if not relaxed_hits:
                continue
            relaxed_matches.append({
                "id": alias_entry.get("id"),
                "title": alias_entry.get("title"),
                "score": len(relaxed_hits),
                "matched_keywords": relaxed_hits,
            })
        if len(relaxed_matches) > 1:
            relaxed_matches.sort(key=lambda item: (-item["score"], item["id"]))
            return {
                "status": "ambiguous",
                "ids": [],
                "matches": relaxed_matches[:3],
            }
        if len(relaxed_matches) == 1:
            paper_id = relaxed_matches[0]["id"]
            return {
                "status": "ok",
                "ids": [paper_id],
                "matches": [item for item in papers if item.get("id") == paper_id],
            }
        return {
            "status": "no_match",
            "ids": [],
            "matches": [],
        }

    if message_has_multi_reference_cue(raw_text):
        selected_ids = [item["id"] for item in scored]
        return {
            "status": "ok",
            "ids": selected_ids,
            "matches": [item for item in papers if item.get("id") in selected_ids],
        }

    best = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if second and second["score"] >= max(24, best["score"] - 10):
        return {
            "status": "ambiguous",
            "ids": [],
            "matches": scored[:3],
        }

    selected_ids = [best["id"]]
    return {
        "status": "ok",
        "ids": selected_ids,
        "matches": [item for item in papers if item.get("id") in selected_ids],
    }


def build_clarification_payload(session: dict, raw_text: str, selection: dict, action: str):
    candidates = []
    for item in selection.get("matches", []):
        title = item.get("title") if isinstance(item, dict) and item.get("title") else None
        paper_id = item.get("id") if isinstance(item, dict) else None
        if title and paper_id:
            candidates.append({
                "id": paper_id,
                "title": title,
            })
    if not candidates and selection.get("status") == "ambiguous":
        for item in selection.get("matches", []):
            candidates.append({
                "id": item.get("id"),
                "title": item.get("title"),
            })
    return {
        "needs_clarification": True,
        "clarification": {
            "action": action,
            "raw_text": raw_text,
            "message": "我匹配到了多篇可能的论文，请你再明确一下编号。",
            "candidates": candidates[:3],
        },
        "card_state": build_card_state_payload(session),
    }


def answer_paper_question(session_dir: Path, session: dict, paper_id: str, question_text: str):
    evidence_items = {
        item.get("id"): item
        for item in session.get("evidence_index", {}).get("items", [])
    }
    paper_map = {
        item.get("id"): item
        for item in session.get("papers", [])
    }
    paper = paper_map.get(paper_id) or {}
    evidence = evidence_items.get(paper_id)
    if not evidence or not evidence.get("qa_ready"):
        index_number = None
        match = re.match(r"^P0*([1-9][0-9]*)$", paper_id or "", flags=re.I)
        if match:
            index_number = int(match.group(1))
        if index_number:
            prompt = f"你可以先说“分析第{index_number}篇”或“全面分析这篇论文的影响力”。"
        else:
            prompt = "你可以先说“分析这篇论文”或“全面分析这篇论文的影响力”。"
        return {
            "status": "needs_full_analysis",
            "text": f"{paper.get('title', paper_id)} 目前还没有可直接问答的全文证据。{prompt}",
            "paper": {
                "id": paper_id,
                "title": paper.get("title"),
            },
        }

    primary = evidence.get("primary_evidence") or {}
    finding = primary.get("finding") or {}
    wants_length = bool(re.search(r"多长|多大的段落|多少字|多长的段落|长度", question_text or ""))
    wants_excerpt = bool(re.search(r"原文|哪一段|具体内容|详细", question_text or ""))

    lines = [
        f"{paper.get('title', paper_id)} 在当前全文分析里，最主要的引用证据位于第 {primary.get('page') or '-'} 页、第 {primary.get('span_index') or '-'} 个候选段落。"
    ]
    if wants_length or True:
        lines.append(
            f"这段核心引用片段约 {primary.get('char_length') or 0} 个非空白字符，约 {primary.get('sentence_count') or 0} 句。"
        )
    if finding.get("function") or finding.get("reason"):
        lines.append(
            f"当前判断：{finding.get('function') or finding.get('reason')}（置信度 {finding.get('confidence') if finding.get('confidence') is not None else '-'}）。"
        )
    if wants_excerpt or not wants_length:
        lines.append(f"证据摘录：{primary.get('excerpt') or '暂无可展示摘录。'}")
    else:
        lines.append(f"可复核摘录：{primary.get('excerpt') or '暂无可展示摘录。'}")

    return {
        "status": "answered",
        "text": "\n".join(lines),
        "paper": {
            "id": paper_id,
            "title": paper.get("title"),
            "status": evidence.get("status"),
        },
        "evidence": primary,
    }


def default_download_probe(paper: dict):
    return {
        "ok": True,
        "status": "not_probed",
        "source": "",
        "queries": RUN_PIPELINE.choose_download_queries(paper),
        "attempts": [],
        "candidate_count": None,
        "local_file_path": None,
        "pdf_candidates": [],
        "error": None,
    }


def build_capabilities_payload():
    lines = [
        "我现在支持这些学术影响力分析能力：",
        "1. 查找哪些论文引用了目标论文",
        "2. 列出候选引用论文，并查看当前下载/分析状态",
        "3. 下载指定论文，或批量下载前几篇",
        "4. 对指定论文做全文引用分析",
        "5. 追问某篇论文是怎么引用目标论文的",
        "6. 绑定本地 PDF 后继续做全文分析",
        "",
        "你可以直接这样说：",
        "- 想知道有哪些论文引用了 Attention Is All You Need",
        "- 下载第2篇、第3篇",
        "- 全面分析前三篇论文",
        "- 论文P001引用目标论文时，引用了多长的段落？",
        "- 把 /path/to/file.pdf 绑定到 P004",
    ]
    return {
        "ok": True,
        "action": "show_capabilities",
        "text": "\n".join(lines),
    }


def find_context_for_title(contexts_data: dict, title: str):
    title_key = RUN_PIPELINE.normalize_title_key(title)
    for item in contexts_data.get("results", []):
        if RUN_PIPELINE.normalize_title_key(item.get("citing_title", "")) == title_key:
            return item
    return None


def probe_paper_downloadability(paper: dict):
    queries = RUN_PIPELINE.choose_download_queries(paper)
    attempts = []
    best = None

    for query in queries:
        probe = DOWNLOAD_PDF.probe_download(query)
        probe = dict(probe)
        probe["requested_via"] = query
        attempts.append(probe)
        if probe.get("ok") and probe.get("status") in {"local_available", "auto_downloadable"}:
            best = dict(probe)
            break
        if best is None and probe.get("ok"):
            best = dict(probe)

    if best is None:
        best = dict(attempts[-1]) if attempts else {
            "ok": False,
            "requested_via": "",
            "status": "probe_failed",
            "error": "未执行任何下载探测。"
        }

    best["attempts"] = attempts
    best["queries"] = queries
    return best


def load_session(session_dir: Path):
    session_path = session_dir / "session.json"
    if not session_path.exists():
        raise FileNotFoundError(f"未找到 session.json: {session_path}")
    session = read_json(session_path)
    session.setdefault("schema_version", SESSION_SCHEMA_VERSION)
    session.setdefault("session_kind", "academic_impact_analysis")
    session.setdefault("session_dir", str(session_dir))
    session.setdefault("paths", {})
    session.setdefault("analysis", {})
    session.setdefault("analysis_mode_last", None)
    session.setdefault("warnings", [])
    session.setdefault("papers", [])
    session.setdefault("paper_aliases", build_session_paper_aliases(session.get("papers", [])))
    session.setdefault("quick_analysis", default_quick_analysis(session))
    session.setdefault("quick_stats", default_quick_stats(session))
    session.setdefault("evidence_index", default_evidence_index())
    session.setdefault("person_candidates", [])
    session.setdefault("overview_stats", default_overview_stats())
    session["exports"] = merge_exports(session.get("exports"))
    ensure_analysis_templates(session)
    session.setdefault("exclusion_profile", {
        "extra_excluded_authors": [],
        "extra_excluded_affiliations": [],
    })
    session.setdefault("task_state", default_task_state())
    session["paper_count"] = len(session.get("papers", []))
    for item in session.get("papers", []):
        item.setdefault("download_queries", RUN_PIPELINE.choose_download_queries(item.get("paper", {})))
        item.setdefault("download_probe", default_download_probe(item.get("paper", {})))
        item.setdefault("analysis_result", {
            "status": None,
            "paths": {},
        })
        item.setdefault("selection", {
            "selected_for_download": False,
            "selected_for_analysis": False,
        })
        item.setdefault("qa_ready", False)
        item.setdefault("person_candidate_hits", [])
    return sync_session_derivatives(session_dir, session)


def save_session(session_dir: Path, session: dict):
    session["schema_version"] = SESSION_SCHEMA_VERSION
    session["session_kind"] = "academic_impact_analysis"
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    session["session_dir"] = str(session_dir)
    session["paper_count"] = len(session.get("papers", []))
    session["paper_aliases"] = build_session_paper_aliases(session.get("papers", []))
    session["quick_stats"] = SCHOLAR_STATS.build_quick_stats(session)
    session["exports"] = merge_exports(session.get("exports"))
    ensure_analysis_templates(session)
    session.setdefault("exclusion_profile", {
        "extra_excluded_authors": [],
        "extra_excluded_affiliations": [],
    })
    apply_qa_flags(session)
    write_json(session_dir / "session.json", session)
    build_phase1_export_payload(session_dir, session)


def build_discover_session(
    query: str,
    session_dir: Path,
    limit: int,
    probe_downloads: bool,
    auto_refresh_count: int = 0,
    sort_preference: str = "context",
):
    session_dir.mkdir(parents=True, exist_ok=True)
    existing_session = {}
    session_path = session_dir / "session.json"
    if session_path.exists():
        try:
            existing_session = read_json(session_path)
        except Exception:
            existing_session = {}
    normalized_sort = (sort_preference or "context").strip().lower()
    fetch_limit = max(limit, auto_refresh_count or 0, 20)
    list_result = LIST_PAPERS.list_all_citations(
        query,
        limit=max(100, fetch_limit),
        sort_by="recent",
        fetch_limit=max(100, min(max(fetch_limit * 5, 100), 500)),
    )
    write_json(session_dir / "list_papers.json", list_result)
    if not list_result.get("ok"):
        return list_result

    warnings = []
    if env_flag("ACADEMIC_IMPACT_CONTEXTS_ENABLED", default=False):
        try:
            contexts_result = FETCH_CONTEXTS.get_citation_contexts(query)
        except Exception as exc:
            contexts_result = {
                "ok": False,
                "query": query,
                "results": [],
                "error": str(exc),
            }
            warnings.append(
                "citation contexts 拉取失败，当前先返回引用论文列表；如需上下文级置信度和快速分析，可稍后重试。"
            )
    else:
        contexts_result = {
            "ok": False,
            "query": query,
            "results": [],
            "skipped": True,
            "message": "citation contexts 默认关闭；全文分析会直接基于 PDF/候选段落运行。",
        }
    write_json(session_dir / "contexts.json", contexts_result)

    target = list_result.get("target", {})
    if normalized_sort == "recent":
        reordered_papers = sort_papers_by_recent(list_result.get("papers", []))
    else:
        reordered_papers = RUN_PIPELINE.reorder_papers_by_context_signal(
            list_result.get("papers", []),
            contexts_result if isinstance(contexts_result, dict) else {},
        )

    entries = []
    for index, paper in enumerate(reordered_papers[:limit], start=1):
        paper_id = f"P{index:03d}"
        context_item = find_context_for_title(contexts_result, paper.get("title", "")) if isinstance(contexts_result, dict) else None
        download_probe = probe_paper_downloadability(paper) if probe_downloads else default_download_probe(paper)
        entries.append({
            "id": paper_id,
            "title": paper.get("title", ""),
            "year": paper.get("year"),
            "venue": paper.get("venue"),
            "authors": paper.get("authors", []),
            "externalIds": paper.get("externalIds", {}),
            "download_queries": RUN_PIPELINE.choose_download_queries(paper),
            "download_probe": download_probe,
            "best_context": context_item.get("best_context") if context_item else None,
            "context_confidence": context_item.get("confidence") if context_item else None,
            "context_count": len(context_item.get("contexts", [])) if context_item else 0,
            "analysis_result": {
                "status": None,
                "paths": {},
            },
            "selection": {
                "selected_for_download": False,
                "selected_for_analysis": False,
            },
            "paper": paper,
        })

    session = {
        "ok": True,
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_kind": "academic_impact_analysis",
        "query": query,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": target,
        "paths": {
            "list_papers": str(session_dir / "list_papers.json"),
            "contexts": str(session_dir / "contexts.json"),
        },
        "paper_count": len(entries),
        "displayed_paper_count": len(entries),
        "total_citation_count": target.get("citationCount"),
        "papers": entries,
        "paper_aliases": build_session_paper_aliases(entries),
        "quick_analysis": default_quick_analysis({"query": query}),
        "quick_stats": default_quick_stats({"query": query, "target": target}),
        "evidence_index": default_evidence_index(),
        "analysis_mode_last": "list",
        "warnings": warnings,
        "list_preferences": {
            "sort_preference": normalized_sort,
            "requested_limit": max(1, int(limit)),
        },
        "auto_refresh": {
            "requested_count": max(0, int(auto_refresh_count or 0)),
            "refreshed_count": 0,
            "refreshed_ids": [],
        },
        "task_state": existing_session.get("task_state", default_task_state()),
    }
    save_session(session_dir, session)

    refresh_limit = min(len(entries), max(0, int(auto_refresh_count or 0)))
    if not probe_downloads and refresh_limit > 0:
        refresh_ids = [item.get("id") for item in entries[:refresh_limit] if item.get("id")]
        if refresh_ids:
            refresh_result = refresh_probes(session_dir=session_dir, ids=refresh_ids, force=False)
            session = load_session(session_dir)
            session["auto_refresh"] = {
                "requested_count": max(0, int(auto_refresh_count or 0)),
                "refreshed_count": refresh_result.get("refreshed_count", 0),
                "refreshed_ids": refresh_ids,
            }
            save_session(session_dir, session)
    return session


def attach_local_pdf(session_dir: Path, paper_id: str, file_path: str):
    session = load_session(session_dir)
    paper_id = str(paper_id or "").strip().upper()
    source_path = Path(file_path).expanduser()
    if not paper_id:
        raise ValueError("attach-pdf 需要 paper_id。")
    if not source_path.exists():
        raise FileNotFoundError(f"未找到 PDF 文件: {source_path}")
    if source_path.suffix.lower() != ".pdf":
        raise ValueError("当前只支持绑定 .pdf 文件。")
    authenticity = DOWNLOAD_PDF.inspect_pdf_file(str(source_path))
    if not authenticity.get("ok"):
        error_type = authenticity.get("error_type", "downloaded_non_pdf")
        raise ValueError(f"绑定失败：{error_type}。{authenticity.get('error', '该文件不是真实 PDF。')}")

    item = next((paper for paper in session.get("papers", []) if paper.get("id") == paper_id), None)
    if item is None:
        raise ValueError(f"当前会话里不存在 {paper_id}。")

    target_title = item.get("title") or paper_id
    target_name = f"{DOWNLOAD_PDF.sanitize_filename(target_title)}.pdf"
    preferred_dir = Path(DOWNLOAD_PDF.DEFAULT_LOCAL_PDF_DIR).expanduser()
    fallback_dir = session_dir / "uploads"
    target_path = None
    copy_errors = []
    for base_dir in [preferred_dir, fallback_dir]:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            candidate_path = base_dir / target_name
            if source_path.resolve() != candidate_path.resolve():
                shutil.copy2(source_path, candidate_path)
            target_path = candidate_path
            break
        except Exception as exc:
            copy_errors.append(f"{base_dir}: {exc}")
    if target_path is None:
        raise RuntimeError("无法保存上传的 PDF：" + " | ".join(copy_errors))

    item.setdefault("selection", {})
    item["selection"]["selected_for_download"] = True
    item["download_probe"] = {
        "ok": True,
        "status": "local_available",
        "source": "manual_upload",
        "queries": RUN_PIPELINE.choose_download_queries(item.get("paper", {})),
        "attempts": [],
        "candidate_count": 1,
        "local_file_path": str(target_path),
        "pdf_candidates": [str(target_path)],
        "error": None,
    }
    item["download_result"] = {
        "ok": True,
        "query": target_title,
        "title": target_title,
        "pdf_url": "",
        "pdf_candidates": [str(target_path)],
        "file_path": str(target_path),
        "source": "manual_upload",
    }
    save_session(session_dir, session)
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "paper_id": paper_id,
        "title": target_title,
        "file_path": str(target_path),
        "status": "local_available",
    }


def refresh_probes(session_dir: Path, ids: List[str], force: bool):
    session = load_session(session_dir)
    selected_ids = set(ids)
    refreshed = []
    for item in session.get("papers", []):
        if selected_ids and item["id"] not in selected_ids:
            continue
        if not force and item.get("download_probe", {}).get("status") == "local_available":
            continue
        item["download_probe"] = probe_paper_downloadability(item.get("paper", {}))
        refreshed.append({
            "id": item["id"],
            "title": item.get("title"),
            "download_status": item.get("download_probe", {}).get("status"),
            "local_file_path": item.get("download_probe", {}).get("local_file_path"),
            "candidate_count": item.get("download_probe", {}).get("candidate_count"),
        })
    save_session(session_dir, session)
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "refreshed_count": len(refreshed),
        "refreshed": refreshed,
    }


def run_downloads(session_dir: Path, ids: List[str], auto_only: bool):
    session = load_session(session_dir)
    selected_ids = set(ids)
    papers = session.get("papers", [])
    updated = []
    for item in papers:
        if selected_ids and item["id"] not in selected_ids:
            continue
        if auto_only and item.get("download_probe", {}).get("status") != "auto_downloadable":
            continue
        item.setdefault("selection", {})
        item["selection"]["selected_for_download"] = True

        attempts = []
        final_result = None
        if (
            item.get("download_probe", {}).get("status") == "local_available"
            and item.get("download_probe", {}).get("local_file_path")
        ):
            final_result = {
                "ok": True,
                "requested_via": item.get("title", ""),
                "source": item.get("download_probe", {}).get("source") or "local_available",
                "file_path": item.get("download_probe", {}).get("local_file_path"),
                "pdf_candidates": item.get("download_probe", {}).get("pdf_candidates", []),
            }
        for query in item.get("download_queries", []):
            if final_result is not None:
                break
            result = DOWNLOAD_PDF.download_paper(query)
            result = dict(result)
            result["requested_via"] = query
            attempts.append(result)
            if result.get("ok"):
                final_result = dict(result)
                break

        if final_result is None:
            final_result = dict(attempts[-1]) if attempts else {
                "ok": False,
                "requested_via": "",
                "error": "未执行任何下载尝试。"
            }
        final_result["attempts"] = attempts
        item["download_result"] = final_result
        item["download_probe"] = {
            "ok": True if final_result.get("ok") else item.get("download_probe", {}).get("ok", False),
            "status": "local_available" if final_result.get("ok") else item.get("download_probe", {}).get("status"),
            "source": final_result.get("source", item.get("download_probe", {}).get("source")),
            "local_file_path": final_result.get("file_path"),
            "candidate_count": len(final_result.get("pdf_candidates", [])),
            "pdf_candidates": final_result.get("pdf_candidates", []),
        } if final_result.get("ok") else item.get("download_probe", {})
        updated.append({
            "id": item["id"],
            "title": item["title"],
            "ok": final_result.get("ok"),
            "source": final_result.get("source", ""),
            "file_path": final_result.get("file_path"),
            "error": final_result.get("error"),
        })

    save_session(session_dir, session)
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "updated_count": len(updated),
        "updated": updated,
    }


def run_analysis(
    session_dir: Path,
    ids: List[str],
    top_k_spans: int,
    analysis_scope: str = "fulltext_direct",
    analysis_model_profile: str = "",
):
    analysis_scope = RUN_PIPELINE.normalize_analysis_scope(analysis_scope)
    session = load_session(session_dir)
    resolved_model_profile = normalize_analysis_model_profile(
        analysis_model_profile or session_analysis_model_profile(session)
    )
    set_session_analysis_model_profile(session, resolved_model_profile)
    contexts_data = read_json(session_dir / "contexts.json")
    target = session.get("target", {})
    papers = session.get("papers", [])
    selected_ids = set(ids)
    template_prompt_fragment = EVIDENCE_TEMPLATES.build_template_prompt_fragment(
        (ensure_analysis_templates(session).get("compiled_templates") or [])
    )

    results = []
    for item in papers:
        if selected_ids and item["id"] not in selected_ids:
            continue
        item.setdefault("selection", {})
        item["selection"]["selected_for_analysis"] = True
        paper = item.get("paper", {})
        item_dir = session_dir / "analysis" / f"{item['id']}_{RUN_PIPELINE.slugify(item.get('title', ''))}"
        paper_result = RUN_PIPELINE.process_citing_paper(
            target=target,
            citing_paper=paper,
            contexts_data=contexts_data if isinstance(contexts_data, dict) else {},
            item_dir=item_dir,
            top_k_spans=top_k_spans,
            local_pdf_path=item.get("download_probe", {}).get("local_file_path") or "",
            analysis_scope=analysis_scope,
            analysis_model_profile=resolved_model_profile,
            template_prompt_fragment=template_prompt_fragment,
        )
        paper_result["id"] = item["id"]
        paper_result["paper_id"] = item["id"]
        paper_result["analysis_status"] = paper_result.get("status")
        item["analysis_result"] = {
            "status": paper_result.get("status"),
            "paths": paper_result.get("paths", {}),
        }
        results.append(paper_result)

    summary = {
        "ok": True,
        "query": session.get("query", ""),
        "target": target,
        "output_dir": str(session_dir / "analysis"),
        "processed_papers": len(results),
        "analysis_scope": analysis_scope,
        "analysis_model_profile": resolved_model_profile,
        "results": results,
    }
    summary_path = session_dir / "analysis" / "summary.json"
    write_json(summary_path, summary)
    report = AGGREGATE_REPORT.build_report(summary)
    report_json_path, report_md_path = AGGREGATE_REPORT.write_outputs(session_dir / "analysis", report)
    session["analysis"] = {
        "summary_path": str(summary_path),
        "report_json_path": str(report_json_path),
        "report_md_path": str(report_md_path),
        "processed_papers": len(results),
        "analysis_scope": analysis_scope,
        "analysis_model_profile": resolved_model_profile,
    }
    session["analysis_mode_last"] = "full"
    sync_session_derivatives(session_dir, session, update_evidence=True)
    save_session(session_dir, session)
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "processed_papers": len(results),
        "summary_path": str(summary_path),
        "report_json_path": str(report_json_path),
        "report_md_path": str(report_md_path),
    }


def review_person_candidate(session_dir: Path, candidate_id: str, action: str, note: str = ""):
    session = load_session(session_dir)
    normalized_action = (action or "").strip().lower()
    if normalized_action not in {"confirm", "reject", "reset"}:
        raise ValueError(f"不支持的人物候选操作: {action}")
    matched = None
    for candidate in session.get("person_candidates", []):
        if candidate.get("candidate_id") != candidate_id:
            continue
        matched = candidate
        if normalized_action == "confirm":
            candidate["status"] = "confirmed"
        elif normalized_action == "reject":
            candidate["status"] = "rejected"
        else:
            candidate["status"] = "pending"
        candidate["review_note"] = (note or "").strip()
        candidate["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
        break
    if matched is None:
        raise ValueError(f"未找到人物候选: {candidate_id}")
    session["overview_stats"] = build_overview_stats(session)
    save_session(session_dir, session)
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "candidate_id": candidate_id,
        "status": matched.get("status"),
    }


def _single_paper_card_sentence(card: dict) -> str:
    labels = "、".join(card.get("labels") or []) or "强引用"
    citing_title = card.get("citing_title") or "引用论文"
    target_title = card.get("target_title") or "目标论文"
    return f"{citing_title} 对 {target_title} 形成{labels}证据，可作为可汇报引用评价。"


def build_highlight_cards_from_papers(
    papers: List[dict],
    *,
    target_title: str = "",
    limit: int = 30,
) -> List[dict]:
    cards = []
    for paper in papers:
        summary = paper.get("citation_method_summary") or {}
        for finding in summary.get("reportable_strong_evidence") or []:
            raw_labels = finding.get("evidence_labels") or []
            labels = finding.get("evidence_label_names") or [
                SCHOLAR_EVIDENCE.evidence_label_display(label)
                for label in raw_labels
            ]
            card = {
                "index": 0,
                "paper_id": paper.get("id"),
                "headline": f"{paper.get('title') or '引用论文'} 引用并评价目标论文",
                "citing_title": paper.get("title") or "",
                "citing_venue": paper.get("venue") or "",
                "citing_year": paper.get("year") or "",
                "target_title": target_title,
                "labels": labels,
                "raw_labels": raw_labels,
                "score": finding.get("strong_citation_score") or 0,
                "evidence_strength": finding.get("evidence_strength") or "",
                "self_citation_status": finding.get("self_citation_status") or "unknown",
                "self_citation_label": finding.get("self_citation_label") or "",
                "important_person": " / ".join(finding.get("person_tag_labels") or []),
                "evidence_excerpt": finding.get("citation_text") or "",
                "highlight_keywords": finding.get("highlight_keywords") or [],
                "highlighted_evidence_excerpt": finding.get("highlighted_citation_text") or "",
                "why_valuable": finding.get("valuable_reason") or finding.get("reason") or "",
                "page": finding.get("page"),
                "span_index": finding.get("span_index"),
            }
            card["report_sentence"] = _single_paper_card_sentence(card)
            cards.append(card)
    cards = sorted(
        cards,
        key=lambda item: (
            -(item.get("score") or 0),
            item.get("citing_title") or "",
            item.get("page") or 0,
        ),
    )[:limit]
    for index, card in enumerate(cards, 1):
        card["index"] = index
    return cards


def render_highlight_cards_csv(cards: List[dict]) -> str:
    headers = [
        "index",
        "paper_id",
        "headline",
        "citing_title",
        "citing_venue",
        "citing_year",
        "labels",
        "score",
        "evidence_strength",
        "self_citation_status",
        "important_person",
        "page",
        "evidence_excerpt",
        "highlight_keywords",
        "why_valuable",
        "report_sentence",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for card in cards:
        row = dict(card)
        row["labels"] = " | ".join(card.get("labels") or [])
        row["highlight_keywords"] = " | ".join(card.get("highlight_keywords") or [])
        writer.writerow({key: row.get(key, "") for key in headers})
    return buffer.getvalue()


def render_highlight_cards_markdown(cards: List[dict]) -> str:
    lines = ["# 亮点评价卡片", ""]
    if not cards:
        lines.append("暂无可导出的亮点评价卡片。")
        return "\n".join(lines).rstrip() + "\n"
    for card in cards:
        excerpt = str(card.get("evidence_excerpt") or "").strip()
        if len(excerpt) > 600:
            excerpt = f"{excerpt[:600]}..."
        lines.extend(
            [
                f"### {card.get('index')}. {card.get('headline') or '-'}",
                "",
                f"- 引用论文：{card.get('citing_title') or '-'}",
                f"- 证据标签：{' / '.join(card.get('labels') or []) or '-'}",
                f"- 强度分：{card.get('score') if card.get('score') is not None else '-'}",
                f"- 自引状态：{card.get('self_citation_label') or card.get('self_citation_status') or '-'}",
                f"- 汇报句：{card.get('report_sentence') or '-'}",
                f"- 汇报价值：{card.get('why_valuable') or '-'}",
                "",
                "原文证据：",
                "",
                excerpt or "-",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_phase1_export_markdown(detail_payload: dict):
    overview = detail_payload.get("target_overview", {})
    person_summary = detail_payload.get("person_summary", {})
    quick_stats = detail_payload.get("quick_stats", default_quick_stats())
    publication_stats = quick_stats.get("publication_statistics", {})
    citation_stats = quick_stats.get("citation_statistics", {})
    lines = [
        "# 单篇论文引用分析报告",
        "",
        f"- 目标论文：{overview.get('title', '')}",
        f"- 查询：`{overview.get('query', '')}`",
        f"- 年份/会议：{overview.get('year') or '-'} / {overview.get('venue') or '-'}",
        f"- 总引用数：{overview.get('total_citation_count') or '-'}",
        f"- 当前候选论文数：{overview.get('paper_count', 0)}",
        "",
        "## 总览统计",
        "",
        f"- 已下载：{(overview.get('overview_stats') or {}).get('downloaded_count', 0)}",
        f"- 已分析：{(overview.get('overview_stats') or {}).get('analyzed_count', 0)}",
        f"- 人物候选：{(overview.get('overview_stats') or {}).get('candidate_people_count', 0)}",
        f"- 已确认人物：{(overview.get('overview_stats') or {}).get('confirmed_people_count', 0)}",
        "",
        "## 快速统计层",
        "",
        "- Publication Statistics",
        f"- 候选论文数：{publication_stats.get('paper_count', 0)}",
        f"- venue 已匹配等级：{publication_stats.get('matched_venue_count', 0)}",
        f"- venue 未匹配等级：{publication_stats.get('unmatched_venue_count', 0)}",
        f"- venue tier 分布：{json.dumps(publication_stats.get('venue_tier_counts', {}), ensure_ascii=False)}",
        "",
        "- Citation Statistics",
        f"- 元数据引用总数：{citation_stats.get('total_citation_count') or '-'}",
        f"- 当前展示引用数：{citation_stats.get('displayed_citation_count', 0)}",
        f"- 上下文置信度分布：{json.dumps(citation_stats.get('context_confidence_counts', {}), ensure_ascii=False)}",
        f"- 人物候选状态分布：{json.dumps(citation_stats.get('person_status_counts', {}), ensure_ascii=False)}",
        "",
        f"- 说明：{quick_stats.get('disclaimer', '')}",
        "",
        "## 人物候选统计",
        "",
        f"- Pending：{person_summary.get('pending_count', 0)}",
        f"- Confirmed：{person_summary.get('confirmed_count', 0)}",
        f"- Rejected：{person_summary.get('rejected_count', 0)}",
        "",
        "## 统计信息",
        "",
        "### 引用作者身份统计",
        "",
    ]
    impact_statistics = detail_payload.get("impact_statistics", {})
    for group in (impact_statistics.get("person") or {}).get("groups", []):
        lines.append(
            f"- {group.get('label')}：{group.get('count', 0)} 人"
            f"（候选人物 {group.get('candidate_count', 0)}，多重碰撞 {group.get('ambiguous_author_count', 0)}，"
            f"高风险 {group.get('high_risk_author_count', 0)}，已确认 {group.get('confirmed_count', 0)}，"
            f"待确认 {group.get('pending_count', 0)}）"
        )
        for candidate in group.get("candidates", [])[:8]:
            paper_ids = ", ".join(candidate.get("matched_paper_ids", [])) or "-"
            lines.append(
                f"  - {candidate.get('name')} | {candidate.get('status')} | 命中论文：{paper_ids}"
            )
    lines.extend([
        "",
        "### 引用方式统计",
        "",
    ])
    for group in (impact_statistics.get("citation_methods") or {}).get("groups", []):
        lines.append(f"- {group.get('label')}：{group.get('count', 0)} 篇")
        for cited_item in group.get("items", [])[:8]:
            lines.append(f"  - {cited_item.get('id')} {cited_item.get('title')}")
    lines.extend([
        "",
        "## 亮点评价卡片",
        "",
    ])
    highlight_cards = detail_payload.get("highlight_cards") or []
    if not highlight_cards:
        lines.append("暂无可汇报的强引用证据。")
    for card in highlight_cards[:10]:
        lines.extend(
            [
                f"### {card.get('index')}. {card.get('headline') or '-'}",
                f"- 引用论文：{card.get('citing_title') or '-'}",
                f"- 证据标签：{' / '.join(card.get('labels') or []) or '-'}",
                f"- 强度分：{card.get('score') if card.get('score') is not None else '-'}",
                f"- 汇报句：{card.get('report_sentence') or '-'}",
                f"- 原文证据：{truncate_text(card.get('evidence_excerpt') or '', limit=360) or '-'}",
                "",
            ]
        )
    lines.extend([
        "",
        "## 深度语义分析结果",
        "",
    ])
    for item in detail_payload.get("papers", []):
        summary = item.get("citation_method_summary", {})
        labels = " / ".join(summary.get("labels", [])) or "-"
        page_start = summary.get("page_start") or "-"
        page_end = summary.get("page_end") or page_start
        lines.extend(
            [
                f"### {item.get('id')} {item.get('title', '')}",
                f"- 年份/会议：{item.get('year') or '-'} / {item.get('venue') or '-'}",
                f"- 下载状态：{item.get('download_status') or '-'}",
                f"- 分析状态：{item.get('analysis_status') or '-'}",
                f"- 引用方式标签：{labels}",
                f"- 页码范围：{page_start} - {page_end}",
                f"- 引用次数：{summary.get('citation_occurrence_count', 0)}",
                f"- 连续引用段数：{summary.get('continuous_mention_count', 0)}",
                f"- 首次/强表述命中：{'是' if summary.get('first_claim_hit') else '否'}",
            ]
        )
        analysis_reason = item.get("analysis_reason") or summary.get("analysis_reason") or {}
        if analysis_reason.get("tags"):
            lines.append(f"- 当前限制标签：{' / '.join(analysis_reason.get('tags', []))}")
        if analysis_reason.get("message"):
            lines.append(f"- 当前限制说明：{analysis_reason.get('message')}")
        for error in analysis_reason.get("errors", [])[:3]:
            lines.append(f"- 失败原因：{error}")
        if summary.get("evidence_excerpt"):
            lines.append(f"- 证据片段：{summary.get('evidence_excerpt')}")
        if item.get("person_candidate_hits"):
            lines.append("- 命中的人物候选：")
            for hit in item.get("person_candidate_hits", []):
                lines.append(
                    f"  - {hit.get('name')} | {hit.get('tag_label')} | {hit.get('status')}"
                )
        lines.append("")
    confirmed_candidates = [
        item for item in detail_payload.get("person_candidates", []) if item.get("status") == "confirmed"
    ]
    if confirmed_candidates:
        lines.extend(["## 已确认人物候选", ""])
        for item in confirmed_candidates:
            links = "、".join(item.get("source_links", [])[:3]) or "-"
            lines.append(f"- {item.get('name')} | {item.get('tag_label')} | 来源：{links}")
    return "\n".join(lines).rstrip() + "\n"


def build_phase1_export_payload(session_dir: Path, session: dict):
    export_dir = session_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = export_dir / "phase1_report.md"
    structured_json_path = export_dir / "phase1_structured.json"
    highlight_cards_csv_path = export_dir / "highlight_cards.csv"
    highlight_cards_md_path = export_dir / "highlight_cards.md"
    session["exports"] = {
        "report_md_path": str(markdown_path),
        "structured_json_path": str(structured_json_path),
        "highlight_cards_csv_path": str(highlight_cards_csv_path),
        "highlight_cards_md_path": str(highlight_cards_md_path),
    }
    detail_payload = build_session_detail_payload(session)
    detail_payload["exports"] = dict(session["exports"])
    highlight_cards = detail_payload.get("highlight_cards") or []
    markdown_path.write_text(render_phase1_export_markdown(detail_payload), encoding="utf-8")
    highlight_cards_csv_path.write_text(render_highlight_cards_csv(highlight_cards), encoding="utf-8-sig")
    highlight_cards_md_path.write_text(render_highlight_cards_markdown(highlight_cards), encoding="utf-8")
    structured_json_path.write_text(
        json.dumps(detail_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_json(session_dir / "session.json", session)
    return detail_payload


def run_quick_analysis(session_dir: Path):
    session = load_session(session_dir)
    session["analysis_mode_last"] = "quick"
    sync_session_derivatives(session_dir, session, update_quick=True)
    save_session(session_dir, session)
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "quick_analysis": session.get("quick_analysis", {}),
    }


def run_full_analysis_workflow(session_dir: Path, refresh_top_n: int = 5, top_k_spans: int = 8, analysis_scope: str = "fulltext_direct"):
    session = load_session(session_dir)
    refresh_ids = [item.get("id") for item in session.get("papers", [])[: max(0, refresh_top_n)] if item.get("id")]
    refresh_result = {
        "ok": True,
        "session_dir": str(session_dir),
        "refreshed_count": 0,
        "refreshed": [],
    }
    if refresh_ids:
        refresh_result = refresh_probes(session_dir=session_dir, ids=refresh_ids, force=False)

    session = load_session(session_dir)
    auto_download_ids = [
        item.get("id")
        for item in session.get("papers", [])[: max(0, refresh_top_n)]
        if item.get("download_probe", {}).get("status") == "auto_downloadable" and item.get("id")
    ]
    download_result = {
        "ok": True,
        "session_dir": str(session_dir),
        "updated_count": 0,
        "updated": [],
    }
    if auto_download_ids:
        download_result = run_downloads(session_dir=session_dir, ids=auto_download_ids, auto_only=False)

    session = load_session(session_dir)
    analyze_ids = [
        item.get("id")
        for item in session.get("papers", [])
        if item.get("download_probe", {}).get("status") == "local_available" and item.get("id")
    ]
    analyze_result = {
        "ok": True,
        "session_dir": str(session_dir),
        "processed_papers": 0,
        "summary_path": "",
        "report_json_path": "",
        "report_md_path": "",
    }
    if analyze_ids:
        analyze_result = run_analysis(
            session_dir=session_dir,
            ids=analyze_ids,
            top_k_spans=max(1, top_k_spans),
            analysis_scope=analysis_scope,
        )

    session = load_session(session_dir)
    session["analysis_mode_last"] = "full"
    sync_session_derivatives(session_dir, session, update_quick=True, update_evidence=True)
    save_session(session_dir, session)

    manual_required_titles = [
        item.get("title")
        for item in session.get("papers", [])
        if item.get("download_probe", {}).get("status") == "manual_required"
    ]
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "refresh": refresh_result,
        "download": download_result,
        "analysis": analyze_result,
        "quick_analysis": session.get("quick_analysis", {}),
        "quick_stats": session.get("quick_stats", {}),
        "evidence_index": session.get("evidence_index", {}),
        "manual_required_titles": manual_required_titles,
    }


def print_discover_summary(session: dict):
    payload = {
        "ok": True,
        "query": session.get("query", ""),
        "schema_version": session.get("schema_version", SESSION_SCHEMA_VERSION),
        "target": session.get("target", {}),
        "paper_count": session.get("paper_count", 0),
        "displayed_paper_count": session.get("paper_count", 0),
        "total_citation_count": ((session.get("target") or {}).get("citationCount")),
        "session_path": str(Path(session.get("paths", {}).get("list_papers", "")).parent / "session.json"),
        "papers": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "year": item.get("year"),
                "download_status": item.get("download_probe", {}).get("status"),
                "local_file_path": item.get("download_probe", {}).get("local_file_path"),
                "candidate_count": item.get("download_probe", {}).get("candidate_count"),
                "context_confidence": item.get("context_confidence"),
                "best_context": (item.get("best_context", {}) or {}).get("text", ""),
            }
            for item in session.get("papers", [])
        ]
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_status_payload(session: dict):
    papers = session.get("papers", [])
    counts = {
        "local_available": 0,
        "auto_downloadable": 0,
        "manual_required": 0,
        "not_probed": 0,
        "analysis_ready": 0,
    }
    items = []
    for item in papers:
        probe_status = item.get("download_probe", {}).get("status", "not_probed")
        counts[probe_status] = counts.get(probe_status, 0) + 1
        if probe_status == "local_available":
            counts["analysis_ready"] += 1
        items.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "download_status": probe_status,
            "local_file_path": item.get("download_probe", {}).get("local_file_path"),
            "candidate_count": item.get("download_probe", {}).get("candidate_count"),
            "analysis_status": item.get("analysis_result", {}).get("status"),
            "context_confidence": item.get("context_confidence"),
            "qa_ready": item.get("qa_ready", False),
        })
    return {
        "ok": True,
        "query": session.get("query", ""),
        "schema_version": session.get("schema_version", SESSION_SCHEMA_VERSION),
        "target": session.get("target", {}),
        "session_dir": session.get("session_dir", ""),
        "paper_count": len(papers),
        "displayed_paper_count": len(papers),
        "total_citation_count": (session.get("target") or {}).get("citationCount"),
        "analysis_mode": session.get("analysis_mode_last"),
        "task_state": session.get("task_state", default_task_state()),
        "warnings": session.get("warnings", []),
        "list_preferences": session.get("list_preferences", {}),
        "download_status_counts": counts,
        "analysis": session.get("analysis", {}),
        "quick_analysis": session.get("quick_analysis", default_quick_analysis(session)),
        "quick_stats": session.get("quick_stats", default_quick_stats(session)),
        "evidence_index": session.get("evidence_index", default_evidence_index()),
        "overview_stats": session.get("overview_stats", default_overview_stats()),
        "person_candidates": session.get("person_candidates", []),
        "exports": merge_exports(session.get("exports")),
        "papers": items,
    }


def build_session_detail_payload(session: dict, filters: Optional[dict] = None):
    filters = filters or {}
    status_payload = build_status_payload(session)
    quick_stats = status_payload.get("quick_stats", default_quick_stats(session))
    venue_match_map = {
        item.get("paper_id"): item
        for item in quick_stats.get("venue_matches", [])
        if isinstance(item, dict) and item.get("paper_id")
    }
    target = status_payload.get("target", {})
    paper_lookup = {item.get("id"): item for item in session.get("papers", [])}
    venue_tier_index = build_venue_tier_index()
    analysis_templates = ensure_analysis_templates(session)
    compiled_templates = analysis_templates.get("compiled_templates") or []
    detail_papers = []
    for item in status_payload.get("papers", []):
        raw_item = paper_lookup.get(item.get("id"), {})
        citation_summary = summarize_citation_method(
            raw_item,
            target=target,
            exclusion_profile=session.get("exclusion_profile"),
            compiled_templates=compiled_templates,
        )
        venue_tier = classify_venue_tier(raw_item.get("venue"), venue_tier_index)
        paper_payload = {
            "id": item.get("id"),
            "title": item.get("title"),
            "year": raw_item.get("year"),
            "venue": raw_item.get("venue"),
            "venue_tier": venue_tier,
            "download_status": item.get("download_status"),
            "download_status_label": _status_label(item.get("download_status")),
            "analysis_status": item.get("analysis_status"),
            "analysis_status_label": ANALYSIS_STATUS_LABELS.get(item.get("analysis_status"), item.get("analysis_status") or "-"),
            "context_confidence": item.get("context_confidence"),
            "qa_ready": item.get("qa_ready", False),
            "candidate_count": len(raw_item.get("person_candidate_hits", [])),
            "citation_method_summary": citation_summary,
            "analysis_reason": citation_summary.get("analysis_reason"),
            "person_candidate_hits": raw_item.get("person_candidate_hits", []),
        }
        download_filter = (filters.get("download_status") or "").strip()
        analysis_filter = (filters.get("analysis_status") or "").strip()
        strong_only = str(filters.get("strong_only") or "").strip().lower() in {"1", "true", "on", "yes"}
        template_only = str(filters.get("template_only") or "").strip().lower() in {"1", "true", "on", "yes"}
        candidate_only = str(filters.get("candidate_only") or "").strip().lower() in {"1", "true", "on", "yes"}
        if download_filter and paper_payload["download_status"] != download_filter:
            continue
        if analysis_filter and paper_payload["analysis_status"] != analysis_filter:
            continue
        if strong_only and not citation_summary.get("reportable_strong_evidence_count"):
            continue
        if template_only and not citation_summary.get("template_match_count"):
            continue
        if candidate_only and not paper_payload.get("candidate_count"):
            continue
        detail_papers.append(paper_payload)

    total_filtered_papers = len(detail_papers)
    highlight_cards = build_highlight_cards_from_papers(
        detail_papers,
        target_title=target.get("title", ""),
    )
    try:
        page_size = int(filters.get("page_size") or 20)
    except (TypeError, ValueError):
        page_size = 20
    page_size = min(max(page_size, 5), 100)
    total_pages = max(1, (total_filtered_papers + page_size - 1) // page_size)
    try:
        page = int(filters.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    page = min(max(page, 1), total_pages)
    page_start = (page - 1) * page_size
    page_end = page_start + page_size
    paged_detail_papers = detail_papers[page_start:page_end]
    pagination_query_base = {
        "page_size": page_size,
    }
    download_status_filter = (filters.get("download_status") or "").strip()
    analysis_status_filter = (filters.get("analysis_status") or "").strip()
    if download_status_filter:
        pagination_query_base["download_status"] = download_status_filter
    if analysis_status_filter:
        pagination_query_base["analysis_status"] = analysis_status_filter
    if str(filters.get("strong_only") or "").strip().lower() in {"1", "true", "on", "yes"}:
        pagination_query_base["strong_only"] = "on"
    if str(filters.get("template_only") or "").strip().lower() in {"1", "true", "on", "yes"}:
        pagination_query_base["template_only"] = "on"
    if str(filters.get("candidate_only") or "").strip().lower() in {"1", "true", "on", "yes"}:
        pagination_query_base["candidate_only"] = "on"

    def make_page_query(target_page: int) -> str:
        query_params = dict(pagination_query_base)
        query_params["page"] = target_page
        return urlencode(query_params)

    confirmed_candidates = [item for item in status_payload.get("person_candidates", []) if item.get("status") == "confirmed"]
    pending_candidates = [item for item in status_payload.get("person_candidates", []) if item.get("status") == "pending"]
    rejected_candidates = [item for item in status_payload.get("person_candidates", []) if item.get("status") == "rejected"]
    venue_statistics = build_venue_statistics(session.get("papers", []), venue_tier_index)
    person_tag_statistics = build_person_tag_statistics(status_payload.get("person_candidates", []))

    return {
        "target_overview": {
            "title": target.get("title", ""),
            "query": status_payload.get("query", ""),
            "year": target.get("year"),
            "venue": target.get("venue"),
            "doi": (target.get("externalIds") or {}).get("DOI", ""),
            "arxiv": (target.get("externalIds") or {}).get("ArXiv", ""),
            "total_citation_count": status_payload.get("total_citation_count"),
            "paper_count": status_payload.get("paper_count", 0),
            "overview_stats": status_payload.get("overview_stats", default_overview_stats()),
            "warnings": status_payload.get("warnings", []),
            "updated_at": session.get("updated_at") or session.get("created_at"),
        },
        "task_state": status_payload.get("task_state", default_task_state()),
        "paper_filters": {
            "download_status_counts": status_payload.get("download_status_counts", {}),
            "analysis_mode": status_payload.get("analysis_mode"),
            "active": {
                "download_status": (filters.get("download_status") or "").strip(),
                "analysis_status": (filters.get("analysis_status") or "").strip(),
                "strong_only": str(filters.get("strong_only") or "").strip().lower() in {"1", "true", "on", "yes"},
                "template_only": str(filters.get("template_only") or "").strip().lower() in {"1", "true", "on", "yes"},
                "candidate_only": str(filters.get("candidate_only") or "").strip().lower() in {"1", "true", "on", "yes"},
                "page_size": page_size,
            },
        },
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_filtered_papers,
            "total_pages": total_pages,
            "start": page_start + 1 if total_filtered_papers else 0,
            "end": min(page_end, total_filtered_papers),
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_page": page - 1 if page > 1 else 1,
            "next_page": page + 1 if page < total_pages else total_pages,
            "previous_query": make_page_query(page - 1 if page > 1 else 1),
            "next_query": make_page_query(page + 1 if page < total_pages else total_pages),
        },
        "quick_stats": quick_stats,
        "papers": paged_detail_papers,
        "highlight_cards": highlight_cards,
        "highlight_summary": {
            "card_count": len(highlight_cards),
            "high_strength_count": sum(
                1 for card in highlight_cards if card.get("evidence_strength") == "high"
            ),
        },
        "venue_statistics": venue_statistics,
        "person_tag_statistics": person_tag_statistics,
        "person_candidates": status_payload.get("person_candidates", []),
        "person_summary": {
            "pending_count": len(pending_candidates),
            "confirmed_count": len(confirmed_candidates),
            "rejected_count": len(rejected_candidates),
        },
        "exports": merge_exports(status_payload.get("exports")),
    }


def build_card_state_payload(session: dict):
    status_payload = build_status_payload(session)
    target = status_payload.get("target", {})
    card_items = []
    for item in status_payload.get("papers", []):
        download_status = item.get("download_status")
        analysis_status = item.get("analysis_status")
        card_items.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "badge": {
                "download_status": download_status,
                "analysis_status": analysis_status,
                "context_confidence": item.get("context_confidence"),
            },
            "actions": {
                "can_refresh_probe": True,
                "can_download": download_status in {"auto_downloadable", "local_available"},
                "can_analyze": download_status == "local_available",
            },
            "meta": {
                "local_file_path": item.get("local_file_path"),
                "candidate_count": item.get("candidate_count"),
                "qa_ready": item.get("qa_ready", False),
            }
        })

    return {
        "ok": True,
        "schema_version": status_payload.get("schema_version", SESSION_SCHEMA_VERSION),
        "card_schema_version": "1.0",
        "session_dir": status_payload.get("session_dir", ""),
        "header": {
            "title": target.get("title", ""),
            "subtitle": status_payload.get("query", ""),
            "paper_count": status_payload.get("paper_count", 0),
            "total_citation_count": status_payload.get("total_citation_count"),
        },
        "summary": status_payload.get("download_status_counts", {}),
        "items": card_items,
        "analysis": status_payload.get("analysis", {}),
        "analysis_mode": status_payload.get("analysis_mode"),
        "warnings": status_payload.get("warnings", []),
        "list_preferences": status_payload.get("list_preferences", {}),
        "quick_analysis": status_payload.get("quick_analysis", {}),
        "quick_stats": status_payload.get("quick_stats", default_quick_stats(session)),
        "qa_ready_count": status_payload.get("evidence_index", {}).get("qa_ready_count", 0),
        "next_actions": [
            "下载第2篇、第3篇",
            "全面分析这篇论文的影响力",
            "论文P001引用目标论文时，引用了多长的段落？",
        ],
    }


def build_markdown_session_summary(session: dict, *, max_items: int = 8, status_line: str = ""):
    card_state = build_card_state_payload(session)
    summary = card_state.get("summary", {})
    header = card_state.get("header", {})
    warnings = card_state.get("warnings", []) or []
    list_preferences = card_state.get("list_preferences", {}) or {}
    sort_preference = list_preferences.get("sort_preference") or "context"
    sort_label = "按最近年份排序" if sort_preference == "recent" else "按引用信号排序"

    lines = []
    if status_line:
        lines.append(status_line.strip())
        lines.append("")
    lines.append("## 学术影响力分析会话")
    lines.append(f"目标论文: {header.get('title') or '-'}")
    lines.append(f"原始查询: {header.get('subtitle') or '-'}")
    total_citation_count = header.get("total_citation_count")
    if total_citation_count:
        lines.append(f"真实总引用数: {total_citation_count}")
    lines.append(f"当前展示候选数: {header.get('paper_count', 0)}")
    lines.append(f"排序方式: {sort_label}")
    lines.append(f"会话目录: {card_state.get('session_dir') or '-'}")
    if warnings:
        lines.append(f"提示: {warnings[0]}")
    lines.append("")
    lines.append("状态概览:")
    lines.append(
        "本地可用 {local_available} | 可自动下载 {auto_downloadable} | 需手动下载 {manual_required} | "
        "待探测 {not_probed} | 可直接分析 {analysis_ready}".format(
            local_available=summary.get("local_available", 0),
            auto_downloadable=summary.get("auto_downloadable", 0),
            manual_required=summary.get("manual_required", 0),
            not_probed=summary.get("not_probed", 0),
            analysis_ready=summary.get("analysis_ready", 0),
        )
    )
    lines.append("")
    lines.append("| 编号 | 年份 | 下载状态 | 分析状态 | 置信度 | 标题 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in session.get("papers", [])[:max_items]:
        lines.append(
            f"| {item.get('id') or '-'} | {item.get('year') or '-'} | "
            f"{_status_label(item.get('download_probe', {}).get('status'))} | "
            f"{_status_label(item.get('analysis_result', {}).get('status'))} | "
            f"{_context_label(item.get('context_confidence'))} | {item.get('title') or '-'} |"
        )
    lines.append("")
    lines.append("下一步可直接说：下载第2篇、第3篇；或说：全面分析这篇论文的影响力。")
    return "\n".join(lines)


def build_feishu_command_text(action: str, session_dir: str, paper_id: str):
    """Legacy/Deprecated: retained only for historical Feishu card output compatibility."""
    if action == "refresh":
        return f"/paperimpact-refresh {session_dir} {paper_id}"
    if action == "download":
        return f"/paperimpact-download {session_dir} {paper_id}"
    if action == "analyze":
        return f"/paperimpact-analyze {session_dir} {paper_id}"
    raise ValueError(f"unknown feishu action: {action}")


def _status_label(status: str):
    mapping = {
        "local_available": "本地可用",
        "auto_downloadable": "可自动下载",
        "manual_required": "需手动下载",
        "not_probed": "待探测",
        "probe_failed": "探测失败",
        "fulltext_analyzed": "全文分析完成",
        "mention_only": "弱提及",
        "reference_only": "仅参考文献",
        "context_only": "仅上下文分析",
        "fulltext_extract_failed": "全文提取失败",
        "analysis_failed": "语义分析失败",
        "write_output_failed": "结果写出失败",
    }
    return mapping.get(status or "", status or "-")


def _context_label(confidence: str):
    mapping = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }
    return mapping.get(confidence or "", confidence or "-")


def build_feishu_card_payload(session: dict, max_items: int = 8):
    """Legacy/Deprecated: retained for historical Feishu card consumers; not part of the main Web path."""
    card_state = build_card_state_payload(session)
    session_dir = card_state.get("session_dir", "")
    summary = card_state.get("summary", {})
    header = card_state.get("header", {})

    elements = [
        {
            "tag": "markdown",
            "content": (
                f"**目标论文**：{header.get('title') or '-'}\n"
                f"**原始查询**：{header.get('subtitle') or '-'}\n"
                f"**真实总引用数**：{header.get('total_citation_count') or '未知'}\n"
                f"**当前展示候选数**：{header.get('paper_count', 0)}\n"
                f"**状态统计**：本地可用 {summary.get('local_available', 0)} ｜ "
                f"自动下载 {summary.get('auto_downloadable', 0)} ｜ "
                f"手动下载 {summary.get('manual_required', 0)} ｜ "
                f"待探测 {summary.get('not_probed', 0)}"
            ),
        },
        {"tag": "hr"},
    ]

    for item in card_state.get("items", [])[:max_items]:
        download_status = item.get("badge", {}).get("download_status")
        analysis_status = item.get("badge", {}).get("analysis_status")
        context_confidence = item.get("badge", {}).get("context_confidence")
        paper_id = item.get("id", "")
        title = item.get("title", "")
        buttons = []

        if item.get("actions", {}).get("can_refresh_probe"):
            buttons.append({
                "tag": "button",
                "type": "default",
                "text": {"tag": "plain_text", "content": "刷新状态"},
                "value": {"text": build_feishu_command_text("refresh", session_dir, paper_id)},
            })
        if item.get("actions", {}).get("can_download"):
            buttons.append({
                "tag": "button",
                "type": "primary",
                "text": {"tag": "plain_text", "content": "下载"},
                "value": {"text": build_feishu_command_text("download", session_dir, paper_id)},
            })
        if item.get("actions", {}).get("can_analyze"):
            buttons.append({
                "tag": "button",
                "type": "primary",
                "text": {"tag": "plain_text", "content": "分析"},
                "value": {"text": build_feishu_command_text("analyze", session_dir, paper_id)},
            })

        elements.append({
            "tag": "markdown",
            "content": (
                f"**{paper_id}** {title}\n"
                f"下载状态：{_status_label(download_status)} ｜ "
                f"分析状态：{_status_label(analysis_status)} ｜ "
                f"上下文置信度：{_context_label(context_confidence)}"
            ),
        })
        if buttons:
            elements.append({
                "tag": "action",
                "actions": buttons,
            })
        elements.append({"tag": "hr"})

    return {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "学术影响力分析",
            },
            "template": "blue",
        },
        "body": {
            "elements": elements,
        },
    }


def build_parser():
    parser = argparse.ArgumentParser(description="学术影响力分析交互式 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="发现 citing papers；默认快速返回，不同步探测下载状态")
    discover.add_argument("query", help="目标论文 DOI、arXiv 编号或标题")
    discover.add_argument("--session-dir", help="会话目录，默认写入工作区内 sessions/<时间戳>_<slug>")
    discover.add_argument("--limit", type=int, default=20, help="最多展示多少篇 citing papers，默认 20")
    discover.add_argument("--probe-downloads", action="store_true", help="同步探测下载能力；默认关闭以便快速返回")
    discover.add_argument("--auto-refresh-top", type=int, default=0, help="发现后自动刷新前 N 篇候选的下载状态，默认 0")

    status = sub.add_parser("status", help="查看会话状态")
    status.add_argument("session_dir", help="discover 阶段生成的会话目录")

    card_state = sub.add_parser("card-state", help="输出轻量状态摘要（legacy card consumer / 非 Web 主路径）")
    card_state.add_argument("session_dir", help="discover 阶段生成的会话目录")

    feishu_card = sub.add_parser("feishu-card", help="输出官方飞书卡片 JSON（legacy/deprecated）")
    feishu_card.add_argument("session_dir", help="discover 阶段生成的会话目录")
    feishu_card.add_argument("--max-items", type=int, default=8, help="最多渲染多少个 citing paper 卡片块")

    refresh = sub.add_parser("refresh-probe", help="刷新会话中的下载探测状态")
    refresh.add_argument("session_dir", help="discover 阶段生成的会话目录")
    refresh.add_argument("--ids", help="要刷新的论文 id，逗号分隔，例如 P001,P003")
    refresh.add_argument("--force", action="store_true", help="即使已经 local_available 也重新探测")

    download = sub.add_parser("download", help="下载会话中的选定论文")
    download.add_argument("session_dir", help="discover 阶段生成的会话目录")
    download.add_argument("--ids", help="要下载的论文 id，逗号分隔，例如 P001,P003")
    download.add_argument("--auto-only", action="store_true", help="只下载标注为 auto_downloadable 的论文")

    analyze = sub.add_parser("analyze", help="分析会话中的选定论文")
    analyze.add_argument("session_dir", help="discover 阶段生成的会话目录")
    analyze.add_argument("--ids", required=True, help="要分析的论文 id，逗号分隔，例如 P001,P003")
    analyze.add_argument("--top-k-spans", type=int, default=8, help="送入 analyze_fulltext 的候选段落数，默认 8")
    analyze.add_argument(
        "--analysis-scope",
        choices=sorted(RUN_PIPELINE.VALID_ANALYSIS_SCOPES),
        default="fulltext_direct",
        help="分析范围：fulltext_direct 为默认单篇全文直读模式，candidate_spans 为候选段落模式",
    )
    analyze.add_argument(
        "--analysis-model-profile",
        choices=[item["value"] for item in ANALYSIS_MODEL_OPTIONS],
        default="",
        help="分析模型：default 跟随环境配置，local 使用本地模型，deepseek 使用 DeepSeek。",
    )

    attach_pdf = sub.add_parser("attach-pdf", help="把本地 PDF 绑定到某篇候选论文，后续按 local_available 处理")
    attach_pdf.add_argument("session_dir", help="discover 阶段生成的会话目录")
    attach_pdf.add_argument("paper_id", help="候选论文编号，例如 P004")
    attach_pdf.add_argument("file_path", help="本地 PDF 路径")

    capabilities = sub.add_parser("capabilities", help="输出当前助手支持的能力说明")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "discover":
        if args.session_dir:
            session_dir = Path(args.session_dir).expanduser()
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = DEFAULT_SESSIONS_DIR / f"{timestamp}_{RUN_PIPELINE.slugify(args.query, limit=50)}"
        session = build_discover_session(
            query=args.query,
            session_dir=session_dir,
            limit=max(1, args.limit),
            probe_downloads=args.probe_downloads,
            auto_refresh_count=max(0, args.auto_refresh_top),
        )
        print_discover_summary(session)
        return

    if args.command == "status":
        session = load_session(Path(args.session_dir).expanduser())
        print(json.dumps(build_status_payload(session), ensure_ascii=False, indent=2))
        return

    if args.command == "card-state":
        print("[legacy] `card-state` is retained for historical card consumers and is not part of the main Web workflow.", file=sys.stderr)
        session = load_session(Path(args.session_dir).expanduser())
        print(json.dumps(build_card_state_payload(session), ensure_ascii=False, indent=2))
        return

    if args.command == "feishu-card":
        print("[legacy/deprecated] `feishu-card` is retained only for historical Feishu output compatibility and is not part of the main Web workflow.", file=sys.stderr)
        session = load_session(Path(args.session_dir).expanduser())
        print(json.dumps(build_feishu_card_payload(session, max_items=max(1, args.max_items)), ensure_ascii=False, indent=2))
        return

    if args.command == "refresh-probe":
        result = refresh_probes(
            session_dir=Path(args.session_dir).expanduser(),
            ids=parse_ids(args.ids),
            force=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "download":
        result = run_downloads(
            session_dir=Path(args.session_dir).expanduser(),
            ids=parse_ids(args.ids),
            auto_only=args.auto_only,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "analyze":
        result = run_analysis(
            session_dir=Path(args.session_dir).expanduser(),
            ids=parse_ids(args.ids),
            top_k_spans=max(1, args.top_k_spans),
            analysis_scope=args.analysis_scope,
            analysis_model_profile=args.analysis_model_profile,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "attach-pdf":
        result = attach_local_pdf(
            session_dir=Path(args.session_dir).expanduser(),
            paper_id=args.paper_id,
            file_path=args.file_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "capabilities":
        print(json.dumps(build_capabilities_payload(), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
