from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.enrich_person_tag_registry_openalex import normalize_external_id


OPENALEX_BASE_URL = "https://api.openalex.org/authors"
DEFAULT_OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_orcid(value: str) -> str:
    text = normalize_external_id(value)
    if text.startswith("orcid:"):
        return text
    if len(text) == 19 and text.count("-") == 3:
        return f"orcid:{text}"
    return text


def split_semicolon(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_name(text: str) -> str:
    value = "".join(char for char in str(text or "").lower().strip() if char.isalnum())
    return value


def extract_known_institutions(author: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for institution in author.get("last_known_institutions") or []:
        if isinstance(institution, dict):
            display_name = str(institution.get("display_name") or institution.get("name") or "").strip()
            if display_name:
                values.append(display_name)
    for affiliation in author.get("affiliations") or []:
        if not isinstance(affiliation, dict):
            continue
        institution = affiliation.get("institution") or {}
        if isinstance(institution, dict):
            display_name = str(institution.get("display_name") or institution.get("name") or "").strip()
            if display_name:
                values.append(display_name)
    return unique(values)


def fetch_openalex_author_by_orcid(
    orcid: str,
    *,
    api_key: str = "",
    mailto: str = "",
    timeout: int = 30,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    normalized = normalize_external_id(orcid)
    if normalized and not normalized.startswith("orcid:") and len(normalized) == 19 and normalized.count("-") == 3:
        normalized = f"orcid:{normalized}"
    if not normalized:
        return None
    params: dict[str, str] = {}
    if api_key:
        params["api_key"] = str(api_key).strip()
    if mailto:
        params["mailto"] = mailto
    url = f"{OPENALEX_BASE_URL}/{urllib.parse.quote(normalized, safe=':')}"
    attempts = max(0, int(max_retries)) + 1
    for attempt in range(attempts):
        response = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "academic-impact-web/1.0 (+fellow-orcid-resolution)"},
        )
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_response = getattr(exc, "response", None) or response
            if getattr(error_response, "status_code", None) == 429 and attempt < attempts - 1:
                retry_after = str((getattr(error_response, "headers", {}) or {}).get("Retry-After") or "").strip()
                try:
                    sleep_seconds = max(float(retry_after), 1.0) if retry_after else 2.0 * (attempt + 1)
                except ValueError:
                    sleep_seconds = 2.0 * (attempt + 1)
                time.sleep(sleep_seconds)
                continue
            raise
        return response.json()
    return None


def score_candidate(row: dict[str, str], author: dict[str, Any] | None) -> tuple[int, list[str]]:
    if not author:
        return 0, ["openalex_not_found"]
    score = 0
    reasons: list[str] = []
    row_name = normalize_name(row.get("name"))
    display_name = normalize_name(author.get("display_name") or "")
    alternative_names = {normalize_name(value) for value in author.get("display_name_alternatives") or [] if value}
    if row_name and row_name == display_name:
        score += 4
        reasons.append("display_name_exact")
    elif row_name and row_name in alternative_names:
        score += 3
        reasons.append("alt_name_match")

    known_institutions = {value.lower() for value in split_semicolon(row.get("known_institutions"))}
    openalex_institutions = extract_known_institutions(author)
    overlaps = sorted(
        {
            institution
            for institution in openalex_institutions
            if institution.lower() in known_institutions
        }
    )
    if overlaps:
        score += 4
        reasons.append("institution_match:" + "|".join(overlaps[:3]))

    if row.get("bridge_status") == "unique_orcid":
        score += 2
        reasons.append("unique_orcid_bridge")
    if row.get("dblp_author_ids"):
        score += 1
        reasons.append("has_dblp_id")
    return score, reasons


def accepted_seed_row(resolved_row: dict[str, str]) -> dict[str, str]:
    institutions = resolved_row.get("selected_institutions", "")
    source_links = split_semicolon(resolved_row.get("source_links"))
    selected_id = resolved_row.get("selected_openalex_id", "")
    if selected_id:
        source_links.append(selected_id)
    return {
        "name": resolved_row.get("name", ""),
        "tag_type": resolved_row.get("tag_type", ""),
        "aliases": "",
        "source_links": ";".join(unique(source_links)),
        "matched_affiliations": "",
        "openalex_author_ids": selected_id,
        "orcid_ids": resolved_row.get("selected_orcid", ""),
        "dblp_author_ids": resolved_row.get("dblp_author_ids", ""),
        "known_institutions": institutions,
        "note": resolved_row.get("seed_note", ""),
    }


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve Fellow OpenAlex IDs from ORCID bridge candidates.")
    parser.add_argument("--bridge-csv", required=True)
    parser.add_argument("--resolved-csv", required=True)
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--seed-csv", default="", help="Optional standard source-list CSV containing accepted IDs.")
    parser.add_argument("--api-key", default=DEFAULT_OPENALEX_API_KEY)
    parser.add_argument("--mailto", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bridge_rows = load_csv(Path(args.bridge_csv))
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in bridge_rows:
        grouped[(row.get("tag_type", ""), row.get("name", ""))].append(row)

    openalex_cache: dict[str, dict[str, Any] | None] = {}
    resolved_rows: list[dict[str, str]] = []
    seed_rows: list[dict[str, str]] = []

    for (tag_type, name), rows in sorted(grouped.items()):
        scored_candidates: list[dict[str, Any]] = []
        source_links = unique([link for row in rows for link in split_semicolon(row.get("source_links"))])
        dblp_author_ids = unique([dblp_id for row in rows for dblp_id in split_semicolon(row.get("dblp_author_ids"))])
        candidate_orcids = unique([normalize_orcid(row.get("orcid", "")) for row in rows if row.get("orcid")])
        for row in rows:
            orcid = normalize_orcid(row.get("orcid", ""))
            if orcid not in openalex_cache:
                openalex_cache[orcid] = fetch_openalex_author_by_orcid(
                    orcid,
                    api_key=args.api_key,
                    mailto=args.mailto,
                )
            author = openalex_cache[orcid]
            score, reasons = score_candidate(row, author)
            scored_candidates.append(
                {
                    "row": row,
                    "author": author,
                    "score": score,
                    "reasons": reasons,
                }
            )

        scored_candidates.sort(
            key=lambda item: (
                -int(item["score"]),
                item["author"].get("id", "") if item["author"] else "",
            )
        )
        best = scored_candidates[0] if scored_candidates else None
        runner_up = scored_candidates[1] if len(scored_candidates) > 1 else None
        decision = "unresolved"
        selected_openalex_id = ""
        selected_display_name = ""
        selected_orcid = ""
        selected_institutions = ""
        reason = "no_viable_orcid_bridge"
        confidence = "0"

        if best and best["author"]:
            institutions = extract_known_institutions(best["author"])
            margin = best["score"] - int(runner_up["score"]) if runner_up else best["score"]
            can_accept = False
            if len(candidate_orcids) == 1 and best["score"] >= 6:
                can_accept = True
            elif best["score"] >= 8 and margin >= 3 and any(part.startswith("institution_match") for part in best["reasons"]):
                can_accept = True
            if can_accept:
                decision = "accepted"
                selected_openalex_id = normalize_external_id(str(best["author"].get("id") or ""))
                selected_display_name = str(best["author"].get("display_name") or "").strip()
                selected_orcid = normalize_orcid(
                    str((best["author"].get("ids") or {}).get("orcid") or best["author"].get("orcid") or best["row"].get("orcid") or "")
                )
                selected_institutions = ";".join(institutions)
                reason = ";".join(best["reasons"])
                confidence = str(min(100, 60 + best["score"] * 5))

        resolved_row = {
            "name": name,
            "tag_type": tag_type,
            "decision": decision,
            "selected_openalex_id": selected_openalex_id,
            "selected_display_name": selected_display_name,
            "selected_orcid": selected_orcid,
            "selected_institutions": selected_institutions,
            "confidence_percent": confidence,
            "reason": reason,
            "source_links": ";".join(source_links),
            "dblp_author_ids": ";".join(dblp_author_ids),
            "candidate_orcids": ";".join(candidate_orcids),
            "candidate_count": str(len(candidate_orcids)),
            "seed_note": f"{tag_type} resolved from DBLP/ORCID bridge",
        }
        resolved_rows.append(resolved_row)
        if decision == "accepted" and args.seed_csv:
            seed_rows.append(accepted_seed_row(resolved_row))

    write_rows(Path(args.resolved_csv), resolved_rows)
    summary = Counter(row["decision"] for row in resolved_rows)
    summary_rows = [{"category": key, "count": value} for key, value in sorted(summary.items())]
    summary_rows.insert(0, {"category": "name_groups", "count": len(resolved_rows)})
    write_rows(Path(args.summary_csv), summary_rows)
    if args.seed_csv:
        write_rows(Path(args.seed_csv), seed_rows)

    print(
        json.dumps(
            {
                "ok": True,
                "name_groups": len(resolved_rows),
                "accepted": summary.get("accepted", 0),
                "unresolved": summary.get("unresolved", 0),
                "resolved_csv": str(Path(args.resolved_csv)),
                "seed_csv": str(Path(args.seed_csv)) if args.seed_csv else "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
