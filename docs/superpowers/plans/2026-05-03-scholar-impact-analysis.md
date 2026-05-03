# Scholar Impact Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scholar-level impact mode that starts from one researcher, summarizes all of their papers and citation network, then performs deeper content analysis on selected high-value citing papers.

**Architecture:** Keep the current paper-level session flow intact and add a parallel scholar session flow. Scholar sessions aggregate author papers, citing papers, venue tiers, and person-tag statistics first; later tasks reuse the existing fulltext analyzer only for selected high-value citations.

**Tech Stack:** FastAPI, Jinja templates, Python JSON session files, DBLP/OpenAlex/Scopus metadata APIs, existing `person_tag_registry.json`, existing `venue_tiers.json`, existing fulltext analysis pipeline.

---

## Product Target

Build a local web workflow similar to NASA CitationMaster, but with one extra capability: after counting who cites a scholar, the system can inspect selected citing full texts and explain how important scholars cite the work.

### MVP Scope

The first working version should support:

- Search by scholar name and show author candidates with DBLP/OpenAlex/Scopus IDs when available.
- Create a scholar session from a selected author identity.
- Fetch that scholar's publications with year, venue, DOI, author list, and citation count.
- Expand each publication into citing papers with source paper linkage.
- Compute paper statistics by CCF/venue tier, year, first-author position, and citation count.
- Compute citation statistics by citing-paper venue tier and citing-author person tags such as ACM Fellow, IEEE Fellow, academicians, and top-school authors.
- Show a scholar report page and export JSON/Markdown.

### Phase 2 Scope

After MVP works:

- Rank high-value citation cases for fulltext analysis.
- Download or upload selected citing PDFs.
- Reuse `fulltext_direct` analysis to determine whether the citation is background, method, baseline, comparison, extension, or application.
- Add strong-evidence labels such as `long_context_100_chars`, `positive_evaluation`, `fellow_strong_citation`, and `method_adoption`.

### Explicit Non-Goals For MVP

- Do not attempt to download every citing paper PDF.
- Do not perform fulltext semantic analysis for every citation.
- Do not rely on author name alone when a stable author ID is available.
- Do not merge scholar sessions into the current paper session schema.

---

## Current Codebase Map

### Existing Paper-Level Flow

- [app/main.py](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/app/main.py): FastAPI routes for paper sessions.
- [app/services/impact_core.py](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/app/services/impact_core.py): web service layer and background task state.
- [skills/academic_impact_analyzer/impact_cli.py](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/skills/academic_impact_analyzer/impact_cli.py): current session schema, paper discovery, venue statistics, person-tag statistics, exports.
- [skills/list_all_citations/list_papers.py](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/skills/list_all_citations/list_papers.py): Semantic Scholar/OpenAlex/Scopus citation source integration.
- [skills/analyze_fulltext_citation/analyze_fulltext.py](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/skills/analyze_fulltext_citation/analyze_fulltext.py): LLM citation semantics.
- [skills/download_paper_pdf/download_pdf.py](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/skills/download_paper_pdf/download_pdf.py): PDF probe/download/upload inspection.
- [data/reference/person_tag_registry.json](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/data/reference/person_tag_registry.json): person identity labels.
- [data/reference/venue_tiers.json](/mnt/c/Users/withe/.codex/worktrees/595e/academic_impact_web/data/reference/venue_tiers.json): venue tier registry.

### New Files To Create

- `skills/scholar_impact_analyzer/__init__.py`
- `skills/scholar_impact_analyzer/author_sources.py`
- `skills/scholar_impact_analyzer/scholar_pipeline.py`
- `skills/scholar_impact_analyzer/scholar_stats.py`
- `skills/scholar_impact_analyzer/SCHOLAR_SESSION_SCHEMA.md`
- `app/services/scholar_core.py`
- `app/templates/scholar_session.html`
- `tests/test_scholar_author_sources.py`
- `tests/test_scholar_pipeline.py`
- `tests/test_scholar_stats.py`
- `tests/test_scholar_web.py`

### Existing Files To Modify

- `app/main.py`: add scholar routes.
- `app/templates/index.html`: add scholar analysis entry form.
- `app/static/style.css`: add compact scholar report styles only where existing classes are insufficient.
- `requirements.txt`: no new dependency for MVP.

---

## Data Model

### Scholar Session Root

Store scholar sessions under:

```text
data/scholar_sessions/{session_id}/session.json
```

### Session Shape

```json
{
  "schema_version": "1.0",
  "session_type": "scholar_impact",
  "session_id": "20260503_180000_scholar_chen_tian",
  "query": "Chen Tian",
  "selected_author": {
    "display_name": "Chen Tian",
    "dblp_id": "94/1247-1",
    "openalex_id": "",
    "scopus_author_id": "",
    "affiliations": [
      "Nanjing University, State Key Laboratory for Novel Software Technology, China"
    ]
  },
  "publications": [
    {
      "id": "S001",
      "title": "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.",
      "year": 2024,
      "venue": "EuroSys",
      "doi": "",
      "unique_ids": {
        "DBLP": "conf/eurosys/...",
        "OpenAlex": "",
        "Scopus": ""
      },
      "authors": ["Songyuan Bai", "Hao Zheng", "Chen Tian"],
      "author_position": "middle_author",
      "citation_count": 0,
      "venue_tier": {
        "tier_label": "CCF A",
        "tier_system": "CCF"
      }
    }
  ],
  "citation_edges": [
    {
      "source_publication_id": "S001",
      "citing_paper_id": "C000001",
      "citing_title": "A citing paper title",
      "citing_year": 2026,
      "citing_venue": "ACM MobiCom",
      "citing_doi": "",
      "citing_authors": ["A Fellow", "Another Author"],
      "provider": "Scopus",
      "cited_publication_title": "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel."
    }
  ],
  "statistics": {
    "publication_tiers": [],
    "citing_venue_tiers": [],
    "person_tag_statistics": [],
    "yearly_citations": [],
    "top_publications": [],
    "strong_evidence_count": 0
  },
  "deep_analysis_queue": [],
  "task_state": {
    "active": false,
    "task_type": null,
    "status": "idle"
  }
}
```

---

## Task 1: Author Search And Disambiguation

**Files:**

- Create: `skills/scholar_impact_analyzer/__init__.py`
- Create: `skills/scholar_impact_analyzer/author_sources.py`
- Test: `tests/test_scholar_author_sources.py`

- [x] **Step 1: Write tests for DBLP author candidate parsing**

Add `tests/test_scholar_author_sources.py`:

