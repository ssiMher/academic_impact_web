from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import requests


DBLP_AUTHOR_SEARCH_URL = "https://dblp.org/search/author/api"
DBLP_AUTHOR_PUBS_URL = "https://dblp.org/pid/{dblp_id}.xml"
DBLP_AUTHOR_PID_PATTERN = re.compile(r"/pid/([^/.]+/[^/.]+)(?:\.html)?")


def extract_dblp_id(url: str) -> str:
    match = DBLP_AUTHOR_PID_PATTERN.search(url or "")
    return match.group(1) if match else ""


def note_text(note: Any) -> str:
    if isinstance(note, str):
        return note
    if isinstance(note, dict):
        return note.get("text") or note.get("#text") or ""
    return ""


def normalize_notes(notes: Any) -> list[str]:
    if isinstance(notes, dict):
        notes = notes.get("note")

    if isinstance(notes, str):
        values = [notes]
    elif isinstance(notes, list):
        values = [note_text(item) for item in notes]
    else:
        values = []

    return [value.strip() for value in values if value.strip()]


def normalize_dblp_author_hit(hit: dict[str, Any]) -> dict[str, Any]:
    info = hit.get("info") or {}
    source_url = info.get("url") or ""
    return {
        "source": "DBLP",
        "display_name": (info.get("author") or "").strip(),
        "dblp_id": extract_dblp_id(source_url),
        "openalex_id": "",
        "scopus_author_id": "",
        "affiliations": normalize_notes(info.get("notes")),
        "source_url": source_url,
    }


def search_dblp_authors(name: str, limit: int = 10) -> list[dict[str, Any]]:
    response = requests.get(
        DBLP_AUTHOR_SEARCH_URL,
        params={"q": name, "format": "json", "h": limit},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    hits = (((payload.get("result") or {}).get("hits") or {}).get("hit") or [])
    if isinstance(hits, dict):
        hits = [hits]
    return [normalize_dblp_author_hit(hit) for hit in hits if isinstance(hit, dict)]


def author_text(author: Any) -> str:
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        return author.get("text") or author.get("#text") or author.get("name") or ""
    return ""


def normalize_author_list(authors: Any) -> list[str]:
    if isinstance(authors, dict):
        authors = authors.get("author")

    if isinstance(authors, (str, dict)):
        values = [author_text(authors)]
    elif isinstance(authors, list):
        values = [author_text(author) for author in authors]
    else:
        values = []

    return [value.strip() for value in values if value.strip()]


def parse_year(value: Any) -> int | None:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def doi_from_ee(value: str) -> str:
    doi_url_prefix = "https://doi.org/"
    if value.startswith(doi_url_prefix):
        return value[len(doi_url_prefix) :].strip()
    return ""


def normalized_author_key(value: str) -> str:
    value = re.sub(r"\s+\d{4}$", "", value.strip())
    return re.sub(r"[^a-z0-9]", "", value.lower())


def author_position(authors: list[str], selected_author_name: str) -> str:
    selected_key = normalized_author_key(selected_author_name)
    if not selected_key:
        return "unknown"

    author_keys = [normalized_author_key(author) for author in authors]
    try:
        index = author_keys.index(selected_key)
    except ValueError:
        return "unknown"

    if index == 0:
        return "first_author"
    if index == len(author_keys) - 1:
        return "last_author"
    return "middle_author"


def xml_child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def normalize_dblp_xml_publication(
    entry: ET.Element, selected_author_name: str
) -> dict[str, Any]:
    doi = xml_child_text(entry, "doi") or doi_from_ee(xml_child_text(entry, "ee"))
    key = (entry.attrib.get("key") or "").strip()
    authors = [
        (author.text or "").strip()
        for author in entry.findall("author")
        if (author.text or "").strip()
    ]
    unique_ids = {}
    if key:
        unique_ids["DBLP"] = key
    if doi:
        unique_ids["DOI"] = doi

    venue = xml_child_text(entry, "booktitle") or xml_child_text(entry, "journal")

    return {
        "title": xml_child_text(entry, "title"),
        "year": parse_year(xml_child_text(entry, "year")),
        "venue": venue or "Unknown Venue",
        "doi": doi,
        "unique_ids": unique_ids,
        "authors": authors,
        "author_position": author_position(authors, selected_author_name),
        "citation_count": 0,
    }


def normalize_dblp_publication(
    entry: dict[str, Any] | ET.Element, selected_author_name: str
) -> dict[str, Any]:
    if isinstance(entry, ET.Element):
        return normalize_dblp_xml_publication(entry, selected_author_name)

    info = entry.get("info") or {}
    doi = (info.get("doi") or "").strip() or doi_from_ee((info.get("ee") or "").strip())
    key = (info.get("key") or "").strip()
    authors = normalize_author_list(info.get("authors"))
    unique_ids = {}
    if key:
        unique_ids["DBLP"] = key
    if doi:
        unique_ids["DOI"] = doi

    return {
        "title": (info.get("title") or "").strip(),
        "year": parse_year(info.get("year")),
        "venue": (
            info.get("venue")
            or info.get("booktitle")
            or info.get("journal")
            or "Unknown Venue"
        ).strip()
        or "Unknown Venue",
        "doi": doi,
        "unique_ids": unique_ids,
        "authors": authors,
        "author_position": author_position(authors, selected_author_name),
        "citation_count": 0,
    }


def fetch_dblp_publications(
    dblp_id: str, selected_author_name: str
) -> list[dict[str, Any]]:
    response = requests.get(
        DBLP_AUTHOR_PUBS_URL.format(dblp_id=dblp_id),
        timeout=20,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    publications = []
    for record in root.findall("r"):
        children = list(record)
        if children:
            publications.append(
                normalize_dblp_publication(children[0], selected_author_name)
            )
    return publications
