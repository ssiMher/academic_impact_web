from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"
SESSIONS_ROOT = PROJECT_ROOT / "data" / "sessions"
_SESSION_TASK_LOCKS: dict[str, threading.Lock] = {}
_ANALYSIS_MODEL_OPTIONS = [
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


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def impact_cli():
    return _load_module(
        SKILLS_ROOT / "academic_impact_analyzer" / "impact_cli.py",
        "academic_impact_web_impact_cli",
    )


@lru_cache(maxsize=1)
def run_pipeline():
    return _load_module(
        SKILLS_ROOT / "academic_impact_analyzer" / "run_pipeline.py",
        "academic_impact_web_run_pipeline",
    )


def analysis_model_options() -> list[dict[str, str]]:
    try:
        return impact_cli().analysis_model_options()
    except AttributeError:
        return [dict(item) for item in _ANALYSIS_MODEL_OPTIONS]


def normalize_analysis_model_profile(value: str = "") -> str:
    try:
        return impact_cli().normalize_analysis_model_profile(value)
    except AttributeError:
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
        if profile not in {item["value"] for item in _ANALYSIS_MODEL_OPTIONS}:
            return "default"
        return profile


def selected_analysis_model_profile(session: dict[str, Any]) -> str:
    try:
        return impact_cli().session_analysis_model_profile(session)
    except AttributeError:
        analysis_model = session.get("analysis_model")
        if isinstance(analysis_model, dict):
            return normalize_analysis_model_profile(analysis_model.get("profile") or "")
        return "default"


def resolve_session_dir(session_id: str) -> Path:
    session_dir = SESSIONS_ROOT / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"未找到会话目录: {session_id}")
    return session_dir


def _task_lock(session_id: str) -> threading.Lock:
    lock = _SESSION_TASK_LOCKS.get(session_id)
    if lock is None:
        lock = threading.Lock()
        _SESSION_TASK_LOCKS[session_id] = lock
    return lock


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
        "requested_ids": [],
        "top_k_spans": None,
        "analysis_scope": "fulltext_direct",
        "analysis_model_profile": "default",
    }


def ensure_task_state(session: dict[str, Any]) -> dict[str, Any]:
    task_state = session.get("task_state")
    if not isinstance(task_state, dict):
        task_state = default_task_state()
        session["task_state"] = task_state
    merged = default_task_state()
    merged.update(task_state)
    session["task_state"] = merged
    return merged


def _session_json_path(session_id: str) -> Path:
    return resolve_session_dir(session_id) / "session.json"


def load_session_summary_record(session_dir: Path) -> dict[str, Any]:
    session_path = session_dir / "session.json"
    if not session_path.exists():
        raise FileNotFoundError(f"未找到 session.json: {session_path}")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    papers = session.get("papers")
    if not isinstance(papers, list):
        papers = []
    analysis = session.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    return {
        "id": session_dir.name,
        "query": session.get("query", ""),
        "updated_at": session.get("updated_at") or session.get("created_at"),
        "paper_count": session.get("paper_count", len(papers)),
        "analysis": analysis,
    }


def load_session_record(session_id: str) -> dict[str, Any]:
    session_dir = resolve_session_dir(session_id)
    session_path = session_dir / "session.json"
    if not session_path.exists():
        raise FileNotFoundError(f"未找到 session.json: {session_path}")
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
    session.setdefault("query", "")
    session.setdefault("papers", [])
    session.setdefault("target", {})
    session.setdefault("warnings", [])
    session.setdefault("analysis", {})
    session.setdefault("exports", {})
    ensure_task_state(session)
    return session


def write_session_record(session_id: str, session: dict[str, Any]):
    session_dir = resolve_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    ensure_task_state(session)
    session_path = session_dir / "session.json"
    session_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def update_task_state(session_id: str, **updates):
    with _task_lock(session_id):
        session = load_session_record(session_id)
        task_state = ensure_task_state(session)
        task_state.update(updates)
        task_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        session["task_state"] = task_state
        write_session_record(session_id, session)
        return dict(task_state)


def mark_task_running(
    session_id: str,
    task_type: str,
    *,
    requested_ids: list[str] | None = None,
    top_k_spans: int | None = None,
    analysis_scope: str | None = None,
    analysis_model_profile: str | None = None,
    message: str = "",
):
    with _task_lock(session_id):
        session = load_session_record(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            return False, dict(task_state)
        now = datetime.now().isoformat(timespec="seconds")
        resolved_model_profile = normalize_analysis_model_profile(
            analysis_model_profile or selected_analysis_model_profile(session)
        )
        if task_type == "analyze":
            try:
                impact_cli().set_session_analysis_model_profile(session, resolved_model_profile)
            except AttributeError:
                session["analysis_model"] = {"profile": resolved_model_profile}
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
                "requested_ids": list(requested_ids or []),
                "top_k_spans": top_k_spans,
                "analysis_scope": analysis_scope or "candidate_spans",
                "analysis_model_profile": resolved_model_profile,
            }
        )
        session["task_state"] = task_state
        write_session_record(session_id, session)
        return True, dict(task_state)


