from __future__ import annotations

import re
from typing import Any

import requests


DBLP_AUTHOR_SEARCH_URL = "https://dblp.org/search/author/api"
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
