from __future__ import annotations

import csv
import importlib.util
import io
import json
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


def create_scholar_session(author: dict[str, Any]) -> str:
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
    _decorate_publication_venue_tiers(session)
    return session


def build_deep_analysis_queue_view(
    session: dict[str, Any],
    *,
    active_reason: str = "",
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

    def decorate_queue_item(item: dict[str, Any]) -> dict[str, Any]:
        result = result_by_queue_id.get(item.get("queue_id"))
        decorated = dict(item)
        manual_pdf = item.get("manual_pdf") or {}
        decorated["citing_identifier"] = citing_identifier(item)
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
        else:
            decorated["analysis_status"] = "not_analyzed"
            decorated["download_source"] = "点击分析时自动尝试下载 PDF"
            decorated["analysis_failure_message"] = ""
            decorated["analysis_error_type"] = ""
        decorated["manual_pdf_status"] = manual_pdf.get("status") or ""
        decorated["manual_pdf_path"] = manual_pdf.get("local_file_path") or ""
        if decorated["manual_pdf_status"]:
            decorated["download_source"] = decorated["manual_pdf_status"]
            if decorated["analysis_status"] == "not_analyzed":
                decorated["analysis_status"] = decorated["manual_pdf_status"]
        if decorated["manual_pdf_status"]:
            decorated["readiness_status"] = "manual_pdf_ready"
            decorated["readiness_label"] = "已上传 PDF，可重试"
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
        },
    }


def build_strong_evidence_view(
    session: dict[str, Any],
    *,
    active_aspect: str = "",
    active_stance: str = "",
    active_flag: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    evidence_items = _deduplicate_strong_evidence(session.get("strong_evidence", []) or [])
    aspect_counts: dict[str, int] = {}
    stance_counts: dict[str, int] = {}
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
        aspect_counts[aspect] = aspect_counts.get(aspect, 0) + 1
        stance_counts[stance] = stance_counts.get(stance, 0) + 1
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
        return f"?{urlencode(query)}#strong-evidence"

    return {
        "items": filtered[start:end],
        "total_count": total_count,
        "unfiltered_count": len(evidence_items),
        "active_aspect": active_aspect,
        "active_stance": active_stance,
        "active_flag": active_flag,
        "aspect_counts": aspect_counts,
        "stance_counts": stance_counts,
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
            1 if evidence.get("fellow_strong_citation") else 0,
            1 if evidence.get("positive_evaluation") or (evidence.get("stance") or "").lower() == "positive" else 0,
            1 if evidence.get("long_context_100_chars") or (evidence.get("citation_char_count") or 0) >= 100 else 0,
            evidence.get("citation_char_count") or len(evidence.get("citation_text") or ""),
        )

    top_evidence = sorted(
        strong_evidence,
        key=evidence_score,
        reverse=True,
    )[:3]

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
                    f"   - Fellow 强引用：{'是' if evidence.get('fellow_strong_citation') else '否'}",
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
    queue_item["manual_pdf"] = {
        "status": "manual_pdf_attached",
        "source": "manual_upload",
        "file_name": filename,
        "local_file_path": str(target_path),
        "size_bytes": inspection.get("size_bytes"),
        "attached_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_scholar_status(session_id, session)
    return {
        "ok": True,
        "queue_id": queue_id,
        "local_file_path": str(target_path),
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