```python
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHOR_SOURCES_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "author_sources.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarAuthorSourcesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = load_module(AUTHOR_SOURCES_PATH, "test_scholar_author_sources")

    def test_normalize_dblp_author_hit(self):
        hit = {
            "info": {
                "author": "Chen Tian",
                "url": "https://dblp.org/pid/94/1247-1.html",
                "notes": {"note": "Nanjing University"}
            }
        }

        candidate = self.sources.normalize_dblp_author_hit(hit)

        self.assertEqual(candidate["display_name"], "Chen Tian")
        self.assertEqual(candidate["dblp_id"], "94/1247-1")
        self.assertEqual(candidate["affiliations"], ["Nanjing University"])
        self.assertEqual(candidate["source"], "DBLP")

    def test_normalize_dblp_author_hit_handles_multiple_notes(self):
        hit = {
            "info": {
                "author": "Chen Tian",
                "url": "https://dblp.org/pid/94/1247-2.html",
                "notes": {"note": ["Huawei America Research Center", "Santa Clara"]}
            }
        }

        candidate = self.sources.normalize_dblp_author_hit(hit)

        self.assertEqual(candidate["dblp_id"], "94/1247-2")
        self.assertEqual(candidate["affiliations"], ["Huawei America Research Center", "Santa Clara"])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_author_sources -q
```

Expected: fails because `skills/scholar_impact_analyzer/author_sources.py` does not exist.

- [x] **Step 3: Implement DBLP author normalization and search skeleton**

Create `skills/scholar_impact_analyzer/__init__.py` as an empty file.

Create `skills/scholar_impact_analyzer/author_sources.py`:

```python
from __future__ import annotations

import re
from typing import Any

import requests


DBLP_AUTHOR_SEARCH_URL = "https://dblp.org/search/author/api"
DBLP_AUTHOR_PID_PATTERN = re.compile(r"/pid/([^/.]+/[^/.]+)(?:\\.html)?")


def extract_dblp_id(url: str) -> str:
    match = DBLP_AUTHOR_PID_PATTERN.search(url or "")
    return match.group(1) if match else ""


def normalize_notes(notes: Any) -> list[str]:
    if isinstance(notes, dict):
        notes = notes.get("note")
    if isinstance(notes, str):
        values = [notes]
    elif isinstance(notes, list):
        values = [item for item in notes if isinstance(item, str)]
    else:
        values = []
    return [value.strip() for value in values if value.strip()]


def normalize_dblp_author_hit(hit: dict[str, Any]) -> dict[str, Any]:
    info = hit.get("info") or {}
    return {
        "source": "DBLP",
        "display_name": (info.get("author") or "").strip(),
        "dblp_id": extract_dblp_id(info.get("url") or ""),
        "openalex_id": "",
        "scopus_author_id": "",
        "affiliations": normalize_notes(info.get("notes")),
        "source_url": info.get("url") or "",
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
```

- [x] **Step 4: Run test to verify it passes**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_author_sources -q
```

Expected: `OK`.

- [x] **Step 5: Commit**

```bash
git add skills/scholar_impact_analyzer/__init__.py skills/scholar_impact_analyzer/author_sources.py tests/test_scholar_author_sources.py
git commit -m "Add scholar author search foundations" \
  -m "Scholar impact analysis needs a stable author identity before citation expansion. DBLP author candidate parsing gives the web flow a disambiguation step instead of relying on names alone." \
  -m "Constraint: Avoid new dependencies for MVP" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_author_sources -q"
```

---

## Task 2: Publication Fetching

**Files:**

- Modify: `skills/scholar_impact_analyzer/author_sources.py`
- Test: `tests/test_scholar_author_sources.py`

- [x] **Step 1: Add tests for DBLP publication normalization**

Append to `ScholarAuthorSourcesTestCase`:

```python
    def test_normalize_dblp_publication(self):
        entry = {
            "info": {
                "title": "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.",
                "year": "2024",
                "venue": "EuroSys",
                "doi": "10.1145/3627703.3629574",
                "authors": {"author": ["Songyuan Bai", "Hao Zheng", "Chen Tian", "A. Coauthor"]},
                "key": "conf/eurosys/BaiZTWLXXD024"
            }
        }

        paper = self.sources.normalize_dblp_publication(entry, selected_author_name="Chen Tian")

        self.assertEqual(paper["title"], "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.")
        self.assertEqual(paper["year"], 2024)
        self.assertEqual(paper["venue"], "EuroSys")
        self.assertEqual(paper["doi"], "10.1145/3627703.3629574")
        self.assertEqual(paper["authors"], ["Songyuan Bai", "Hao Zheng", "Chen Tian", "A. Coauthor"])
        self.assertEqual(paper["author_position"], "middle_author")
        self.assertEqual(paper["unique_ids"]["DBLP"], "conf/eurosys/BaiZTWLXXD024")
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_author_sources -q
```

Expected: fails because `normalize_dblp_publication` is undefined.

- [x] **Step 3: Implement publication normalization and fetch**

Implementation note: DBLP's recommended stable person export API uses PID XML URLs such as
`https://dblp.org/pid/65/9612.xml`; the original JSON sketch was replaced because live
`/pid/<PID>.json` probes returned 404.

Add to `author_sources.py`:

```python
import xml.etree.ElementTree as ET


DBLP_AUTHOR_PUBS_URL = "https://dblp.org/pid/{dblp_id}.xml"


def normalize_author_list(authors: Any) -> list[str]:
    if isinstance(authors, dict):
        authors = authors.get("author")
    if isinstance(authors, str):
        return [authors.strip()] if authors.strip() else []
    if isinstance(authors, list):
        result = []
        for author in authors:
            if isinstance(author, str):
                name = author
            elif isinstance(author, dict):
                name = author.get("text") or author.get("#text") or author.get("name") or ""
            else:
                name = ""
            if name.strip():
                result.append(name.strip())
        return result
    return []


def parse_year(value: Any):
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def author_position(authors: list[str], selected_author_name: str) -> str:
    normalized_target = re.sub(r"[^a-z0-9]+", "", selected_author_name.lower())
    normalized_authors = [re.sub(r"[^a-z0-9]+", "", author.lower()) for author in authors]
    if normalized_target not in normalized_authors:
        return "unknown"
    index = normalized_authors.index(normalized_target)
    if index == 0:
        return "first_author"
    if index == len(authors) - 1:
        return "last_author"
    return "middle_author"


def normalize_dblp_publication(entry: dict[str, Any], selected_author_name: str) -> dict[str, Any]:
    info = entry.get("info") or {}
    authors = normalize_author_list(info.get("authors"))
    doi = (info.get("doi") or "").strip()
    unique_ids = {"DBLP": info.get("key") or ""}
    if doi:
        unique_ids["DOI"] = doi
    return {
        "title": (info.get("title") or "").strip(),
        "year": parse_year(info.get("year")),
        "venue": (info.get("venue") or "").strip() or "Unknown Venue",
        "doi": doi,
        "unique_ids": unique_ids,
        "authors": authors,
        "author_position": author_position(authors, selected_author_name),
        "citation_count": 0,
    }


def fetch_dblp_publications(dblp_id: str, selected_author_name: str) -> list[dict[str, Any]]:
    response = requests.get(DBLP_AUTHOR_PUBS_URL.format(dblp_id=dblp_id), timeout=20)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    publications = [list(record)[0] for record in root.findall("r") if list(record)]
    return [
        normalize_dblp_publication(item, selected_author_name=selected_author_name)
        for item in publications
    ]
```

