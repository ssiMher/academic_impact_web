from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"
DEFAULT_SOURCE_DIR = ROOT / "data" / "reference" / "source_lists"
ACM_FELLOWS_URL = "https://awards.acm.org/fellows/award-recipients"
IEEE_CS_FELLOW_URLS = {
    "2026": "https://www.computer.org/press-room/2026-class-fellows",
    "2025": "https://www.computer.org/press-room/2025-class-fellows",
    "2024": "https://www.computer.org/press-room/2024-fellows-announced",
    "2023": "https://www.computer.org/press-room/2022-news/ieee-computer-society-announces-2023-class-of-fellows",
}

SUPPORTED_TAG_TYPES = {
    "acm_fellow",
    "ieee_fellow",
    "cas_academician",
    "cae_academician",
    "top_school",
}

LIST_FIELDS = {"aliases", "source_links", "matched_affiliations"}


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").strip().lower())


def split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [
        item.strip()
        for item in re.split(r"[;|]", str(value))
        if item.strip()
    ]


def unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def normalize_entry(item: dict[str, Any], *, default_tag_type: str = "") -> dict[str, Any] | None:
    name = str(item.get("name") or item.get("Name") or "").strip()
    tag_type = str(item.get("tag_type") or item.get("tag") or default_tag_type or "").strip()
    if not name or tag_type not in SUPPORTED_TAG_TYPES:
        return None
    entry = {
        "name": name,
        "tag_type": tag_type,
        "aliases": unique(split_list(item.get("aliases"))),
        "source_links": unique(split_list(item.get("source_links"))),
        "matched_affiliations": unique(split_list(item.get("matched_affiliations"))),
        "note": str(item.get("note") or "").strip(),
    }
    return entry


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_comment": "组内可维护的人物标签来源。每项至少包含 name、tag_type、source_links。", "items": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"items": payload}
    if not isinstance(payload, dict):
        return {"items": []}
    payload.setdefault("items", [])
    return payload


def load_entries_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        return []
    return [
        normalized
        for item in payload
        if isinstance(item, dict)
        for normalized in [normalize_entry(item)]
        if normalized
    ]


def load_entries_from_csv(path: Path) -> list[dict[str, Any]]:
    entries = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = normalize_entry(row)
            if normalized:
                entries.append(normalized)
    return entries


def build_acm_entry(name: str, year: str = "", source_url: str = ACM_FELLOWS_URL) -> dict[str, Any] | None:
    name = (name or "").strip()
    if not name or normalize_name(name) in {"name", "award", "year", "region", "dl"}:
        return None
    note = "ACM Fellow"
    if year:
        note += f", elected {year}"
    return {
        "name": name,
        "tag_type": "acm_fellow",
        "aliases": [],
        "source_links": [source_url],
        "matched_affiliations": [],
        "note": note,
    }


def build_ieee_cs_entry(
    name: str,
    year: str = "",
    citation: str = "",
    source_url: str = "",
) -> dict[str, Any] | None:
    name = (name or "").strip()
    if not name or normalize_name(name) in {"name", "award", "year", "region", "dl"}:
        return None
    if normalize_name(name).startswith("ieeecomputersociety"):
        return None
    note = "IEEE Computer Society Fellow"
    if year:
        note += f" class {year}"
    citation = re.sub(r"\s+", " ", (citation or "").strip(" .;"))
    if citation:
        note += f"; citation: {citation}"
    return {
        "name": name,
        "tag_type": "ieee_fellow",
        "aliases": [],
        "source_links": [source_url] if source_url else [],
        "matched_affiliations": [],
        "note": note,
    }


