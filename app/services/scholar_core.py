from __future__ import annotations

import concurrent.futures
import csv
import importlib.util
import io
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"
SCHOLAR_SESSIONS_ROOT = PROJECT_ROOT / "data" / "scholar_sessions"
_SCHOLAR_TASK_LOCKS: dict[str, threading.Lock] = {}
_SCHOLAR_TASK_LOCKS_LOCK = threading.Lock()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def scholar_pipeline():
    return _load_module(
        SKILLS_ROOT / "scholar_impact_analyzer" / "scholar_pipeline.py",
        "academic_impact_web_scholar_pipeline",
    )


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return re.sub(r"_+", "_", text).strip("_") or "scholar"


def make_scholar_session_id(display_name: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_scholar_{slugify(display_name)}_{uuid4().hex[:8]}"


def normalize_scholar_dblp_id(value: str) -> str:
    return scholar_pipeline().AUTHOR_SOURCES.normalize_dblp_id(value)


def create_scholar_session(author: dict[str, Any]) -> str:
    author = dict(author)
    author["dblp_id"] = normalize_scholar_dblp_id(author.get("dblp_id") or "")
    session_id = make_scholar_session_id(author.get("display_name") or "")
    session_dir = SCHOLAR_SESSIONS_ROOT / session_id
    pipeline = scholar_pipeline()
    session = pipeline.build_scholar_session(author, session_dir)
    pipeline.save_scholar_session(session_dir, session)
    return session_id


def list_scholar_sessions(limit: int = 20) -> list[dict[str, Any]]:
    if not SCHOLAR_SESSIONS_ROOT.exists():
        return []

    sessions: list[dict[str, Any]] = []
    for session_dir in sorted(SCHOLAR_SESSIONS_ROOT.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        session_path = session_dir / "session.json"
        if not session_path.exists():
            continue
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        publications = session.get("publications") or []
        statistics = session.get("statistics") or {}
        selected_author = session.get("selected_author") or {}
        sessions.append(
            {
                "id": session_dir.name,
                "query": selected_author.get("display_name", ""),
                "updated_at": session.get("updated_at") or session.get("created_at"),
                "paper_count": statistics.get("publication_count", len(publications)),
                "session_type": "scholar_impact",
                "detail_url": f"/scholars/{session_dir.name}",
            }
        )
        if len(sessions) >= limit:
            break
    return sessions


def default_task_state() -> dict[str, Any]:
    return {
        "active": False,
        "task_type": None,
        "status": "idle",
        "message": "",
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "error": "",
        "processed_count": 0,
        "total_count": 0,
        "citation_edge_count": 0,
        "deep_analysis_queue_count": 0,
        "limit_per_publication": None,
        "selected_queue_ids": [],
        "stage": "",
        "stage_message": "",
        "current_queue_id": "",
        "current_title": "",
        "current_index": 0,
    }


def ensure_task_state(session: dict[str, Any]) -> dict[str, Any]:
    task_state = session.get("task_state")
    if not isinstance(task_state, dict):
        task_state = default_task_state()
    merged = default_task_state()
    merged.update(task_state)
    session["task_state"] = merged
    return merged


def parse_multiline_values(value: str) -> list[str]:
    parts = re.split(r"[\n\r;；|]+", str(value or ""))
    result = []
    seen = set()
    for part in parts:
        text = part.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_analysis_templates() -> dict[str, Any]:
    try:
        templates = scholar_pipeline().EVIDENCE_TEMPLATES.load_builtin_templates()
    except Exception:
        templates = []
    compiled = [
        template for template in templates if template.get("id") == "ppt_highlight_default"
    ]
    return {
        "active_template_ids": ["ppt_highlight_default"],
        "custom_requests": [],
        "compiled_templates": compiled,
        "builtin_templates": templates,
    }


def ensure_analysis_templates(session: dict[str, Any]) -> dict[str, Any]:
    template_state = session.get("analysis_templates")
    defaults = default_analysis_templates()
    if not isinstance(template_state, dict):
        session["analysis_templates"] = defaults
        return defaults
    template_state.setdefault("active_template_ids", defaults["active_template_ids"])
    template_state.setdefault("custom_requests", [])
    template_state.setdefault("compiled_templates", defaults["compiled_templates"])
    template_state["builtin_templates"] = defaults["builtin_templates"]
    session["analysis_templates"] = template_state
    return template_state


def ensure_exclusion_profile(session: dict[str, Any]) -> dict[str, Any]:
    profile = session.get("exclusion_profile")
    if not isinstance(profile, dict):
        profile = {}
    profile.setdefault("exclude_selected_author", True)
    profile.setdefault("exclude_source_paper_authors", True)
    profile.setdefault("extra_excluded_authors", [])
    profile.setdefault("extra_excluded_affiliations", [])
    session["exclusion_profile"] = profile
    return profile


def _task_lock(session_id: str) -> threading.Lock:
    with _SCHOLAR_TASK_LOCKS_LOCK:
        lock = _SCHOLAR_TASK_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _SCHOLAR_TASK_LOCKS[session_id] = lock
        return lock


def resolve_scholar_session_dir(session_id: str) -> Path:
    session_dir = SCHOLAR_SESSIONS_ROOT / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"未找到学者会话目录: {session_id}")
    return session_dir


def write_scholar_status(session_id: str, session: dict[str, Any]) -> None:
    session_dir = resolve_scholar_session_dir(session_id)
    ensure_task_state(session)
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    session_path = session_dir / "session.json"
    tmp_path = session_dir / f".{session_path.name}.{uuid4().hex}.tmp"
    try:
        tmp_path.write_text(
            json.dumps(session, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(session_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _decorate_publication_venue_tiers(session: dict[str, Any]) -> None:
    stats = scholar_pipeline().SCHOLAR_STATS
    tier_index = stats.IMPACT_CLI.build_venue_tier_index()
    for publication in session.get("publications", []) or []:
        if publication.get("venue_tier"):
            continue
        publication["venue_tier"] = stats.IMPACT_CLI.classify_venue_tier(
            publication.get("venue") or "",
            tier_index,
        )


def load_scholar_status(session_id: str) -> dict[str, Any]:
    session_path = resolve_scholar_session_dir(session_id) / "session.json"
    last_error = None
    session = None
    for _ in range(5):
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
            break
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.02)
    if session is None:
        raise last_error
    ensure_task_state(session)
    session.setdefault("publications", [])
    session.setdefault("citation_edges", [])
    session.setdefault("deep_analysis_queue", [])
    session.setdefault("strong_evidence", [])
    session.setdefault("scholar_fulltext_results", [])
    session.setdefault("statistics", {})
    ensure_analysis_templates(session)
    ensure_exclusion_profile(session)
    _decorate_publication_venue_tiers(session)
    return session


def load_local_pdf_index_status(session: dict[str, Any] | None = None) -> dict[str, Any]:
    pipeline = scholar_pipeline()
    download_pdf = pipeline.RUN_PIPELINE.DOWNLOAD_PDF
    search_dirs = pipeline.configured_local_pdf_library_dirs(download_pdf)
    index_path = str(Path(download_pdf.DEFAULT_LOCAL_PDF_INDEX_PATH).expanduser())
    index_data = download_pdf.load_local_pdf_index(index_path=index_path) or {}
    refresh_meta = (session or {}).get("local_pdf_index_refresh") or {}
    queue = (session or {}).get("deep_analysis_queue", []) or []
    queue_matched_count = sum(
        1
        for item in queue
        if ((item.get("library_pdf") or {}).get("status") or "") == "local_library_matched"
    )
    queue_manual_pdf_count = sum(
        1
        for item in queue
        if (item.get("manual_pdf") or {}).get("local_file_path")
        or (item.get("manual_pdf") or {}).get("status")
    )
    queue_ready_pdf_count = sum(
        1
        for item in queue
        if _queue_item_has_bound_pdf(item)
    )
    return {
        "exists": bool(index_data),
        "entry_count": int(index_data.get("entry_count") or 0),
        "scanned_pdf_count": int(index_data.get("scanned_pdf_count") or index_data.get("entry_count") or 0),
        "build_elapsed_ms": int(index_data.get("build_elapsed_ms") or 0),
        "generated_at": index_data.get("generated_at") or "",
        "index_path": index_path,
        "search_dirs": index_data.get("search_dirs") or search_dirs,
        "queue_matched_count": queue_matched_count,
        "queue_manual_pdf_count": queue_manual_pdf_count,
        "queue_ready_pdf_count": queue_ready_pdf_count,
        "refresh_total_ms": int(refresh_meta.get("refresh_total_ms") or 0),
        "queue_rematch_elapsed_ms": int(refresh_meta.get("queue_rematch_elapsed_ms") or 0),
        "queue_items_scanned": int(refresh_meta.get("queue_items_scanned") or 0),
        "queue_items_updated": int(refresh_meta.get("queue_items_updated") or 0),
        "last_refreshed_at": refresh_meta.get("last_refreshed_at") or "",
    }


def build_deep_analysis_queue_view(
    session: dict[str, Any],
    *,
    active_reason: str = "",
    active_scope: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    queue = session.get("deep_analysis_queue", []) or []
    reason_counts: dict[str, int] = {}
    for item in queue:
        for reason in item.get("reasons") or []:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    filtered = queue
    if active_reason:
        filtered = [
            item for item in queue if active_reason in (item.get("reasons") or [])
        ]
    if active_scope == "non_self":
        filtered = [
            item for item in filtered
            if (item.get("third_party_status") or item.get("self_citation_status") or "unknown")
            == "non_self_citation"
        ]
    elif active_scope == "ready":
        filtered = [item for item in filtered if _queue_item_has_bound_pdf(item)]
    elif active_scope == "person_tag":
        filtered = [
            item for item in filtered
            if any(str(reason).startswith("person_tag:") for reason in item.get("reasons") or [])
        ]

    result_by_queue_id = {
        result.get("queue_id"): result
        for result in session.get("scholar_fulltext_results", []) or []
        if result.get("queue_id")
    }

    page_size = min(max(page_size, 1), 100)
    total_count = len(filtered)
    total_pages = max((total_count + page_size - 1) // page_size, 1)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    end = start + page_size

    def page_url(target_page: int) -> str:
        query = {
            "queue_page": target_page,
            "queue_page_size": page_size,
        }
        if active_reason:
            query["queue_reason"] = active_reason
        if active_scope:
            query["queue_scope"] = active_scope
        return f"?{urlencode(query)}#deep-analysis-queue"

    def citing_identifier(item: dict[str, Any]) -> str:
        if item.get("citing_doi"):
            return f"DOI: {item.get('citing_doi')}"
        if item.get("citing_scopus_id"):
            return f"Scopus: {item.get('citing_scopus_id')}"
        if item.get("citing_openalex_id"):
            return f"OpenAlex: {item.get('citing_openalex_id')}"
        if item.get("citing_paper_id"):
            return f"ID: {item.get('citing_paper_id')}"
        return "-"

    def publisher_url(item: dict[str, Any]) -> str:
        return _queue_item_publisher_url(item)

    def decorate_queue_item(item: dict[str, Any]) -> dict[str, Any]:
        result = result_by_queue_id.get(item.get("queue_id"))
        decorated = dict(item)
        manual_pdf = item.get("manual_pdf") or {}
        library_pdf = item.get("library_pdf") or {}
        decorated["citing_identifier"] = citing_identifier(item)
        decorated["publisher_url"] = publisher_url(item)
        if result:
            download = result.get("download") or {}
            analysis = result.get("analysis") or {}
            decorated["analysis_status"] = (
                result.get("status")
                or analysis.get("final_status")
                or "unknown"
            )
            decorated["download_source"] = download.get("source") or "-"
            decorated["analysis_failure_message"] = _result_failure_message(result)
            decorated["analysis_error_type"] = analysis.get("error_type") or ""
            decorated["download_failure_type"] = download.get("failure_type") or ""
        else:
            decorated["analysis_status"] = "not_analyzed"
            decorated["download_source"] = "点击分析时自动尝试下载 PDF"
            decorated["analysis_failure_message"] = ""
            decorated["analysis_error_type"] = ""
            decorated["download_failure_type"] = ""
        decorated["manual_pdf_status"] = manual_pdf.get("status") or ""
        decorated["manual_pdf_path"] = manual_pdf.get("local_file_path") or ""
        decorated["library_pdf_status"] = library_pdf.get("status") or ""
        decorated["library_pdf_path"] = library_pdf.get("local_file_path") or ""
        decorated["self_citation_label"] = {
            "self_citation": "自引",
            "excluded_collaborator": "本组/合作者",
            "non_self_citation": "非自引",
            "unknown": "自引未知",
        }.get(decorated.get("third_party_status") or decorated.get("self_citation_status") or "unknown", "自引未知")
        decorated["third_party_label"] = {
            "self_citation": "自引",
            "excluded_collaborator": "本组/合作者",
            "non_self_citation": "第三方引用",
            "unknown": "第三方状态未知",
        }.get(decorated.get("third_party_status") or decorated.get("self_citation_status") or "unknown", "第三方状态未知")
        if decorated["manual_pdf_status"]:
            decorated["download_source"] = decorated["manual_pdf_status"]
            if decorated["analysis_status"] == "not_analyzed":
                decorated["analysis_status"] = decorated["manual_pdf_status"]
        elif decorated["library_pdf_status"]:
            decorated["download_source"] = decorated["library_pdf_status"]
            if decorated["analysis_status"] == "not_analyzed":
                decorated["analysis_status"] = decorated["library_pdf_status"]
        if decorated["manual_pdf_status"]:
            decorated["readiness_status"] = "manual_pdf_ready"
            decorated["readiness_label"] = "已上传 PDF，可重试"
        elif decorated["library_pdf_status"]:
            decorated["readiness_status"] = "local_library_ready"
            decorated["readiness_label"] = "已命中本地论文库，可直接分析"
        elif decorated["download_failure_type"] == "requires_institution_login":
            decorated["readiness_status"] = "institution_login_required"
            decorated["readiness_label"] = "需要机构登录下载 PDF"
        elif (
            decorated["analysis_status"] in {"context_only", "fulltext_extract_failed"}
            or decorated["download_source"] == "manual_required"
            or decorated["analysis_error_type"] in {"download_failed", "fulltext_extract_failed"}
        ):
            decorated["readiness_status"] = "manual_pdf_recommended"
            decorated["readiness_label"] = "建议先上传 PDF"
        elif decorated["citing_identifier"] == "-":
            decorated["readiness_status"] = "missing_identifier"
            decorated["readiness_label"] = "缺少 DOI/ID，可能失败"
        else:
            decorated["readiness_status"] = "auto_try"
            decorated["readiness_label"] = "可自动尝试"
        return decorated

    return {
        "items": [decorate_queue_item(item) for item in filtered[start:end]],
        "total_count": total_count,
        "unfiltered_count": len(queue),
        "active_reason": active_reason,
        "active_scope": active_scope,
        "scope_options": [
            {
                "scope": "non_self",
                "label": "只看第三方引用",
                "count": sum(
                    1 for item in queue
                    if (item.get("third_party_status") or item.get("self_citation_status") or "unknown")
                    == "non_self_citation"
                ),
            },
            {
                "scope": "person_tag",
                "label": "只看 Fellow/院士等重要人物",
                "count": sum(
                    1 for item in queue
                    if any(str(reason).startswith("person_tag:") for reason in item.get("reasons") or [])
                ),
            },
            {
                "scope": "ready",
                "label": "只看已准备 PDF",
                "count": sum(1 for item in queue if _queue_item_has_bound_pdf(item)),
            },
        ],
        "reason_options": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                reason_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_url": page_url(page - 1) if page > 1 else "",
            "next_url": page_url(page + 1) if page < total_pages else "",
            "start_index": start + 1 if total_count else 0,
            "active_reason": active_reason,
            "active_scope": active_scope,
        },
    }


def build_strong_evidence_view(
    session: dict[str, Any],
    *,
    active_aspect: str = "",
    active_stance: str = "",
    active_flag: str = "",
    active_label: str = "",
    active_strength: str = "",
    active_self: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    evidence_helper = scholar_pipeline().SCHOLAR_EVIDENCE
    evidence_items = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    evidence_items = sorted(
        evidence_items,
        key=lambda item: (
            -(item.get("strong_citation_score") or 0),
            -(item.get("citation_char_count") or 0),
            item.get("citing_title") or "",
        ),
    )
    aspect_counts: dict[str, int] = {}
    stance_counts: dict[str, int] = {}
    label_counts: dict[str, int] = {}
    strength_counts: dict[str, int] = {}
    self_counts: dict[str, int] = {}
    flag_counts = {
        "fellow_strong": 0,
        "positive": 0,
        "long_context": 0,
    }

    def is_positive(item: dict[str, Any]) -> bool:
        return bool(item.get("positive_evaluation")) or (
            item.get("stance") or ""
        ).lower() == "positive"

    def is_long_context(item: dict[str, Any]) -> bool:
        return bool(item.get("long_context_100_chars")) or (
            item.get("citation_char_count") or 0
        ) >= 100

    def matches_flag(item: dict[str, Any], flag: str) -> bool:
        if flag == "fellow_strong":
            return bool(item.get("fellow_strong_citation"))
        if flag == "positive":
            return is_positive(item)
        if flag == "long_context":
            return is_long_context(item)
        return True

    for item in evidence_items:
        aspect = item.get("aspect") or "-"
        stance = item.get("stance") or "-"
        strength = item.get("evidence_strength") or "-"
        self_status = item.get("self_citation_status") or "unknown"
        aspect_counts[aspect] = aspect_counts.get(aspect, 0) + 1
        stance_counts[stance] = stance_counts.get(stance, 0) + 1
        strength_counts[strength] = strength_counts.get(strength, 0) + 1
        self_counts[self_status] = self_counts.get(self_status, 0) + 1
        for label in item.get("evidence_labels") or []:
            label_counts[label] = label_counts.get(label, 0) + 1
        if item.get("fellow_strong_citation"):
            flag_counts["fellow_strong"] += 1
        if is_positive(item):
            flag_counts["positive"] += 1
        if is_long_context(item):
            flag_counts["long_context"] += 1

    filtered = evidence_items
    if active_aspect:
        filtered = [item for item in filtered if (item.get("aspect") or "-") == active_aspect]
    if active_stance:
        filtered = [item for item in filtered if (item.get("stance") or "-") == active_stance]
    if active_flag:
        filtered = [item for item in filtered if matches_flag(item, active_flag)]
    if active_label:
        filtered = [
            item for item in filtered if active_label in (item.get("evidence_labels") or [])
        ]
    if active_strength:
        filtered = [
            item for item in filtered if (item.get("evidence_strength") or "-") == active_strength
        ]
    if active_self:
        filtered = [
            item for item in filtered if (item.get("self_citation_status") or "unknown") == active_self
        ]

    page_size = min(max(page_size, 1), 100)
    total_count = len(filtered)
    total_pages = max((total_count + page_size - 1) // page_size, 1)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    end = start + page_size

    def page_url(target_page: int) -> str:
        query = {
            "strong_page": target_page,
            "strong_page_size": page_size,
        }
        if active_aspect:
            query["strong_aspect"] = active_aspect
        if active_stance:
            query["strong_stance"] = active_stance
        if active_flag:
            query["strong_flag"] = active_flag
        if active_label:
            query["strong_label"] = active_label
        if active_strength:
            query["strong_strength"] = active_strength
        if active_self:
            query["strong_self"] = active_self
        return f"?{urlencode(query)}#strong-evidence"

    def decorate_evidence(item: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(item)
        labels = decorated.get("evidence_labels") or []
        decorated["evidence_label_names"] = (
            decorated.get("evidence_label_names")
            or [evidence_helper.evidence_label_display(label) for label in labels]
        )
        decorated["self_citation_label"] = {
            "self_citation": "自引",
            "non_self_citation": "非自引",
            "unknown": "自引未知",
        }.get(decorated.get("self_citation_status") or "unknown", "自引未知")
        decorated["highlighted_citation_text"] = evidence_helper.highlight_excerpt_html(
            decorated.get("citation_text") or "",
            decorated.get("highlight_keywords") or [],
        )
        return decorated

    return {
        "items": [decorate_evidence(item) for item in filtered[start:end]],
        "total_count": total_count,
        "unfiltered_count": len(evidence_items),
        "active_aspect": active_aspect,
        "active_stance": active_stance,
        "active_flag": active_flag,
        "active_label": active_label,
        "active_strength": active_strength,
        "active_self": active_self,
        "aspect_counts": aspect_counts,
        "stance_counts": stance_counts,
        "label_counts": label_counts,
        "strength_counts": strength_counts,
        "self_counts": self_counts,
        "flag_counts": flag_counts,
        "aspect_options": [
            {"aspect": aspect, "count": count}
            for aspect, count in sorted(
                aspect_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "stance_options": [
            {"stance": stance, "count": count}
            for stance, count in sorted(
                stance_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "label_options": [
            {
                "label": label,
                "display": evidence_helper.evidence_label_display(label),
                "count": count,
            }
            for label, count in sorted(
                label_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "strength_options": [
            {"strength": strength, "label": {"high": "高", "medium": "中", "low": "低"}.get(strength, strength), "count": count}
            for strength, count in sorted(
                strength_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "self_options": [
            {"self": status, "label": {"self_citation": "自引", "non_self_citation": "非自引", "unknown": "自引未知"}.get(status, status), "count": count}
            for status, count in sorted(
                self_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "flag_options": [
            {"flag": "fellow_strong", "label": "Fellow 强引用", "count": flag_counts["fellow_strong"]},
            {"flag": "positive", "label": "正向评价", "count": flag_counts["positive"]},
            {"flag": "long_context", "label": "长引用", "count": flag_counts["long_context"]},
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_url": page_url(page - 1) if page > 1 else "",
            "next_url": page_url(page + 1) if page < total_pages else "",
            "start_index": start + 1 if total_count else 0,
        },
    }


def _compact_evidence_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\W+", "", text)


def _normalize_evidence_excerpt(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _strong_evidence_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("queue_id") or "",
        _compact_evidence_text(item.get("citing_title")),
        _compact_evidence_text(item.get("cited_publication_title")),
        _normalize_evidence_excerpt(item.get("citation_text")),
        item.get("page"),
        item.get("span_index"),
        item.get("aspect") or "",
        item.get("stance") or "",
        item.get("mention_type") or "",
    )


def _deduplicate_strong_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for item in items:
        key = _strong_evidence_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def build_person_candidate_view(
    session: dict[str, Any],
    *,
    active_status: str = "",
    active_tag_type: str = "",
    page: int = 1,
    page_size: int = 12,
) -> dict[str, Any]:
    candidates = session.get("person_candidates", []) or []
    status_counts = {"pending": 0, "confirmed": 0, "rejected": 0}
    tag_counts: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        status = candidate.get("status") or "pending"
        if status not in status_counts:
            status_counts[status] = 0
        status_counts[status] += 1

        tag_type = candidate.get("tag_type") or ""
        if not tag_type:
            continue
        tag = tag_counts.setdefault(
            tag_type,
            {
                "tag_type": tag_type,
                "tag_label": candidate.get("tag_label") or tag_type,
                "count": 0,
            },
        )
        tag["count"] += 1

    filtered = candidates
    if active_status:
        filtered = [
            item for item in filtered
            if (item.get("status") or "pending") == active_status
        ]
    if active_tag_type:
        filtered = [
            item for item in filtered
            if (item.get("tag_type") or "") == active_tag_type
        ]

    page_size = min(max(page_size, 1), 100)
    total_count = len(filtered)
    total_pages = max((total_count + page_size - 1) // page_size, 1)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    end = start + page_size

    def page_url(target_page: int) -> str:
        query = {
            "person_page": target_page,
            "person_page_size": page_size,
        }
        if active_status:
            query["person_status"] = active_status
        if active_tag_type:
            query["person_tag_type"] = active_tag_type
        return f"?{urlencode(query)}#person-candidates"

    return {
        "items": filtered[start:end],
        "total_count": total_count,
        "unfiltered_count": len(candidates),
        "active_status": active_status,
        "active_tag_type": active_tag_type,
        "status_counts": status_counts,
        "tag_options": sorted(
            tag_counts.values(),
            key=lambda item: (-item["count"], item["tag_label"]),
        ),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_url": page_url(page - 1) if page > 1 else "",
            "next_url": page_url(page + 1) if page < total_pages else "",
            "start_index": start + 1 if total_count else 0,
        },
    }


def _result_citing_title(result: dict[str, Any]) -> str:
    citing_paper = result.get("citing_paper") or {}
    return (
        result.get("citing_title")
        or citing_paper.get("title")
        or result.get("title")
        or ""
    )


def _result_failure_message(result: dict[str, Any]) -> str:
    status_note = result.get("status_note") or {}
    analysis = result.get("analysis") or {}
    download = result.get("download") or {}
    fallback = result.get("fallback_analysis") or {}
    return (
        status_note.get("message")
        or analysis.get("message")
        or analysis.get("error")
        or download.get("error")
        or fallback.get("message")
        or "未能完成全文分析。"
    )


def _result_action_hint(result: dict[str, Any]) -> str:
    status = result.get("status") or (result.get("analysis") or {}).get("final_status") or ""
    analysis = result.get("analysis") or {}
    download = result.get("download") or {}
    error_type = analysis.get("error_type") or ""
    download_source = download.get("source") or ""
    if (
        status in {"context_only", "fulltext_extract_failed"}
        or error_type in {"download_failed", "fulltext_extract_failed"}
        or download_source == "manual_required"
    ):
        return "未找到可用全文：请在高价值引用队列中上传该引用论文 PDF，然后重试失败项。"
    if status == "analysis_failed" or error_type:
        return "模型分析失败：可先重试；若持续失败，请减少单次选择数量并检查模型服务。"
    return "检查失败原因后重试；如果仍失败，请补充 PDF 或缩小本次分析范围。"


def build_scholar_analysis_summary(session: dict[str, Any]) -> dict[str, Any]:
    results = session.get("scholar_fulltext_results", []) or []
    strong_evidence = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    status_counts: dict[str, int] = {}
    failed_statuses = {
        "context_only",
        "fulltext_extract_failed",
        "analysis_failed",
        "write_output_failed",
    }
    failure_items = []
    retry_queue_ids = []

    for result in results:
        status = result.get("status") or (result.get("analysis") or {}).get("final_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        analysis = result.get("analysis") or {}
        download = result.get("download") or {}
        is_failed = status in failed_statuses or analysis.get("ok") is False
        if not is_failed:
            continue
        queue_id = result.get("queue_id") or ""
        if queue_id and queue_id not in retry_queue_ids:
            retry_queue_ids.append(queue_id)
        failure_items.append(
            {
                "queue_id": queue_id,
                "status": status,
                "citing_title": _result_citing_title(result),
                "cited_publication_title": result.get("cited_publication_title") or "",
                "message": _result_failure_message(result),
                "error_type": analysis.get("error_type") or "",
                "error_detail_type": analysis.get("error_detail_type") or "",
                "download_source": download.get("source") or "",
                "download_error": download.get("error") or "",
                "action_hint": _result_action_hint(result),
            }
        )

    target_index: dict[str, dict[str, Any]] = {}
    for evidence in strong_evidence:
        title = evidence.get("cited_publication_title") or evidence.get("source_publication_id") or "未知目标论文"
        key = f"{evidence.get('source_publication_id') or ''}::{title}"
        item = target_index.setdefault(
            key,
            {
                "source_publication_id": evidence.get("source_publication_id") or "",
                "title": title,
                "evidence_count": 0,
                "citing_titles": [],
                "aspects": [],
                "positive_count": 0,
                "long_context_count": 0,
                "fellow_strong_count": 0,
                "example_text": "",
            },
        )
        item["evidence_count"] += 1
        citing_title = evidence.get("citing_title") or ""
        if citing_title and citing_title not in item["citing_titles"]:
            item["citing_titles"].append(citing_title)
        aspect = evidence.get("aspect") or ""
        if aspect and aspect not in item["aspects"]:
            item["aspects"].append(aspect)
        if evidence.get("positive_evaluation") or (evidence.get("stance") or "").lower() == "positive":
            item["positive_count"] += 1
        if evidence.get("long_context_100_chars") or (evidence.get("citation_char_count") or 0) >= 100:
            item["long_context_count"] += 1
        if evidence.get("fellow_strong_citation"):
            item["fellow_strong_count"] += 1
        if not item["example_text"] and evidence.get("citation_text"):
            item["example_text"] = evidence.get("citation_text")

    target_summaries = sorted(
        target_index.values(),
        key=lambda item: (
            item["evidence_count"],
            item["fellow_strong_count"],
            item["positive_count"],
        ),
        reverse=True,
    )
    analyzed_queue_ids = {
        result.get("queue_id")
        for result in results
        if result.get("queue_id")
    }
    queue_count = len(session.get("deep_analysis_queue", []) or [])
    fellow_strong_count = sum(item["fellow_strong_count"] for item in target_summaries)
    if failure_items:
        next_action = "建议先重试失败项或补充 PDF。"
    elif queue_count > len(analyzed_queue_ids):
        next_action = "建议继续分析高价值引用队列。"
    elif strong_evidence:
        next_action = "可以整理强引用证据用于报告。"
    else:
        next_action = "建议先展开引用网络，再选择高价值引用论文做全文分析。"
    overview = {
        "analyzed_queue_count": len(analyzed_queue_ids),
        "queue_count": queue_count,
        "target_with_evidence_count": len(target_summaries),
        "strong_evidence_count": len(strong_evidence),
        "fellow_strong_count": fellow_strong_count,
        "failure_count": len(failure_items),
        "top_target_title": target_summaries[0]["title"] if target_summaries else "",
        "next_action": next_action,
    }

    return {
        "result_count": len(results),
        "strong_evidence_count": len(strong_evidence),
        "failure_count": len(failure_items),
        "status_counts": [
            {"status": status, "count": count}
            for status, count in sorted(status_counts.items())
        ],
        "failure_items": failure_items,
        "retry_queue_ids": retry_queue_ids,
        "target_summaries": target_summaries,
        "overview": overview,
    }


def build_scholar_demo_guidance(
    session: dict[str, Any],
    *,
    analysis_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    statistics = session.get("statistics") or {}
    analysis = analysis_summary or build_scholar_analysis_summary(session)
    overview = analysis.get("overview") or {}
    queue_count = overview.get(
        "queue_count",
        len(session.get("deep_analysis_queue", []) or []),
    )
    analyzed_queue_count = overview.get("analyzed_queue_count", 0)
    remaining_queue_count = max((queue_count or 0) - (analyzed_queue_count or 0), 0)
    failure_count = overview.get("failure_count", analysis.get("failure_count", 0))
    strong_evidence_count = overview.get(
        "strong_evidence_count",
        len(_deduplicate_strong_evidence(session.get("strong_evidence", []) or [])),
    )
    citation_edge_count = statistics.get("citation_edge_count")
    if citation_edge_count is None:
        citation_edge_count = len(session.get("citation_edges", []) or [])
    pending_person_count = sum(
        1
        for candidate in session.get("person_candidates", []) or []
        if (candidate.get("status") or "pending") == "pending"
    )
    analysis_percent = round((analyzed_queue_count * 100 / queue_count), 1) if queue_count else 0.0

    steps: list[dict[str, str]] = []

    def add_step(kind: str, title: str, action: str, anchor: str) -> None:
        steps.append(
            {
                "kind": kind,
                "title": title,
                "action": action,
                "anchor": anchor,
            }
        )

    if citation_edge_count == 0:
        add_step(
            "expand_citations",
            "先展开引用网络",
            "点击“展开引用论文”，让系统收集引用边、作者线索和高价值队列。",
            "#scholar-actions",
        )
    if pending_person_count:
        add_step(
            "review_people",
            "审核人物标签候选",
            "确认 Fellow、院士、海外高校作者等候选，统计口径会更稳。",
            "#person-candidates",
        )
    if queue_count and remaining_queue_count:
        add_step(
            "analyze_queue",
            "分析高价值引用队列",
            "优先勾选 Top 队列，点击“分析所选引用论文”生成强引用证据。",
            "#deep-analysis-queue",
        )
    if failure_count:
        add_step(
            "recover_failures",
            "补 PDF 并重试失败项",
            "失败项通常是缺全文或模型调用失败；缺全文时在队列中上传 PDF 后重试。",
            "#fulltext-status",
        )
    if strong_evidence_count:
        add_step(
            "export_report",
            "下载报告并核对强引用证据",
            "已有强引用证据时，可以下载 Markdown 报告，并检查证据摘录是否适合放进组会材料。",
            "#report-summary",
        )
    if not steps:
        add_step(
            "continue_demo",
            "继续扩展或导出报告",
            "当前流程没有明显阻塞，可以继续扩大引用网络，或导出报告做人工核对。",
            "#report-summary",
        )

    return {
        "steps": steps,
        "completeness": {
            "citation_edge_count": citation_edge_count,
            "queue_count": queue_count,
            "analyzed_queue_count": analyzed_queue_count,
            "remaining_queue_count": remaining_queue_count,
            "failure_count": failure_count,
            "strong_evidence_count": strong_evidence_count,
            "pending_person_count": pending_person_count,
            "analysis_percent": analysis_percent,
        },
    }


def build_scholar_report_payload(
    session: dict[str, Any],
    *,
    analysis_summary: dict[str, Any] | None = None,
    strong_evidence_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    author = session.get("selected_author") or {}
    name = author.get("display_name") or session.get("query") or "该学者"
    statistics = session.get("statistics") or {}
    analysis = analysis_summary or build_scholar_analysis_summary(session)
    strong_view = strong_evidence_view or build_strong_evidence_view(session)
    overview = analysis.get("overview") or {}
    flag_counts = strong_view.get("flag_counts") or {}
    label_counts = strong_view.get("label_counts") or {}

    publication_count = statistics.get("publication_count") or len(
        session.get("publications", []) or []
    )
    citation_edge_count = statistics.get("citation_edge_count") or len(
        session.get("citation_edges", []) or []
    )
    first_author_count = statistics.get("first_author_publication_count") or 0
    queue_count = overview.get(
        "queue_count",
        len(session.get("deep_analysis_queue", []) or []),
    )
    analyzed_queue_count = overview.get("analyzed_queue_count", 0)
    strong_evidence_count = overview.get(
        "strong_evidence_count",
        len(_deduplicate_strong_evidence(session.get("strong_evidence", []) or [])),
    )
    fellow_strong_count = overview.get("fellow_strong_count", 0)
    positive_count = flag_counts.get("positive", 0)
    long_context_count = flag_counts.get("long_context", 0)
    failure_count = overview.get("failure_count", 0)
    top_target_title = overview.get("top_target_title") or "暂无"
    next_action = overview.get("next_action") or "建议继续完善引用网络和全文分析。"
    strong_evidence = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    pending_person_count = sum(
        1
        for candidate in session.get("person_candidates", []) or []
        if candidate.get("status") == "pending"
    )
    remaining_queue_count = max((queue_count or 0) - (analyzed_queue_count or 0), 0)

    aspect_counts: dict[str, int] = {}
    for evidence in strong_evidence:
        aspect = evidence.get("aspect") or "other"
        aspect_counts[aspect] = aspect_counts.get(aspect, 0) + 1

    narrative_bullets: list[str] = []
    label_names = scholar_pipeline().SCHOLAR_EVIDENCE.LABEL_DISPLAY_NAMES
    for label in [
        "first_or_pioneering",
        "baseline",
        "comparison",
        "method_foundation",
        "theory_foundation",
        "positive_evaluation",
        "large_context",
        "important_person",
    ]:
        count = label_counts.get(label, 0)
        if count:
            narrative_bullets.append(f"{label_names.get(label, label)}证据 {count} 条。")
    method_count = aspect_counts.get("method", 0)
    if method_count:
        narrative_bullets.append(f"方法采用类证据 {method_count} 条，说明目标工作被后续论文直接使用或复现。")
    baseline_count = aspect_counts.get("baseline", 0) + aspect_counts.get("comparison", 0)
    if baseline_count:
        narrative_bullets.append(f"基线/比较类证据 {baseline_count} 条，说明目标工作进入后续实验比较体系。")
    extension_count = aspect_counts.get("extension", 0) + aspect_counts.get("application", 0)
    if extension_count:
        narrative_bullets.append(f"应用拓展类证据 {extension_count} 条，说明目标工作被迁移、扩展或用于新场景。")
    background_count = aspect_counts.get("background", 0)
    if background_count:
        narrative_bullets.append(f"背景支撑类证据 {background_count} 条，说明目标工作被后续研究用于问题背景或领域脉络。")
    if not narrative_bullets:
        narrative_bullets.append("当前还缺少可归类的强引用证据，建议继续分析高价值引用队列。")

    def evidence_score(evidence: dict[str, Any]) -> tuple[int, int, int, int]:
        return (
            evidence.get("strong_citation_score") or 0,
            1 if evidence.get("fellow_strong_citation") else 0,
            1 if evidence.get("positive_evaluation") or (evidence.get("stance") or "").lower() == "positive" else 0,
            evidence.get("citation_char_count") or len(evidence.get("citation_text") or ""),
        )

    top_evidence = sorted(
        strong_evidence,
        key=evidence_score,
        reverse=True,
    )[:10]

    limitations: list[str] = []
    if remaining_queue_count:
        limitations.append(f"待分析高价值引用 {remaining_queue_count} 篇")
    if failure_count:
        limitations.append(f"待补全文/失败项 {failure_count} 条")
    if pending_person_count:
        limitations.append(f"人物标签待确认 {pending_person_count} 人")
    if not limitations:
        limitations.append("当前暂无明显流程缺口，后续可继续扩展更多引用论文。")

    summary_text = (
        f"{name} 当前汇总 {publication_count} 篇论文，展开 "
        f"{citation_edge_count} 条引用边，高价值引用队列 {queue_count} 篇，"
        f"已分析 {analyzed_queue_count} 篇。目前发现强引用证据 "
        f"{strong_evidence_count} 条，其中 Fellow 强引用 {fellow_strong_count} 条、"
        f"正向评价 {positive_count} 条、长引用 {long_context_count} 条；"
        f"待补全文/失败项 {failure_count} 条。"
    )

    bullets = [
        (
            f"{name}：论文 {publication_count} 篇，引用边 {citation_edge_count} 条，"
            f"一作论文 {first_author_count} 篇。"
        ),
        (
            f"高价值引用队列 {queue_count} 篇，已完成全文语义分析 "
            f"{analyzed_queue_count} 篇。"
        ),
        (
            f"强引用证据 {strong_evidence_count} 条，其中 Fellow 强引用 "
            f"{fellow_strong_count} 条、正向评价 {positive_count} 条、"
            f"长引用 {long_context_count} 条。"
        ),
        (
            "高质量证据标签："
            + "，".join(
                f"{label_names.get(label, label)} {count} 条"
                for label, count in sorted(label_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:6]
            )
            if label_counts
            else "高质量证据标签：暂无。"
        ),
        f"当前最强目标论文：{top_target_title}",
        f"下一步建议：{next_action}",
    ]

    markdown_lines = [
        f"# {name} 学者影响力报告",
        "",
        "## 摘要",
        "",
        summary_text,
        "",
        "## 可复制结论",
        "",
    ]
    markdown_lines.extend(f"- {bullet}" for bullet in bullets)
    markdown_lines.extend(["", "## 证据解读", ""])
    markdown_lines.extend(f"- {bullet}" for bullet in narrative_bullets)
    markdown_lines.extend(["", "## Top 强引用证据", ""])
    if top_evidence:
        for index, evidence in enumerate(top_evidence, 1):
            excerpt = str(evidence.get("citation_text") or "").strip()
            if len(excerpt) > 420:
                excerpt = f"{excerpt[:420]}..."
            markdown_lines.extend(
                [
                    f"{index}. {evidence.get('citing_title') or '未知引用论文'}",
                    f"   - 命中目标：{evidence.get('cited_publication_title') or '-'}",
                    f"   - 类型/态度：{evidence.get('aspect') or '-'} / {evidence.get('stance') or '-'}",
                    f"   - 证据标签：{' / '.join(evidence.get('evidence_label_names') or [label_names.get(label, label) for label in evidence.get('evidence_labels') or []]) or '-'}",
                    f"   - 强度分：{evidence.get('strong_citation_score') if evidence.get('strong_citation_score') is not None else '-'}",
                    f"   - 自引：{ {'self_citation': '是', 'non_self_citation': '否', 'unknown': '未知'}.get(evidence.get('self_citation_status') or 'unknown', '未知') }",
                    f"   - Fellow 强引用：{'是' if evidence.get('fellow_strong_citation') else '否'}",
                    f"   - 汇报价值：{evidence.get('valuable_reason') or evidence.get('reason') or '-'}",
                    f"   - 摘录：{excerpt}",
                ]
            )
    else:
        markdown_lines.append("- 暂无强引用证据示例。")
    markdown_lines.extend(["", "## 当前不足", ""])
    markdown_lines.extend(f"- {item}" for item in limitations)
    markdown_lines.extend(
        [
            "",
            "## 关键统计",
            "",
            f"- 论文数：{publication_count}",
            f"- 引用边：{citation_edge_count}",
            f"- 高价值引用队列：{queue_count}",
            f"- 已分析队列：{analyzed_queue_count}",
            f"- 强引用证据：{strong_evidence_count}",
            f"- Fellow 强引用：{fellow_strong_count}",
            f"- 正向评价：{positive_count}",
            f"- 长引用：{long_context_count}",
            f"- 待补全文/失败项：{failure_count}",
        ]
    )

    examples = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    if examples:
        markdown_lines.extend(["", "## 强引用证据示例", ""])
    for evidence in examples[:5]:
        markdown_lines.extend(
            [
                f"### {evidence.get('citing_title') or '未知引用论文'}",
                "",
                f"- 命中目标：{evidence.get('cited_publication_title') or '-'}",
                (
                    f"- 类型/态度：{evidence.get('aspect') or '-'} / "
                    f"{evidence.get('stance') or '-'}"
                ),
                f"- Fellow 强引用：{'是' if evidence.get('fellow_strong_citation') else '否'}",
                f"- 证据标签：{' / '.join(evidence.get('evidence_label_names') or [label_names.get(label, label) for label in evidence.get('evidence_labels') or []]) or '-'}",
                f"- 强度分：{evidence.get('strong_citation_score') if evidence.get('strong_citation_score') is not None else '-'}",
                f"- 汇报价值：{evidence.get('valuable_reason') or evidence.get('reason') or '-'}",
                "",
                str(evidence.get("citation_text") or "").strip(),
                "",
            ]
        )

    return {
        "summary_text": summary_text,
        "bullets": bullets,
        "narrative_bullets": narrative_bullets,
        "top_evidence": top_evidence,
        "limitations": limitations,
        "markdown": "\n".join(markdown_lines).rstrip() + "\n",
        "overview": {
            "publication_count": publication_count,
            "citation_edge_count": citation_edge_count,
            "queue_count": queue_count,
            "analyzed_queue_count": analyzed_queue_count,
            "strong_evidence_count": strong_evidence_count,
            "fellow_strong_count": fellow_strong_count,
            "positive_count": positive_count,
            "long_context_count": long_context_count,
            "failure_count": failure_count,
            "top_target_title": top_target_title,
        },
    }


def write_scholar_report_markdown(session_id: str) -> Path:
    session = load_scholar_status(session_id)
    payload = build_scholar_report_payload(session)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "report.md"
    path.write_text(payload["markdown"], encoding="utf-8")
    return path


def split_review_comment_snippets(text: str) -> list[str]:
    snippets = []
    seen = set()
    for chunk in re.split(r"\n\s*\n|\r\n\s*\r\n", str(text or "")):
        normalized_lines = []
        for line in chunk.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*>\d.)]+)\s*", "", line).strip()
            if cleaned:
                normalized_lines.append(cleaned)
        snippet = re.sub(r"\s+", " ", " ".join(normalized_lines)).strip()
        if len(snippet) < 8:
            continue
        key = snippet.lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(snippet)
    return snippets


def _build_review_comment_evidence_items(
    session: dict[str, Any],
    snippets: list[str],
    *,
    existing_count: int,
) -> list[dict[str, Any]]:
    evidence_helper = scholar_pipeline().SCHOLAR_EVIDENCE
    selected_author = session.get("selected_author") or {}
    target_title = selected_author.get("display_name") or session.get("query") or "目标工作"
    new_items = []
    for index, snippet in enumerate(snippets, 1):
        labels = evidence_helper.derive_evidence_labels(
            {
                "evidence_labels": ["review_comment_praise", "positive_evaluation"],
                "citation_text": snippet,
                "aspect": "review_comment",
                "stance": "positive",
            },
            citation_char_count=len(snippet),
        )
        keywords = [
            keyword
            for keyword in REVIEW_COMMENT_KEYWORDS
            if keyword.lower() in snippet.lower()
        ]
        evidence = {
            "queue_id": f"review_comment_{existing_count + index:03d}",
            "source_type": "review_comment",
            "source_publication_id": "",
            "citing_title": "审稿意见 / 外部评价",
            "citing_venue": "Review Comment",
            "citing_year": "",
            "cited_publication_title": target_title,
            "citation_text": snippet,
            "aspect": "review_comment",
            "stance": "positive",
            "mention_type": "review_comment",
            "confidence": 0.95,
            "evidence_labels": labels,
            "evidence_label_names": [
                evidence_helper.evidence_label_display(label)
                for label in labels
            ],
            "highlight_keywords": keywords,
            "positive_evaluation": True,
            "long_context_100_chars": len(snippet) >= 100,
            "citation_char_count": len(snippet),
            "self_citation_status": "non_self_citation",
            "self_citation_overlap_authors": [],
            "fellow_strong_citation": False,
            "valuable_reason": "来自审稿意见或外部评价原文，可作为补充亮点评价证据。",
            "reason": "review_comment_import",
        }
        evidence["strong_citation_score"] = evidence_helper.score_strong_evidence(
            labels=labels,
            confidence=evidence["confidence"],
            citation_char_count=len(snippet),
            person_tag_labels=[],
            self_citation_status="non_self_citation",
        )
        evidence["evidence_strength"] = (
            "high" if evidence["strong_citation_score"] >= 70
            else "medium" if evidence["strong_citation_score"] >= 45
            else "low"
        )
        new_items.append(evidence)
    return new_items


REVIEW_COMMENT_KEYWORDS = [
    "excellent",
    "novel",
    "important",
    "significant",
    "state-of-the-art",
    "first",
    "首次",
    "创新",
    "重要",
    "优秀",
]


def _append_review_comment_evidence(
    session: dict[str, Any],
    snippets: list[str],
) -> int:
    existing = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    new_items = _build_review_comment_evidence_items(
        session,
        snippets,
        existing_count=len(existing),
    )

    session["strong_evidence"] = _deduplicate_strong_evidence(existing + new_items)
    session["review_comment_imports"] = (session.get("review_comment_imports") or []) + [
        {
            "imported_at": datetime.now().isoformat(timespec="seconds"),
            "snippet_count": len(new_items),
        }
    ]
    return len(new_items)


def import_review_comment_evidence(session_id: str, review_comments_text: str) -> int:
    session = load_scholar_status(session_id)
    snippets = split_review_comment_snippets(review_comments_text)
    if not snippets:
        raise ValueError("请先粘贴审稿意见或外部评价原文。")
    imported_count = _append_review_comment_evidence(session, snippets)
    write_scholar_status(session_id, session)
    return imported_count


def _evidence_team_key(item: dict[str, Any]) -> str:
    for author in item.get("person_tag_matched_authors") or []:
        key = scholar_pipeline().SCHOLAR_STATS.normalized_name(author)
        if key:
            return key
    for author in item.get("citing_authors") or []:
        key = scholar_pipeline().SCHOLAR_STATS.normalized_name(author)
        if key:
            return key
    return ""


def _highlight_card_report_sentence(item: dict[str, Any], labels: list[str]) -> str:
    citing_title = item.get("citing_title") or "该引用论文"
    target_title = item.get("cited_publication_title") or "目标工作"
    label_text = "、".join(labels[:4]) if labels else "强引用"
    return (
        f"{citing_title} 将 {target_title} 作为{label_text}证据；"
        f"其原文摘录可支撑该亮点评价。"
    )


def build_highlight_cards(session: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    evidence_items = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    team_groups: dict[str, list[dict[str, Any]]] = {}
    for item in evidence_items:
        if (item.get("third_party_status") or item.get("self_citation_status") or "unknown") != "non_self_citation":
            continue
        key = _evidence_team_key(item)
        if key:
            team_groups.setdefault(key, []).append(item)

    cards = []
    evidence_helper = scholar_pipeline().SCHOLAR_EVIDENCE
    for item in evidence_items:
        if (item.get("third_party_status") or item.get("self_citation_status") or "unknown") != "non_self_citation":
            continue
        if (item.get("strong_citation_score") or 0) < 45:
            continue
        raw_labels = list(item.get("evidence_labels") or [])
        labels = list(
            item.get("evidence_label_names")
            or [evidence_helper.evidence_label_display(label) for label in raw_labels]
        )
        team_key = _evidence_team_key(item)
        followup_group = team_groups.get(team_key, []) if team_key else []
        followup_titles = [
            evidence.get("citing_title") or ""
            for evidence in followup_group
            if evidence.get("citing_title")
        ]
        if len(followup_titles) >= 2 and "sustained_followup" not in raw_labels:
            raw_labels.append("sustained_followup")
            display = evidence_helper.evidence_label_display("sustained_followup")
            if display not in labels:
                labels.append(display)
        important = " / ".join(item.get("person_tag_labels") or [])
        citing_title = item.get("citing_title") or "未知引用论文"
        target_title = item.get("cited_publication_title") or "目标工作"
        headline = (
            f"{important} 团队引用并评价 {target_title}"
            if important
            else f"{citing_title} 引用并评价 {target_title}"
        )
        cards.append(
            {
                "headline": headline,
                "citing_title": citing_title,
                "citing_venue": item.get("citing_venue") or "",
                "citing_year": item.get("citing_year") or "",
                "target_title": target_title,
                "labels": labels,
                "raw_labels": raw_labels,
                "score": item.get("strong_citation_score") or 0,
                "self_citation_status": item.get("self_citation_status") or "unknown",
                "important_person": important,
                "evidence_excerpt": item.get("citation_text") or "",
                "highlight_keywords": item.get("highlight_keywords") or [],
                "highlighted_evidence_excerpt": evidence_helper.highlight_excerpt_html(
                    item.get("citation_text") or "",
                    item.get("highlight_keywords") or [],
                ),
                "why_valuable": item.get("valuable_reason") or item.get("why_valuable") or item.get("reason") or "",
                "report_sentence_label": "汇报句",
                "report_sentence": _highlight_card_report_sentence(item, labels),
                "followup_group": team_key,
                "followup_count": len(set(followup_titles)),
                "followup_titles": sorted(set(followup_titles)),
            }
        )
    cards = sorted(
        cards,
        key=lambda item: (
            -(item.get("score") or 0),
            -len(item.get("labels") or []),
            item.get("citing_title") or "",
        ),
    )[:limit]
    for index, card in enumerate(cards, 1):
        card["index"] = index
    return cards


def build_highlight_cards_csv(session: dict[str, Any]) -> str:
    headers = [
        "index",
        "headline",
        "citing_title",
        "citing_venue",
        "citing_year",
        "target_title",
        "labels",
        "score",
        "self_citation_status",
        "important_person",
        "evidence_excerpt",
        "highlight_keywords",
        "why_valuable",
        "report_sentence",
        "followup_count",
        "followup_titles",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for card in build_highlight_cards(session):
        row = dict(card)
        row["labels"] = " | ".join(card.get("labels") or [])
        row["highlight_keywords"] = " | ".join(card.get("highlight_keywords") or [])
        row["followup_titles"] = " | ".join(card.get("followup_titles") or [])
        writer.writerow({key: row.get(key, "") for key in headers})
    return buffer.getvalue()


def build_highlight_cards_markdown(session: dict[str, Any]) -> str:
    cards = build_highlight_cards(session)
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
                f"### {card['index']}. {card.get('headline') or '-'}",
                "",
                f"- 引用论文：{card.get('citing_title') or '-'}",
                f"- 命中目标：{card.get('target_title') or '-'}",
                f"- 证据标签：{' / '.join(card.get('labels') or []) or '-'}",
                f"- 重要人物：{card.get('important_person') or '-'}",
                f"- 强度分：{card.get('score') if card.get('score') is not None else '-'}",
                f"- {card.get('report_sentence_label') or '汇报句'}：{card.get('report_sentence') or '-'}",
                f"- 汇报价值：{card.get('why_valuable') or '-'}",
                "",
                "原文证据：",
                "",
                excerpt or "-",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_highlight_cards_csv(session_id: str) -> Path:
    session = load_scholar_status(session_id)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "highlight_cards.csv"
    path.write_text(build_highlight_cards_csv(session), encoding="utf-8-sig")
    return path


def write_highlight_cards_markdown(session_id: str) -> Path:
    session = load_scholar_status(session_id)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "highlight_cards.md"
    path.write_text(build_highlight_cards_markdown(session), encoding="utf-8")
    return path


def build_scholar_citation_statistics_csv(session: dict[str, Any]) -> str:
    person_candidates = session.get("person_candidates", []) or []
    statistics = session.get("statistics") or {}
    person_stats = statistics.get("person_tag_statistics")
    if not isinstance(person_stats, list):
        person_stats = scholar_pipeline().SCHOLAR_STATS.person_tag_statistics(
            person_candidates
        )
    group_by_type = {
        (group.get("tag_type") or ""): group
        for group in person_stats
        if isinstance(group, dict)
    }
    headers = [
        "candidate_id",
        "tag_type",
        "tag_label",
        "matched_author_count",
        "candidate_count",
        "ambiguous_author_count",
        "high_risk_author_count",
        "confirmed_count",
        "pending_count",
        "rejected_count",
        "source_complete_count",
        "matched_paper_count",
        "candidate_name",
        "candidate_status",
        "matched_authors",
        "resolved_matched_authors",
        "matched_paper_ids",
        "matched_paper_titles",
        "matched_affiliations",
        "homonym_risk",
        "risk_flags",
        "auto_match_status",
        "auto_match_score",
        "auto_match_confidence",
        "auto_match_reasons",
        "source_links",
        "review_note",
        "reviewed_at",
        "note",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()

    for candidate in person_candidates:
        if not isinstance(candidate, dict):
            continue
        tag_type = (candidate.get("tag_type") or "").strip()
        group = group_by_type.get(tag_type, {})
        matched_authors = []
        seen_authors = set()
        for item in candidate.get("evidence", []) or []:
            matched_author = (item.get("matched_author") or "").strip()
            normalized = scholar_pipeline().SCHOLAR_STATS.normalized_name(matched_author)
            if not normalized or normalized in seen_authors:
                continue
            seen_authors.add(normalized)
            matched_authors.append(matched_author)
        resolved_authors = scholar_pipeline().SCHOLAR_STATS.PERSON_CANDIDATES.candidate_resolved_authors(candidate)
        writer.writerow(
            {
                "candidate_id": candidate.get("candidate_id") or "",
                "tag_type": tag_type,
                "tag_label": candidate.get("tag_label") or group.get("tag_label") or "",
                "matched_author_count": group.get("matched_author_count", group.get("count", 0)),
                "candidate_count": group.get("candidate_count", 0),
                "ambiguous_author_count": group.get("ambiguous_author_count", 0),
                "high_risk_author_count": group.get("high_risk_author_count", 0),
                "confirmed_count": group.get("confirmed_count", 0),
                "pending_count": group.get("pending_count", 0),
                "rejected_count": group.get("rejected_count", 0),
                "source_complete_count": group.get("source_complete_count", 0),
                "matched_paper_count": group.get("matched_paper_count", 0),
                "candidate_name": candidate.get("name") or "",
                "candidate_status": candidate.get("status") or "",
                "matched_authors": " | ".join(matched_authors),
                "resolved_matched_authors": " | ".join(resolved_authors),
                "matched_paper_ids": " | ".join(candidate.get("matched_paper_ids") or []),
                "matched_paper_titles": " | ".join(candidate.get("matched_paper_titles") or []),
                "matched_affiliations": " | ".join(candidate.get("matched_affiliations") or []),
                "homonym_risk": "yes" if candidate.get("homonym_risk") else "no",
                "risk_flags": " | ".join(candidate.get("risk_flags") or []),
                "auto_match_status": candidate.get("auto_match_status") or "",
                "auto_match_score": candidate.get("auto_match_score") or 0,
                "auto_match_confidence": candidate.get("auto_match_confidence") or "",
                "auto_match_reasons": " | ".join(candidate.get("auto_match_reasons") or []),
                "source_links": " | ".join(candidate.get("source_links") or []),
                "review_note": candidate.get("review_note") or "",
                "reviewed_at": candidate.get("reviewed_at") or "",
                "note": candidate.get("note") or "",
            }
        )

    return buffer.getvalue()


def write_scholar_citation_statistics_csv(session_id: str) -> Path:
    session = load_scholar_status(session_id)
    csv_text = build_scholar_citation_statistics_csv(session)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "citation_statistics.csv"
    path.write_text(csv_text, encoding="utf-8-sig")
    return path


def build_scholar_raw_citing_authors_csv(session: dict[str, Any]) -> str:
    headers = [
        "source_publication_id",
        "citing_paper_id",
        "citing_title",
        "citing_year",
        "citing_venue",
        "citing_doi",
        "provider",
        "cited_publication_title",
        "author_position",
        "author_name",
        "raw_author_name",
        "author_institutions",
        "author_source_url",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()

    for edge in session.get("citation_edges", []) or []:
        if not isinstance(edge, dict):
            continue
        author_details = edge.get("citing_author_details") or []
        if isinstance(author_details, list) and author_details:
            wrote_detail = False
            for index, detail in enumerate(author_details, 1):
                if not isinstance(detail, dict):
                    continue
                author_name = (detail.get("name") or "").strip()
                if not author_name:
                    continue
                institutions = [
                    item.strip()
                    for item in (detail.get("institutions") or [])
                    if isinstance(item, str) and item.strip()
                ]
                writer.writerow(
                    {
                        "source_publication_id": edge.get("source_publication_id") or "",
                        "citing_paper_id": edge.get("citing_paper_id") or "",
                        "citing_title": edge.get("citing_title") or "",
                        "citing_year": edge.get("citing_year") or "",
                        "citing_venue": edge.get("citing_venue") or "",
                        "citing_doi": edge.get("citing_doi") or "",
                        "provider": edge.get("provider") or "",
                        "cited_publication_title": edge.get("cited_publication_title") or "",
                        "author_position": index,
                        "author_name": author_name,
                        "raw_author_name": (
                            (edge.get("citing_authors") or [])[index - 1]
                            if len(edge.get("citing_authors") or []) >= index
                            else author_name
                        ),
                        "author_institutions": " | ".join(institutions),
                        "author_source_url": detail.get("source_url") or "",
                    }
                )
                wrote_detail = True
            if wrote_detail:
                continue

        for index, author_name in enumerate(edge.get("citing_authors") or [], 1):
            if not author_name:
                continue
            writer.writerow(
                {
                    "source_publication_id": edge.get("source_publication_id") or "",
                    "citing_paper_id": edge.get("citing_paper_id") or "",
                    "citing_title": edge.get("citing_title") or "",
                    "citing_year": edge.get("citing_year") or "",
                    "citing_venue": edge.get("citing_venue") or "",
                    "citing_doi": edge.get("citing_doi") or "",
                    "provider": edge.get("provider") or "",
                    "cited_publication_title": edge.get("cited_publication_title") or "",
                    "author_position": index,
                    "author_name": author_name,
                    "raw_author_name": author_name,
                    "author_institutions": "",
                    "author_source_url": "",
                }
            )

    return buffer.getvalue()


def write_scholar_raw_citing_authors_csv(session_id: str) -> Path:
    session = load_scholar_status(session_id)
    csv_text = build_scholar_raw_citing_authors_csv(session)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "raw_citing_authors.csv"
    path.write_text(csv_text, encoding="utf-8-sig")
    return path


def _queue_item_has_bound_pdf(item: dict[str, Any]) -> bool:
    manual_pdf = item.get("manual_pdf") or {}
    library_pdf = item.get("library_pdf") or {}
    return bool(
        manual_pdf.get("local_file_path")
        or manual_pdf.get("status")
        or library_pdf.get("local_file_path")
        or library_pdf.get("status")
    )


def _unique_pdf_path(directory: Path, stem: str) -> Path:
    safe_stem = stem.strip()[:160] or "paper"
    candidate = directory / f"{safe_stem}.pdf"
    if not candidate.exists():
        return candidate
    return directory / f"{safe_stem}_{uuid4().hex[:8]}.pdf"


def _import_uploaded_pdf_to_library(
    *,
    source_path: Path,
    queue_item: dict[str, Any],
    download_pdf: Any,
    pipeline: Any,
) -> dict[str, Any]:
    search_dirs = pipeline.configured_local_pdf_library_dirs(download_pdf)
    if not search_dirs:
        return {
            "status": "skipped",
            "reason": "local_pdf_library_not_configured",
        }

    library_dir = Path(search_dirs[0]).expanduser()
    library_dir.mkdir(parents=True, exist_ok=True)
    safe_title = download_pdf.sanitize_filename(
        queue_item.get("citing_title") or queue_item.get("queue_id") or "paper"
    )
    library_path = _unique_pdf_path(library_dir, safe_title)
    shutil.copy2(source_path, library_path)
    return {
        "status": "imported",
        "library_file_path": str(library_path),
        "library_dir": str(library_dir),
    }


def _arxiv_id_from_queue_item(item: dict[str, Any]) -> str:
    candidates = [
        item.get("citing_arxiv_id") or "",
        item.get("arxiv_id") or "",
        item.get("citing_doi") or "",
        item.get("citing_paper_id") or "",
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text, flags=re.I)
        text = re.sub(r"^doi\s*:\s*", "", text, flags=re.I)
        text = re.sub(r"^10\.48550/arxiv\.", "", text, flags=re.I)
        text = re.sub(r"^arxiv\s*:\s*", "", text, flags=re.I)
        text = re.sub(r"\.pdf$", "", text, flags=re.I)
        text = re.sub(r"v\d+$", "", text, flags=re.I)
        if re.fullmatch(r"\d{4}\.\d{4,5}", text):
            return text
    return ""


def _doi_suffix_filename(doi: str) -> str:
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi or "", flags=re.I)
    normalized = re.sub(r"^doi\s*:\s*", "", normalized, flags=re.I).strip()
    suffix = normalized.split("/", 1)[1] if "/" in normalized else normalized
    suffix = suffix.strip("._- ")
    return f"{suffix}.pdf" if suffix else ""


def build_scholar_missing_pdfs_csv(session: dict[str, Any]) -> str:
    headers = [
        "queue_id",
        "priority_score",
        "reasons",
        "citing_title",
        "citing_doi",
        "doi_url",
        "suggested_filename",
        "arxiv_id",
        "arxiv_url",
        "citing_year",
        "citing_venue",
        "citing_authors",
        "cited_publication_count",
        "cited_publication_titles",
        "source_publication_ids",
        "provider",
        "citing_paper_id",
        "citing_openalex_id",
        "citing_scopus_id",
        "source_url",
        "download_priority",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()

    for item in session.get("deep_analysis_queue", []) or []:
        if not isinstance(item, dict) or _queue_item_has_bound_pdf(item):
            continue
        doi = (item.get("citing_doi") or "").strip()
        arxiv_id = _arxiv_id_from_queue_item(item)
        if arxiv_id:
            priority = "arxiv"
        elif doi:
            priority = "doi"
        elif item.get("source_url"):
            priority = "source_url"
        else:
            priority = "title_search"
        writer.writerow(
            {
                "queue_id": item.get("queue_id") or "",
                "priority_score": item.get("priority_score") or "",
                "reasons": " | ".join(item.get("reasons") or []),
                "citing_title": item.get("citing_title") or "",
                "citing_doi": doi,
                "doi_url": f"https://doi.org/{doi}" if doi else "",
                "suggested_filename": _doi_suffix_filename(doi),
                "arxiv_id": arxiv_id,
                "arxiv_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
                "citing_year": item.get("citing_year") or "",
                "citing_venue": item.get("citing_venue") or "",
                "citing_authors": " | ".join(item.get("citing_authors") or []),
                "cited_publication_count": item.get("cited_publication_count") or "",
                "cited_publication_titles": " | ".join(item.get("cited_publication_titles") or []),
                "source_publication_ids": " | ".join(item.get("source_publication_ids") or []),
                "provider": item.get("provider") or "",
                "citing_paper_id": item.get("citing_paper_id") or "",
                "citing_openalex_id": item.get("citing_openalex_id") or "",
                "citing_scopus_id": item.get("citing_scopus_id") or "",
                "source_url": item.get("source_url") or "",
                "download_priority": priority,
            }
        )

    return buffer.getvalue()


def write_scholar_missing_pdfs_csv(session_id: str) -> Path:
    session = load_scholar_status(session_id)
    csv_text = build_scholar_missing_pdfs_csv(session)
    export_dir = resolve_scholar_session_dir(session_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "missing_pdfs.csv"
    path.write_text(csv_text, encoding="utf-8-sig")
    return path


def get_scholar_pdf_download_report_path(session_id: str) -> Path:
    return resolve_scholar_session_dir(session_id) / "exports" / "pdf_download_report.csv"


def _queue_item_publisher_url(item: dict[str, Any]) -> str:
    source_url = (item.get("source_url") or "").strip()
    if source_url and _is_human_browsable_publisher_url(source_url):
        return source_url
    doi = (item.get("citing_doi") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    scopus_id = _scopus_id_from_queue_item(item)
    if scopus_id:
        return f"https://www.scopus.com/inward/record.uri?scp={scopus_id}&partnerID=HzOxMe3b&origin=inward"
    if source_url:
        return source_url
    return ""


def _is_human_browsable_publisher_url(url: str) -> bool:
    lowered = str(url or "").strip().lower()
    if not lowered:
        return False
    machine_url_markers = [
        "api.elsevier.com/content/",
        "api.openalex.org/",
        "api.crossref.org/",
    ]
    return not any(marker in lowered for marker in machine_url_markers)


def _scopus_id_from_queue_item(item: dict[str, Any]) -> str:
    raw_values = [
        item.get("citing_scopus_id"),
        item.get("citing_paper_id"),
        item.get("source_url"),
    ]
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        scopus_match = re.search(r"(?:scopus_id/|scp=|2-s2\.0-)(\d+)", text)
        if scopus_match:
            return scopus_match.group(1)
        if text.isdigit():
            return text
    return ""


def _queue_item_download_query(item: dict[str, Any]) -> tuple[str, str]:
    arxiv_id = _arxiv_id_from_queue_item(item)
    if arxiv_id:
        return "arxiv", arxiv_id
    doi = (item.get("citing_doi") or "").strip()
    if doi:
        return "doi", doi
    source_url = (item.get("source_url") or "").strip()
    if source_url:
        return "source_url", source_url
    title = (item.get("citing_title") or "").strip()
    if title:
        return "title", title
    return "", ""


def _write_pdf_download_report(session_id: str, rows: list[dict[str, Any]]) -> Path:
    headers = [
        "queue_id",
        "status",
        "query_type",
        "query",
        "citing_title",
        "citing_doi",
        "file_path",
        "pdf_url",
        "publisher_url",
        "source_strategy",
        "candidate_count",
        "attempted_count",
        "failure_type",
        "elapsed_ms",
        "download_errors",
        "error",
    ]
    path = get_scholar_pdf_download_report_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) or "" for key in headers})
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")
    return path


def _pdf_download_max_workers(value: int | None = None) -> int:
    if value is not None:
        return max(1, min(int(value), 8))
    raw_value = os.getenv("ACADEMIC_IMPACT_PDF_DOWNLOAD_WORKERS", "4")
    try:
        return max(1, min(int(raw_value), 8))
    except ValueError:
        return 4


INSTITUTION_LOGIN_HOST_HINTS = (
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "acm.org",
    "sciencedirect.com",
    "link.springer.com",
    "springer.com",
    "wiley.com",
    "tandfonline.com",
    "worldscientific.com",
)


def _download_failure_text(result: dict[str, Any]) -> str:
    values: list[Any] = [
        result.get("error"),
        result.get("pdf_url"),
        result.get("source_url"),
        result.get("publisher_url"),
        result.get("query"),
        result.get("source_strategy"),
    ]
    values.extend(result.get("pdf_candidates") or [])
    for error in result.get("download_errors") or []:
        if isinstance(error, dict):
            values.extend([error.get("url"), error.get("error")])
        else:
            values.append(error)
    return " ".join(str(value or "") for value in values).lower()


def _looks_like_institution_login_required(result: dict[str, Any]) -> bool:
    text = _download_failure_text(result)
    if not text:
        return False
    login_markers = (
        "denied",
        "institutional sign in",
        "institution login",
        "institutional login",
        "subscribe to access",
        "access denied",
        "permission_required",
    )
    return any(marker in text for marker in login_markers) or any(
        host in text for host in INSTITUTION_LOGIN_HOST_HINTS
    )


def _classify_pdf_download_failure(result: dict[str, Any]) -> str:
    if _looks_like_institution_login_required(result):
        return "requires_institution_login"
    error = str(result.get("error") or "").lower()
    if not result.get("pdf_candidates") and "开源 pdf" in error:
        return "no_pdf_candidates"
    if not result.get("pdf_candidates") and "pdf candidate" in error:
        return "no_pdf_candidates"
    if "timeout" in error or "timed out" in error:
        return "timeout"
    if "403" in error or "401" in error:
        return "permission_required"
    if "404" in error:
        return "not_found"
    if "不是 pdf" in error or "not pdf" in error or "html" in error:
        return "downloaded_non_pdf"
    if "未找到论文" in error:
        return "metadata_not_found"
    if error:
        return "download_failed"
    return ""


def _download_pdf_from_source_url(
    item: dict[str, Any],
    source_url: str,
    *,
    download_pdf: Any,
    pipeline: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    is_probable_pdf_url = getattr(
        download_pdf,
        "is_probable_pdf_url",
        lambda url: str(url).lower().split("?", 1)[0].endswith(".pdf"),
    )
    if is_probable_pdf_url(source_url):
        candidates = [source_url]
        source_strategy = "source_url_direct_pdf"
    else:
        extractor = getattr(download_pdf, "extract_pdf_candidates_from_html_page", None)
        candidates = list(extractor(source_url) or []) if extractor else []
        source_strategy = "source_url_candidate_extraction"

    if not candidates:
        failure = {
            "ok": False,
            "source_strategy": source_strategy,
            "source_url": source_url,
            "publisher_url": _queue_item_publisher_url(item) or source_url,
            "pdf_candidates": [],
            "candidate_count": 0,
            "attempted_count": 0,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error": "source_url_no_pdf_candidates",
        }
        failure["failure_type"] = _classify_pdf_download_failure(failure)
        return {
            **failure,
        }

    search_dirs = pipeline.configured_local_pdf_library_dirs(download_pdf)
    fallback_dir = getattr(download_pdf, "DEFAULT_LOCAL_PDF_DIR", str(PROJECT_ROOT / "data" / "downloads"))
    save_dir = Path(search_dirs[0] if search_dirs else fallback_dir).expanduser()
    save_dir.mkdir(parents=True, exist_ok=True)
    sanitize = getattr(download_pdf, "sanitize_filename", lambda value: re.sub(r"[\\/]+", "_", value).strip()[:180] or "paper")
    target_path = _unique_pdf_path(
        save_dir,
        sanitize(item.get("citing_title") or item.get("queue_id") or "paper"),
    )
    download_file = getattr(download_pdf, "download_file", None)
    if download_file is None:
        return {
            "ok": False,
            "source_strategy": source_strategy,
            "pdf_candidates": candidates,
            "candidate_count": len(candidates),
            "attempted_count": 0,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "failure_type": "download_failed",
            "error": "download_file_not_available",
        }

    errors = []
    for candidate in candidates:
        ok, error = download_file(candidate, str(target_path))
        if ok:
            return {
                "ok": True,
                "file_path": str(target_path),
                "pdf_url": candidate,
                "publisher_url": _queue_item_publisher_url(item) or source_url,
                "pdf_candidates": candidates,
                "source_strategy": source_strategy,
                "candidate_count": len(candidates),
                "attempted_count": len(errors) + 1,
                "download_errors": errors,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        errors.append({"url": candidate, "error": error or ""})

    failure = {
        "ok": False,
        "pdf_url": candidates[-1] if candidates else "",
        "publisher_url": _queue_item_publisher_url(item) or source_url,
        "source_url": source_url,
        "pdf_candidates": candidates,
        "source_strategy": source_strategy,
        "candidate_count": len(candidates),
        "attempted_count": len(errors),
        "download_errors": errors,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "error": errors[-1]["error"] if errors else "download_failed",
    }
    failure["failure_type"] = _classify_pdf_download_failure(failure)
    return failure


def _download_queue_item_pdf(
    item: dict[str, Any],
    *,
    query_type: str,
    query: str,
    download_pdf: Any,
    pipeline: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    if query_type == "source_url":
        return _download_pdf_from_source_url(
            item,
            query,
            download_pdf=download_pdf,
            pipeline=pipeline,
        )

    result = dict(download_pdf.download_paper(query) or {})
    result["source_strategy"] = "download_paper"
    result["publisher_url"] = _queue_item_publisher_url(item)
    result["candidate_count"] = len(result.get("pdf_candidates") or [])
    result["download_errors"] = result.get("download_errors") or []
    if result.get("ok") and result.get("file_path"):
        result["attempted_count"] = len(result["download_errors"]) + (1 if result.get("pdf_url") else 0)
    else:
        result["attempted_count"] = len(result["download_errors"])
        result["failure_type"] = _classify_pdf_download_failure(result)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def _serialize_download_errors(value: Any) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False)


def download_missing_scholar_pdfs(
    session_id: str,
    *,
    max_workers: int | None = None,
) -> dict[str, Any]:
    session = load_scholar_status(session_id)
    pipeline = scholar_pipeline()
    download_pdf = pipeline.RUN_PIPELINE.DOWNLOAD_PDF
    queue = session.get("deep_analysis_queue", []) or []
    total = len(queue)
    rows: list[dict[str, Any]] = []
    work_items: list[dict[str, Any]] = []
    success_count = 0
    failed_count = 0
    skipped_count = 0

    update_task_state(
        session_id,
        processed_count=0,
        total_count=total,
        message=f"正在批量下载待补 PDF 0/{total}",
        stage="downloading_missing_pdf",
        stage_message="准备下载待补 PDF",
        current_queue_id="",
        current_title="",
        current_index=0,
    )

    for index, item in enumerate(queue, start=1):
        queue_id = item.get("queue_id") or ""
        title = item.get("citing_title") or ""
        row = {
            "queue_id": queue_id,
            "citing_title": title,
            "citing_doi": item.get("citing_doi") or "",
            "publisher_url": _queue_item_publisher_url(item),
            "_index": index,
        }
        if _queue_item_has_bound_pdf(item):
            skipped_count += 1
            rows.append({**row, "status": "skipped_existing_pdf"})
            continue

        query_type, query = _queue_item_download_query(item)
        row.update({"query_type": query_type, "query": query})
        if not query:
            failed_count += 1
            rows.append(
                {
                    **row,
                    "status": "failed",
                    "failure_type": "missing_download_query",
                    "error": "missing_download_query",
                }
            )
            continue
        work_items.append(
            {
                "index": index,
                "item": item,
                "row": row,
                "query_type": query_type,
                "query": query,
            }
        )

    completed_count = len(rows)
    worker_count = _pdf_download_max_workers(max_workers)
    future_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        for work in work_items:
            future = executor.submit(
                _download_queue_item_pdf,
                work["item"],
                query_type=work["query_type"],
                query=work["query"],
                download_pdf=download_pdf,
                pipeline=pipeline,
            )
            future_map[future] = work

        for future in concurrent.futures.as_completed(future_map):
            work = future_map[future]
            item = work["item"]
            row = work["row"]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "failure_type": "download_failed",
                    "source_strategy": work["query_type"],
                    "elapsed_ms": 0,
                }

            completed_count += 1
            update_task_state(
                session_id,
                processed_count=completed_count,
                total_count=total,
                message=f"正在批量下载待补 PDF {completed_count}/{total}",
                stage="downloading_missing_pdf",
                stage_message=f"并发下载待补 PDF（{worker_count} 线程）",
                current_queue_id=item.get("queue_id") or "",
                current_title=item.get("citing_title") or "",
                current_index=work["index"],
            )

            file_path = str(Path(result.get("file_path") or "").expanduser()) if result.get("file_path") else ""
            if result.get("ok") and file_path and Path(file_path).exists():
                item["library_pdf"] = {
                    "status": "local_library_matched",
                    "source": "local_pdf_library",
                    "local_file_path": file_path,
                    "matched_dir": str(Path(file_path).parent),
                    "match_source": "batch_missing_pdf_download",
                    "matched_at": datetime.now().isoformat(timespec="seconds"),
                }
                success_count += 1
                rows.append(
                    {
                        **row,
                        "status": "downloaded",
                        "file_path": file_path,
                        "pdf_url": result.get("pdf_url") or "",
                        "publisher_url": result.get("publisher_url") or row.get("publisher_url") or "",
                        "source_strategy": result.get("source_strategy") or "",
                        "candidate_count": result.get("candidate_count") or 0,
                        "attempted_count": result.get("attempted_count") or 0,
                        "elapsed_ms": result.get("elapsed_ms") or 0,
                        "download_errors": _serialize_download_errors(result.get("download_errors")),
                    }
                )
                continue

            failed_count += 1
            rows.append(
                {
                    **row,
                    "status": "failed",
                    "pdf_url": result.get("pdf_url") or "",
                    "publisher_url": result.get("publisher_url") or row.get("publisher_url") or "",
                    "source_strategy": result.get("source_strategy") or "",
                    "candidate_count": result.get("candidate_count") or 0,
                    "attempted_count": result.get("attempted_count") or 0,
                    "failure_type": result.get("failure_type") or _classify_pdf_download_failure(result),
                    "elapsed_ms": result.get("elapsed_ms") or 0,
                    "download_errors": _serialize_download_errors(result.get("download_errors")),
                    "error": result.get("error") or "download_failed",
                }
            )

    rows.sort(key=lambda item: int(item.get("_index") or 0))
    for row in rows:
        row.pop("_index", None)

    search_dirs = pipeline.configured_local_pdf_library_dirs(download_pdf)
    index_path = download_pdf.DEFAULT_LOCAL_PDF_INDEX_PATH
    if search_dirs:
        download_pdf.build_local_pdf_index(search_dirs, index_path=index_path)
    report_path = _write_pdf_download_report(session_id, rows)

    with _task_lock(session_id):
        current = load_scholar_status(session_id)
        session["task_state"] = ensure_task_state(current)
        session["pdf_download_report"] = {
            "report_path": str(report_path),
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_scholar_status(session_id, session)

    update_task_state(
        session_id,
        processed_count=total,
        total_count=total,
        message=f"批量下载待补 PDF 完成：成功 {success_count}，失败 {failed_count}，跳过 {skipped_count}",
        stage="downloading_missing_pdf",
        stage_message="待补 PDF 下载完成",
        current_queue_id="",
        current_title="",
        current_index=total,
    )
    return {
        "ok": True,
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "report_path": str(report_path),
    }


def update_task_state(session_id: str, **updates) -> dict[str, Any]:
    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        task_state.update(updates)
        task_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        session["task_state"] = task_state
        write_scholar_status(session_id, session)
        return dict(task_state)


def mark_task_running(
    session_id: str,
    task_type: str,
    *,
    limit_per_publication: int | None = None,
    message: str = "",
) -> tuple[bool, dict[str, Any]]:
    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            return False, dict(task_state)
        now = datetime.now().isoformat(timespec="seconds")
        task_state.update(
            {
                "active": True,
                "task_type": task_type,
                "status": "running",
                "message": message,
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
                "error": "",
                "processed_count": 0,
                "total_count": len(session.get("publications", []) or []),
                "citation_edge_count": len(session.get("citation_edges", []) or []),
                "deep_analysis_queue_count": len(session.get("deep_analysis_queue", []) or []),
                "limit_per_publication": limit_per_publication,
                "stage": "",
                "stage_message": "",
                "current_queue_id": "",
                "current_title": "",
                "current_index": 0,
            }
        )
        session["task_state"] = task_state
        write_scholar_status(session_id, session)
        return True, dict(task_state)


def mark_task_finished(
    session_id: str,
    *,
    status: str,
    message: str = "",
    error: str = "",
) -> dict[str, Any]:
    session = load_scholar_status(session_id)
    return update_task_state(
        session_id,
        active=False,
        status=status,
        message=message,
        error=error,
        finished_at=datetime.now().isoformat(timespec="seconds"),
        citation_edge_count=len(session.get("citation_edges", []) or []),
        deep_analysis_queue_count=len(session.get("deep_analysis_queue", []) or []),
    )


def expand_scholar_citations(session_id: str, *, limit_per_publication: int = 100) -> dict[str, Any]:
    session = load_scholar_status(session_id)
    total = len(session.get("publications", []) or [])

    def progress_callback(progress: dict[str, Any]) -> None:
        update_task_state(
            session_id,
            processed_count=progress.get("processed_count", 0),
            total_count=progress.get("total_count", total),
            citation_edge_count=progress.get("citation_edge_count", 0),
            message=f"正在展开引用论文 {progress.get('processed_count', 0)}/{progress.get('total_count', total)}",
        )

    expanded = scholar_pipeline().expand_publication_citations(
        session,
        limit_per_publication=limit_per_publication,
        progress_callback=progress_callback,
    )
    with _task_lock(session_id):
        current = load_scholar_status(session_id)
        expanded["task_state"] = ensure_task_state(current)
        write_scholar_status(session_id, expanded)
    return expanded


def rebuild_scholar_derived_outputs(
    session_id: str,
    *,
    queue_limit: int = 300,
) -> dict[str, Any]:
    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            raise ValueError("当前后台任务仍在运行，暂时不能重建统计和队列。")
        rebuilt = scholar_pipeline().rebuild_scholar_derived_outputs(
            session,
            queue_limit=queue_limit,
        )
        write_scholar_status(session_id, rebuilt)
        return rebuilt


def update_scholar_exclusion_profile(
    session_id: str,
    *,
    extra_excluded_authors_text: str,
    extra_excluded_affiliations_text: str,
    exclude_selected_author: bool = True,
    exclude_source_paper_authors: bool = True,
) -> dict[str, Any]:
    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            raise ValueError("当前后台任务仍在运行，暂时不能更新排除配置。")
        session["exclusion_profile"] = {
            "exclude_selected_author": bool(exclude_selected_author),
            "exclude_source_paper_authors": bool(exclude_source_paper_authors),
            "extra_excluded_authors": parse_multiline_values(extra_excluded_authors_text),
            "extra_excluded_affiliations": parse_multiline_values(extra_excluded_affiliations_text),
        }
        rebuilt = scholar_pipeline().rebuild_scholar_derived_outputs(
            session,
            queue_limit=len(session.get("deep_analysis_queue", []) or []) or 300,
        )
        write_scholar_status(session_id, rebuilt)
        return rebuilt


def update_scholar_analysis_templates(
    session_id: str,
    *,
    active_template_ids: list[str],
    custom_requests_text: str,
) -> dict[str, Any]:
    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            raise ValueError("当前后台任务仍在运行，暂时不能更新分析模板。")
        template_module = scholar_pipeline().EVIDENCE_TEMPLATES
        builtin = template_module.load_builtin_templates()
        builtin_by_id = {item.get("id"): item for item in builtin}
        active_ids = []
        compiled = []
        for template_id in active_template_ids:
            template_id = str(template_id or "").strip()
            if template_id and template_id in builtin_by_id and template_id not in active_ids:
                active_ids.append(template_id)
                compiled.append(builtin_by_id[template_id])
        custom_requests = parse_multiline_values(custom_requests_text)
        compiled.extend(
            template_module.compile_custom_request(request)
            for request in custom_requests
        )
        session["analysis_templates"] = {
            "active_template_ids": active_ids,
            "custom_requests": custom_requests,
            "compiled_templates": compiled,
        }
        write_scholar_status(session_id, session)
        return session


def add_scholar_review_comment_evidence(
    session_id: str,
    *,
    review_comments_text: str,
) -> int:
    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            raise ValueError("当前后台任务仍在运行，暂时不能导入审稿意见。")
        snippets = split_review_comment_snippets(review_comments_text)
        if not snippets:
            raise ValueError("请先粘贴审稿意见或外部评价原文。")
        imported_count = _append_review_comment_evidence(session, snippets)
        write_scholar_status(session_id, session)
        return imported_count


def refresh_scholar_local_pdf_index(session_id: str) -> dict[str, Any]:
    with _task_lock(session_id):
        refresh_started = time.perf_counter()
        session = load_scholar_status(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            raise ValueError("当前后台任务仍在运行，暂时不能刷新本地 PDF 索引。")

        pipeline = scholar_pipeline()
        download_pdf = pipeline.RUN_PIPELINE.DOWNLOAD_PDF
        search_dirs = pipeline.configured_local_pdf_library_dirs(download_pdf)
        index_path = download_pdf.DEFAULT_LOCAL_PDF_INDEX_PATH
        download_pdf.build_local_pdf_index(search_dirs, index_path=index_path)
        index_data = download_pdf.load_local_pdf_index(index_path=index_path)
        queue_started = time.perf_counter()
        queue_items_scanned = 0
        queue_items_updated = 0
        for item in session.get("deep_analysis_queue", []) or []:
            if item.get("manual_pdf"):
                continue
            queue_items_scanned += 1
            existing = item.get("library_pdf")
            matched = pipeline.match_queue_item_local_pdf(
                item,
                download_pdf,
                search_dirs=search_dirs,
                index_data=index_data,
            )
            if matched:
                item["library_pdf"] = matched
            else:
                item.pop("library_pdf", None)
            if item.get("library_pdf") != existing:
                queue_items_updated += 1
        queue_rematch_elapsed_ms = int((time.perf_counter() - queue_started) * 1000)
        session["local_pdf_index_refresh"] = {
            "refresh_total_ms": int((time.perf_counter() - refresh_started) * 1000),
            "queue_rematch_elapsed_ms": queue_rematch_elapsed_ms,
            "queue_items_scanned": queue_items_scanned,
            "queue_items_updated": queue_items_updated,
            "last_refreshed_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_scholar_status(session_id, session)
        return load_local_pdf_index_status(session)


def review_person_candidate(
    session_id: str,
    candidate_id: str,
    *,
    action: str,
    note: str = "",
) -> dict[str, Any]:
    normalized_action = (action or "").strip().lower()
    if normalized_action not in {"confirm", "reject", "reset"}:
        raise ValueError(f"不支持的人物候选操作: {action}")

    with _task_lock(session_id):
        session = load_scholar_status(session_id)
        matched = None
        for candidate in session.get("person_candidates", []) or []:
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

        stats = scholar_pipeline().SCHOLAR_STATS
        session["statistics"] = stats.build_scholar_statistics(
            session.get("publications", []),
            session.get("citation_edges", []),
            session.get("person_candidates", []),
            strong_evidence_count=len(
                _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
            ),
        )
        session["deep_analysis_queue"] = stats.build_deep_analysis_queue(
            session.get("citation_edges", []),
            session.get("person_candidates", []),
            limit=len(session.get("deep_analysis_queue", []) or []) or 300,
            selected_author_names=[
                (session.get("selected_author") or {}).get("display_name") or "",
            ],
            exclusion_profile=session.get("exclusion_profile") or {},
        )
        write_scholar_status(session_id, session)
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "status": matched.get("status"),
        }


def attach_scholar_queue_pdf(
    session_id: str,
    queue_id: str,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    if not queue_id.strip():
        raise ValueError("绑定 PDF 需要 queue_id。")
    if not filename.lower().endswith(".pdf"):
        raise ValueError("当前只支持上传 PDF 文件。")
    if not content:
        raise ValueError("上传的 PDF 文件为空。")

    session = load_scholar_status(session_id)
    queue_item = None
    for item in session.get("deep_analysis_queue", []) or []:
        if item.get("queue_id") == queue_id:
            queue_item = item
            break
    if queue_item is None:
        raise ValueError(f"未找到高价值引用队列项: {queue_id}")

    pipeline = scholar_pipeline()
    download_pdf = pipeline.RUN_PIPELINE.DOWNLOAD_PDF
    session_dir = resolve_scholar_session_dir(session_id)
    upload_dir = session_dir / "uploads" / "scholar_queue"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f".{queue_id}.{uuid4().hex}.pdf"
    temp_path.write_bytes(content)
    inspection = download_pdf.inspect_pdf_file(str(temp_path))
    if not inspection.get("ok"):
        temp_path.unlink(missing_ok=True)
        error_type = inspection.get("error_type") or "pdf_invalid"
        error = inspection.get("error") or "PDF 文件校验失败。"
        raise ValueError(f"绑定失败：{error_type}。{error}")

    safe_title = download_pdf.sanitize_filename(
        queue_item.get("citing_title") or queue_id
    )
    target_path = upload_dir / f"{queue_id}_{safe_title}.pdf"
    if target_path.exists():
        target_path.unlink()
    shutil.move(str(temp_path), str(target_path))
    library_import = _import_uploaded_pdf_to_library(
        source_path=target_path,
        queue_item=queue_item,
        download_pdf=download_pdf,
        pipeline=pipeline,
    )
    queue_item["manual_pdf"] = {
        "status": "manual_pdf_attached",
        "source": "manual_upload",
        "file_name": filename,
        "local_file_path": str(target_path),
        "size_bytes": inspection.get("size_bytes"),
        "attached_at": datetime.now().isoformat(timespec="seconds"),
        "library_import_status": library_import.get("status") or "",
        "library_file_path": library_import.get("library_file_path") or "",
        "library_import_reason": library_import.get("reason") or "",
    }
    if library_import.get("status") == "imported":
        queue_item["library_pdf"] = {
            "status": "local_library_matched",
            "source": "local_pdf_library",
            "local_file_path": library_import.get("library_file_path") or "",
            "matched_dir": library_import.get("library_dir") or "",
            "match_source": "manual_upload_import",
            "matched_at": datetime.now().isoformat(timespec="seconds"),
        }
    write_scholar_status(session_id, session)
    return {
        "ok": True,
        "queue_id": queue_id,
        "local_file_path": str(target_path),
        "library_file_path": library_import.get("library_file_path") or "",
        "library_import_status": library_import.get("status") or "",
        "status": "manual_pdf_attached",
    }


def analyze_scholar_queue(
    session_id: str,
    *,
    queue_ids: list[str],
    top_k_spans: int = 8,
    analysis_scope: str = "fulltext_direct",
) -> dict[str, Any]:
    session = load_scholar_status(session_id)
    session_dir = resolve_scholar_session_dir(session_id)
    total = len(queue_ids)

    def progress_callback(progress: dict[str, Any]) -> None:
        stage = progress.get("stage") or ""
        stage_message = progress.get("stage_message") or ""
        current_title = progress.get("current_title") or ""
        base_message = f"正在分析高价值引用 {progress.get('processed_count', 0)}/{progress.get('total_count', total)}"
        if stage_message:
            base_message = f"{base_message}：{stage_message}"
        update_task_state(
            session_id,
            processed_count=progress.get("processed_count", 0),
            total_count=progress.get("total_count", total),
            message=base_message,
            stage=stage,
            stage_message=stage_message,
            current_queue_id=progress.get("queue_id") or "",
            current_title=current_title,
            current_index=progress.get("current_index", 0),
        )

    analyzed = scholar_pipeline().analyze_scholar_queue(
        session,
        session_dir,
        queue_ids=queue_ids,
        top_k_spans=top_k_spans,
        analysis_scope=analysis_scope,
        progress_callback=progress_callback,
    )
    with _task_lock(session_id):
        current = load_scholar_status(session_id)
        analyzed["task_state"] = ensure_task_state(current)
        write_scholar_status(session_id, analyzed)
    return analyzed


def start_analyze_queue_task(
    session_id: str,
    *,
    queue_ids: list[str],
    top_k_spans: int = 8,
    analysis_scope: str = "fulltext_direct",
) -> tuple[bool, dict[str, Any]]:
    started, task_state = mark_task_running(
        session_id,
        "analyze_queue",
        message="正在分析所选高价值引用论文…",
    )
    if not started:
        return False, task_state
    update_task_state(
        session_id,
        selected_queue_ids=queue_ids,
        top_k_spans=top_k_spans,
        total_count=len(queue_ids),
    )

    def worker():
        analyze_scholar_queue(
            session_id,
            queue_ids=queue_ids,
            top_k_spans=top_k_spans,
            analysis_scope=analysis_scope,
        )

    thread = threading.Thread(
        target=_run_background_task,
        args=(session_id, "analyze_queue", worker),
        kwargs={"success_message": "高价值引用分析完成"},
        daemon=True,
    )
    thread.start()
    return True, task_state


def start_download_missing_pdfs_task(session_id: str) -> tuple[bool, dict[str, Any]]:
    started, task_state = mark_task_running(
        session_id,
        "download_missing_pdfs",
        message="正在批量下载待补 PDF…",
    )
    if not started:
        return False, task_state
    session = load_scholar_status(session_id)
    update_task_state(
        session_id,
        total_count=len(session.get("deep_analysis_queue", []) or []),
    )

    def worker():
        download_missing_scholar_pdfs(session_id)

    thread = threading.Thread(
        target=_run_background_task,
        args=(session_id, "download_missing_pdfs", worker),
        kwargs={"success_message": "待补 PDF 批量下载完成"},
        daemon=True,
    )
    thread.start()
    return True, task_state


def _run_background_task(session_id: str, task_type: str, worker, *, success_message: str) -> None:
    try:
        worker()
    except Exception as exc:
        mark_task_finished(
            session_id,
            status="failed",
            message=f"{task_type} 执行失败",
            error=str(exc),
        )
        return
    mark_task_finished(session_id, status="succeeded", message=success_message, error="")


def start_expand_citations_task(
    session_id: str,
    *,
    limit_per_publication: int = 100,
) -> tuple[bool, dict[str, Any]]:
    started, task_state = mark_task_running(
        session_id,
        "expand_citations",
        limit_per_publication=limit_per_publication,
        message="正在展开学者论文的引用网络…",
    )
    if not started:
        return False, task_state

    def worker():
        expand_scholar_citations(
            session_id,
            limit_per_publication=limit_per_publication,
        )

    thread = threading.Thread(
        target=_run_background_task,
        args=(session_id, "expand_citations", worker),
        kwargs={"success_message": "引用网络展开完成"},
        daemon=True,
    )
    thread.start()
    return True, task_state


def get_scholar_task_status(session_id: str) -> dict[str, Any]:
    session = load_scholar_status(session_id)
    task_state = ensure_task_state(session)
    return {
        "ok": True,
        "session_id": session_id,
        "task_state": task_state,
        "publication_count": len(session.get("publications", []) or []),
        "citation_edge_count": len(session.get("citation_edges", []) or []),
        "deep_analysis_queue_count": len(session.get("deep_analysis_queue", []) or []),
        "statistics": session.get("statistics", {}),
        "updated_at": session.get("updated_at") or session.get("created_at"),
    }