- [x] **Step 4: Run test**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_author_sources -q
```

Expected: `OK`.

- [x] **Step 5: Commit**

```bash
git add skills/scholar_impact_analyzer/author_sources.py tests/test_scholar_author_sources.py
git commit -m "Fetch scholar publications from DBLP" \
  -m "Scholar sessions need a publication list before citation expansion. DBLP provides a stable computer-science publication baseline keyed by author PID." \
  -m "Constraint: Citation counts may remain zero until Scopus or OpenAlex enrichment runs" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_author_sources -q"
```

---

## Task 3: Scholar Session Pipeline

**Files:**

- Create: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Create: `skills/scholar_impact_analyzer/SCHOLAR_SESSION_SCHEMA.md`
- Test: `tests/test_scholar_pipeline.py`

- [x] **Step 1: Write session creation tests**

Create `tests/test_scholar_pipeline.py`:

```python
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_pipeline.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarPipelineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_module(PIPELINE_PATH, "test_scholar_pipeline")

    def test_build_scholar_session_from_dblp_author(self):
        author = {
            "display_name": "Chen Tian",
            "dblp_id": "94/1247-1",
            "affiliations": ["Nanjing University"],
            "source": "DBLP",
        }
        publications = [
            {
                "title": "Paper One",
                "year": 2024,
                "venue": "EuroSys",
                "doi": "10.1000/one",
                "unique_ids": {"DBLP": "conf/test/one", "DOI": "10.1000/one"},
                "authors": ["Chen Tian", "A. Coauthor"],
                "author_position": "first_author",
                "citation_count": 0,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            self.pipeline.AUTHOR_SOURCES,
            "fetch_dblp_publications",
            return_value=publications,
        ):
            session = self.pipeline.build_scholar_session(author, Path(tmpdir))

        self.assertEqual(session["session_type"], "scholar_impact")
        self.assertEqual(session["selected_author"]["display_name"], "Chen Tian")
        self.assertEqual(session["publications"][0]["id"], "S001")
        self.assertEqual(session["publications"][0]["title"], "Paper One")
        self.assertEqual(session["statistics"]["publication_count"], 1)

    def test_save_scholar_session_writes_json(self):
        session = {
            "schema_version": "1.0",
            "session_type": "scholar_impact",
            "session_id": "test_scholar",
            "selected_author": {"display_name": "Chen Tian"},
            "publications": [],
            "citation_edges": [],
            "statistics": {},
            "task_state": {"active": False},
            "updated_at": "old",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            self.pipeline.save_scholar_session(session_dir, session)
            loaded = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))

        self.assertEqual(loaded["session_id"], "test_scholar")
        self.assertIn("updated_at", loaded)
        self.assertNotEqual(loaded["updated_at"], "old")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q
```

Expected: fails because `scholar_pipeline.py` does not exist.

- [x] **Step 3: Implement minimal scholar session builder**

Create `skills/scholar_impact_analyzer/scholar_pipeline.py`:

```python
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AUTHOR_SOURCES_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "author_sources.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUTHOR_SOURCES = load_module("scholar_author_sources", AUTHOR_SOURCES_PATH)


def default_task_state() -> dict[str, Any]:
    return {
        "active": False,
        "task_type": None,
        "status": "idle",
        "message": "",
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "error": "",
    }


def assign_publication_ids(publications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, publication in enumerate(publications, 1):
        item = dict(publication)
        item["id"] = f"S{index:03d}"
        result.append(item)
    return result


def build_initial_statistics(publications: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "publication_count": len(publications),
        "citation_edge_count": 0,
        "total_citation_count": sum(item.get("citation_count") or 0 for item in publications),
        "publication_tiers": [],
        "citing_venue_tiers": [],
        "person_tag_statistics": [],
        "yearly_citations": [],
        "strong_evidence_count": 0,
        "top_publications": sorted(
            publications,
            key=lambda item: (-(item.get("citation_count") or 0), -(item.get("year") or 0), item.get("title") or ""),
        )[:10],
    }


def build_scholar_session(selected_author: dict[str, Any], session_dir: Path) -> dict[str, Any]:
    publications = AUTHOR_SOURCES.fetch_dblp_publications(
        selected_author.get("dblp_id") or "",
        selected_author_name=selected_author.get("display_name") or "",
    )
    publications = assign_publication_ids(publications)
    session_id = session_dir.name
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": "1.0",
        "session_type": "scholar_impact",
        "session_id": session_id,
        "query": selected_author.get("display_name") or "",
        "selected_author": selected_author,
        "publications": publications,
        "citation_edges": [],
        "statistics": build_initial_statistics(publications),
        "deep_analysis_queue": [],
        "task_state": default_task_state(),
        "created_at": now,
        "updated_at": now,
    }


def save_scholar_session(session_dir: Path, session: dict[str, Any]):
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

Create `skills/scholar_impact_analyzer/SCHOLAR_SESSION_SCHEMA.md` with the session JSON shape from the "Data Model" section of this plan.

- [x] **Step 4: Run test**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q
```

Expected: `OK`.

- [x] **Step 5: Commit**

```bash
git add skills/scholar_impact_analyzer/scholar_pipeline.py skills/scholar_impact_analyzer/SCHOLAR_SESSION_SCHEMA.md tests/test_scholar_pipeline.py
git commit -m "Create scholar impact session pipeline" \
  -m "Scholar analysis needs its own session schema instead of overloading paper sessions. This commit adds the initial builder and JSON persistence layer." \
  -m "Constraint: Keep paper-level session behavior unchanged" \
  -m "Confidence: high" \
  -m "Scope-risk: moderate" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q"