def parse_acm_copied_table_text(content: str, source_url: str = ACM_FELLOWS_URL) -> list[dict[str, Any]]:
    entries = []
    seen = set()
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line in {"Name", "Award", "Year", "Region", "DL"}:
            continue

        name = ""
        year = ""
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
            if len(cells) >= 3 and cells[1] == "ACM Fellows" and re.fullmatch(r"\d{4}", cells[2] or ""):
                name = cells[0]
                year = cells[2]
        else:
            match = re.match(r"^(?P<name>.+?)\s+ACM Fellows\s+(?P<year>\d{4})(?:\s+.*)?$", line)
            if match:
                name = match.group("name")
                year = match.group("year")
        entry = build_acm_entry(name, year, source_url=source_url)
        if not entry:
            continue
        key = normalize_name(entry["name"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def collect_visible_text(content: str) -> str:
    content = str(content or "")
    if "<" not in content or ">" not in content:
        return content
    parser = TextCollector()
    parser.feed(content)
    return "\n".join(parser.parts)


def infer_ieee_cs_year(text: str, source_url: str = "") -> str:
    for value in [source_url, text]:
        match = re.search(r"\b(20\d{2})\b", value or "")
        if match:
            return match.group(1)
    return ""


def infer_ieee_cs_source_url(year: str = "", fallback: str = "") -> str:
    return fallback or IEEE_CS_FELLOW_URLS.get(str(year or ""), "")


def parse_ieee_cs_fellows_text(content: str, source_url: str = "") -> list[dict[str, Any]]:
    text = collect_visible_text(content)
    year = infer_ieee_cs_year(text, source_url=source_url)
    source_url = infer_ieee_cs_source_url(year, source_url)
    entries = []
    seen = set()
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line:
            continue
        line = re.sub(r"^[*•]\s+", "", line)
        match = re.match(
            r"^(?P<name>.+?)(?:\s+[–—-]\s+|\s+)(?P<citation>for\s+.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            match = re.match(
                r"^(?P<name>.+?)\s+[–—-]\s+(?P<citation>\(?Fellow citation under review.+)$",
                line,
                flags=re.IGNORECASE,
            )
        if not match:
            continue

        name = match.group("name").strip(" -*•")
        citation = match.group("citation").strip()
        if len(name) > 100 or re.search(r"\b(visit|view|include|includes|recommended|elevated)\b", name, re.I):
            continue
        entry = build_ieee_cs_entry(name, year, citation=citation, source_url=source_url)
        if not entry:
            continue
        key = normalize_name(entry["name"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def load_entries_from_text(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8-sig")
    if "ACM Fellows" in content:
        return parse_acm_copied_table_text(content)
    if "IEEE Computer Society" in content and "Fellow" in content:
        source_url = infer_ieee_cs_source_url(infer_ieee_cs_year(path.name))
        return parse_ieee_cs_fellows_text(content, source_url=source_url)
    return []


def load_source_entries(source_dir: Path) -> list[dict[str, Any]]:
    if not source_dir.exists():
        return []
    entries = []
    for path in sorted(source_dir.iterdir()):
        if path.name.startswith(".") or path.name.upper() == "README.MD":
            continue
        if path.suffix.lower() == ".json":
            entries.extend(load_entries_from_json(path))
        elif path.suffix.lower() == ".csv":
            entries.extend(load_entries_from_csv(path))
        elif path.suffix.lower() in {".txt", ".tsv"}:
            entries.extend(load_entries_from_text(path))
    return entries


class TextCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str):
        text = html.unescape(data or "").strip()
        if text:
            self.parts.append(re.sub(r"\s+", " ", text))


def parse_acm_fellows_html(content: str, source_url: str = ACM_FELLOWS_URL) -> list[dict[str, Any]]:
    parser = TextCollector()
    parser.feed(content)
    parts = parser.parts
    entries = []
    seen = set()
    for index, value in enumerate(parts):
        if value != "ACM Fellows" or index == 0:
            continue
        previous = parts[index - 1].strip()
        next_value = parts[index + 1].strip() if index + 1 < len(parts) else ""
        if not re.fullmatch(r"\d{4}", next_value):
            continue
        if previous.lower().startswith("acm ") or previous.lower().startswith("choose "):
            continue
        key = normalize_name(previous)
        if not key or key in seen:
            continue
        seen.add(key)
        entry = build_acm_entry(previous, next_value, source_url=source_url)
        if entry:
            entries.append(entry)
    return entries


def fetch_acm_fellows(url: str = ACM_FELLOWS_URL) -> tuple[list[dict[str, Any]], str]:
    response = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "academic-impact-web/1.0 (+https://github.com/ssiMher/academic_impact_web)"},
    )
    if response.status_code != 200:
        return [], f"ACM Fellows fetch failed: HTTP {response.status_code}"
    entries = parse_acm_fellows_html(response.text, source_url=url)
    if not entries:
        return [], "ACM Fellows fetch returned no parseable entries"
    return entries, ""


def fetch_ieee_cs_fellows(urls: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    urls = urls or list(IEEE_CS_FELLOW_URLS.values())
    entries = []
    warnings = []
    for url in urls:
        response = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "academic-impact-web/1.0 (+https://github.com/ssiMher/academic_impact_web)"},
        )
        if response.status_code != 200:
            warnings.append(f"IEEE CS Fellows fetch failed: {url} -> HTTP {response.status_code}")
            continue
        parsed = parse_ieee_cs_fellows_text(response.text, source_url=url)
        if not parsed:
            warnings.append(f"IEEE CS Fellows fetch returned no parseable entries: {url}")
            continue
        entries.extend(parsed)
    return entries, warnings


def merge_entries(existing_items: list[dict[str, Any]], new_entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    added = 0
    updated = 0

    for item in existing_items:
        if not isinstance(item, dict):
            continue
        normalized = normalize_entry(item)
        if not normalized:
            continue
        key = (normalized["tag_type"], normalize_name(normalized["name"]))
        original = dict(item)
        for field in LIST_FIELDS:
            original[field] = unique(split_list(original.get(field)) + normalized[field])
        original["name"] = normalized["name"]
        original["tag_type"] = normalized["tag_type"]
        original["note"] = str(original.get("note") or normalized.get("note") or "").strip()
        merged[key] = original

    for entry in new_entries:
        key = (entry["tag_type"], normalize_name(entry["name"]))
        if key not in merged:
            merged[key] = dict(entry)
            added += 1
            continue
        target = merged[key]
        before = json.dumps(target, sort_keys=True, ensure_ascii=False)
        for field in LIST_FIELDS:
            target[field] = unique(split_list(target.get(field)) + entry.get(field, []))
        if entry.get("note") and entry["note"] not in str(target.get("note", "")):
            target["note"] = "；".join([part for part in [str(target.get("note") or "").strip(), entry["note"]] if part])
        after = json.dumps(target, sort_keys=True, ensure_ascii=False)
        if after != before:
            updated += 1

    items = sorted(merged.values(), key=lambda item: (item.get("tag_type", ""), item.get("name", "")))
    return items, {"added": added, "updated": updated, "total": len(items)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh the local person tag registry from curated source lists.")
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--fetch-acm", action="store_true", help="尝试从 ACM 官方 Fellows 页面抓取 acm_fellow 名单。")
    parser.add_argument("--acm-url", default=ACM_FELLOWS_URL)
    parser.add_argument(
        "--fetch-ieee-cs",
        action="store_true",
        help="尝试从 IEEE Computer Society 官方 Fellow class 页面抓取 ieee_fellow 名单。",
    )
    parser.add_argument("--ieee-cs-url", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry_path = Path(args.registry_path).expanduser()
    source_dir = Path(args.source_dir).expanduser()

    registry = load_registry(registry_path)
    source_entries = load_source_entries(source_dir)
    fetch_warnings = []
    if args.fetch_acm:
        acm_entries, warning = fetch_acm_fellows(args.acm_url)
        source_entries.extend(acm_entries)
        if warning:
            fetch_warnings.append(warning)
    if args.fetch_ieee_cs:
        ieee_entries, warnings = fetch_ieee_cs_fellows(args.ieee_cs_url or None)
        source_entries.extend(ieee_entries)
        fetch_warnings.extend(warnings)

    merged_items, stats = merge_entries(registry.get("items", []), source_entries)
    registry["items"] = merged_items
    registry["generated_by"] = "scripts/refresh_person_tag_registry.py"

    if not args.dry_run:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "ok": True,
        "registry_path": str(registry_path),
        "source_dir": str(source_dir),
        "source_entry_count": len(source_entries),
        "dry_run": bool(args.dry_run),
        "stats": stats,
        "warnings": fetch_warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