def mark_task_finished(session_id: str, *, status: str, message: str = "", error: str = ""):
    updates = {
        "active": False,
        "status": status,
        "message": message,
        "error": error,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    return update_task_state(session_id, **updates)


def _build_progress_payload(session: dict[str, Any]) -> dict[str, Any]:
    counts = {
        "local_available": 0,
        "auto_downloadable": 0,
        "manual_required": 0,
        "not_probed": 0,
        "analysis_ready": 0,
    }
    analyzed_count = 0
    for item in session.get("papers", []):
        probe_status = item.get("download_probe", {}).get("status") or "not_probed"
        counts[probe_status] = counts.get(probe_status, 0) + 1
        if probe_status == "local_available":
            counts["analysis_ready"] += 1
        if item.get("analysis_result", {}).get("status"):
            analyzed_count += 1

    overview_stats = session.get("overview_stats") if isinstance(session.get("overview_stats"), dict) else {}
    overview_stats = dict(overview_stats)
    overview_stats.setdefault("downloaded_count", counts["analysis_ready"])
    overview_stats.setdefault("analyzed_count", analyzed_count)
    return {
        "download_status_counts": counts,
        "overview_stats": overview_stats,
        "analysis": session.get("analysis", {}),
    }


def get_task_status(session_id: str):
    session = load_session_record(session_id)
    task_state = ensure_task_state(session)
    progress_payload = _build_progress_payload(session)
    return {
        "ok": True,
        "session_id": session_id,
        "task_state": task_state,
        "paper_count": len(session.get("papers", [])),
        "download_status_counts": progress_payload["download_status_counts"],
        "overview_stats": progress_payload["overview_stats"],
        "analysis": progress_payload["analysis"],
        "updated_at": session.get("updated_at") or session.get("created_at"),
    }


def _run_background_task(session_id: str, task_type: str, worker, *, success_message: str):
    try:
        outcome = worker()
    except Exception as exc:
        mark_task_finished(
            session_id,
            status="failed",
            message=f"{task_type} 执行失败",
            error=str(exc),
        )
        return

    if isinstance(outcome, dict) and outcome.get("status") == "failed":
        mark_task_finished(
            session_id,
            status="failed",
            message=outcome.get("message", f"{task_type} 执行失败"),
            error=outcome.get("error", ""),
        )
        return

    if isinstance(outcome, dict) and outcome.get("status") == "succeeded":
        mark_task_finished(
            session_id,
            status="succeeded",
            message=outcome.get("message", success_message),
            error="",
        )
        return

    mark_task_finished(
        session_id,
        status="succeeded",
        message=success_message,
        error="",
    )


def _start_background_task(
    session_id: str,
    task_type: str,
    worker,
    *,
    requested_ids: list[str] | None = None,
    top_k_spans: int | None = None,
    analysis_scope: str | None = None,
    analysis_model_profile: str | None = None,
    message: str = "",
    success_message: str = "",
):
    started, task_state = mark_task_running(
        session_id,
        task_type,
        requested_ids=requested_ids,
        top_k_spans=top_k_spans,
        analysis_scope=analysis_scope,
        analysis_model_profile=analysis_model_profile,
        message=message,
    )
    if not started:
        return False, task_state

    thread = threading.Thread(
        target=_run_background_task,
        args=(session_id, task_type, worker),
        kwargs={"success_message": success_message},
        daemon=True,
    )
    thread.start()
    return True, task_state


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    if not SESSIONS_ROOT.exists():
        return []

    sessions: list[dict[str, Any]] = []
    for session_dir in sorted(SESSIONS_ROOT.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        session_path = session_dir / "session.json"
        if not session_path.exists():
            continue
        try:
            session = load_session_summary_record(session_dir)
        except Exception:
            continue
        sessions.append(session)
        if len(sessions) >= limit:
            break
    return sessions


def create_session(
    query: str,
    *,
    limit: int = 20,
    probe_downloads: bool = False,
    auto_refresh_top: int = 0,
    sort_preference: str = "context",
):
    slug = run_pipeline().slugify(query, limit=50)
    session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}"
    session_dir = SESSIONS_ROOT / session_id
    session = impact_cli().build_discover_session(
        query=query,
        session_dir=session_dir,
        limit=limit,
        probe_downloads=probe_downloads,
        auto_refresh_count=auto_refresh_top,
        sort_preference=sort_preference,
    )
    return session_id, session


def create_pending_session(
    query: str,
    *,
    limit: int = 20,
    probe_downloads: bool = False,
    auto_refresh_top: int = 0,
    sort_preference: str = "context",
):
    slug = run_pipeline().slugify(query, limit=50)
    session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}"
    session_dir = SESSIONS_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    session = {
        "ok": True,
        "query": query,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": {},
        "papers": [],
        "warnings": [],
        "analysis": {},
        "exports": {},
        "list_preferences": {
            "sort_preference": sort_preference,
            "requested_limit": limit,
        },
        "pending_discover": {
            "limit": limit,
            "probe_downloads": probe_downloads,
            "auto_refresh_top": auto_refresh_top,
            "sort_preference": sort_preference,
        },
        "task_state": default_task_state(),
    }
    write_session_record(session_id, session)
    return session_id


