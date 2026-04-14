from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"
DEFAULT_TOP_INSTITUTIONS_PATH = ROOT / "data" / "reference" / "top_institutions.json"

TAG_LABELS = {
    "acm_fellow": "ACM Fellow",
    "ieee_fellow": "IEEE Fellow",
    "cas_academician": "中国科学院院士",
    "cae_academician": "中国工程院院士",
    "top_school": "国外牛校作者",
}


def normalize_name(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)
    return text


def slugify_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "candidate"


def load_registry(path: str | None = None) -> list[dict[str, Any]]:
    registry_path = Path(path).expanduser() if path else DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        return []
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        tag_type = (item.get("tag_type") or "").strip()
        if not name or not tag_type:
            continue
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        entries.append(
            {
                "name": name,
                "tag_type": tag_type,
                "tag_label": TAG_LABELS.get(tag_type, tag_type),
                "aliases": [alias for alias in aliases if isinstance(alias, str) and alias.strip()],
                "source_links": [
                    url for url in (item.get("source_links") or []) if isinstance(url, str) and url.strip()
                ],
                "matched_affiliations": [
                    value
                    for value in (item.get("matched_affiliations") or [])
                    if isinstance(value, str) and value.strip()
                ],
                "note": (item.get("note") or "").strip(),
            }
        )
    return entries


def load_top_institutions(path: str | None = None) -> list[dict[str, Any]]:
    config_path = Path(path).expanduser() if path else DEFAULT_TOP_INSTITUTIONS_PATH
    if not config_path.exists():
        return []
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        return []

    institutions: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        institutions.append({
            "name": name,
            "aliases": [alias for alias in aliases if isinstance(alias, str) and alias.strip()],
            "source_links": [
                url for url in (item.get("source_links") or []) if isinstance(url, str) and url.strip()
            ],
            "note": (item.get("note") or "").strip(),
        })
    return institutions


