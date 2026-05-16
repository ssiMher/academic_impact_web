from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "reference" / "person_tag_registry.json"
DEFAULT_REPORT_CSV_PATH = ROOT / "data" / "reference" / "openalex_enrichment_audit.csv"
DEFAULT_OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
MAX_OPENALEX_MATCH_SCORE = 12
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
    api_key: str = "",
    timeout: int = 30,
    max_retries: int = 3,
    base_backoff_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    params = {
        "search": name,
        "per-page": per_page,
    }
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = str(api_key).strip()
    attempts = max(0, int(max_retries)) + 1
    for attempt in range(attempts):
        response = requests.get(
            OPENALEX_AUTHORS_URL,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "academic-impact-web/1.0 (+registry-openalex-enrichment)"},
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_response = getattr(exc, "response", None) or response
            status_code = getattr(error_response, "status_code", None)
            if status_code == 429 and attempt < attempts - 1:
                retry_after = str((getattr(error_response, "headers", {}) or {}).get("Retry-After") or "").strip()
                try:
                    sleep_seconds = max(float(retry_after), 0.0) if retry_after else 0.0
                except ValueError:
                    sleep_seconds = 0.0
                if sleep_seconds <= 0:
                    sleep_seconds = max(float(base_backoff_seconds), 0.0) * (2 ** attempt)
                time.sleep(sleep_seconds)
                continue
            raise
        payload = response.json()
        return payload.get("results", []) or []
    return []


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


def score_percent(score: int | None) -> int:
    if not score or score <= 0:
        return 0
    return int(round((float(score) / float(MAX_OPENALEX_MATCH_SCORE)) * 100))


def confidence_percent(top_score: int | None, runner_up_score: int | None) -> int:
    top_percent = score_percent(top_score)
    if top_percent <= 0:
        return 0
    if runner_up_score is None:
        return top_percent
    margin = max(0, int(top_score or 0) - int(runner_up_score or 0))
    if margin <= 0:
        return 0
    margin_factor = min(1.0, float(margin) / 3.0)
    return int(round(top_percent * margin_factor))


def author_summary(author: dict[str, Any] | None) -> dict[str, str]:
    if not author:
        return {
            "openalex_id": "",
            "display_name": "",
            "orcid": "",
            "institutions": "",
        }
    return {
        "openalex_id": normalize_external_id(str(author.get("id") or "")),
        "display_name": str(author.get("display_name") or "").strip(),
        "orcid": normalize_external_id(
            str((author.get("ids") or {}).get("orcid") or author.get("orcid") or "")
        ),
        "institutions": ";".join(extract_known_institutions(author)),
    }


