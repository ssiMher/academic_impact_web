from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4


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


def resolve_scholar_session_dir(session_id: str) -> Path:
    session_dir = SCHOLAR_SESSIONS_ROOT / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"未找到学者会话目录: {session_id}")
    return session_dir


def load_scholar_status(session_id: str) -> dict[str, Any]:
    session_path = resolve_scholar_session_dir(session_id) / "session.json"
    return json.loads(session_path.read_text(encoding="utf-8"))