def start_discover_task(
    query: str,
    *,
    limit: int = 20,
    probe_downloads: bool = False,
    auto_refresh_top: int = 0,
    sort_preference: str = "context",
):
    session_id = create_pending_session(
        query,
        limit=limit,
        probe_downloads=probe_downloads,
        auto_refresh_top=auto_refresh_top,
        sort_preference=sort_preference,
    )
    session_dir = resolve_session_dir(session_id)

    def worker():
        result = impact_cli().build_discover_session(
            query=query,
            session_dir=session_dir,
            limit=limit,
            probe_downloads=probe_downloads,
            auto_refresh_count=auto_refresh_top,
            sort_preference=sort_preference,
        )
        if not result.get("ok", True):
            raise RuntimeError(result.get("error", "discover 失败"))

    _start_background_task(
        session_id,
        "discover",
        worker,
        requested_ids=[],
        message="正在发现引用论文…",
        success_message="Discover 完成",
    )
    return session_id


def load_session(session_id: str):
    session_dir = resolve_session_dir(session_id)
    last_error = None
    for _ in range(5):
        try:
            return impact_cli().load_session(session_dir)
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.02)
    if last_error is not None:
        raise last_error
    return impact_cli().load_session(session_dir)


def refresh_phase1_exports(session_id: str, session: dict[str, Any] | None = None):
    session_dir = resolve_session_dir(session_id)
    current_session = session if session is not None else load_session(session_id)
    return impact_cli().build_phase1_export_payload(session_dir, current_session)


def load_status(session_id: str, filters: dict[str, Any] | None = None):
    session = load_session(session_id)
    task_state = ensure_task_state(session)
    status_payload = impact_cli().build_status_payload(session)
    if task_state.get("active"):
        detail_payload = impact_cli().build_session_detail_payload(session, filters or {})
        detail_payload["exports"] = impact_cli().merge_exports(session.get("exports", {}))
    else:
        detail_payload = refresh_phase1_exports(session_id, session=session)
    if filters:
        detail_payload = impact_cli().build_session_detail_payload(session, filters)
        detail_payload["exports"] = impact_cli().merge_exports(session.get("exports", {}))
    status_payload["task_state"] = dict(task_state)
    detail_payload["task_state"] = dict(task_state)
    status_payload["exports"] = detail_payload.get("exports", {})
    report_md = ""
    report_path = detail_payload.get("exports", {}).get("report_md_path")
    if report_path:
        path = Path(report_path)
        if path.exists():
            report_md = path.read_text(encoding="utf-8")
    return session, status_payload, detail_payload, report_md


def refresh_probes(session_id: str, ids: list[str] | None = None, *, force: bool = False):
    return impact_cli().refresh_probes(resolve_session_dir(session_id), ids or [], force)


def download_papers(session_id: str, ids: list[str] | None = None, *, auto_only: bool = False):
    return impact_cli().run_downloads(resolve_session_dir(session_id), ids or [], auto_only)


def analyze_papers(
    session_id: str,
    ids: list[str] | None = None,
    *,
    top_k_spans: int = 8,
    analysis_scope: str = "fulltext_direct",
    analysis_model_profile: str = "",
):
    return impact_cli().run_analysis(
        resolve_session_dir(session_id),
        ids or [],
        top_k_spans,
        analysis_scope,
        analysis_model_profile=analysis_model_profile,
    )


def update_analysis_templates(
    session_id: str,
    *,
    active_template_ids: list[str],
    custom_requests_text: str,
):
    with _task_lock(session_id):
        session = load_session(session_id)
        task_state = ensure_task_state(session)
        if task_state.get("active"):
            raise ValueError("当前后台任务仍在运行，暂时不能更新分析模板。")
        return impact_cli().update_analysis_templates(
            resolve_session_dir(session_id),
            active_template_ids,
            custom_requests_text,
        )