def rank_openalex_candidates(item: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for author in results:
        score, reasons = score_openalex_candidate(item, author)
        if score <= 0:
            continue
        summary = author_summary(author)
        ranked.append(
            {
                "author": author,
                "score": score,
                "score_percent": score_percent(score),
                "reasons": reasons,
                "summary": summary,
            }
        )
    ranked.sort(
        key=lambda row: (
            -row["score"],
            -(1 if summary_has_orcid(row["summary"]) else 0),
            row["summary"]["openalex_id"],
        )
    )
    return ranked


def summary_has_orcid(summary: dict[str, str]) -> bool:
    return bool(str(summary.get("orcid") or "").strip())


def write_decision_csv(path: Path, decisions: list[dict[str, Any]]) -> None:
    rows = []
    for decision in decisions:
        rows.append(
            {
                "name": decision.get("name") or "",
                "tag_type": decision.get("tag_type") or "",
                "decision": decision.get("decision") or "",
                "reason": decision.get("reason") or "",
                "confidence_percent": str(decision.get("confidence_percent") or 0),
                "score_percent": str(decision.get("score_percent") or 0),
                "candidate_count": str(decision.get("candidate_count") or 0),
                "top_score": str(decision.get("top_score") or 0),
                "top_score_percent": str(decision.get("top_score_percent") or 0),
                "top_openalex_id": decision.get("top_openalex_id") or "",
                "top_display_name": decision.get("top_display_name") or "",
                "top_orcid": decision.get("top_orcid") or "",
                "top_institutions": decision.get("top_institutions") or "",
                "top_reasons": ";".join(decision.get("top_reasons") or []),
                "runner_up_score": str(decision.get("runner_up_score") or 0),
                "runner_up_score_percent": str(decision.get("runner_up_score_percent") or 0),
                "runner_up_openalex_id": decision.get("runner_up_openalex_id") or "",
                "runner_up_display_name": decision.get("runner_up_display_name") or "",
                "runner_up_orcid": decision.get("runner_up_orcid") or "",
                "runner_up_institutions": decision.get("runner_up_institutions") or "",
                "runner_up_reasons": ";".join(decision.get("runner_up_reasons") or []),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [
            "name", "tag_type", "decision", "reason", "confidence_percent", "score_percent", "candidate_count",
            "top_score", "top_score_percent", "top_openalex_id", "top_display_name",
            "top_orcid", "top_institutions", "top_reasons", "runner_up_score",
            "runner_up_score_percent", "runner_up_openalex_id", "runner_up_display_name",
            "runner_up_orcid", "runner_up_institutions", "runner_up_reasons",
        ])
        writer.writeheader()
        writer.writerows(rows)


def write_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "name",
        "tag_type",
        "decision",
        "reason",
        "candidate_count",
        "rank",
        "score",
        "score_percent",
        "openalex_id",
        "display_name",
        "orcid",
        "institutions",
        "reasons",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def select_best_openalex_match(item: dict[str, Any], results: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    scored = rank_openalex_candidates(item, results)

    if not scored:
        return None, {
            "decision": "skipped",
            "reason": "no_scored_candidates",
            "candidate_count": 0,
            "confidence_percent": 0,
            "score_percent": 0,
            "top_score": 0,
            "top_score_percent": 0,
            "top_reasons": [],
            "runner_up_score": 0,
            "runner_up_score_percent": 0,
            "runner_up_reasons": [],
        }

    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    best_summary = best["summary"]
    runner_summary = runner_up["summary"] if runner_up else author_summary(None)
    margin_ok = runner_up is None or best["score"] >= runner_up["score"] + 3
    exact_match = "display_name_exact" in best["reasons"]
    has_orcid = summary_has_orcid(best_summary)
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
            "candidate_count": len(scored),
            "confidence_percent": confidence_percent(best["score"], runner_up["score"] if runner_up else None),
            "score_percent": score_percent(best["score"]),
            "top_score": best["score"],
            "top_score_percent": score_percent(best["score"]),
            "top_openalex_id": best_summary["openalex_id"],
            "top_display_name": best_summary["display_name"],
            "top_orcid": best_summary["orcid"],
            "top_institutions": best_summary["institutions"],
            "runner_up_score": runner_up["score"] if runner_up else None,
            "runner_up_score_percent": score_percent(runner_up["score"] if runner_up else None),
            "runner_up_openalex_id": runner_summary["openalex_id"],
            "runner_up_display_name": runner_summary["display_name"],
            "runner_up_orcid": runner_summary["orcid"],
            "runner_up_institutions": runner_summary["institutions"],
            "top_reasons": best["reasons"],
            "runner_up_reasons": runner_up["reasons"] if runner_up else [],
        }
    return best["author"], {
        "decision": "matched",
        "candidate_count": len(scored),
        "confidence_percent": confidence_percent(best["score"], runner_up["score"] if runner_up else None),
        "score": best["score"],
        "score_percent": score_percent(best["score"]),
        "top_score": best["score"],
        "top_score_percent": score_percent(best["score"]),
        "top_openalex_id": best_summary["openalex_id"],
        "top_display_name": best_summary["display_name"],
        "top_orcid": best_summary["orcid"],
        "top_institutions": best_summary["institutions"],
        "reasons": best["reasons"],
        "runner_up_score": runner_up["score"] if runner_up else None,
        "runner_up_score_percent": score_percent(runner_up["score"] if runner_up else None),
        "runner_up_openalex_id": runner_summary["openalex_id"],
        "runner_up_display_name": runner_summary["display_name"],
        "runner_up_orcid": runner_summary["orcid"],
        "runner_up_institutions": runner_summary["institutions"],
        "top_reasons": best["reasons"],
        "runner_up_reasons": runner_up["reasons"] if runner_up else [],
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
    offset: int = 0,
    max_targets: int | None = None,
    per_page: int = 10,
    mailto: str = "",
    api_key: str = "",
    dry_run: bool = False,
    report_csv_path: Path | None = None,
    candidate_report_csv_path: Path | None = None,
    candidate_limit_per_name: int = 5,
) -> dict[str, Any]:
    payload = load_registry(registry_path)
    items = payload.get("items") or []
    targets = find_registry_targets(
        items,
        target_names=target_names,
        tag_types=tag_types,
        missing_external_ids_only=missing_external_ids_only,
    )
    if offset > 0:
        targets = targets[max(0, int(offset)) :]
    if max_targets is not None:
        targets = targets[: max(0, int(max_targets))]
    updated = 0
    skipped = 0
    decisions: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    for item in targets:
        query_name = str(item.get("name") or "").strip()
        results = fetch_openalex_authors(
            query_name,
            per_page=per_page,
            mailto=mailto,
            api_key=api_key,
        )
        ranked_candidates = rank_openalex_candidates(item, results)
        author, decision = select_best_openalex_match(item, results)
        decisions.append(
            {
                "name": query_name,
                "tag_type": item.get("tag_type") or "",
                **decision,
            }
        )
        if candidate_report_csv_path is not None:
            for index, candidate in enumerate(ranked_candidates[: max(0, int(candidate_limit_per_name))], start=1):
                candidate_rows.append(
                    {
                        "name": query_name,
                        "tag_type": item.get("tag_type") or "",
                        "decision": decision.get("decision") or "",
                        "reason": decision.get("reason") or "",
                        "candidate_count": str(len(ranked_candidates)),
                        "rank": str(index),
                        "score": str(candidate["score"]),
                        "score_percent": str(candidate["score_percent"]),
                        "openalex_id": candidate["summary"]["openalex_id"],
                        "display_name": candidate["summary"]["display_name"],
                        "orcid": candidate["summary"]["orcid"],
                        "institutions": candidate["summary"]["institutions"],
                        "reasons": ";".join(candidate["reasons"]),
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

    if report_csv_path is not None:
        write_decision_csv(report_csv_path, decisions)
    if candidate_report_csv_path is not None:
        write_candidate_csv(candidate_report_csv_path, candidate_rows)

    report = {
        "target_count": len(targets),
        "updated": updated,
        "skipped": skipped,
        "decisions": decisions,
    }
    if report_csv_path is not None:
        report["decision_csv_path"] = str(report_csv_path)
    if candidate_report_csv_path is not None:
        report["candidate_csv_path"] = str(candidate_report_csv_path)
    return report


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
    parser.add_argument("--offset", type=int, default=0, help="可选，跳过前 N 个目标，适合续跑下一批。")
    parser.add_argument("--limit", type=int, default=0, help="可选，只处理前 N 个目标，适合分批跑。")
    parser.add_argument("--per-page", type=int, default=10)
    parser.add_argument("--mailto", default="")
    parser.add_argument(
        "--api-key",
        default=DEFAULT_OPENALEX_API_KEY,
        help="OpenAlex API key。也可通过环境变量 OPENALEX_API_KEY 提供。",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path", default="", help="可选，写出 enrichment 决策 JSON。")
    parser.add_argument(
        "--report-csv",
        default=str(DEFAULT_REPORT_CSV_PATH),
        help="写出 CSV 审计结果；包含命中与未命中记录，默认写到 data/reference/openalex_enrichment_audit.csv",
    )
    parser.add_argument(
        "--candidate-report-csv",
        default="",
        help="可选，额外导出每个名字的候选 OpenAlex ID 集合，供二次 AI/人工判定使用。",
    )
    parser.add_argument(
        "--candidate-limit-per-name",
        type=int,
        default=5,
        help="candidate-report-csv 模式下，每个名字最多导出前 N 个候选，默认 5。",
    )
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
        offset=max(0, int(args.offset or 0)),
        max_targets=(max(0, int(args.limit or 0)) or None),
        per_page=max(1, int(args.per_page or 10)),
        mailto=str(args.mailto or "").strip(),
        api_key=str(args.api_key or "").strip(),
        dry_run=bool(args.dry_run),
        report_csv_path=Path(args.report_csv).expanduser() if str(args.report_csv or "").strip() else None,
        candidate_report_csv_path=Path(args.candidate_report_csv).expanduser() if str(args.candidate_report_csv or "").strip() else None,
        candidate_limit_per_name=max(0, int(args.candidate_limit_per_name or 0)),
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
