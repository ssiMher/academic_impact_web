from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"
SCHOLAR_SESSIONS_ROOT = PROJECT_ROOT / "data" / "scholar_sessions"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scholar_pipeline():
    return _load_module(
        SKILLS_ROOT / "scholar_impact_analyzer" / "scholar_pipeline.py",
        "academic_impact_web_scholar_pipeline",
    )


def resolve_scholar_session_dir(session_id: str) -> Path:
    session_dir = SCHOLAR_SESSIONS_ROOT / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"未找到学者会话目录: {session_id}")
    return session_dir


def load_scholar_status(session_id: str) -> dict[str, Any]:
    session_path = resolve_scholar_session_dir(session_id) / "session.json"
    return json.loads(session_path.read_text(encoding="utf-8"))
