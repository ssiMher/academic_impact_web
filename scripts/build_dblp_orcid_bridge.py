from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills.academic_impact_analyzer.person_candidates import load_registry, normalize_external_id, normalized_name_variants


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"


def split_semicolon(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


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


def parse_list_cell(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in text.split(";") if part.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_alias_index(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        alias = str(row.get("alias") or "").strip()
        if not alias:
            continue
        key = next(iter(normalized_name_variants(alias)), "")
        if not key:
            continue
        index[key].append(row)
    return index


def build_orcid_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        normalized = normalize_orcid(str(row.get("orcid") or ""))
        if normalized:
            index[normalized] = row
    return index


def entry_variants(entry: dict[str, Any]) -> set[str]:
    variants: set[str] = set()
    variants.update(normalized_name_variants(entry.get("name", "")))
    for alias in entry.get("aliases", []) or []:
        variants.update(normalized_name_variants(alias))
    variants.discard("")
    return variants


def bridge_rows_for_entry(
    entry: dict[str, Any],
    *,
    alias_index: dict[str, list[dict[str, str]]],
    orcid_index: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    variants = entry_variants(entry)
    matched_alias_rows: list[dict[str, str]] = []
    for variant in sorted(variants):
        matched_alias_rows.extend(alias_index.get(variant, []))

    candidates: dict[str, dict[str, Any]] = {}
    for alias_row in matched_alias_rows:
        raw_orcids = parse_list_cell(alias_row.get("orcid"))
        matched_alias = str(alias_row.get("alias") or "").strip()
        for raw_orcid in raw_orcids:
            orcid = normalize_orcid(raw_orcid)
            if not orcid:
                continue
            candidate = candidates.setdefault(
                orcid,
                {
                    "matched_aliases": [],
                    "dblp_author_ids": [],
                    "dblp_aliases": [],
                    "acm_ids": [],
                    "scopus_ids": [],
                },
            )
            candidate["matched_aliases"].append(matched_alias)
            candidate["acm_ids"].extend(parse_list_cell(alias_row.get("acm_id")))
            candidate["scopus_ids"].extend(parse_list_cell(alias_row.get("scopus_id")))
            orcid_row = orcid_index.get(orcid, {})
            candidate["dblp_author_ids"].extend(parse_list_cell(orcid_row.get("dblp_key")))
            candidate["dblp_aliases"].extend(parse_list_cell(orcid_row.get("alias")))
            candidate["acm_ids"].extend(parse_list_cell(orcid_row.get("acm_id")))
            candidate["scopus_ids"].extend(parse_list_cell(orcid_row.get("scopus_id")))

    if not candidates:
        return []

    status = "unique_orcid" if len(candidates) == 1 else "multi_orcid"
    rows: list[dict[str, str]] = []
    for orcid, candidate in sorted(candidates.items()):
        rows.append(
            {
                "name": entry["name"],
                "tag_type": entry["tag_type"],
                "matched_alias": unique(candidate["matched_aliases"])[0] if candidate["matched_aliases"] else "",
                "matched_aliases": ";".join(unique(candidate["matched_aliases"])),
                "bridge_status": status,
                "orcid": orcid,
                "dblp_author_ids": ";".join(unique(candidate["dblp_author_ids"])),
                "dblp_aliases": ";".join(unique(candidate["dblp_aliases"])),
                "acm_ids": ";".join(unique(candidate["acm_ids"])),
                "scopus_ids": ";".join(unique(candidate["scopus_ids"])),
                "known_institutions": ";".join(unique(entry.get("known_institutions", []) or [])),
                "source_links": ";".join(unique(entry.get("source_links", []) or [])),
                "note": str(entry.get("note") or "").strip(),
                "existing_openalex_author_ids": ";".join(unique(entry.get("openalex_author_ids", []) or [])),
                "existing_orcid_ids": ";".join(unique(entry.get("orcid_ids", []) or [])),
                "existing_dblp_author_ids": ";".join(unique(entry.get("dblp_author_ids", []) or [])),
            }
        )
    return rows


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Join registry Fellow names with DBLP/ORCID bridge CSV files.")
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--tag-type", required=True, help="acm_fellow or ieee_fellow")
    parser.add_argument("--dblp-alias-csv", required=True, help="jfloff/dblp-orcids by_alias.csv")
    parser.add_argument("--dblp-orcid-csv", required=True, help="jfloff/dblp-orcids by_orcid.csv")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--all-entries", action="store_true", help="Include entries that already have external IDs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    entries = [
        entry
        for entry in load_registry(args.registry_path)
        if entry.get("tag_type") == args.tag_type
        and (args.all_entries or not (entry.get("openalex_author_ids") or entry.get("orcid_ids") or entry.get("dblp_author_ids")))
    ]
    alias_index = build_alias_index(load_csv(Path(args.dblp_alias_csv)))
    orcid_index = build_orcid_index(load_csv(Path(args.dblp_orcid_csv)))

    output_rows: list[dict[str, str]] = []
    names_with_matches = 0
    for entry in entries:
        rows = bridge_rows_for_entry(entry, alias_index=alias_index, orcid_index=orcid_index)
        if rows:
            names_with_matches += 1
            output_rows.extend(rows)

    write_rows(Path(args.output_csv), output_rows)
    summary = Counter(row["bridge_status"] for row in output_rows)
    summary_rows = [
        {"category": "entries_scanned", "count": len(entries)},
        {"category": "names_with_matches", "count": names_with_matches},
        {"category": "names_without_matches", "count": max(0, len(entries) - names_with_matches)},
        {"category": "candidate_rows", "count": len(output_rows)},
    ]
    summary_rows.extend({"category": key, "count": value} for key, value in sorted(summary.items()))
    write_rows(Path(args.summary_csv), summary_rows)

    print(
        json.dumps(
            {
                "ok": True,
                "tag_type": args.tag_type,
                "entries_scanned": len(entries),
                "names_with_matches": names_with_matches,
                "candidate_rows": len(output_rows),
                "output_csv": str(Path(args.output_csv)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
