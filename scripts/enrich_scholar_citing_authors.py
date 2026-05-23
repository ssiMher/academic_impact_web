#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHOLAR_SESSIONS_ROOT = PROJECT_ROOT / "data" / "scholar_sessions"
SCHOLAR_PIPELINE_PATH = (
    PROJECT_ROOT / "skills" / "scholar_impact_analyzer" / "scholar_pipeline.py"
)
LIST_PAPERS_PATH = PROJECT_ROOT / "skills" / "list_all_citations" / "list_papers.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHOLAR_PIPELINE = load_module(SCHOLAR_PIPELINE_PATH, "enrich_scholar_pipeline")
LIST_PAPERS = load_module(LIST_PAPERS_PATH, "enrich_list_papers")


def session_path(session_id_or_path: str) -> Path:
    value = Path(session_id_or_path)
    if value.exists():
        if value.is_dir():
            return value / "session.json"
        return value
    return SCHOLAR_SESSIONS_ROOT / session_id_or_path / "session.json"


def load_session(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Session file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def edge_citing_paper(edge: dict[str, Any]) -> dict[str, Any]:
    external_ids = {}
    if edge.get("citing_doi"):
        external_ids["DOI"] = edge.get("citing_doi")
    if edge.get("citing_scopus_id"):
        external_ids["Scopus"] = edge.get("citing_scopus_id")
    if edge.get("citing_openalex_id"):
        external_ids["OpenAlex"] = edge.get("citing_openalex_id")
    return {
        "title": edge.get("citing_title") or "",
        "year": edge.get("citing_year"),
        "venue": edge.get("citing_venue") or "Unknown Venue",
        "externalIds": external_ids,
        "authors": [{"name": name} for name in edge.get("citing_authors") or []],
        "source_url": edge.get("source_url") or "",
        "citedby_count": edge.get("citing_citation_count") or 0,
    }


def enrich_edge(edge: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    paper = edge_citing_paper(edge)
    enriched = LIST_PAPERS.enrich_scopus_citing_paper_authors(paper)
    if enriched is paper or not enriched.get("author_enrichment_source"):
        return edge, False
    names = [
        author.get("name")
        for author in enriched.get("authors") or []
        if isinstance(author, dict) and author.get("name")
    ]
    if not names:
        return edge, False
    updated = dict(edge)
    updated["citing_authors"] = names
    updated["citing_author_details"] = enriched.get("author_details") or []
    updated["citing_author_enrichment_source"] = enriched.get("author_enrichment_source")
    return updated, True


def enrich_session(session: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    updated_edges = []
    changed_count = 0
    for edge in session.get("citation_edges", []) or []:
        updated, changed = enrich_edge(edge)
        updated_edges.append(updated)
        changed_count += 1 if changed else 0
    session = dict(session)
    session["citation_edges"] = updated_edges
    if changed_count:
        session = SCHOLAR_PIPELINE.rebuild_scholar_derived_outputs(session)
    return session, {
        "citation_edge_count": len(updated_edges),
        "enriched_edge_count": changed_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill full citing-paper author names for a scholar session."
    )
    parser.add_argument("session", help="Scholar session id, directory, or session.json path.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = session_path(args.session)
    session = load_session(path)
    updated, report = enrich_session(session)
    report["session_file"] = str(path)
    report["dry_run"] = args.dry_run
    if not args.dry_run and report["enriched_edge_count"]:
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
