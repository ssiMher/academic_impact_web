from __future__ import annotations

import importlib.util
import json
import re
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

    return {
        "items": filtered[start:end],
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
