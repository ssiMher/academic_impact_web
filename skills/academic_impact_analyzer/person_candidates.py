from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"
DEFAULT_TOP_INSTITUTIONS_PATH = ROOT / "data" / "reference" / "top_institutions.json"

TAG_LABELS = {
    "acm_fellow": "ACM Fellow",
    "ieee_fellow": "IEEE Fellow",
    "aaai_fellow": "AAAI Fellow",
    "cas_academician": "中国科学院院士",
    "cae_academician": "中国工程院院士",
    "godel_prize": "Gödel Prize",
    "top_school": "国外牛校作者",
}


def normalize_name(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)
    return text


def name_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text or "")


def normalized_name_variants(text: str) -> set[str]:
    raw = (text or "").strip()
    variants = {normalize_name(raw)}
    if not raw or re.search(r"[\u4e00-\u9fff]", raw):
        variants.discard("")
        return variants

    if "," in raw:
        family, given = raw.split(",", 1)
        family_tokens = name_tokens(family)
        given_tokens = name_tokens(given)
        if family_tokens and given_tokens:
            ordered = [*given_tokens, *family_tokens]
            variants.add(normalize_name(" ".join(ordered)))
            without_initials = [token for token in given_tokens if len(token) > 1]
            if without_initials:
                variants.add(normalize_name(" ".join([*without_initials, *family_tokens])))
            variants.add(normalize_name(" ".join([given_tokens[0], *family_tokens])))
    else:
        tokens = name_tokens(raw)
        if len(tokens) >= 3:
            variants.add(normalize_name(" ".join([tokens[0], tokens[-1]])))

    variants.discard("")
    return variants


def slugify_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "candidate"


