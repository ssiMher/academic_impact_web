from __future__ import annotations

import importlib.util
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
IMPACT_CLI_PATH = ROOT / "skills" / "academic_impact_analyzer" / "impact_cli.py"
PERSON_CANDIDATES_PATH = ROOT / "skills" / "academic_impact_analyzer" / "person_candidates.py"
SCHOLAR_EVIDENCE_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_evidence.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IMPACT_CLI = load_module("scholar_stats_impact_cli", IMPACT_CLI_PATH)
PERSON_CANDIDATES = load_module(
    "scholar_stats_person_candidates", PERSON_CANDIDATES_PATH
)
SCHOLAR_EVIDENCE = load_module("scholar_stats_evidence", SCHOLAR_EVIDENCE_PATH)


def normalize_doi(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


def venue_distribution(
    items: list[dict[str, Any]], venue_key: str
) -> list[dict[str, Any]]:
    tier_index = IMPACT_CLI.build_venue_tier_index()
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}

    for item in items:
        venue = item.get(venue_key) or item.get("venue") or "Unknown Venue"
        tier = IMPACT_CLI.classify_venue_tier(venue, tier_index)
        label = tier.get("tier_label") or "未匹配等级"
        counts[label] += 1

        title = item.get("title") or item.get("citing_title") or ""
        if title and len(examples.setdefault(label, [])) < 5:
            examples[label].append(title)

    return [
        {"tier_label": label, "count": count, "examples": examples.get(label, [])}
        for label, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def person_tag_statistics(
    person_candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    labels = PERSON_CANDIDATES.TAG_LABELS
    present_tag_types = {
        candidate.get("tag_type") or "" for candidate in person_candidates
    }
    present_tag_types.discard("")
    ordered_tag_types = [
        tag_type for tag_type in labels.keys() if tag_type in present_tag_types
    ]
    for candidate in person_candidates:
        tag_type = candidate.get("tag_type") or ""
        if tag_type and tag_type not in ordered_tag_types:
            ordered_tag_types.append(tag_type)

    result = []
    for tag_type in ordered_tag_types:
        candidates = [
            item for item in person_candidates if item.get("tag_type") == tag_type
        ]
        summary = PERSON_CANDIDATES.summarize_candidates(candidates)
        matched_paper_ids = set()
        for candidate in candidates:
            matched_paper_ids.update(candidate.get("matched_paper_ids") or [])
        result.append(
            {
                "tag_type": tag_type,
                "tag_label": labels.get(tag_type, tag_type or "-"),
                "count": summary["matched_author_count"],
                "matched_author_count": summary["matched_author_count"],
                "candidate_count": len(candidates),
                "ambiguous_author_count": summary["ambiguous_author_count"],
                "high_risk_author_count": summary["high_risk_author_count"],
                "matched_author_preview": summary["matched_author_preview"],
                "confirmed_count": sum(
                    1 for item in candidates if item.get("status") == "confirmed"
                ),
                "pending_count": sum(
                    1 for item in candidates if item.get("status") == "pending"
                ),
                "rejected_count": sum(
                    1 for item in candidates if item.get("status") == "rejected"
                ),
                "source_complete_count": sum(
                    1 for item in candidates if item.get("source_links")
                ),
                "matched_paper_count": len(matched_paper_ids),
                "candidates": candidates[:5],
            }
        )
    return result


def build_person_candidates_from_citation_edges(
    citation_edges: list[dict[str, Any]],
    existing: list[dict[str, Any]] | None = None,
    registry_path: str | None = None,
) -> list[dict[str, Any]]:
    papers = []
    seen_ids = set()
    for index, edge in enumerate(citation_edges, 1):
        paper_id = (
            edge.get("citing_paper_id")
            or edge.get("citing_doi")
            or edge.get("citing_title")
            or f"C{index:06d}"
        )
        if paper_id in seen_ids:
            continue
        seen_ids.add(paper_id)
        author_details = edge.get("citing_author_details") or []
        authors = []
        for detail in author_details:
            if not isinstance(detail, dict):
                continue
            name = detail.get("name")
            if name and name not in authors:
                authors.append(name)
        for author in edge.get("citing_authors") or []:
            if author and author not in authors:
                authors.append(author)
        papers.append(
            {
                "id": paper_id,
                "title": edge.get("citing_title") or "",
                "authors": authors,
                "author_details": author_details,
            }
        )
    return PERSON_CANDIDATES.build_candidates(
        papers,
        existing=existing,
        registry_path=registry_path,
    )


def build_scholar_statistics(
    publications: list[dict[str, Any]],
    citation_edges: list[dict[str, Any]],
    person_candidates: list[dict[str, Any]],
    strong_evidence_count: int = 0,
) -> dict[str, Any]:
    yearly_citations = Counter(
        edge.get("citing_year") for edge in citation_edges if edge.get("citing_year")
    )
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
        "first_author_publication_count": sum(
            1 for item in publications if item.get("author_position") == "first_author"
        ),
        "total_citation_count": sum(
            item.get("citation_count") or 0 for item in publications
        ),
        "citation_edge_count": len(citation_edges),
        "publication_tiers": venue_distribution(publications, "venue"),
        "citing_venue_tiers": venue_distribution(citation_edges, "citing_venue"),
        "person_tag_statistics": person_tag_statistics(person_candidates),
        "yearly_citations": [
            {"year": year, "count": count}
            for year, count in sorted(yearly_citations.items())
        ],
        "top_publications": top_publications,
        "strong_evidence_count": strong_evidence_count,
    }


def normalized_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def citation_group_key(edge: dict[str, Any]) -> str:
    doi = normalize_doi(edge.get("citing_doi") or "")
    if doi:
        return f"doi:{doi}"

    title = normalize_title(edge.get("citing_title") or "")
    if title:
        authors = edge.get("citing_authors") or []
        first_author = normalized_name(authors[0]) if authors else ""
        return f"title:{title}|year:{edge.get('citing_year') or ''}|first:{first_author}"

    return (
        edge.get("citing_paper_id")
        or edge.get("source_url")
        or edge.get("citing_title")
        or ""
    )


def reason_priority_score(reasons: list[str]) -> int:
    score = 0
    for reason in reasons:
        if reason.startswith("person_tag:"):
            score += 50
        elif reason.startswith("venue:"):
            score += 25
        else:
            score += 10
    return score


def edge_has_analysis_identifier(edge: dict[str, Any]) -> bool:
    return bool(
        edge.get("citing_doi")
        or edge.get("citing_openalex_id")
        or edge.get("citing_scopus_id")
        or edge.get("source_url")
        or edge.get("citing_paper_id")
    )


def classify_edge_self_citation(edge: dict[str, Any]) -> dict[str, Any]:
    return SCHOLAR_EVIDENCE.classify_self_citation(
        edge.get("source_publication_authors") or edge.get("target_authors") or [],
        edge.get("citing_authors") or [],
    )


def merge_self_citation_status(existing: str, new_status: str) -> str:
    if new_status == "non_self_citation" or existing == "non_self_citation":
        return "non_self_citation"
    if new_status == "self_citation" or existing == "self_citation":
        return "self_citation"
    return existing or new_status or "unknown"


def person_tag_by_author(person_candidates: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for candidate in person_candidates:
        if candidate.get("status") == "rejected":
            continue
        matched_authors = PERSON_CANDIDATES.candidate_matched_authors(candidate)
        if not matched_authors:
            continue
        for author_name in matched_authors:
            result[normalized_name(author_name)] = (
                candidate.get("tag_label") or candidate.get("tag_type") or ""
            )
    return result


def person_tag_info_by_author(
    person_candidates: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    result = {}
    for candidate in person_candidates:
        if candidate.get("status") == "rejected":
            continue
        matched_authors = PERSON_CANDIDATES.candidate_matched_authors(candidate)
        if not matched_authors:
            continue
        candidate_status = candidate.get("status") or "pending"
        if candidate.get("auto_match_status") == "matched":
            candidate_status = "confirmed"
        for author_name in matched_authors:
            result[normalized_name(author_name)] = {
                "label": candidate.get("tag_label") or candidate.get("tag_type") or "",
                "status": candidate_status,
            }
    return result


def build_deep_analysis_queue(
    citation_edges: list[dict[str, Any]],
    person_candidates: list[dict[str, Any]],
    limit: int = 100,
) -> list[dict[str, Any]]:
    tag_map = person_tag_info_by_author(person_candidates)
    tier_index = IMPACT_CLI.build_venue_tier_index()
    grouped: dict[str, dict[str, Any]] = {}

    for edge in citation_edges:
        score = 0
        reasons = []
        for author in edge.get("citing_authors") or []:
            tag = tag_map.get(normalized_name(author))
            if tag:
                score += 60 if tag.get("status") == "confirmed" else 40
                reasons.append(f"person_tag:{tag.get('label')}")

        tier = IMPACT_CLI.classify_venue_tier(
            edge.get("citing_venue") or "", tier_index
        )
        if tier.get("tier_label") in {"CCF A", "Top venue seed"}:
            score += 25
            reasons.append(f"venue:{tier.get('tier_label')}")

        citing_citation_count = int(edge.get("citing_citation_count") or 0)
        if citing_citation_count >= 50:
            score += 10
            reasons.append("citation_count:high")

        self_citation = classify_edge_self_citation(edge)
        self_status = self_citation.get("status") or "unknown"
        if score > 0 and self_status == "non_self_citation":
            score += 8
            reasons.append("self_citation:non_self")
        elif score > 0 and self_status == "self_citation":
            score -= 30
            reasons.append("self_citation:self")

        if score > 0 and edge_has_analysis_identifier(edge):
            score += 6

        if score <= 0:
            continue

        key = citation_group_key(edge)
        item = grouped.get(key)
        if item is None:
            item = dict(edge)
            item["priority_score"] = score
            item["reasons"] = []
            item["source_publication_ids"] = []
            item["cited_publication_titles"] = []
            item["self_citation_status"] = "unknown"
            item["self_citation_overlap_authors"] = []
            grouped[key] = item
        item["priority_score"] = max(item.get("priority_score") or 0, score)
        for reason in reasons:
            if reason not in item["reasons"]:
                item["reasons"].append(reason)
        item["self_citation_status"] = merge_self_citation_status(
            item.get("self_citation_status") or "unknown",
            self_status,
        )
        for author in self_citation.get("overlap_authors") or []:
            if author not in item["self_citation_overlap_authors"]:
                item["self_citation_overlap_authors"].append(author)
        item["priority_score"] = max(
            item.get("priority_score") or 0,
            reason_priority_score(item["reasons"]),
        )
        source_id = edge.get("source_publication_id")
        if source_id and source_id not in item["source_publication_ids"]:
            item["source_publication_ids"].append(source_id)
        cited_title = edge.get("cited_publication_title")
        if cited_title and cited_title not in item["cited_publication_titles"]:
            item["cited_publication_titles"].append(cited_title)
        item["cited_publication_count"] = len(item["source_publication_ids"])

    ranked = sorted(
        list(grouped.values()),
        key=lambda item: (
            -(item["priority_score"]),
            -(item.get("cited_publication_count") or 0),
            item.get("citing_title") or "",
        ),
    )[:limit]
    for index, item in enumerate(ranked, 1):
        item["queue_id"] = f"Q{index:03d}"
    return ranked
