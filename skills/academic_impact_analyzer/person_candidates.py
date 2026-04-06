from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"

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


def build_candidates(
    papers: list[dict[str, Any]],
    existing: list[dict[str, Any]] | None = None,
    registry_path: str | None = None,
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
        candidates[candidate_id] = {
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
        }
    return sorted(candidates.values(), key=lambda item: (item.get("tag_label", ""), item.get("name", "")))
