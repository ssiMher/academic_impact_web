#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHOLAR_STATS_PATH = (
    PROJECT_ROOT / "skills" / "scholar_impact_analyzer" / "scholar_stats.py"
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHOLAR_STATS = load_module(SCHOLAR_STATS_PATH, "debug_scholar_stats")


def session_path(session_id_or_path: str) -> Path:
    value = Path(session_id_or_path)
    if value.exists():
        if value.is_dir():
            return value / "session.json"
        return value
    return PROJECT_ROOT / "data" / "scholar_sessions" / session_id_or_path / "session.json"


def load_session(session_id_or_path: str) -> dict[str, Any]:
    path = session_path(session_id_or_path)
    if not path.exists():
        raise FileNotFoundError(f"Session file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalized(value: str) -> str:
    return SCHOLAR_STATS.normalize_title(value or "")


def find_queue_item(
    session: dict[str, Any],
    *,
    queue_index: int | None,
    queue_id: str,
    title: str,
    doi: str,
) -> dict[str, Any]:
    queue = session.get("deep_analysis_queue") or []
    if queue_index is not None:
        if queue_index < 1 or queue_index > len(queue):
            raise IndexError(f"Queue index out of range: {queue_index}")
        return queue[queue_index - 1]
    if queue_id:
        for item in queue:
            if item.get("queue_id") == queue_id:
                return item
        raise ValueError(f"Queue item not found by queue_id: {queue_id}")
    if doi:
        target = SCHOLAR_STATS.normalize_doi(doi)
        for item in queue:
            if SCHOLAR_STATS.normalize_doi(item.get("citing_doi") or "") == target:
                return item
        raise ValueError(f"Queue item not found by DOI: {doi}")
    if title:
        target = normalized(title)
        for item in queue:
            if target and target in normalized(item.get("citing_title") or ""):
                return item
        raise ValueError(f"Queue item not found by title: {title}")
    if not queue:
        raise ValueError("Session has an empty deep_analysis_queue")
    return queue[0]


def selected_author_names(session: dict[str, Any]) -> list[str]:
    selected = session.get("selected_author") or {}
    names = [
        selected.get("display_name") or "",
        session.get("query") or "",
    ]
    return [name for name in names if name]


def matching_edges(session: dict[str, Any], queue_item: dict[str, Any]) -> list[dict[str, Any]]:
    key = SCHOLAR_STATS.citation_group_key(queue_item)
    return [
        edge
        for edge in session.get("citation_edges", []) or []
        if SCHOLAR_STATS.citation_group_key(edge) == key
    ]


def recompute_group_status(
    edges: list[dict[str, Any]],
    selected_names: list[str],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    status = "unknown"
    overlaps: list[str] = []
    edge_rows = []
    for edge in edges:
        result = SCHOLAR_STATS.classify_edge_self_citation(
            edge,
            selected_author_names=selected_names,
        )
        edge_status = result.get("status") or "unknown"
        status = SCHOLAR_STATS.merge_self_citation_status(status, edge_status)
        for author in result.get("overlap_authors") or []:
            if author not in overlaps:
                overlaps.append(author)
        edge_rows.append(
            {
                "source_publication_id": edge.get("source_publication_id"),
                "cited_publication_title": edge.get("cited_publication_title"),
                "stored_source_publication_authors": edge.get("source_publication_authors"),
                "stored_citing_authors": edge.get("citing_authors"),
                "recomputed_status": edge_status,
                "recomputed_overlap_authors": result.get("overlap_authors") or [],
            }
        )
    return status, overlaps, edge_rows


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    session = load_session(args.session)
    item = find_queue_item(
        session,
        queue_index=args.queue_index,
        queue_id=args.queue_id,
        title=args.title,
        doi=args.doi,
    )
    names = selected_author_names(session)
    edges = matching_edges(session, item)
    recomputed_status, recomputed_overlaps, edge_rows = recompute_group_status(
        edges,
        names,
    )
    stored_status = item.get("self_citation_status") or "unknown"
    return {
        "session_file": str(session_path(args.session)),
        "selected_author_names": names,
        "queue_item": {
            "queue_id": item.get("queue_id"),
            "citing_title": item.get("citing_title"),
            "citing_doi": item.get("citing_doi"),
            "stored_self_citation_status": stored_status,
            "stored_self_citation_overlap_authors": item.get(
                "self_citation_overlap_authors"
            )
            or [],
            "stored_reasons": item.get("reasons") or [],
            "source_publication_ids": item.get("source_publication_ids") or [],
        },
        "matching_edge_count": len(edges),
        "recomputed_group_status": recomputed_status,
        "recomputed_group_overlap_authors": recomputed_overlaps,
        "stored_matches_recomputed": stored_status == recomputed_status,
        "edges": edge_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Debug scholar self-citation labels for one high-value queue item."
    )
    parser.add_argument(
        "session",
        help="Scholar session id, session directory, or session.json path.",
    )
    parser.add_argument("--queue-index", type=int, default=None)
    parser.add_argument("--queue-id", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--doi", default="")
    args = parser.parse_args()
    print(json.dumps(build_report(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
