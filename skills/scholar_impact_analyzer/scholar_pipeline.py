from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AUTHOR_SOURCES_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "author_sources.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUTHOR_SOURCES = load_module("scholar_author_sources", AUTHOR_SOURCES_PATH)


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
    }


def assign_publication_ids(publications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, publication in enumerate(publications, 1):
        item = dict(publication)
        item["id"] = f"S{index:03d}"
        result.append(item)
    return result


def build_initial_statistics(publications: list[dict[str, Any]]) -> dict[str, Any]:
    top_publications = sorted(
        publications,
        key=lambda item: (
            -(item.get("citation_count") or 0),
            -(item.get("year") or 0),
            item.get("title") or "",
        ),
    )[:10]
    return {
        "publication_count": len(publications),
        "citation_edge_count": 0,
        "total_citation_count": sum(
            item.get("citation_count") or 0 for item in publications
        ),
        "publication_tiers": [],
        "citing_venue_tiers": [],
        "person_tag_statistics": [],
        "yearly_citations": [],
        "top_publications": top_publications,
        "strong_evidence_count": 0,
    }


def build_scholar_session(
    selected_author: dict[str, Any], session_dir: Path
) -> dict[str, Any]:
    display_name = selected_author.get("display_name") or ""
    publications = AUTHOR_SOURCES.fetch_dblp_publications(
        selected_author.get("dblp_id") or "",
        selected_author_name=display_name,
    )
    publications = assign_publication_ids(publications)
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": "1.0",
        "session_type": "scholar_impact",
        "session_id": session_dir.name,
        "query": display_name,
        "selected_author": selected_author,
        "publications": publications,
        "citation_edges": [],
        "statistics": build_initial_statistics(publications),
        "deep_analysis_queue": [],
        "task_state": default_task_state(),
        "created_at": now,
        "updated_at": now,
    }


def save_scholar_session(session_dir: Path, session: dict[str, Any]) -> None:
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