def match_top_institution(institution_name: str, institutions: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = normalize_name(institution_name)
    if not normalized:
        return None
    for institution in institutions:
        names = [institution.get("name", ""), *(institution.get("aliases", []) or [])]
        for candidate_name in names:
            normalized_candidate = normalize_name(candidate_name)
            if not normalized_candidate:
                continue
            if len(normalized_candidate) <= 4:
                pattern = rf"(?<![A-Za-z0-9]){re.escape(str(candidate_name).strip())}(?![A-Za-z0-9])"
                if re.search(pattern, institution_name, flags=re.IGNORECASE):
                    return institution
                continue
            if normalized_candidate in normalized:
                return institution
    return None


def iter_author_details(paper: dict[str, Any]) -> list[dict[str, Any]]:
    details = []
    raw_details = paper.get("author_details") or (paper.get("paper") or {}).get("author_details") or []
    if isinstance(raw_details, list):
        for detail in raw_details:
            if isinstance(detail, dict) and (detail.get("name") or "").strip():
                details.append(detail)

    seen_names = {normalize_name(detail.get("name", "")) for detail in details}
    raw_authors = paper.get("authors", []) or (paper.get("paper") or {}).get("authors", []) or []
    for author_name in raw_authors:
        normalized = normalize_name(author_name)
        if not normalized or normalized in seen_names:
            continue
        seen_names.add(normalized)
        details.append({"name": author_name, "institutions": [], "source_url": ""})
    return details


def merge_candidate(candidates: dict[str, dict[str, Any]], candidate: dict[str, Any], prior: dict[str, Any]):
    candidate_id = candidate["candidate_id"]
    if candidate_id not in candidates:
        candidate["status"] = prior.get("status") or candidate.get("status") or "pending"
        candidate["review_note"] = prior.get("review_note") or candidate.get("review_note") or ""
        candidate["reviewed_at"] = prior.get("reviewed_at") or candidate.get("reviewed_at")
        candidates[candidate_id] = candidate
        return

    existing = candidates[candidate_id]
    for key in ["matched_paper_ids", "matched_paper_titles", "matched_affiliations", "source_links"]:
        merged = []
        for value in [*(existing.get(key, []) or []), *(candidate.get(key, []) or [])]:
            if value and value not in merged:
                merged.append(value)
        existing[key] = merged
    existing["evidence"].extend(candidate.get("evidence", []))
    if candidate.get("note") and candidate.get("note") not in existing.get("note", ""):
        existing["note"] = "；".join([part for part in [existing.get("note", ""), candidate.get("note", "")] if part])


def build_candidates(
    papers: list[dict[str, Any]],
    existing: list[dict[str, Any]] | None = None,
    registry_path: str | None = None,
    top_institutions_path: str | None = None,
) -> list[dict[str, Any]]:
    existing = existing or []
    existing_by_id = {
        item.get("candidate_id"): item for item in existing if isinstance(item, dict) and item.get("candidate_id")
    }
    candidates: dict[str, dict[str, Any]] = {}
    for entry in load_registry(registry_path):
        normalized_names = {
            normalize_name(entry.get("name", "")),
            *(normalize_name(alias) for alias in entry.get("aliases", [])),
        }
        normalized_names.discard("")
        if not normalized_names:
            continue

        matched_paper_ids: list[str] = []
        matched_paper_titles: list[str] = []
        match_evidence: list[dict[str, Any]] = []
        seen_match_keys: set[tuple[str, str]] = set()
        for paper in papers:
            paper_id = paper.get("id")
            title = paper.get("title", "")
            for author_name in paper.get("authors", []) or []:
                normalized_author = normalize_name(author_name)
                if not normalized_author or normalized_author not in normalized_names:
                    continue
                key = (paper_id or "", normalized_author)
                if key in seen_match_keys:
                    continue
                seen_match_keys.add(key)
                if paper_id and paper_id not in matched_paper_ids:
                    matched_paper_ids.append(paper_id)
                if title and title not in matched_paper_titles:
                    matched_paper_titles.append(title)
                match_evidence.append(
                    {
                        "paper_id": paper_id,
                        "paper_title": title,
                        "matched_author": author_name,
                        "match_type": "exact_name",
                    }
                )
        if not match_evidence:
            continue
        candidate_id = f"{entry['tag_type']}::{slugify_text(entry['name'])}"
        prior = existing_by_id.get(candidate_id, {})
        merge_candidate(candidates, {
            "candidate_id": candidate_id,
            "name": entry["name"],
            "tag_type": entry["tag_type"],
            "tag_label": entry["tag_label"],
            "matched_paper_ids": matched_paper_ids,
            "matched_paper_titles": matched_paper_titles,
            "matched_affiliations": entry.get("matched_affiliations", []),
            "source_links": entry.get("source_links", []),
            "status": prior.get("status") or "pending",
            "review_note": prior.get("review_note") or "",
            "reviewed_at": prior.get("reviewed_at"),
            "evidence": match_evidence,
            "note": entry.get("note", ""),
        }, prior)

    top_institutions = load_top_institutions(top_institutions_path)
    for paper in papers:
        paper_id = paper.get("id")
        title = paper.get("title", "")
        for author in iter_author_details(paper):
            author_name = (author.get("name") or "").strip()
            if not author_name:
                continue
            for institution_name in author.get("institutions", []) or []:
                matched_institution = match_top_institution(str(institution_name), top_institutions)
                if not matched_institution:
                    continue
                candidate_id = f"top_school::{slugify_text(author_name)}"
                prior = existing_by_id.get(candidate_id, {})
                source_links = list(matched_institution.get("source_links", []))
                if author.get("source_url"):
                    source_links.append(author.get("source_url"))
                merge_candidate(candidates, {
                    "candidate_id": candidate_id,
                    "name": author_name,
                    "tag_type": "top_school",
                    "tag_label": TAG_LABELS["top_school"],
                    "matched_paper_ids": [paper_id] if paper_id else [],
                    "matched_paper_titles": [title] if title else [],
                    "matched_affiliations": [matched_institution.get("name") or str(institution_name)],
                    "source_links": source_links,
                    "status": "pending",
                    "review_note": "",
                    "reviewed_at": None,
                    "evidence": [
                        {
                            "paper_id": paper_id,
                            "paper_title": title,
                            "matched_author": author_name,
                            "match_type": "top_institution_affiliation",
                            "institution": matched_institution.get("name") or str(institution_name),
                            "raw_institution": str(institution_name),
                        }
                    ],
                    "note": matched_institution.get("note", ""),
                }, prior)
    return sorted(candidates.values(), key=lambda item: (item.get("tag_label", ""), item.get("name", "")))
