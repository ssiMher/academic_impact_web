from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"
OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
SUPPORTED_TAG_TYPES = {
    "acm_fellow",
    "ieee_fellow",
    "aaai_fellow",
    "cas_academician",
    "cae_academician",
    "godel_prize",
}
LIST_FIELDS = {
    "aliases",
    "source_links",
    "matched_affiliations",
    "openalex_author_ids",
    "orcid_ids",
    "dblp_author_ids",
    "known_institutions",
}


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").strip().lower())


def normalize_external_id(value: str) -> str:
    text = (value or "").strip().lower().rstrip("/")
    if not text:
        return ""
    if text.startswith("https://orcid.org/"):
        return text.replace("https://orcid.org/", "orcid:")
    if text.startswith("http://orcid.org/"):
        return text.replace("http://orcid.org/", "orcid:")
    return text


def split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in re.split(r"[;|]", str(value)) if item.strip()]


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


def normalize_institution(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def has_external_identity(item: dict[str, Any]) -> bool:
    return bool(split_list(item.get("openalex_author_ids")) or split_list(item.get("orcid_ids")))


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"items": payload}
    if not isinstance(payload, dict):
        return {"items": []}
    payload.setdefault("items", [])
    return payload


def write_registry(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_openalex_authors(
    name: str,
    *,
    per_page: int = 10,
    mailto: str = "",
    timeout: int = 30,
) -> list[dict[str, Any]]:
    params = {
        "search": name,
        "per-page": per_page,
    }
    if mailto:
        params["mailto"] = mailto
    response = requests.get(
        OPENALEX_AUTHORS_URL,
        params=params,
        timeout=timeout,
        headers={"User-Agent": "academic-impact-web/1.0 (+registry-openalex-enrichment)"},
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("results", []) or []


def registry_names(item: dict[str, Any]) -> list[str]:
    return [str(item.get("name") or "").strip(), *split_list(item.get("aliases"))]


def openalex_names(author: dict[str, Any]) -> list[str]:
    names = [str(author.get("display_name") or "").strip()]
    names.extend(str(value).strip() for value in (author.get("display_name_alternatives") or []) if str(value).strip())
    return unique(names)


def score_openalex_candidate(item: dict[str, Any], author: dict[str, Any]) -> tuple[int, list[str]]:
    registry_norms = {normalize_name(value) for value in registry_names(item) if value}
    author_norms = {normalize_name(value) for value in openalex_names(author) if value}
    score = 0
    reasons: list[str] = []

    direct_name = normalize_name(item.get("name") or "")
    display_norm = normalize_name(author.get("display_name") or "")
    if direct_name and direct_name == display_norm:
        score += 6
        reasons.append("display_name_exact")
    if registry_norms & author_norms:
        score += 4
        reasons.append("alt_name_match")

    orcid_value = normalize_external_id(
        str((author.get("ids") or {}).get("orcid") or author.get("orcid") or "")
    )
    if orcid_value:
        score += 1
        reasons.append("has_orcid")

    institutions = extract_known_institutions(author)
    if institutions:
        score += 1
        reasons.append("has_institutions")

    return score, reasons


def extract_known_institutions(author: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for institution in author.get("last_known_institutions") or []:
        if isinstance(institution, dict):
            display_name = normalize_institution(
                institution.get("display_name") or institution.get("name") or ""
            )
            if display_name:
                values.append(display_name)
    for affiliation in author.get("affiliations") or []:
        if not isinstance(affiliation, dict):
            continue
        institution = affiliation.get("institution") or {}
        if isinstance(institution, dict):
            display_name = normalize_institution(
                institution.get("display_name") or institution.get("name") or ""
            )
            if display_name:
                values.append(display_name)
    return unique(values)


def select_best_openalex_match(item: dict[str, Any], results: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for author in results:
        score, reasons = score_openalex_candidate(item, author)
        if score <= 0:
            continue
        scored.append(
            {
                "author": author,
                "score": score,
                "reasons": reasons,
            }
        )
    scored.sort(
        key=lambda row: (
            -row["score"],
            -(1 if normalize_external_id(str((row["author"].get("ids") or {}).get("orcid") or row["author"].get("orcid") or "")) else 0),
            row["author"].get("id") or "",
        )
    )

    if not scored:
        return None, {"decision": "skipped", "reason": "no_scored_candidates"}

    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    margin_ok = runner_up is None or best["score"] >= runner_up["score"] + 3
    exact_match = "display_name_exact" in best["reasons"]
    has_orcid = bool(
        normalize_external_id(str((best["author"].get("ids") or {}).get("orcid") or best["author"].get("orcid") or ""))
    )
    has_institutions = bool(extract_known_institutions(best["author"]))
    accepted = (
        exact_match
        and margin_ok
        and (has_orcid or has_institutions or runner_up is None)
        and (best["score"] >= 10 or (best["score"] >= 8 and has_orcid))
    )
    if not accepted:
        return None, {
            "decision": "skipped",
            "reason": "ambiguous_or_low_confidence",
            "top_score": best["score"],
            "runner_up_score": runner_up["score"] if runner_up else None,
            "top_reasons": best["reasons"],
        }
    return best["author"], {
        "decision": "matched",
        "score": best["score"],
        "reasons": best["reasons"],
        "runner_up_score": runner_up["score"] if runner_up else None,
    }


def merge_list_field(item: dict[str, Any], field: str, values: list[str]) -> None:
    current = split_list(item.get(field))
    item[field] = unique(current + values)


def enrich_item_from_author(item: dict[str, Any], author: dict[str, Any]) -> None:
    author_id = normalize_external_id(str(author.get("id") or ""))
    if author_id:
        merge_list_field(item, "openalex_author_ids", [author_id])

    orcid_value = normalize_external_id(
        str((author.get("ids") or {}).get("orcid") or author.get("orcid") or "")
    )
    if orcid_value:
        merge_list_field(item, "orcid_ids", [orcid_value])

    institutions = extract_known_institutions(author)
    if institutions:
        merge_list_field(item, "known_institutions", institutions)

    source_links = split_list(item.get("source_links"))
    openalex_url = str(author.get("id") or "").strip()
    if openalex_url:
        item["source_links"] = unique(source_links + [openalex_url])


def load_target_names_from_review_zip(path: Path) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for member, field in [
            ("manual_review_top50.csv", "display_name"),
            ("missing_from_candidate_matching.csv", "raw_author_names"),
        ]:
            if member not in archive.namelist():
                continue
            with archive.open(member) as handle:
                text = handle.read().decode("utf-8-sig")
            reader = csv.DictReader(text.splitlines())
            for row in reader:
                raw_value = (row.get(field) or "").split("|")[0].strip()
                normalized = normalize_name(raw_value)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                names.append(raw_value)
    return names


def find_registry_targets(
    items: list[dict[str, Any]],
    *,
    target_names: list[str],
    tag_types: set[str] | None = None,
    missing_external_ids_only: bool = False,
) -> list[dict[str, Any]]:
    wanted = {normalize_name(name) for name in target_names if name}
    targets: list[dict[str, Any]] = []
    for item in items:
        tag_type = str(item.get("tag_type") or "")
        if tag_types and tag_type not in tag_types:
            continue
        if tag_type not in SUPPORTED_TAG_TYPES:
            continue
        if missing_external_ids_only and has_external_identity(item):
            continue
        if not wanted:
            if missing_external_ids_only:
                targets.append(item)
            continue
        names = {normalize_name(value) for value in registry_names(item) if value}
        if names & wanted:
            targets.append(item)
    return targets


def enrich_registry(
    *,
    registry_path: Path,
    target_names: list[str],
    tag_types: set[str] | None = None,
    missing_external_ids_only: bool = False,
    max_targets: int | None = None,
    per_page: int = 10,
    mailto: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = load_registry(registry_path)
    items = payload.get("items") or []
    targets = find_registry_targets(
        items,
        target_names=target_names,
        tag_types=tag_types,
        missing_external_ids_only=missing_external_ids_only,
    )
    if max_targets is not None:
        targets = targets[: max(0, int(max_targets))]
    updated = 0
    skipped = 0
    decisions: list[dict[str, Any]] = []

    for item in targets:
        query_name = str(item.get("name") or "").strip()
        results = fetch_openalex_authors(query_name, per_page=per_page, mailto=mailto)
        author, decision = select_best_openalex_match(item, results)
        decisions.append(
            {
                "name": query_name,
                "tag_type": item.get("tag_type") or "",
                **decision,
            }
        )
        if not author:
            skipped += 1
            continue
        before = json.dumps(item, sort_keys=True, ensure_ascii=False)
        enrich_item_from_author(item, author)
        after = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if after != before:
            updated += 1

    if not dry_run:
        write_registry(registry_path, payload)

    return {
        "target_count": len(targets),
        "updated": updated,
        "skipped": skipped,
        "decisions": decisions,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich person tag registry with OpenAlex IDs and institutions.")
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--review-zip", default="", help="包含 manual_review_top50.csv / missing_from_candidate_matching.csv 的 zip 包。")
    parser.add_argument("--name", action="append", default=[], help="直接指定要 enrichment 的作者名，可重复。")
    parser.add_argument(
        "--all-missing-external-ids",
        action="store_true",
        help="从 registry 中批量处理缺少 OpenAlex/ORCID 的条目，可配合 --tag-type 缩小范围。",
    )
    parser.add_argument("--tag-type", action="append", default=[], help="限制处理的 tag_type，可重复。")
    parser.add_argument("--limit", type=int, default=0, help="可选，只处理前 N 个目标，适合分批跑。")
    parser.add_argument("--per-page", type=int, default=10)
    parser.add_argument("--mailto", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path", default="", help="可选，写出 enrichment 决策 JSON。")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    target_names = list(args.name or [])
    if args.review_zip:
        target_names.extend(load_target_names_from_review_zip(Path(args.review_zip)))
    target_names = unique(target_names)
    if not target_names and not args.all_missing_external_ids:
        parser.error("请至少通过 --name、--review-zip，或 --all-missing-external-ids 提供目标范围。")

    report = enrich_registry(
        registry_path=Path(args.registry_path),
        target_names=target_names,
        tag_types=set(args.tag_type or []) or None,
        missing_external_ids_only=bool(args.all_missing_external_ids),
        max_targets=(max(0, int(args.limit or 0)) or None),
        per_page=max(1, int(args.per_page or 10)),
        mailto=str(args.mailto or "").strip(),
        dry_run=bool(args.dry_run),
    )
    if args.report_path:
        Path(args.report_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