```

---

## Task 4: Citation Expansion For Scholar Publications

**Files:**

- Modify: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Test: `tests/test_scholar_pipeline.py`

- [ ] **Step 1: Add tests for citation edge expansion**

Append to `ScholarPipelineTestCase`:

```python
    def test_expand_publication_citations_creates_edges(self):
        session = {
            "publications": [
                {
                    "id": "S001",
                    "title": "Target Paper",
                    "doi": "10.1000/target",
                    "unique_ids": {"DOI": "10.1000/target"},
                }
            ],
            "citation_edges": [],
            "statistics": {},
        }
        list_result = {
            "ok": True,
            "papers": [
                {
                    "title": "Citing Paper",
                    "year": 2025,
                    "venue": "ACM MobiCom",
                    "externalIds": {"DOI": "10.1000/citing"},
                    "authors": ["Fellow A"],
                    "source_url": "https://example.test/citing",
                }
            ],
        }

        with mock.patch.object(self.pipeline.LIST_PAPERS, "list_all_citations", return_value=list_result):
            updated = self.pipeline.expand_publication_citations(session, limit_per_publication=10)

        self.assertEqual(len(updated["citation_edges"]), 1)
        edge = updated["citation_edges"][0]
        self.assertEqual(edge["source_publication_id"], "S001")
        self.assertEqual(edge["citing_title"], "Citing Paper")
        self.assertEqual(edge["cited_publication_title"], "Target Paper")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q
```

Expected: fails because `LIST_PAPERS` and `expand_publication_citations` are undefined.

- [ ] **Step 3: Implement citation expansion**

Add to `scholar_pipeline.py`:

```python
LIST_PAPERS_PATH = ROOT / "skills" / "list_all_citations" / "list_papers.py"
LIST_PAPERS = load_module("scholar_list_papers", LIST_PAPERS_PATH)


def publication_query(publication: dict[str, Any]) -> str:
    return publication.get("doi") or (publication.get("unique_ids") or {}).get("DOI") or publication.get("title") or ""


def edge_key(edge: dict[str, Any]) -> tuple[str, str]:
    return (
        edge.get("source_publication_id") or "",
        edge.get("citing_doi") or edge.get("citing_title") or "",
    )


def normalize_citation_edge(source_publication: dict[str, Any], citing_paper: dict[str, Any], provider: str) -> dict[str, Any]:
    external_ids = citing_paper.get("externalIds") or {}
    authors = citing_paper.get("authors") or []
    normalized_authors = [
        item.get("name") if isinstance(item, dict) else item
        for item in authors
        if (item.get("name") if isinstance(item, dict) else item)
    ]
    return {
        "source_publication_id": source_publication.get("id"),
        "source_publication_doi": source_publication.get("doi") or (source_publication.get("unique_ids") or {}).get("DOI", ""),
        "cited_publication_title": source_publication.get("title") or "",
        "citing_title": citing_paper.get("title") or "",
        "citing_doi": external_ids.get("DOI", ""),
        "citing_year": citing_paper.get("year"),
        "citing_venue": citing_paper.get("venue") or "Unknown Venue",
        "citing_authors": normalized_authors,
        "provider": provider,
        "source_url": citing_paper.get("source_url") or "",
    }


def expand_publication_citations(session: dict[str, Any], limit_per_publication: int = 100) -> dict[str, Any]:
    existing = {edge_key(edge): edge for edge in session.get("citation_edges", [])}
    for publication in session.get("publications", []):
        query = publication_query(publication)
        if not query:
            continue
        payload = LIST_PAPERS.list_all_citations(query, limit=limit_per_publication)
        provider = payload.get("data_provider") or "unknown"
        for citing_paper in payload.get("papers", []):
            edge = normalize_citation_edge(publication, citing_paper, provider)
            existing[edge_key(edge)] = edge
    session["citation_edges"] = list(existing.values())
    session.setdefault("statistics", {})["citation_edge_count"] = len(session["citation_edges"])
    return session
```

- [ ] **Step 4: Run test**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/scholar_impact_analyzer/scholar_pipeline.py tests/test_scholar_pipeline.py
git commit -m "Expand scholar publications into citing papers" \
  -m "Scholar impact needs citation edges linking each author publication to papers that cite it. The pipeline now reuses the existing citation-source module and deduplicates edges per source paper." \
  -m "Constraint: Limit per publication prevents accidental full-network expansion during MVP" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q"
```

---

## Task 5: Scholar Statistics Aggregation

**Files:**

- Create: `skills/scholar_impact_analyzer/scholar_stats.py`
- Modify: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Test: `tests/test_scholar_stats.py`

- [ ] **Step 1: Write tests for publication, citing venue, and person-tag stats**

Create `tests/test_scholar_stats.py`:

```python
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_stats.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarStatsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = load_module(STATS_PATH, "test_scholar_stats")

    def test_build_scholar_statistics(self):
        publications = [
            {
                "id": "S001",
                "title": "Paper One",
                "year": 2024,
                "venue": "ACM MobiCom",
                "author_position": "first_author",
                "citation_count": 10,
            },
            {
                "id": "S002",
                "title": "Paper Two",
                "year": 2023,
                "venue": "IEEE Transactions on Mobile Computing",
                "author_position": "middle_author",
                "citation_count": 5,
            },
        ]
        citation_edges = [
            {
                "source_publication_id": "S001",
                "citing_title": "Citing One",
                "citing_venue": "ACM MobiCom",
                "citing_year": 2025,
                "citing_authors": ["Alice Fellow"],
            },
            {
                "source_publication_id": "S002",
                "citing_title": "Citing Two",
                "citing_venue": "Unknown Venue",
                "citing_year": 2025,
                "citing_authors": ["Bob"],
            },
        ]
        person_candidates = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "matched_paper_ids": ["C000001"],
                "status": "pending",
            }
        ]

        result = self.stats.build_scholar_statistics(publications, citation_edges, person_candidates)

        self.assertEqual(result["publication_count"], 2)
        self.assertEqual(result["first_author_publication_count"], 1)
        self.assertEqual(result["total_citation_count"], 15)
        self.assertEqual(result["citation_edge_count"], 2)
        self.assertEqual(result["top_publications"][0]["title"], "Paper One")
        self.assertEqual(result["person_tag_statistics"][0]["tag_label"], "ACM Fellow")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_stats -q
```

Expected: fails because `scholar_stats.py` does not exist.

- [ ] **Step 3: Implement statistics aggregation**

Create `skills/scholar_impact_analyzer/scholar_stats.py`:

