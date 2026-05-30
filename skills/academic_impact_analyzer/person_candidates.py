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
    "academia_europaea_member": "Member of Academia Europaea(欧洲科学院院士)",
    "godel_prize": "Gödel Prize",
    "top_school": "国外牛校作者",
}

STRICT_IDENTITY_TAGS = {"cas_academician", "cae_academician"}


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


def normalize_external_id(value: str) -> str:
    text = (value or "").strip().lower().rstrip("/")
    if not text:
        return ""
    if text.startswith("https://orcid.org/"):
        return text.replace("https://orcid.org/", "orcid:")
    if text.startswith("http://orcid.org/"):
        return text.replace("http://orcid.org/", "orcid:")
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
                    "openalex_author_ids": [
                        normalize_external_id(value)
                        for value in (item.get("openalex_author_ids") or [])
                        if isinstance(value, str) and value.strip()
                    ],
                    "orcid_ids": [
                        normalize_external_id(value)
                        for value in (item.get("orcid_ids") or [])
                        if isinstance(value, str) and value.strip()
                    ],
                    "dblp_author_ids": [
                        normalize_external_id(value)
                        for value in (item.get("dblp_author_ids") or [])
                        if isinstance(value, str) and value.strip()
                    ],
                    "known_institutions": [
                        normalize_affiliation(value)
                        for value in (item.get("known_institutions") or [])
                        if isinstance(value, str) and value.strip()
                    ],
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


def candidate_resolved_authors(candidate: dict[str, Any]) -> list[str]:
    values = candidate.get("resolved_matched_authors")
    if isinstance(values, list):
        result = []
        seen = set()
        for value in values:
            normalized = normalize_name(str(value))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(str(value))
        return result
    return []


def _match_type_rank(match_type: str) -> int:
    return {
        "identity_match": 4,
        "top_institution_affiliation": 4,
        "institution_supported": 3,
        "exact_name": 3,
        "alias": 2,
        "name_variant": 1,
    }.get(match_type or "", 0)


def _match_type_score(match_type: str) -> int:
    return {
        "identity_match": 12,
        "top_institution_affiliation": 10,
        "institution_supported": 8,
        "exact_name": 4,
        "alias": 3,
        "name_variant": 1,
    }.get(match_type or "", 0)


def _display_author_name(evidence: list[dict[str, Any]]) -> str:
    for item in evidence:
        name = (item.get("matched_author") or "").strip()
        if name:
            return name
    return ""


