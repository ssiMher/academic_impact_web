from __future__ import annotations

import importlib.util
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


def build_scholar_analysis_summary(session: dict[str, Any]) -> dict[str, Any]:
    results = session.get("scholar_fulltext_results", []) or []
    strong_evidence = session.get("strong_evidence", []) or []
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
            strong_evidence_count=len(session.get("strong_evidence", []) or []),
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
        update_task_state(
            session_id,
            processed_count=progress.get("processed_count", 0),
            total_count=progress.get("total_count", total),
            message=f"正在分析高价值引用 {progress.get('processed_count', 0)}/{progress.get('total_count', total)}",
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