```python
from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
IMPACT_CLI_PATH = ROOT / "skills" / "academic_impact_analyzer" / "impact_cli.py"
PERSON_CANDIDATES_PATH = ROOT / "skills" / "academic_impact_analyzer" / "person_candidates.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IMPACT_CLI = load_module("scholar_stats_impact_cli", IMPACT_CLI_PATH)
PERSON_CANDIDATES = load_module("scholar_stats_person_candidates", PERSON_CANDIDATES_PATH)


def venue_distribution(items: list[dict[str, Any]], venue_key: str) -> list[dict[str, Any]]:
    tier_index = IMPACT_CLI.build_venue_tier_index()
    counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for item in items:
        venue = item.get(venue_key) or item.get("venue") or "Unknown Venue"
        tier = IMPACT_CLI.classify_venue_tier(venue, tier_index)
        label = tier.get("tier_label") or "未匹配等级"
        counter[label] += 1
        examples.setdefault(label, [])
        title = item.get("title") or item.get("citing_title") or ""
        if title and len(examples[label]) < 5:
            examples[label].append(title)
    return [
        {"tier_label": label, "count": count, "examples": examples.get(label, [])}
        for label, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def person_tag_statistics(person_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = PERSON_CANDIDATES.TAG_LABELS
    result = []
    for tag_type, tag_label in labels.items():
        candidates = [item for item in person_candidates if item.get("tag_type") == tag_type]
        result.append({
            "tag_type": tag_type,
            "tag_label": tag_label,
            "count": len(candidates),
            "confirmed_count": sum(1 for item in candidates if item.get("status") == "confirmed"),
            "pending_count": sum(1 for item in candidates if item.get("status") == "pending"),
        })
    return result


def build_scholar_statistics(
    publications: list[dict[str, Any]],
    citation_edges: list[dict[str, Any]],
    person_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "publication_count": len(publications),
        "first_author_publication_count": sum(1 for item in publications if item.get("author_position") == "first_author"),
        "total_citation_count": sum(item.get("citation_count") or 0 for item in publications),
        "citation_edge_count": len(citation_edges),
        "publication_tiers": venue_distribution(publications, "venue"),
        "citing_venue_tiers": venue_distribution(citation_edges, "citing_venue"),
        "person_tag_statistics": person_tag_statistics(person_candidates),
        "yearly_citations": [
            {"year": year, "count": count}
            for year, count in sorted(Counter(edge.get("citing_year") for edge in citation_edges if edge.get("citing_year")).items())
        ],
        "top_publications": sorted(
            publications,
            key=lambda item: (-(item.get("citation_count") or 0), -(item.get("year") or 0), item.get("title") or ""),
        )[:10],
    }
```

- [ ] **Step 4: Wire stats into pipeline**

Modify `scholar_pipeline.py`:

```python
SCHOLAR_STATS_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "scholar_stats.py"
SCHOLAR_STATS = load_module("scholar_stats", SCHOLAR_STATS_PATH)
```

Replace `build_initial_statistics(publications)` with:

```python
SCHOLAR_STATS.build_scholar_statistics(publications, [], [])
```

After `expand_publication_citations`, recompute:

```python
session["statistics"] = SCHOLAR_STATS.build_scholar_statistics(
    session.get("publications", []),
    session.get("citation_edges", []),
    session.get("person_candidates", []),
)
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_stats tests.test_scholar_pipeline -q
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/scholar_impact_analyzer/scholar_stats.py skills/scholar_impact_analyzer/scholar_pipeline.py tests/test_scholar_stats.py tests/test_scholar_pipeline.py
git commit -m "Aggregate scholar-level impact statistics" \
  -m "Scholar sessions now summarize publication tiers, citing venue tiers, citation counts, and person-tag groups before any fulltext analysis is attempted." \
  -m "Constraint: Statistics must work from metadata alone" \
  -m "Rejected: Require PDF availability for statistics | blocks the fast CitationMaster-style view" \
  -m "Confidence: high" \
  -m "Scope-risk: moderate" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_stats tests.test_scholar_pipeline -q"
```

---

## Task 6: Web Service And Routes

**Files:**

- Create: `app/services/scholar_core.py`
- Modify: `app/main.py`
- Modify: `app/templates/index.html`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Write service tests**

Create `tests/test_scholar_web.py`:

```python
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app
from app.services import scholar_core


TEST_SESSION_ID = "test_scholar_session"
TEST_SESSION_DIR = scholar_core.SCHOLAR_SESSIONS_ROOT / TEST_SESSION_ID


class ScholarWebTestCase(unittest.TestCase):
    def tearDown(self):
        if TEST_SESSION_DIR.exists():
            shutil.rmtree(TEST_SESSION_DIR)

    def test_load_scholar_status(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [],
                    "citation_edges": [],
                    "statistics": {"publication_count": 0},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        payload = scholar_core.load_scholar_status(TEST_SESSION_ID)

        self.assertEqual(payload["session_id"], TEST_SESSION_ID)
        self.assertEqual(payload["selected_author"]["display_name"], "Chen Tian")

    def test_scholar_route_renders(self):
        TEST_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (TEST_SESSION_DIR / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_type": "scholar_impact",
                    "session_id": TEST_SESSION_ID,
                    "selected_author": {"display_name": "Chen Tian"},
                    "publications": [],
                    "citation_edges": [],
                    "statistics": {"publication_count": 0, "person_tag_statistics": []},
                    "task_state": {"active": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(app)

        response = client.get(f"/scholars/{TEST_SESSION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Chen Tian", response.text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_web -q
```

Expected: fails because `app.services.scholar_core` and `/scholars/{session_id}` do not exist.

- [ ] **Step 3: Implement service layer**

Create `app/services/scholar_core.py`:

```python
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"
SCHOLAR_SESSIONS_ROOT = PROJECT_ROOT / "data" / "scholar_sessions"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scholar_pipeline():
    return _load_module(
        SKILLS_ROOT / "scholar_impact_analyzer" / "scholar_pipeline.py",
        "academic_impact_web_scholar_pipeline",
    )


def resolve_scholar_session_dir(session_id: str) -> Path:
    session_dir = SCHOLAR_SESSIONS_ROOT / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"未找到学者会话目录: {session_id}")
    return session_dir


def load_scholar_status(session_id: str) -> dict[str, Any]:
    session_path = resolve_scholar_session_dir(session_id) / "session.json"
    return json.loads(session_path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Add FastAPI route**

Modify `app/main.py`:

```python
from app.services import impact_core, scholar_core
```

Add:

```python
@app.get("/scholars/{session_id}", response_class=HTMLResponse)
async def scholar_detail(request: Request, session_id: str):
    payload = scholar_core.load_scholar_status(session_id)
    return templates.TemplateResponse(
        request,
        "scholar_session.html",
        {
            "request": request,
            "session_id": session_id,
            "payload": payload,
            "payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
        },
    )
