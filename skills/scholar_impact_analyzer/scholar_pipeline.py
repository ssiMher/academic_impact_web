from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AUTHOR_SOURCES_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "author_sources.py"
LIST_PAPERS_PATH = ROOT / "skills" / "list_all_citations" / "list_papers.py"
SCHOLAR_STATS_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_stats.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUTHOR_SOURCES = load_module("scholar_author_sources", AUTHOR_SOURCES_PATH)
LIST_PAPERS = load_module("scholar_list_papers", LIST_PAPERS_PATH)
SCHOLAR_STATS = load_module("scholar_stats", SCHOLAR_STATS_PATH)


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
    return SCHOLAR_STATS.build_scholar_statistics(publications, [], [])


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


def publication_query(publication: dict[str, Any]) -> str:
    unique_ids = publication.get("unique_ids") or {}
    return (
        publication.get("doi")
        or unique_ids.get("DOI")
        or publication.get("title")
        or ""
    )


def edge_key(edge: dict[str, Any]) -> tuple[str, str]:
    return (
        edge.get("source_publication_id") or "",
        edge.get("citing_paper_id")
        or edge.get("citing_doi")
        or edge.get("citing_title")
        or "",
    )


def citing_paper_id(citing_paper: dict[str, Any]) -> str:
    external_ids = citing_paper.get("externalIds") or {}
    return (
        citing_paper.get("paperId")
        or external_ids.get("Scopus")
        or external_ids.get("OpenAlex")
        or external_ids.get("DOI")
        or citing_paper.get("source_url")
        or citing_paper.get("title")
        or ""
    )


def normalize_citation_authors(authors: list[Any]) -> list[str]:
    normalized = []
    for author in authors:
        name = author.get("name") if isinstance(author, dict) else author
        if name:
            normalized.append(name)
    return normalized


def normalize_citation_edge(
    source_publication: dict[str, Any],
    citing_paper: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    external_ids = citing_paper.get("externalIds") or {}
    unique_ids = source_publication.get("unique_ids") or {}
    return {
        "source_publication_id": source_publication.get("id"),
        "source_publication_doi": source_publication.get("doi")
        or unique_ids.get("DOI")
        or "",
        "cited_publication_title": source_publication.get("title") or "",
        "citing_paper_id": citing_paper_id(citing_paper),
        "citing_title": citing_paper.get("title") or "",
        "citing_doi": external_ids.get("DOI") or "",
        "citing_year": citing_paper.get("year"),
        "citing_venue": citing_paper.get("venue") or "Unknown Venue",
        "citing_authors": normalize_citation_authors(citing_paper.get("authors") or []),
        "provider": provider,
        "source_url": citing_paper.get("source_url") or "",
    }


def normalize_strong_evidence(
    edge: dict[str, Any],
    finding: dict[str, Any],
    person_tag_labels: list[str],
) -> dict[str, Any]:
    citation_text = finding.get("citation_text") or ""
    positive = (finding.get("stance") or "").lower() == "positive"
    fellow = any(
        "Fellow" in label
        or "院士" in label
        or "Turing" in label
        or "Prize" in label
        for label in person_tag_labels
    )
    return {
        "source_publication_id": edge.get("source_publication_id"),
        "citing_title": edge.get("citing_title"),
        "citing_authors": edge.get("citing_authors", []),
        "person_tag_labels": person_tag_labels,
        "citation_text": citation_text,
        "citation_char_count": len(citation_text),
        "long_context_100_chars": len(citation_text) >= 100,
        "positive_evaluation": positive,
        "fellow_strong_citation": fellow and len(citation_text) >= 100 and positive,
        "aspect": finding.get("aspect") or "",
        "function": finding.get("function") or "",
        "reason": finding.get("reason") or "",
        "confidence": finding.get("confidence"),
    }


def expand_publication_citations(
    session: dict[str, Any],
    limit_per_publication: int = 100,
    progress_callback=None,
) -> dict[str, Any]:
    existing = {edge_key(edge): edge for edge in session.get("citation_edges", [])}
    errors = []
    publications = session.get("publications", []) or []
    total_count = len(publications)
    for index, publication in enumerate(publications, 1):
        query = publication_query(publication)
        if not query:
            if progress_callback:
                progress_callback(
                    {
                        "processed_count": index,
                        "total_count": total_count,
                        "citation_edge_count": len(existing),
                        "error_count": len(errors),
                    }
                )
            continue

        try:
            payload = LIST_PAPERS.list_all_citations(
                query,
                limit=limit_per_publication,
            )
        except Exception as exc:
            errors.append(
                {
                    "source_publication_id": publication.get("id"),
                    "query": query,
                    "error": str(exc),
                }
            )
            if progress_callback:
                progress_callback(
                    {
                        "processed_count": index,
                        "total_count": total_count,
                        "citation_edge_count": len(existing),
                        "error_count": len(errors),
                    }
                )
            continue

        provider = payload.get("data_provider") or "unknown"
        for citing_paper in payload.get("papers", []):
            edge = normalize_citation_edge(publication, citing_paper, provider)
            existing[edge_key(edge)] = edge
        if progress_callback:
            progress_callback(
                {
                    "processed_count": index,
                    "total_count": total_count,
                    "citation_edge_count": len(existing),
                    "error_count": len(errors),
                }
            )

    session["citation_edges"] = list(existing.values())
    session["citation_expansion_errors"] = errors
    session["person_candidates"] = SCHOLAR_STATS.build_person_candidates_from_citation_edges(
        session.get("citation_edges", []),
        existing=session.get("person_candidates", []),
    )
    existing_statistics = session.get("statistics") or {}
    session["statistics"] = SCHOLAR_STATS.build_scholar_statistics(
        session.get("publications", []),
        session.get("citation_edges", []),
        session.get("person_candidates", []),
        strong_evidence_count=existing_statistics.get("strong_evidence_count", 0),
    )
    session["deep_analysis_queue"] = SCHOLAR_STATS.build_deep_analysis_queue(
        session.get("citation_edges", []),
        session.get("person_candidates", []),
        limit=100,
    )
    return session


def save_scholar_session(session_dir: Path, session: dict[str, Any]) -> None:
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
