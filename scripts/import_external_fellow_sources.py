from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "reference" / "source_lists"
STANDARD_FIELDNAMES = [
    "name",
    "tag_type",
    "aliases",
    "source_links",
    "matched_affiliations",
    "openalex_author_ids",
    "orcid_ids",
    "dblp_author_ids",
    "known_institutions",
    "note",
]
SUPPORTED_DATASETS = {"academic-awards-acm", "academic-awards-ieee"}


def normalize_name_with_alias(name: str) -> tuple[str, list[str]]:
    value = " ".join(str(name or "").strip().split())
    if not value or "," not in value:
        return value, []
    family, given = [part.strip() for part in value.split(",", 1)]
    if not family or not given:
        return value, []
    return f"{given} {family}", [value]


def load_json_payload(path_or_url: str) -> Any:
    source = str(path_or_url or "").strip()
    if source.startswith(("http://", "https://")):
        response = requests.get(
            source,
            timeout=30,
            headers={"User-Agent": "academic-impact-web/1.0 (+external-fellow-import)"},
        )
        response.raise_for_status()
        return response.json()
    return json.loads(Path(source).read_text(encoding="utf-8"))


def standard_row(
    *,
    name: str,
    tag_type: str,
    aliases: list[str],
    source_url: str,
    note: str,
) -> dict[str, str]:
    return {
        "name": name,
        "tag_type": tag_type,
        "aliases": ";".join(aliases),
        "source_links": source_url,
        "matched_affiliations": "",
        "openalex_author_ids": "",
        "orcid_ids": "",
        "dblp_author_ids": "",
        "known_institutions": "",
        "note": note,
    }


def import_academic_awards_acm(records: list[dict[str, Any]], source_url: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        display_name, aliases = normalize_name_with_alias(str(record.get("name") or ""))
        if not display_name:
            continue
        key = display_name.lower()
        if key in seen:
            continue
        seen.add(key)
        year = str(record.get("year") or "").strip()
        note = "ACM Fellow; source: academic-awards GitHub mirror"
        if year:
            note = f"ACM Fellow, elected {year}; source: academic-awards GitHub mirror"
        rows.append(
            standard_row(
                name=display_name,
                tag_type="acm_fellow",
                aliases=aliases,
                source_url=source_url,
                note=note,
            )
        )
    return rows


def import_academic_awards_ieee(records: list[dict[str, Any]], source_url: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        display_name, aliases = normalize_name_with_alias(str(record.get("name") or ""))
        if not display_name:
            continue
        key = display_name.lower()
        if key in seen:
            continue
        seen.add(key)
        parts = ["IEEE Fellow"]
        year = str(record.get("year") or "").strip()
        category = str(record.get("category") or "").strip()
        region = str(record.get("region") or "").strip()
        citation = " ".join(str(record.get("citation") or "").strip().split())
        if year:
            parts.append(f"class {year}")
        if category:
            parts.append(f"category: {category}")
        if region:
            parts.append(f"region: {region}")
        if citation:
            parts.append(f"citation: {citation}")
        parts.append("source: academic-awards GitHub mirror")
        note = "; ".join(parts)
        rows.append(
            standard_row(
                name=display_name,
                tag_type="ieee_fellow",
                aliases=aliases,
                source_url=source_url,
                note=note,
            )
        )
    return rows


def dataset_to_rows(dataset: str, payload: Any, source_url: str) -> list[dict[str, str]]:
    records = payload if isinstance(payload, list) else []
    if dataset == "academic-awards-acm":
        return import_academic_awards_acm(records, source_url)
    if dataset == "academic-awards-ieee":
        return import_academic_awards_ieee(records, source_url)
    raise ValueError(f"unsupported dataset: {dataset}")


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STANDARD_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert external ACM/IEEE Fellow datasets into source-list CSV files.")
    parser.add_argument("--dataset", required=True, choices=sorted(SUPPORTED_DATASETS))
    parser.add_argument("--input", required=True, help="Local JSON path or URL.")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--source-url", default="", help="Canonical source URL written into source_links.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = load_json_payload(args.input)
    source_url = str(args.source_url or args.input).strip()
    rows = dataset_to_rows(args.dataset, payload, source_url)
    write_rows(Path(args.output_csv), rows)
    print(
        json.dumps(
            {
                "ok": True,
                "dataset": args.dataset,
                "input": args.input,
                "output_csv": str(Path(args.output_csv)),
                "row_count": len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