```

- [ ] **Step 5: Create scholar template**

Create `app/templates/scholar_session.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ payload.selected_author.display_name }} · 学者影响力分析</title>
    <link rel="stylesheet" href="/static/style.css" />
  </head>
  <body>
    <main class="page">
      <section class="panel">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Scholar Impact</p>
            <h1>{{ payload.selected_author.display_name }}</h1>
            <p class="muted">{{ payload.selected_author.affiliations | join(' / ') }}</p>
          </div>
        </div>
        <div class="stats stats-dense">
          <div class="stat"><span>论文数</span><strong>{{ payload.statistics.publication_count or 0 }}</strong></div>
          <div class="stat"><span>引用边</span><strong>{{ payload.statistics.citation_edge_count or 0 }}</strong></div>
          <div class="stat"><span>总引用数</span><strong>{{ payload.statistics.total_citation_count or 0 }}</strong></div>
          <div class="stat"><span>一作论文</span><strong>{{ payload.statistics.first_author_publication_count or 0 }}</strong></div>
        </div>
      </section>

      <section class="panel">
        <h2>论文统计</h2>
        <div class="status-chips">
          {% for group in payload.statistics.publication_tiers or [] %}
          <span class="chip">{{ group.tier_label }}: {{ group.count }}</span>
          {% endfor %}
        </div>
      </section>

      <section class="panel">
        <h2>引用统计</h2>
        <div class="status-chips">
          {% for group in payload.statistics.person_tag_statistics or [] %}
          <span class="chip">{{ group.tag_label }}: {{ group.count }}</span>
          {% endfor %}
        </div>
      </section>

      <section class="panel">
        <h2>论文列表</h2>
        <div class="table-shell">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>等级</th>
                <th>年份</th>
                <th>会议/期刊</th>
                <th>标题</th>
                <th>引用</th>
                <th>DOI/Unique ID</th>
              </tr>
            </thead>
            <tbody>
              {% for paper in payload.publications %}
              <tr>
                <td>{{ loop.index }}</td>
                <td>{{ paper.venue_tier.tier_label if paper.venue_tier else '-' }}</td>
                <td>{{ paper.year or '-' }}</td>
                <td>{{ paper.venue or '-' }}</td>
                <td>{{ paper.title }}</td>
                <td>{{ paper.citation_count or 0 }}</td>
                <td>{{ paper.doi or paper.unique_ids.DBLP or '-' }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <details>
          <summary>调试：原始 JSON</summary>
          <pre>{{ payload_json }}</pre>
        </details>
      </section>
    </main>
  </body>
</html>
```

- [ ] **Step 6: Run test**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_web -q
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add app/services/scholar_core.py app/main.py app/templates/scholar_session.html tests/test_scholar_web.py
git commit -m "Add scholar impact web shell" \
  -m "Scholar sessions now have a web route and template so the metadata-first report can be viewed separately from paper-level sessions." \
  -m "Constraint: Initial route renders existing session JSON and does not start background jobs yet" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_web -q"
```

---

## Task 7: Scholar Create Flow

**Files:**

- Modify: `app/services/scholar_core.py`
- Modify: `app/main.py`
- Modify: `app/templates/index.html`
- Test: `tests/test_scholar_web.py`

- [ ] **Step 1: Add create-session service test**

Append to `ScholarWebTestCase`:

```python
    def test_create_scholar_session_from_author_payload(self):
        author = {
            "display_name": "Chen Tian",
            "dblp_id": "94/1247-1",
            "affiliations": ["Nanjing University"],
        }
        fake_session = {
            "session_id": TEST_SESSION_ID,
            "session_type": "scholar_impact",
            "selected_author": author,
            "publications": [],
            "citation_edges": [],
            "statistics": {"publication_count": 0},
            "task_state": {"active": False},
        }

        with mock.patch.object(scholar_core, "make_scholar_session_id", return_value=TEST_SESSION_ID), \
             mock.patch.object(scholar_core.scholar_pipeline(), "build_scholar_session", return_value=fake_session):
            session_id = scholar_core.create_scholar_session(author)

        self.assertEqual(session_id, TEST_SESSION_ID)
        self.assertTrue((TEST_SESSION_DIR / "session.json").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_web -q
```

Expected: fails because `create_scholar_session` is undefined.

- [ ] **Step 3: Implement create service**

Add to `scholar_core.py`:

```python
import re
from datetime import datetime


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return re.sub(r"_+", "_", text).strip("_") or "scholar"


def make_scholar_session_id(display_name: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_scholar_{slugify(display_name)}"


def create_scholar_session(author: dict[str, Any]) -> str:
    session_id = make_scholar_session_id(author.get("display_name") or "")
    session_dir = SCHOLAR_SESSIONS_ROOT / session_id
    session = scholar_pipeline().build_scholar_session(author, session_dir)
    scholar_pipeline().save_scholar_session(session_dir, session)
    return session_id
```

- [ ] **Step 4: Add POST route for selected author**

Modify `app/main.py`:

```python
@app.post("/scholars/create")
async def create_scholar(
    display_name: str = Form(...),
    dblp_id: str = Form(""),
    openalex_id: str = Form(""),
    scopus_author_id: str = Form(""),
    affiliations: str = Form(""),
):
    author = {
        "display_name": display_name.strip(),
        "dblp_id": dblp_id.strip(),
        "openalex_id": openalex_id.strip(),
        "scopus_author_id": scopus_author_id.strip(),
        "affiliations": [item.strip() for item in affiliations.split("|") if item.strip()],
    }
    session_id = scholar_core.create_scholar_session(author)
    return RedirectResponse(url=f"/scholars/{session_id}", status_code=303)
```

- [ ] **Step 5: Add index form**

Modify `app/templates/index.html` near the existing paper query form:

```html
<section class="panel">
  <div class="panel-header">
    <div>
      <p class="eyebrow">Scholar Impact</p>
      <h2>学者影响力分析</h2>
    </div>
  </div>
  <form action="/scholars/create" method="post" class="stack">
    <label>
      作者英文名
      <input name="display_name" placeholder="Chen Tian" required />
    </label>
    <label>
      DBLP ID
      <input name="dblp_id" placeholder="94/1247-1" />
    </label>
    <label>
      Scopus Author ID
      <input name="scopus_author_id" placeholder="可选" />
    </label>
    <label>
      OpenAlex Author ID
      <input name="openalex_id" placeholder="可选" />
    </label>
    <button type="submit">创建学者分析</button>
  </form>
</section>
```

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_web -q
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add app/services/scholar_core.py app/main.py app/templates/index.html tests/test_scholar_web.py
git commit -m "Create scholar sessions from the web UI" \
  -m "The web app can now start a scholar impact report from a selected author identity, giving users a CitationMaster-style entry point without disturbing paper sessions." \
  -m "Constraint: MVP expects the user to provide a stable DBLP ID or external author ID" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_web -q"
```

---

## Task 8: High-Value Citation Queue

**Files:**

- Modify: `skills/scholar_impact_analyzer/scholar_stats.py`
- Modify: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Test: `tests/test_scholar_stats.py`

- [ ] **Step 1: Add tests for queue ranking**

Append to `ScholarStatsTestCase`:

```python
    def test_build_deep_analysis_queue_prioritizes_fellow_and_top_venue(self):
        citation_edges = [
            {
                "source_publication_id": "S001",
                "citing_title": "Fellow Citation",
                "citing_venue": "Unknown Venue",
                "citing_authors": ["Alice Fellow"],
            },
            {
                "source_publication_id": "S002",
                "citing_title": "Top Venue Citation",
                "citing_venue": "ACM MobiCom",
                "citing_authors": ["Regular Author"],
            },
        ]
        person_candidates = [
            {
                "name": "Alice Fellow",
                "tag_type": "acm_fellow",
                "tag_label": "ACM Fellow",
                "matched_paper_ids": [],
                "status": "pending",
            }
        ]

        queue = self.stats.build_deep_analysis_queue(citation_edges, person_candidates, limit=10)

        self.assertEqual(queue[0]["citing_title"], "Fellow Citation")
        self.assertIn("person_tag:ACM Fellow", queue[0]["reasons"])
        self.assertTrue(any(item["citing_title"] == "Top Venue Citation" for item in queue))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_stats -q
```

Expected: fails because `build_deep_analysis_queue` is undefined.

- [ ] **Step 3: Implement queue ranking**

Add to `scholar_stats.py`:

```python
def normalized_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def person_tag_by_author(person_candidates: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for candidate in person_candidates:
        result[normalized_name(candidate.get("name") or "")] = candidate.get("tag_label") or candidate.get("tag_type") or ""
    return result


def build_deep_analysis_queue(
    citation_edges: list[dict[str, Any]],
    person_candidates: list[dict[str, Any]],
    limit: int = 100,
) -> list[dict[str, Any]]:
    tag_map = person_tag_by_author(person_candidates)
    tier_index = IMPACT_CLI.build_venue_tier_index()
    ranked = []
    for edge in citation_edges:
        score = 0
        reasons = []
        for author in edge.get("citing_authors") or []:
            label = tag_map.get(normalized_name(author))
            if label:
                score += 50
                reasons.append(f"person_tag:{label}")
        tier = IMPACT_CLI.classify_venue_tier(edge.get("citing_venue") or "", tier_index)
        if tier.get("tier_label") in {"CCF A", "Top venue seed"}:
            score += 25
            reasons.append(f"venue:{tier.get('tier_label')}")
        if score <= 0:
            continue
        item = dict(edge)
        item["priority_score"] = score
        item["reasons"] = reasons
        ranked.append(item)
    return sorted(ranked, key=lambda item: (-item["priority_score"], item.get("citing_title") or ""))[:limit]
```

- [ ] **Step 4: Wire queue into pipeline**

In `scholar_pipeline.py`, after recomputing statistics:

```python
session["deep_analysis_queue"] = SCHOLAR_STATS.build_deep_analysis_queue(
    session.get("citation_edges", []),
    session.get("person_candidates", []),
    limit=100,
)
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_stats tests.test_scholar_pipeline -q
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/scholar_impact_analyzer/scholar_stats.py skills/scholar_impact_analyzer/scholar_pipeline.py tests/test_scholar_stats.py
git commit -m "Rank scholar citations for deep analysis" \
  -m "The scholar workflow should not download or analyze every citing paper. A priority queue selects Fellow and top-venue citations for later fulltext inspection." \
  -m "Rejected: Analyze every citation edge | too slow and PDF availability is unreliable" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_stats tests.test_scholar_pipeline -q"
```

---

## Task 9: Deep Citation Content Analysis Integration

**Files:**

- Modify: `skills/scholar_impact_analyzer/scholar_pipeline.py`
- Modify: `app/templates/scholar_session.html`
- Test: `tests/test_scholar_pipeline.py`

- [ ] **Step 1: Add tests for strong evidence normalization**

Append to `ScholarPipelineTestCase`:

```python
    def test_normalize_deep_analysis_finding_marks_long_positive_fellow_citation(self):
        edge = {
            "source_publication_id": "S001",
            "citing_title": "Fellow Citation",
            "citing_authors": ["Alice Fellow"],
        }
        finding = {
            "citation_text": "This influential system changed the way we build network simulators. " * 3,
            "aspect": "method",
            "stance": "positive",
            "function": "引用者采用了目标工作的核心方法。",
            "reason": "正文明确肯定并采用该方法。",
            "confidence": 0.91,
        }

        evidence = self.pipeline.normalize_strong_evidence(edge, finding, person_tag_labels=["ACM Fellow"])

        self.assertTrue(evidence["long_context_100_chars"])
        self.assertTrue(evidence["positive_evaluation"])
        self.assertTrue(evidence["fellow_strong_citation"])
        self.assertEqual(evidence["aspect"], "method")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline -q
```

Expected: fails because `normalize_strong_evidence` is undefined.

- [ ] **Step 3: Implement strong evidence normalization**

Add to `scholar_pipeline.py`:

```python
def normalize_strong_evidence(edge: dict[str, Any], finding: dict[str, Any], person_tag_labels: list[str]) -> dict[str, Any]:
    citation_text = finding.get("citation_text") or ""
    positive = (finding.get("stance") or "").lower() == "positive"
    fellow = any("Fellow" in label or "院士" in label or "Turing" in label or "Prize" in label for label in person_tag_labels)
    return {
        "source_publication_id": edge.get("source_publication_id"),
        "citing_title": edge.get("citing_title"),
        "citing_authors": edge.get("citing_authors", []),
        "person_tag_labels": person_tag_labels,
        "citation_text": citation_text,
        "citation_char_count": len(citation_text),
        "long_context_100_chars": len(citation_text) >= 100,
        "positive_evaluation": positive,
        "fellow_strong_citation": fellow and len(citation_text) >= 100 and positive,
        "aspect": finding.get("aspect") or "",
        "function": finding.get("function") or "",
        "reason": finding.get("reason") or "",
        "confidence": finding.get("confidence"),
    }
```

- [ ] **Step 4: Add scholar page strong evidence section**

Add to `app/templates/scholar_session.html` after citation stats:

```html
<section class="panel">
  <h2>强引用证据</h2>
  {% if payload.strong_evidence %}
  <div class="cards">
    {% for evidence in payload.strong_evidence %}
    <article class="card">
      <div class="card-header">
        <strong>{{ evidence.citing_title }}</strong>
        <span class="chip">{{ evidence.aspect or '-' }}</span>
      </div>
      <div class="card-metrics">
        <span class="chip">字数：{{ evidence.citation_char_count }}</span>
        <span class="chip">Fellow 强引用：{{ '是' if evidence.fellow_strong_citation else '否' }}</span>
        <span class="chip">正向评价：{{ '是' if evidence.positive_evaluation else '否' }}</span>
      </div>
      <p>{{ evidence.function }}</p>
      <p class="evidence-excerpt">{{ evidence.citation_text }}</p>
    </article>
    {% endfor %}
  </div>
  {% else %}
  <p class="muted">当前还没有完成全文语义分析的强引用证据。</p>
  {% endif %}
</section>
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline tests.test_scholar_web -q
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/scholar_impact_analyzer/scholar_pipeline.py app/templates/scholar_session.html tests/test_scholar_pipeline.py
git commit -m "Represent strong scholar citation evidence" \
  -m "Deep citation analysis needs to turn raw findings into scholar-level claims such as long Fellow citations and positive evaluation." \
  -m "Constraint: This task normalizes completed analysis results but does not yet automate PDF acquisition" \
  -m "Confidence: medium" \
  -m "Scope-risk: narrow" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_scholar_pipeline tests.test_scholar_web -q"
```

---

## Task 10: Verification And Demo Run

**Files:**

- Modify: `README.md`
- Create: `docs/ops/scholar-impact.md`

- [ ] **Step 1: Add ops documentation**

Create `docs/ops/scholar-impact.md`:

```markdown
# Scholar Impact Workflow

## Required IDs

Prefer DBLP ID, Scopus Author ID, or OpenAlex Author ID. Name-only search is only for finding candidates.

## Required Environment

Use Scopus when available:

```bash
export ACADEMIC_IMPACT_CITATION_SOURCE=scopus
export ELSEVIER_API_KEY="..."
```

Use OpenAlex fallback when Scopus is unavailable:

```bash
export ACADEMIC_IMPACT_CITATION_SOURCE=openalex
```

## MVP Workflow

1. Open the web app.
2. Create a scholar session with author name and DBLP ID.
3. Review publication statistics.
4. Expand citations with a conservative limit per publication.
5. Review Fellow and venue statistics.
6. Select high-value citation cases for PDF upload or download.
7. Run fulltext analysis only for selected cases.

## Expected Runtime

Metadata-only statistics should finish in minutes for tens of publications.
Deep fulltext analysis should be treated as a background batch. A queue of 100 citing papers may take 30 to 90 minutes depending on PDF availability and LLM latency.
```

- [ ] **Step 2: Add README pointer**

Append to `README.md`:

```markdown
## Scholar Impact Mode

Scholar impact mode extends the paper-level workflow from one target paper to one target researcher. It first builds metadata statistics for the researcher's publications and citation network, then performs fulltext semantic analysis on selected high-value citing papers.

Operational notes: [docs/ops/scholar-impact.md](docs/ops/scholar-impact.md)
```

- [ ] **Step 3: Run full test suite used by this repo**

Run:

```bash
PYTHONPATH=.:${PYTHONPATH:-} python3 -m unittest \
  tests.test_web_attach_pdf \
  tests.test_citation_sources \
  tests.test_background_tasks \
  tests.test_venue_statistics \
  tests.test_compare_analysis_scopes \
  tests.test_analysis_scope \
  tests.test_analyze_fulltext \
  tests.test_fulltext_gold_workflow \
  tests.test_scholar_author_sources \
  tests.test_scholar_pipeline \
  tests.test_scholar_stats \
  tests.test_scholar_web \
  -q
```

Expected: all tests pass.

- [ ] **Step 4: Run compile and diff checks**

Run:

```bash
python3 -m compileall app skills scripts
git diff --check
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ops/scholar-impact.md
git commit -m "Document scholar impact operations" \
  -m "The scholar workflow depends on author IDs, metadata source selection, and conservative fulltext analysis queues, so operators need a short runbook before demo use." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: PYTHONPATH=.:\\${PYTHONPATH:-} python3 -m unittest tests.test_web_attach_pdf tests.test_citation_sources tests.test_background_tasks tests.test_venue_statistics tests.test_compare_analysis_scopes tests.test_analysis_scope tests.test_analyze_fulltext tests.test_fulltext_gold_workflow tests.test_scholar_author_sources tests.test_scholar_pipeline tests.test_scholar_stats tests.test_scholar_web -q" \
  -m "Tested: python3 -m compileall app skills scripts" \
  -m "Tested: git diff --check"
```

---

## Risk Register

### Author Disambiguation

Risk: name-only search can merge multiple scholars.

Mitigation: MVP requires user confirmation of DBLP ID, Scopus Author ID, or OpenAlex Author ID before building a session.

### Citation Explosion

Risk: expanding every publication can produce thousands of citing papers.

Mitigation: use `limit_per_publication`, cache provider responses, and prioritize deep analysis queue.

### API Quotas

Risk: Scopus Search default quota is finite and resets every seven days; OpenAlex free tier also has daily usage constraints.

Mitigation: cache responses, show provider counts in session JSON, and allow OpenAlex fallback.

### PDF Availability

Risk: metadata APIs do not guarantee fulltext access.

Mitigation: metadata statistics are useful without PDF; deep analysis operates only on downloaded or uploaded PDFs.

### LLM Runtime

Risk: fulltext semantic analysis is slow for large queues.

Mitigation: background jobs and queue limits; default to high-value citations only.

---

## Self-Review

### Spec Coverage

- NASA-style author search: Tasks 1, 6, 7.
- Scholar publication list: Tasks 2, 3.
- Paper venue/CCF statistics: Task 5.
- Fellow/person-tag citation statistics: Task 5.
- High-value fulltext content analysis: Tasks 8, 9.
- Runtime and PDF constraints: Risk Register and Task 10.

### Placeholder Scan

The plan avoids deferred-detail markers and vague "write tests" instructions. Each code task includes file paths, test commands, and expected outcomes.

### Type Consistency

The plan uses `selected_author`, `publications`, `citation_edges`, `statistics`, `deep_analysis_queue`, and `strong_evidence` consistently across pipeline, service, and template tasks.

---

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-05-03-scholar-impact-analysis.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using checkpoints.