def start_refresh_task(session_id: str, ids: list[str] | None = None, *, force: bool = False):
    ids = ids or []
    def worker():
        impact_cli().refresh_probes(resolve_session_dir(session_id), ids, force)

    return _start_background_task(
        session_id,
        "refresh",
        worker,
        requested_ids=ids,
        message="正在刷新下载探测状态…",
        success_message="Refresh 完成",
    )


def start_download_task(session_id: str, ids: list[str] | None = None, *, auto_only: bool = False):
    ids = ids or []
    def worker():
        impact_cli().run_downloads(resolve_session_dir(session_id), ids, auto_only)

    return _start_background_task(
        session_id,
        "download",
        worker,
        requested_ids=ids,
        message="正在下载所选论文…",
        success_message="Download 完成",
    )


def start_analyze_task(
    session_id: str,
    ids: list[str] | None = None,
    *,
    top_k_spans: int = 8,
    analysis_scope: str = "fulltext_direct",
    analysis_model_profile: str = "",
):
    ids = ids or []
    session = load_session_record(session_id)
    resolved_model_profile = normalize_analysis_model_profile(
        analysis_model_profile or selected_analysis_model_profile(session)
    )
    def worker():
        impact_cli().run_analysis(
            resolve_session_dir(session_id),
            ids,
            top_k_spans,
            analysis_scope,
            analysis_model_profile=resolved_model_profile,
        )
        session = load_session(session_id)
        papers = {item.get("id"): item for item in session.get("papers", [])}
        for paper_id in ids:
            item = papers.get(paper_id) or {}
            status = (item.get("analysis_result") or {}).get("status")
            if status not in {"analysis_failed", "fulltext_extract_failed", "write_output_failed"}:
                continue
            analysis_path = ((item.get("analysis_result") or {}).get("paths") or {}).get("analysis", "")
            analysis_data = {}
            if analysis_path:
                path = Path(analysis_path)
                if path.exists():
                    try:
                        analysis_data = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        analysis_data = {}
            error_type = analysis_data.get("error_type") or ("extract_text_failed" if status == "fulltext_extract_failed" else status)
            message_map = {
                "extract_text_failed": "全文提取失败",
                "pdf_parse_failed": "PDF 解析失败",
                "empty_text_pdf": "PDF 文本几乎为空",
                "likely_scanned_pdf": "疑似扫描版 PDF",
                "candidate_span_failed": "候选段落定位失败",
                "single_model_request_failed": "分析模型请求失败",
                "single_model_json_parse_failed": "分析模型 JSON 解析失败",
                "single_model_schema_invalid": "分析模型 JSON 结构不合法",
                "fulltext_direct_empty_text": "全文直读缺少文本",
                "local_model_request_failed": "本地模型请求失败",
                "blank_model_output": "分析模型返回空输出",
                "deepseek_request_failed": "DeepSeek 请求失败",
                "deepseek_json_parse_failed": "DeepSeek JSON 解析失败",
                "write_output_failed": "结果写出失败",
            }
            return {
                "status": "failed",
                "message": message_map.get(error_type, "全文分析失败"),
                "error": analysis_data.get("error") or ((item.get("analysis_result") or {}).get("status") or ""),
            }

    return _start_background_task(
        session_id,
        "analyze",
        worker,
        requested_ids=ids,
        top_k_spans=top_k_spans,
        analysis_scope=analysis_scope,
        analysis_model_profile=resolved_model_profile,
        message="正在进行全文分析…",
        success_message="Analyze 完成",
    )


def attach_uploaded_pdf(session_id: str, paper_id: str, filename: str, content: bytes):
    session_dir = resolve_session_dir(session_id)
    uploads_dir = session_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(filename or "upload.pdf").suffix or ".pdf"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=uploads_dir, suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            temp_path = Path(tmp.name)
        return impact_cli().attach_local_pdf(session_dir, paper_id, str(temp_path))
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def review_person_candidate(session_id: str, candidate_id: str, *, action: str, note: str = ""):
    return impact_cli().review_person_candidate(
        resolve_session_dir(session_id),
        candidate_id,
        action,
        note,
    )


def resolve_export_path(session_id: str, export_name: str) -> Path:
    detail_payload = refresh_phase1_exports(session_id)
    exports = detail_payload.get("exports", {})
    mapping = {
        "report.md": exports.get("report_md_path", ""),
        "structured.json": exports.get("structured_json_path", ""),
        "highlight_cards.csv": exports.get("highlight_cards_csv_path", ""),
        "highlight_cards.md": exports.get("highlight_cards_md_path", ""),
    }
    raw_path = mapping.get(export_name, "")
    if not raw_path:
        raise FileNotFoundError(f"未找到导出文件: {export_name}")
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"未找到导出文件: {export_name}")
    return path