def normalize_affiliation(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _expand_tag_items(item: dict[str, Any]) -> list[dict[str, Any]]:
    legacy_tag_type = (item.get("tag_type") or "").strip()
    legacy_links = item.get("source_links") or []
    legacy_note = (item.get("note") or "").strip()
    raw_tags = item.get("tags")
    if not isinstance(raw_tags, list) or not raw_tags:
        raw_tags = []
        if legacy_tag_type:
            raw_tags.append(
                {
                    "type": legacy_tag_type,
                    "source_links": legacy_links,
                    "note": legacy_note,
                }
            )

    tags: list[dict[str, Any]] = []
    for tag in raw_tags:
        if not isinstance(tag, dict):
            continue
        tag_type = (tag.get("type") or tag.get("tag_type") or "").strip()
        if not tag_type:
            continue
        source_links = tag.get("source_links")
        if not isinstance(source_links, list):
            source_links = legacy_links if isinstance(legacy_links, list) else []
        tags.append(
            {
                "tag_type": tag_type,
                "tag_label": (tag.get("label") or TAG_LABELS.get(tag_type, tag_type)).strip(),
                "source_links": [url for url in source_links if isinstance(url, str) and url.strip()],
                "note": (tag.get("note") or legacy_note or "").strip(),
            }
        )
    return tags


def extract_affiliation_candidates(paper: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add_value(value: Any):
        if isinstance(value, str):
            values.append(value)
            return
        if isinstance(value, dict):
            for nested in value.values():
                add_value(nested)
            return
        if isinstance(value, list):
            for nested in value:
                add_value(nested)

    for key in ["affiliations", "author_affiliations", "institutions"]:
        add_value(paper.get(key))
    if isinstance(paper.get("paper"), dict):
        for key in ["affiliations", "author_affiliations", "institutions"]:
            add_value(paper["paper"].get(key))

    normalized = []
    seen = set()
    for value in values:
        item = normalize_affiliation(value)
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


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
        if not name:
            continue
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        matched_affiliations = [
            normalize_affiliation(value)
            for value in (item.get("matched_affiliations") or [])
            if isinstance(value, str) and value.strip()
        ]
        for tag in _expand_tag_items(item):
            entries.append(
                {
                    "name": name,
                    "tag_type": tag["tag_type"],
                    "tag_label": tag["tag_label"],
                    "aliases": [alias for alias in aliases if isinstance(alias, str) and alias.strip()],
                    "source_links": tag["source_links"],
                    "matched_affiliations": matched_affiliations,
                    "note": tag["note"],
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


def candidate_matched_authors(candidate: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in candidate.get("evidence", []) or []:
        matched_author = (item.get("matched_author") or "").strip()
        normalized = normalize_name(matched_author)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(matched_author)
    if names:
        return names
    fallback_name = (candidate.get("name") or "").strip()
    if fallback_name:
        return [fallback_name]
    return []


def summarize_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    author_display: OrderedDict[str, str] = OrderedDict()
    author_candidate_ids: dict[str, set[str]] = {}
    high_risk_authors: set[str] = set()

    for candidate in candidates:
        candidate_id = (candidate.get("candidate_id") or "").strip()
        is_high_risk = bool(
            candidate.get("homonym_risk")
            or "name_only_match" in (candidate.get("risk_flags") or [])
        )
        for author_name in candidate_matched_authors(candidate):
            normalized = normalize_name(author_name)
            if not normalized:
                continue
            author_display.setdefault(normalized, author_name)
            author_candidate_ids.setdefault(normalized, set()).add(candidate_id or normalized)
            if is_high_risk:
                high_risk_authors.add(normalized)

    ambiguous_author_count = sum(
        1 for ids in author_candidate_ids.values() if len(ids) > 1
    )
    return {
        "matched_author_count": len(author_display),
        "matched_author_preview": list(author_display.values())[:5],
        "ambiguous_author_count": ambiguous_author_count,
        "high_risk_author_count": len(high_risk_authors),
    }


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
        raw_names = [entry.get("name", ""), *(entry.get("aliases", []) or [])]
        exact_names = {normalize_name(raw_name) for raw_name in raw_names}
        alias_exact_names = {normalize_name(raw_name) for raw_name in (entry.get("aliases", []) or [])}
        normalized_names = set()
        for raw_name in raw_names:
            normalized_names.update(normalized_name_variants(raw_name))
        exact_names.discard("")
        normalized_names.discard("")
        if not normalized_names:
            continue

        matched_paper_ids: list[str] = []
        matched_paper_titles: list[str] = []
        match_evidence: list[dict[str, Any]] = []
        risk_flags: set[str] = set()
        seen_match_keys: set[tuple[str, str]] = set()
        for paper in papers:
            paper_id = paper.get("id")
            title = paper.get("title", "")
            affiliations = extract_affiliation_candidates(paper)
            matched_affiliations = [
                token
                for token in entry.get("matched_affiliations", [])
                if token and any(token in affiliation for affiliation in affiliations)
            ]
            for author_name in paper.get("authors", []) or []:
                normalized_author = normalize_name(author_name)
                author_variants = normalized_name_variants(str(author_name))
                matched_variant = next((variant for variant in author_variants if variant in normalized_names), None)
                if not normalized_author or not matched_variant:
                    continue
                key = (paper_id or "", normalized_author, matched_variant)
                if key in seen_match_keys:
                    continue
                seen_match_keys.add(key)
                if paper_id and paper_id not in matched_paper_ids:
                    matched_paper_ids.append(paper_id)
                if title and title not in matched_paper_titles:
                    matched_paper_titles.append(title)
                if not matched_affiliations:
                    risk_flags.add("name_only_match")
                match_evidence.append(
                    {
                        "paper_id": paper_id,
                        "paper_title": title,
                        "matched_author": author_name,
                        "match_type": (
                            "exact_name"
                            if normalized_author == normalize_name(entry.get("name", ""))
                            else "alias"
                            if normalized_author in alias_exact_names
                            else "name_variant"
                        ),
                        "matched_affiliations": matched_affiliations,
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
            "homonym_risk": bool(risk_flags),
            "risk_flags": sorted(risk_flags),
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