def _candidate_author_groups(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in candidate.get("evidence", []) or []:
        matched_author = (item.get("matched_author") or "").strip()
        normalized = normalize_name(matched_author)
        if not normalized:
            continue
        group = groups.setdefault(
            normalized,
            {
                "author_name": matched_author,
                "evidence": [],
                "match_type": "",
                "match_type_rank": -1,
                "has_identity": False,
                "has_institution": False,
                "identity_sources": set(),
                "institution_values": set(),
            },
        )
        group["evidence"].append(item)
        rank = _match_type_rank(item.get("match_type") or "")
        if rank > group["match_type_rank"]:
            group["match_type_rank"] = rank
            group["match_type"] = item.get("match_type") or ""
        if item.get("matched_identity_sources"):
            group["has_identity"] = True
            group["identity_sources"].update(item.get("matched_identity_sources") or [])
        if item.get("matched_known_institutions"):
            group["has_institution"] = True
            group["institution_values"].update(item.get("matched_known_institutions") or [])
        if item.get("match_type") == "top_institution_affiliation" and item.get("institution"):
            group["has_institution"] = True
            group["institution_values"].add(normalize_affiliation(item.get("institution") or ""))
    return groups


def _score_candidate_author_match(
    candidate: dict[str, Any],
    author_group: dict[str, Any],
) -> tuple[int, list[str], str]:
    reasons: list[str] = []
    score = _match_type_score(author_group.get("match_type") or "")
    if author_group.get("has_identity"):
        score += 8
        reasons.append("identity_match")
    if author_group.get("has_institution"):
        score += 4
        reasons.append("institution_match")
    evidence_count = len(author_group.get("evidence") or [])
    if evidence_count > 1:
        score += min(evidence_count - 1, 2)
        reasons.append("multi_paper_support")
    match_type = author_group.get("match_type") or ""
    if match_type:
        reasons.append(match_type)
    confidence = "low"
    if author_group.get("has_identity") or score >= 12:
        confidence = "high"
    elif author_group.get("has_institution") or score >= 7:
        confidence = "medium"
    return score, reasons, confidence


def apply_auto_resolution(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    author_tag_matches: dict[tuple[str, str], list[dict[str, Any]]] = {}
    strict_author_matches: dict[str, list[dict[str, Any]]] = {}

    for candidate in candidates:
        candidate_id = (candidate.get("candidate_id") or "").strip()
        candidate["resolved_matched_authors"] = []
        candidate["auto_match_status"] = "not_matched"
        candidate["auto_match_score"] = 0
        candidate["auto_match_confidence"] = "low"
        candidate["auto_match_reasons"] = []
        groups = _candidate_author_groups(candidate)
        for normalized_author, group in groups.items():
            score, reasons, confidence = _score_candidate_author_match(candidate, group)
            contender = {
                "candidate": candidate,
                "author_name": group.get("author_name") or normalized_author,
                "score": score,
                "reasons": reasons,
                "confidence": confidence,
                "has_identity": group.get("has_identity", False),
                "has_institution": group.get("has_institution", False),
                "match_type": group.get("match_type") or "",
            }
            author_tag_matches.setdefault((candidate.get("tag_type") or "", normalized_author), []).append(contender)
            if (candidate.get("tag_type") or "") in STRICT_IDENTITY_TAGS:
                strict_author_matches.setdefault(normalized_author, []).append(contender)

    for (tag_type, _normalized_author), contenders in author_tag_matches.items():
        contenders.sort(
            key=lambda item: (
                -item["score"],
                -(1 if item["has_identity"] else 0),
                -(1 if item["has_institution"] else 0),
                item["candidate"].get("candidate_id") or "",
            )
        )
        winner = contenders[0]
        runner_up_score = contenders[1]["score"] if len(contenders) > 1 else None
        score_margin_ok = runner_up_score is None or winner["score"] >= runner_up_score + 3
        has_strong_evidence = winner["has_identity"] or winner["has_institution"]
        strict_tag = tag_type in STRICT_IDENTITY_TAGS
        strict_cross_tag_collision = (
            strict_tag
            and len(strict_author_matches.get(_normalized_author, [])) > 1
            and not any(
                contender["has_identity"] or contender["has_institution"]
                for contender in strict_author_matches.get(_normalized_author, [])
            )
        )
        winner_reasons = list(winner["reasons"])
        accepted = False
        if strict_tag:
            accepted = (
                has_strong_evidence
                and winner["score"] >= 10
                and score_margin_ok
                and not strict_cross_tag_collision
            )
        else:
            accepted = (
                winner["score"] >= 4
                and score_margin_ok
                and (
                    has_strong_evidence
                    or (
                        len(contenders) == 1
                        and winner["match_type"] in {"exact_name", "alias"}
                    )
                )
            )
        if strict_cross_tag_collision:
            winner_reasons.append("ambiguous_name_collision")
        elif not score_margin_ok:
            winner_reasons.append("ambiguous_name_collision")
        elif strict_tag and not has_strong_evidence:
            winner_reasons.append("strict_tag_requires_identity_or_institution")
        elif winner["score"] < 4:
            winner_reasons.append("insufficient_score")

        if accepted:
            candidate = winner["candidate"]
            resolved = candidate.setdefault("resolved_matched_authors", [])
            if winner["author_name"] not in resolved:
                resolved.append(winner["author_name"])
            candidate["auto_match_status"] = "matched"
            candidate["auto_match_score"] = max(candidate.get("auto_match_score") or 0, winner["score"])
            candidate["auto_match_confidence"] = winner["confidence"]
            candidate["auto_match_reasons"] = sorted(
                {*(candidate.get("auto_match_reasons") or []), *winner_reasons, "auto_resolved"}
            )
        else:
            for contender in contenders:
                candidate = contender["candidate"]
                candidate["auto_match_score"] = max(candidate.get("auto_match_score") or 0, contender["score"])
                candidate["auto_match_reasons"] = sorted(
                    {*(candidate.get("auto_match_reasons") or []), *winner_reasons}
                )

    for candidate in candidates:
        if candidate.get("auto_match_status") == "matched":
            if (candidate.get("auto_match_score") or 0) >= 12:
                candidate["auto_match_confidence"] = "high"
            elif (candidate.get("auto_match_score") or 0) >= 7:
                candidate["auto_match_confidence"] = "medium"
            else:
                candidate["auto_match_confidence"] = "low"
        else:
            candidate["auto_match_confidence"] = "low"
    return candidates


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
    if "resolved_matched_authors" in candidate:
        resolved = candidate_resolved_authors(candidate)
        return resolved
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
    ambiguous_authors: set[str] = set()
    high_risk_authors: set[str] = set()
    resolved_only_available = any(
        isinstance(candidate.get("resolved_matched_authors"), list)
        for candidate in candidates
    )

    for candidate in candidates:
        candidate_id = (candidate.get("candidate_id") or "").strip()
        is_high_risk = bool(
            candidate.get("homonym_risk")
            or "name_only_match" in (candidate.get("risk_flags") or [])
        )
        raw_authors = []
        seen_raw: set[str] = set()
        for item in candidate.get("evidence", []) or []:
            matched_author = (item.get("matched_author") or "").strip()
            normalized_raw = normalize_name(matched_author)
            if not normalized_raw or normalized_raw in seen_raw:
                continue
            seen_raw.add(normalized_raw)
            raw_authors.append(matched_author)
        counted_authors = (
            candidate_resolved_authors(candidate)
            if resolved_only_available
            else candidate_matched_authors(candidate)
        )
        for author_name in counted_authors:
            normalized = normalize_name(author_name)
            if not normalized:
                continue
            author_display.setdefault(normalized, author_name)
        for author_name in raw_authors:
            normalized = normalize_name(author_name)
            if not normalized:
                continue
            author_candidate_ids.setdefault(normalized, set()).add(candidate_id or normalized)
            if "ambiguous_name_collision" in (candidate.get("auto_match_reasons") or []):
                ambiguous_authors.add(normalized)
            if is_high_risk:
                high_risk_authors.add(normalized)

    ambiguous_author_count = sum(
        1 for ids in author_candidate_ids.values() if len(ids) > 1
    )
    ambiguous_author_count = max(ambiguous_author_count, len(ambiguous_authors))
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
        openalex_author_ids = {
            normalize_external_id(value)
            for value in entry.get("openalex_author_ids", [])
            if value
        }
        orcid_ids = {
            normalize_external_id(value)
            for value in entry.get("orcid_ids", [])
            if value
        }
        dblp_author_ids = {
            normalize_external_id(value)
            for value in entry.get("dblp_author_ids", [])
            if value
        }
        known_institutions = {
            normalize_affiliation(value)
            for value in entry.get("known_institutions", [])
            if value
        }
        for paper in papers:
            paper_id = paper.get("id")
            title = paper.get("title", "")
            affiliations = extract_affiliation_candidates(paper)
            matched_affiliations = [
                token
                for token in entry.get("matched_affiliations", [])
                if token and any(token in affiliation for affiliation in affiliations)
            ]
            for author in iter_author_details(paper):
                author_name = (author.get("name") or "").strip()
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
                normalized_author_id = normalize_external_id(
                    str(author.get("author_id") or author.get("source_url") or "")
                )
                matched_identity_sources = []
                if normalized_author_id:
                    if normalized_author_id in openalex_author_ids:
                        matched_identity_sources.append("openalex_author_id")
                    if normalized_author_id in orcid_ids:
                        matched_identity_sources.append("orcid_id")
                    if normalized_author_id in dblp_author_ids:
                        matched_identity_sources.append("dblp_author_id")
                author_institutions = [
                    normalize_affiliation(value)
                    for value in (author.get("institutions") or [])
                    if isinstance(value, str) and value.strip()
                ]
                matched_known_institutions = [
                    value
                    for value in known_institutions
                    if value and any(value == institution for institution in author_institutions)
                ]
                if not matched_affiliations and not matched_known_institutions and not matched_identity_sources:
                    risk_flags.add("name_only_match")
                match_evidence.append(
                    {
                        "paper_id": paper_id,
                        "paper_title": title,
                        "matched_author": author_name,
                        "matched_author_id": normalized_author_id,
                        "matched_author_source_url": author.get("source_url") or "",
                        "match_type": (
                            "exact_name"
                            if normalized_author == normalize_name(entry.get("name", ""))
                            else "alias"
                            if normalized_author in alias_exact_names
                            else "name_variant"
                        ),
                        "matched_affiliations": matched_affiliations,
                        "matched_known_institutions": matched_known_institutions,
                        "matched_identity_sources": matched_identity_sources,
                        "author_institutions": [value for value in (author.get("institutions") or []) if isinstance(value, str)],
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
    resolved = sorted(candidates.values(), key=lambda item: (item.get("tag_label", ""), item.get("name", "")))
    return apply_auto_resolution(resolved)
