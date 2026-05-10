from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENUE_REGISTRY_PATH = ROOT / "data" / "reference" / "venue_tiers.json"

TIER_ORDER = ["Top", "CCF-A", "CCF-B", "CCF-C", "Unmatched"]
PERSON_STATUS_ORDER = ["pending", "confirmed", "rejected"]
VENUE_NOISE_TOKENS = {
    "proceedings",
    "proc",
    "the",
    "of",
    "and",
    "for",
    "in",
    "on",
    "at",
    "from",
    "with",
    "to",
    "a",
    "an",
    "annual",
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_ordinal_or_year(token: str) -> bool:
    token = (token or "").strip().lower()
    if not token:
        return False
    if token.isdigit():
        return True
    return bool(re.fullmatch(r"\d+(st|nd|rd|th)", token))


def venue_tokens(text: str) -> list[str]:
    return [token for token in normalize_text(text).split(" ") if token]


def distilled_venue_tokens(text: str) -> list[str]:
    tokens = [
        token
        for token in venue_tokens(text)
        if token not in VENUE_NOISE_TOKENS and not _is_ordinal_or_year(token)
    ]
    return tokens or venue_tokens(text)


def unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = (value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_venue_registry(path: str | None = None) -> list[dict[str, Any]]:
    registry_path = Path(path).expanduser() if path else DEFAULT_VENUE_REGISTRY_PATH
    if not registry_path.exists():
        return []
    try:
        payload = _read_json(registry_path)
    except Exception:
        return []
    items = payload if isinstance(payload, list) else payload.get("items", [])
    if not isinstance(items, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        tier = (item.get("tier") or "").strip() or "Unmatched"
        if not name:
            continue
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        all_aliases = unique_strings([name, *[alias for alias in aliases if isinstance(alias, str)]])
        entries.append(
            {
                "name": name,
                "tier": tier,
                "category": (item.get("category") or "").strip(),
                "source": (item.get("source") or "").strip(),
                "aliases": all_aliases,
            }
        )
    return entries


def _match_score(alias: str, venue_name: str) -> tuple[int, str] | None:
    alias_normalized = normalize_text(alias)
    venue_normalized = normalize_text(venue_name)
    if not alias_normalized or not venue_normalized:
        return None

    if alias_normalized == venue_normalized:
        return 500 + len(alias_normalized), "normalized_exact"

    if alias_normalized.replace(" ", "") == venue_normalized.replace(" ", ""):
        return 450 + len(alias_normalized), "normalized_exact"

    alias_tokens = distilled_venue_tokens(alias)
    venue_tokens_set = set(distilled_venue_tokens(venue_name))
    alias_tokens_set = set(alias_tokens)
    if alias_tokens and len(alias_tokens_set) >= 2 and alias_tokens_set.issubset(venue_tokens_set):
        return 300 + len(alias_tokens_set) * 10 + len(alias_normalized), "normalized_contains"

    venue_tokens_distilled = distilled_venue_tokens(venue_name)
    if venue_tokens_distilled and len(venue_tokens_distilled) >= 2 and set(venue_tokens_distilled).issubset(alias_tokens_set):
        return 220 + len(venue_tokens_distilled) * 8 + len(alias_normalized), "normalized_contains"

    return None


def match_venue_tier(
    venue_name: str,
    *,
    registry: list[dict[str, Any]] | None = None,
    registry_path: str | None = None,
) -> dict[str, Any]:
    name = (venue_name or "").strip()
    if not name:
        return {
            "matched": False,
            "tier": "Unmatched",
            "canonical_name": "",
            "matched_alias": "",
            "matched_by": None,
            "source": "",
            "category": "",
        }

    registry = registry if registry is not None else load_venue_registry(registry_path)
    best_entry = None
    best_alias = ""
    best_matched_by = None
    best_score = -1

    for entry in registry:
        for alias in entry.get("aliases", []):
            score = _match_score(alias, name)
            if score is None:
                continue
            numeric_score, matched_by = score
            if numeric_score <= best_score:
                continue
            best_score = numeric_score
            best_entry = entry
            best_alias = alias
            best_matched_by = matched_by

    if best_entry is None:
        return {
            "matched": False,
            "tier": "Unmatched",
            "canonical_name": "",
            "matched_alias": "",
            "matched_by": None,
            "source": "",
            "category": "",
        }

    return {
        "matched": True,
        "tier": best_entry.get("tier") or "Unmatched",
        "canonical_name": best_entry.get("name", ""),
        "matched_alias": best_alias,
        "matched_by": best_matched_by,
        "source": best_entry.get("source", ""),
        "category": best_entry.get("category", ""),
    }


def _ordered_count_dict(counter: Counter, preferred_order: list[str]) -> dict[str, int]:
    ordered: dict[str, int] = {}
    for key in preferred_order:
        ordered[key] = int(counter.get(key, 0))
    for key in sorted(counter):
        if key in ordered:
            continue
        ordered[key] = int(counter.get(key, 0))
    return ordered


def default_quick_stats(session: dict | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "not_ready",
        "query": (session or {}).get("query", ""),
        "layer": "metadata_only",
        "disclaimer": "快速统计基于元数据和本地 registry，可能存在同名或 venue alias 误差；深度分析才是全文语义判断。",
        "publication_statistics": {
            "paper_count": 0,
            "matched_venue_count": 0,
            "unmatched_venue_count": 0,
            "venue_tier_counts": _ordered_count_dict(Counter(), TIER_ORDER),
            "year_range": {"min": None, "max": None},
            "top_venues": [],
        },
        "citation_statistics": {
            "total_citation_count": (session or {}).get("target", {}).get("citationCount"),
            "displayed_citation_count": 0,
            "context_confidence_counts": {"high": 0, "medium": 0, "low": 0, "unknown": 0},
            "matched_person_candidate_count": 0,
            "matched_person_paper_count": 0,
            "person_status_counts": _ordered_count_dict(Counter(), PERSON_STATUS_ORDER),
            "top_tier_citation_count": 0,
        },
        "venue_matches": [],
        "generated_at": None,
    }


def build_quick_stats(session: dict, *, venue_registry_path: str | None = None) -> dict[str, Any]:
    papers = session.get("papers", [])
    if not papers:
        result = default_quick_stats(session)
        result["status"] = "empty"
        result["generated_at"] = datetime.now().isoformat(timespec="seconds")
        return result

    venue_registry = load_venue_registry(venue_registry_path)
    tier_counts: Counter = Counter()
    venue_label_counts: Counter = Counter()
    venue_matches: list[dict[str, Any]] = []
    matched_venue_count = 0
    unmatched_venue_count = 0
    years: list[int] = []
    top_tier_citation_count = 0

    for paper in papers:
        match = match_venue_tier(
            paper.get("venue", ""),
            registry=venue_registry,
        )
        tier = match.get("tier") or "Unmatched"
        tier_counts[tier] += 1
        if match.get("matched"):
            matched_venue_count += 1
        else:
            unmatched_venue_count += 1
        if tier in {"Top", "CCF-A"}:
            top_tier_citation_count += 1

        label = match.get("canonical_name") or (paper.get("venue") or "Unknown Venue")
        venue_label_counts[label] += 1
        year = paper.get("year")
        if isinstance(year, int):
            years.append(year)

        venue_matches.append(
            {
                "paper_id": paper.get("id"),
                "title": paper.get("title", ""),
                "venue": paper.get("venue", ""),
                "tier": tier,
                "matched": bool(match.get("matched")),
                "matched_by": match.get("matched_by"),
                "canonical_name": match.get("canonical_name", ""),
            }
        )

    context_confidence_counts = Counter((paper.get("context_confidence") or "unknown") for paper in papers)
    person_candidates = session.get("person_candidates", [])
    person_status_counts = Counter((item.get("status") or "pending") for item in person_candidates)
    matched_person_paper_ids = {
        paper_id
        for item in person_candidates
        for paper_id in (item.get("matched_paper_ids") or [])
        if paper_id
    }

    top_venues = []
    for venue_name, count in venue_label_counts.most_common(5):
        matched_entry = next(
            (
                item
                for item in venue_matches
                if (item.get("canonical_name") or item.get("venue") or "Unknown Venue") == venue_name
            ),
            {},
        )
        top_venues.append(
            {
                "venue": venue_name,
                "paper_count": count,
                "tier": matched_entry.get("tier", "Unmatched"),
            }
        )

    result = default_quick_stats(session)
    result.update(
        {
            "status": "ready",
            "publication_statistics": {
                "paper_count": len(papers),
                "matched_venue_count": matched_venue_count,
                "unmatched_venue_count": unmatched_venue_count,
                "venue_tier_counts": _ordered_count_dict(tier_counts, TIER_ORDER),
                "year_range": {
                    "min": min(years) if years else None,
                    "max": max(years) if years else None,
                },
                "top_venues": top_venues,
            },
            "citation_statistics": {
                "total_citation_count": (session.get("target") or {}).get("citationCount"),
                "displayed_citation_count": len(papers),
                "context_confidence_counts": {
                    "high": int(context_confidence_counts.get("high", 0)),
                    "medium": int(context_confidence_counts.get("medium", 0)),
                    "low": int(context_confidence_counts.get("low", 0)),
                    "unknown": int(context_confidence_counts.get("unknown", 0)),
                },
                "matched_person_candidate_count": len(person_candidates),
                "matched_person_paper_count": len(matched_person_paper_ids),
                "person_status_counts": _ordered_count_dict(person_status_counts, PERSON_STATUS_ORDER),
                "top_tier_citation_count": top_tier_citation_count,
            },
            "venue_matches": venue_matches,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return result
