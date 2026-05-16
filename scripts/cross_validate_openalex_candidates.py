from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_CSV = ROOT / "data" / "reference" / "openalex_candidate_cross_validation.csv"
DEFAULT_SUMMARY_CSV = ROOT / "data" / "reference" / "openalex_candidate_cross_validation_summary.csv"
DBLP_AUTHOR_SEARCH_URL = "https://dblp.org/search/author/api"
DBLP_AUTHOR_PUBS_URL = "https://dblp.org/pid/{dblp_id}.xml"
DBLP_AUTHOR_PID_PATTERN = re.compile(r"/pid/([^?#]+?)(?:\.html)?/?$")
SCOPUS_AUTHOR_SEARCH_URL = "https://api.elsevier.com/content/search/author"


def normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").strip().lower())


def normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").strip().lower())


def split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [part.strip() for part in re.split(r"[;|]", str(value)) if part.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_csv_from_zip(path: Path, member: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        with archive.open(member) as handle:
            text = handle.read().decode("utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def load_resolution_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".zip":
        return read_csv_from_zip(path, "openalex_ai_resolved_ids.csv")
    return read_csv(path)


def institution_tokens(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    stop = {"university", "college", "institute", "school", "department", "laboratory", "lab", "center", "centre"}
    for value in values:
        for raw in re.split(r"[^A-Za-z0-9]+", str(value or "")):
            token = raw.strip().lower()
            if len(token) < 4 or token in stop:
                continue
            tokens.add(token)
    return tokens


def build_raw_author_metadata(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    metadata: dict[str, dict[str, Any]] = defaultdict(lambda: {"institutions": [], "source_urls": []})
    for row in read_csv(path):
        name = row.get("author_name") or row.get("raw_author_name") or ""
        key = normalize_name(name)
        if not key:
            continue
        metadata[key]["institutions"].extend(split_list(row.get("author_institutions")))
        source_url = str(row.get("author_source_url") or "").strip()
        if source_url:
            metadata[key]["source_urls"].append(source_url)
    return {
        key: {
            "institutions": unique(value["institutions"]),
            "source_urls": unique(value["source_urls"]),
        }
        for key, value in metadata.items()
    }


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


def extract_dblp_pid(url: str) -> str:
    match = DBLP_AUTHOR_PID_PATTERN.search(str(url or "").strip())
    return match.group(1) if match else ""


def request_dblp(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 20,
    max_retries: int = 2,
) -> requests.Response:
    for attempt in range(max_retries + 1):
        response = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "academic-impact-web/1.0 (+openalex-cross-validation)"},
        )
        if response.status_code == 429 and attempt < max_retries:
            try:
                retry_after = float(response.headers.get("Retry-After") or 5)
            except ValueError:
                retry_after = 5
            time.sleep(max(1.0, retry_after))
            continue
        response.raise_for_status()
        return response
    raise RuntimeError("unreachable DBLP retry state")


def fetch_dblp_authors(name: str, *, timeout: int = 20) -> list[dict[str, str]]:
    response = request_dblp(
        DBLP_AUTHOR_SEARCH_URL,
        params={"q": name, "format": "json", "h": "5"},
        timeout=timeout,
    )
    payload = response.json()
    hits = (((payload.get("result") or {}).get("hits") or {}).get("hit") or [])
    if isinstance(hits, dict):
        hits = [hits]
    authors: list[dict[str, str]] = []
    for hit in hits:
        info = (hit or {}).get("info") or {}
        url = str(info.get("url") or "").strip()
        authors.append(
            {
                "pid": extract_dblp_pid(url),
                "name": str(info.get("author") or "").strip(),
                "url": url,
            }
        )
    return [author for author in authors if author["name"]]


def xml_child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return "".join(child.itertext()).strip() if child is not None else ""


def normalize_dblp_xml_publication(entry: ET.Element) -> dict[str, Any]:
    authors = [
        (author.text or "").strip()
        for author in entry.findall("author")
        if (author.text or "").strip()
    ]
    venue = xml_child_text(entry, "booktitle") or xml_child_text(entry, "journal")
    return {
        "title": xml_child_text(entry, "title"),
        "venue": venue,
        "year": xml_child_text(entry, "year"),
        "coauthors": authors,
        "key": (entry.attrib.get("key") or "").strip(),
    }


def publication_year(publication: dict[str, Any]) -> int:
    try:
        return int(str(publication.get("year") or "0"))
    except ValueError:
        return 0


def fetch_dblp_publications(dblp_id: str, *, limit: int = 20, timeout: int = 20) -> list[dict[str, Any]]:
    if not dblp_id:
        return []
    response = request_dblp(
        DBLP_AUTHOR_PUBS_URL.format(dblp_id=dblp_id),
        timeout=timeout,
    )
    root = ET.fromstring(response.text)
    publications: list[dict[str, Any]] = []
    for record in root.findall("r"):
        children = list(record)
        if not children:
            continue
        publication = normalize_dblp_xml_publication(children[0])
        if publication.get("title"):
            publications.append(publication)
    publications.sort(key=publication_year, reverse=True)
    return publications[:limit] if limit > 0 else publications


def wait_between_dblp_requests(delay_seconds: float) -> None:
    if delay_seconds > 0:
        time.sleep(delay_seconds)


def fetch_dblp_publications_for_authors(
    authors: list[dict[str, Any]],
    *,
    limit: int,
    request_delay_seconds: float,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    seen_pids: set[str] = set()
    for author in authors:
        item = dict(author)
        pid = str(item.get("pid") or "").strip()
        if not pid or pid in seen_pids:
            item["publications"] = []
            enriched.append(item)
            continue
        seen_pids.add(pid)
        try:
            item["publications"] = fetch_dblp_publications(pid, limit=limit)
        except Exception as exc:
            item["publications"] = []
            item["publication_error"] = f"{type(exc).__name__}: {exc}"
        enriched.append(item)
        wait_between_dblp_requests(request_delay_seconds)
    return enriched


def dblp_publication_profile_fields(authors: list[dict[str, Any]], target_name: str) -> dict[str, str]:
    counts: list[str] = []
    year_ranges: list[str] = []
    titles: list[str] = []
    venues: list[str] = []
    coauthors: list[str] = []
    target_key = normalize_name(target_name)

    for author in authors:
        pid = str(author.get("pid") or "").strip()
        publications = [pub for pub in author.get("publications", []) if isinstance(pub, dict)]
        if pid and publications:
            counts.append(f"{pid}={len(publications)}")
            years = sorted({publication_year(pub) for pub in publications if publication_year(pub)})
            if years:
                year_ranges.append(f"{pid}={years[0]}-{years[-1]}")
        for publication in publications:
            title = str(publication.get("title") or "").strip()
            venue = str(publication.get("venue") or "").strip()
            year = str(publication.get("year") or "").strip()
            if title:
                context = " ".join(part for part in [venue, year] if part).strip()
                titles.append(f"{title} ({context})" if context else title)
            if venue:
                venues.append(venue)
            for coauthor in publication.get("coauthors", []):
                coauthor = str(coauthor or "").strip()
                if coauthor and normalize_name(coauthor) != target_key:
                    coauthors.append(coauthor)

    return {
        "dblp_publication_counts": ";".join(unique(counts)),
        "dblp_year_ranges": ";".join(unique(year_ranges)),
        "dblp_recent_titles": " | ".join(unique(titles)[:12]),
        "dblp_recent_venues": ";".join(unique(venues)[:12]),
        "dblp_coauthors": ";".join(unique(coauthors)[:30]),
    }


def scopus_author_query(name: str) -> str:
    parts = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    if len(parts) >= 2:
        first = re.sub(r"[^A-Za-z-]", "", parts[0])
        last = re.sub(r"[^A-Za-z-]", "", parts[-1])
        if first and last:
            return f"AUTHLASTNAME({last}) AND AUTHFIRST({first})"
    return f'AUTH("{str(name or "").replace(chr(34), " ")}")'


def fetch_scopus_authors(
    name: str,
    *,
    api_key: str = "",
    insttoken: str = "",
    timeout: int = 30,
) -> list[dict[str, str]]:
    api_key = (api_key or os.environ.get("ELSEVIER_API_KEY") or "").strip()
    if not api_key:
        return []
    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": api_key,
        "User-Agent": "academic-impact-web/1.0 (+openalex-cross-validation)",
    }
    insttoken = (insttoken or os.environ.get("ELSEVIER_INSTTOKEN") or "").strip()
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    response = requests.get(
        SCOPUS_AUTHOR_SEARCH_URL,
        params={
            "query": scopus_author_query(name),
            "count": 5,
            "httpAccept": "application/json",
        },
        headers=headers,
        timeout=timeout,
    )
    if response.status_code == 429:
        time.sleep(3)
    response.raise_for_status()
    entries = ((response.json().get("search-results") or {}).get("entry") or [])
    if isinstance(entries, dict):
        entries = [entries]
    return [normalize_scopus_author(entry) for entry in entries if isinstance(entry, dict)]


def normalize_scopus_author(entry: dict[str, Any]) -> dict[str, str]:
    preferred = entry.get("preferred-name") or {}
    if isinstance(preferred, dict):
        name = preferred.get("indexed-name") or " ".join(
            part for part in [preferred.get("given-name"), preferred.get("surname")] if part
        )
    else:
        name = entry.get("dc:title") or ""
    author_id = str(entry.get("dc:identifier") or entry.get("eid") or "").replace("AUTHOR_ID:", "").strip()
    affiliation = entry.get("affiliation-current") or entry.get("affiliation-name") or ""
    if isinstance(affiliation, dict):
        affiliation = affiliation.get("affiliation-name") or affiliation.get("name") or ""
    elif isinstance(affiliation, list):
        affiliation = ";".join(str((item or {}).get("affiliation-name") or "") for item in affiliation if isinstance(item, dict))
    return {
        "scopus_author_id": author_id,
        "name": str(name or "").strip(),
        "affiliation": str(affiliation or "").strip(),
        "document_count": str(entry.get("document-count") or entry.get("document_count") or ""),
    }


def external_evidence_for_name(
    name: str,
    *,
    use_dblp: bool,
    fetch_dblp_publication_profiles: bool,
    dblp_publication_limit: int,
    dblp_request_delay: float,
    use_scopus: bool,
    scopus_api_key: str = "",
    scopus_insttoken: str = "",
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"dblp": [], "scopus": []}
    if use_dblp:
        try:
            evidence["dblp"] = fetch_dblp_authors(name)
            wait_between_dblp_requests(dblp_request_delay)
            if fetch_dblp_publication_profiles:
                evidence["dblp"] = fetch_dblp_publications_for_authors(
                    evidence["dblp"],
                    limit=dblp_publication_limit,
                    request_delay_seconds=dblp_request_delay,
                )
        except Exception as exc:
            evidence["dblp_error"] = f"{type(exc).__name__}: {exc}"
    if use_scopus:
        try:
            evidence["scopus"] = fetch_scopus_authors(name, api_key=scopus_api_key, insttoken=scopus_insttoken)
        except Exception as exc:
            evidence["scopus_error"] = f"{type(exc).__name__}: {exc}"
    return evidence


def score_candidate(
    candidate: dict[str, str],
    resolution_row: dict[str, str],
    raw_metadata: dict[str, Any],
    external_evidence: dict[str, Any],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    candidate_name = candidate.get("display_name") or candidate.get("name") or ""
    target_name = resolution_row.get("name") or candidate.get("name") or ""

    if normalize_name(candidate_name) == normalize_name(target_name):
        score += 12
        reasons.append("candidate_name_exact")
    if candidate.get("orcid"):
        score += 8
        reasons.append("candidate_has_orcid")

    raw_institutions = raw_metadata.get("institutions") or []
    candidate_institutions = split_list(candidate.get("institutions"))
    raw_overlap = institution_tokens(raw_institutions) & institution_tokens(candidate_institutions)
    if raw_overlap:
        score += 35
        reasons.append("raw_institution_overlap:" + "|".join(sorted(raw_overlap)[:5]))

    dblp_matches = [
        item for item in external_evidence.get("dblp", [])
        if normalize_name(item.get("name")) == normalize_name(target_name)
    ]
    if dblp_matches:
        score += 12
        reasons.append("dblp_exact_name")

    scopus_matches = [
        item for item in external_evidence.get("scopus", [])
        if normalize_name(item.get("name")) == normalize_name(target_name)
    ]
    if scopus_matches:
        score += 15
        reasons.append("scopus_exact_name")
    scopus_institutions = [item.get("affiliation", "") for item in external_evidence.get("scopus", [])]
    scopus_overlap = institution_tokens(scopus_institutions) & institution_tokens(candidate_institutions + raw_institutions)
    if scopus_overlap:
        score += 25
        reasons.append("scopus_institution_overlap:" + "|".join(sorted(scopus_overlap)[:5]))

    try:
        score += min(10, int(float(candidate.get("score_percent") or 0) / 10))
    except ValueError:
        pass
    return score, reasons


def status_for_ranked_scores(rows: list[dict[str, Any]], row: dict[str, Any]) -> str:
    if not rows:
        return "unresolved"
    if row is not rows[0]:
        return "candidate_evidence_only"
    if len(rows) == 1 and row["evidence_score"] >= 30:
        return "cross_validated_suggestion"
    runner = rows[1] if len(rows) > 1 else None
    if row["evidence_score"] >= 45 and (runner is None or row["evidence_score"] >= runner["evidence_score"] + 15):
        return "cross_validated_suggestion"
    return "candidate_evidence_only"


def cross_validate(
    *,
    resolution_zip_path: Path,
    candidates_csv_path: Path,
    raw_citing_authors_csv_path: Path | None,
    output_csv_path: Path,
    summary_csv_path: Path,
    use_dblp: bool = False,
    fetch_dblp_publications: bool = False,
    dblp_publication_limit: int = 20,
    dblp_request_delay: float = 0.0,
    use_scopus: bool = False,
    scopus_api_key: str = "",
    scopus_insttoken: str = "",
) -> dict[str, Any]:
    resolution_rows = load_resolution_rows(resolution_zip_path)
    resolution_by_name = {normalize_name(row.get("name")): row for row in resolution_rows}
    candidates_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(candidates_csv_path):
        key = normalize_name(row.get("name"))
        if key:
            candidates_by_name[key].append(row)

    raw_by_name = build_raw_author_metadata(raw_citing_authors_csv_path)
    output_rows: list[dict[str, Any]] = []
    external_cache: dict[str, dict[str, Any]] = {}
    processed_names = 0

    for name_key, candidates in candidates_by_name.items():
        resolution_row = resolution_by_name.get(name_key) or {"name": candidates[0].get("name", ""), "tag_type": candidates[0].get("tag_type", "")}
        if (resolution_row.get("resolution_status") or "").strip() not in {"", "unresolved"}:
            continue
        processed_names += 1
        target_name = resolution_row.get("name") or candidates[0].get("name", "")
        external = external_cache.get(name_key)
        if external is None:
            external = external_evidence_for_name(
                target_name,
                use_dblp=use_dblp,
                fetch_dblp_publication_profiles=fetch_dblp_publications,
                dblp_publication_limit=dblp_publication_limit,
                dblp_request_delay=dblp_request_delay,
                use_scopus=use_scopus,
                scopus_api_key=scopus_api_key,
                scopus_insttoken=scopus_insttoken,
            )
            external_cache[name_key] = external
        raw_metadata = raw_by_name.get(name_key, {"institutions": [], "source_urls": []})
        dblp_profile = dblp_publication_profile_fields(external.get("dblp", []), target_name)
        scored_rows: list[dict[str, Any]] = []
        for candidate in candidates:
            evidence_score, evidence_reasons = score_candidate(candidate, resolution_row, raw_metadata, external)
            scored_rows.append(
                {
                    "name": target_name,
                    "tag_type": resolution_row.get("tag_type") or candidate.get("tag_type", ""),
                    "openalex_id": candidate.get("openalex_id", ""),
                    "candidate_rank": candidate.get("rank", ""),
                    "candidate_score_percent": candidate.get("score_percent", ""),
                    "display_name": candidate.get("display_name", ""),
                    "orcid": candidate.get("orcid", ""),
                    "candidate_institutions": candidate.get("institutions", ""),
                    "raw_author_institutions": ";".join(raw_metadata.get("institutions") or []),
                    "raw_author_source_urls": ";".join(raw_metadata.get("source_urls") or []),
                    "dblp_pids": ";".join(item.get("pid", "") for item in external.get("dblp", []) if item.get("pid")),
                    "dblp_names": ";".join(item.get("name", "") for item in external.get("dblp", []) if item.get("name")),
                    "dblp_urls": ";".join(item.get("url", "") for item in external.get("dblp", []) if item.get("url")),
                    **dblp_profile,
                    "scopus_author_ids": ";".join(item.get("scopus_author_id", "") for item in external.get("scopus", []) if item.get("scopus_author_id")),
                    "scopus_names": ";".join(item.get("name", "") for item in external.get("scopus", []) if item.get("name")),
                    "scopus_affiliations": ";".join(item.get("affiliation", "") for item in external.get("scopus", []) if item.get("affiliation")),
                    "evidence_score": evidence_score,
                    "evidence_reasons": ";".join(evidence_reasons),
                    "cross_validation_status": "",
                }
            )
        scored_rows.sort(key=lambda row: (-int(row["evidence_score"]), int(row["candidate_rank"] or 9999)))
        for row in scored_rows:
            row["cross_validation_status"] = status_for_ranked_scores(scored_rows, row)
        output_rows.extend(scored_rows)

    write_rows(output_csv_path, output_rows)
    summary = Counter(row["cross_validation_status"] for row in output_rows)
    write_rows(summary_csv_path, [{"category": key, "count": value} for key, value in sorted(summary.items())])
    return {
        "candidate_rows": len(output_rows),
        "candidate_names": len(candidates_by_name),
        "processed_names": processed_names,
        "summary": dict(summary),
    }


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-validate unresolved OpenAlex author candidates with Scopus/DBLP/raw author metadata.")
    parser.add_argument("--resolution-zip", required=True, help="openalex_ai_resolution_2600.zip 或 openalex_ai_resolved_ids.csv")
    parser.add_argument("--candidates-csv", required=True, help="OpenAlex candidate set CSV，例如 openalex_candidates_ieee_merged_2600.csv")
    parser.add_argument("--raw-citing-authors-csv", default="", help="可选，Export Raw Citing Authors CSV 输出。")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    parser.add_argument("--summary-csv", default=str(DEFAULT_SUMMARY_CSV))
    parser.add_argument("--use-dblp", action="store_true")
    parser.add_argument("--fetch-dblp-publications", action="store_true", help="Fetch DBLP author PID XML pages and add publication titles, venues, years, and coauthors to the output.")
    parser.add_argument("--dblp-publication-limit", type=int, default=20, help="Maximum DBLP publications to summarize per DBLP author PID.")
    parser.add_argument("--dblp-request-delay", type=float, default=1.0, help="Seconds to wait between DBLP requests. DBLP recommends at least 1-2 seconds for crawlers.")
    parser.add_argument("--use-scopus", action="store_true")
    parser.add_argument("--scopus-api-key", default=os.environ.get("ELSEVIER_API_KEY", ""))
    parser.add_argument("--scopus-insttoken", default=os.environ.get("ELSEVIER_INSTTOKEN", ""))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = cross_validate(
        resolution_zip_path=Path(args.resolution_zip),
        candidates_csv_path=Path(args.candidates_csv),
        raw_citing_authors_csv_path=Path(args.raw_citing_authors_csv) if args.raw_citing_authors_csv else None,
        output_csv_path=Path(args.output_csv),
        summary_csv_path=Path(args.summary_csv),
        use_dblp=bool(args.use_dblp),
        fetch_dblp_publications=bool(args.fetch_dblp_publications),
        dblp_publication_limit=int(args.dblp_publication_limit),
        dblp_request_delay=float(args.dblp_request_delay),
        use_scopus=bool(args.use_scopus),
        scopus_api_key=str(args.scopus_api_key or "").strip(),
        scopus_insttoken=str(args.scopus_insttoken or "").strip(),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
