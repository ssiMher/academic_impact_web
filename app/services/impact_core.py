from __future__ import annotations

import importlib.util
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"
SESSIONS_ROOT = PROJECT_ROOT / "data" / "sessions"


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


def resolve_session_dir(session_id: str) -> Path:
    session_dir = SESSIONS_ROOT / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"未找到会话目录: {session_id}")
    return session_dir


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
            session = impact_cli().load_session(session_dir)
        except Exception:
            continue
        sessions.append(
            {
                "id": session_dir.name,
                "query": session.get("query", ""),
                "updated_at": session.get("updated_at") or session.get("created_at"),
                "paper_count": session.get("paper_count", 0),
                "analysis": session.get("analysis", {}),
            }
        )
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


def load_session(session_id: str):
    return impact_cli().load_session(resolve_session_dir(session_id))


def load_status(session_id: str, filters: dict[str, Any] | None = None):
    session_dir = resolve_session_dir(session_id)
    session = load_session(session_id)
    status_payload = impact_cli().build_status_payload(session)
    detail_payload = impact_cli().build_phase1_export_payload(session_dir, session)
    if filters:
        detail_payload = impact_cli().build_session_detail_payload(session, filters)
        detail_payload["exports"] = dict(session.get("exports", {}))
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


def analyze_papers(session_id: str, ids: list[str] | None = None, *, top_k_spans: int = 8):
    return impact_cli().run_analysis(resolve_session_dir(session_id), ids or [], top_k_spans)


def review_person_candidate(session_id: str, candidate_id: str, *, action: str, note: str = ""):
    return impact_cli().review_person_candidate(
        resolve_session_dir(session_id),
        candidate_id,
        action,
        note,
    )


def resolve_export_path(session_id: str, export_name: str) -> Path:
    session = load_session(session_id)
    exports = session.get("exports", {})
    mapping = {
        "report.md": exports.get("report_md_path", ""),
        "structured.json": exports.get("structured_json_path", ""),
    }
    raw_path = mapping.get(export_name, "")
    if not raw_path:
        raise FileNotFoundError(f"未找到导出文件: {export_name}")
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"未找到导出文件: {export_name}")
    return path
