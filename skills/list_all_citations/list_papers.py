import sys
import json
import os
import re
import time
import requests
import urllib.parse
import hashlib
import unicodedata
from pathlib import Path
from typing import Optional

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CACHE_DIR = Path("/tmp/academic_impact_http_cache")


def normalize_arxiv_id(query: str) -> str:
    query = (query or "").strip()
    query = query.replace("10.48550/arXiv.", "")
    query = query.replace("10.48550/arxiv.", "")
    return query.replace("arXiv:", "").replace("arxiv:", "").strip()


def looks_like_arxiv_id(query: str) -> bool:
    query = normalize_arxiv_id(query)
    return bool(query) and query[0].isdigit() and "." in query


def get_cache_path(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def load_cached_response(url: str):
    path = get_cache_path(url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("url") != url or payload.get("status_code") != 200:
            return None
        return payload
    except Exception:
        return None


def save_cached_response(url: str, res):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": url,
            "status_code": res.status_code,
            "text": res.text,
        }
        get_cache_path(url).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


class CachedResponse:
    def __init__(self, payload: dict):
        self.status_code = payload["status_code"]
        self.text = payload["text"]

    def json(self):
        return json.loads(self.text)


def safe_get(url, retries=5, sleep_sec=3):
    cached = load_cached_response(url)
    if cached:
        return CachedResponse(cached)

    last_err = None
    backoff_schedule = [3, 8, 15, 30, 45]
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                save_cached_response(url, r)
                return r
            if r.status_code == 429:
                last_err = f"[attempt {attempt}] HTTP 429 rate limited"
                time.sleep(backoff_schedule[min(attempt - 1, len(backoff_schedule) - 1)])
                continue
            last_err = f"[attempt {attempt}] HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_err = f"[attempt {attempt}] {type(e).__name__}: {e!s}" or repr(e)
            time.sleep(sleep_sec)
    raise RuntimeError(last_err or "unknown request error")

# ==========================================
# OpenAlex 备用源逻辑 (Fallback)
# ==========================================
OPENALEX_HEADERS = {"User-Agent": "mailto:youdeng78@gmail.com"} 
ELSEVIER_SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
TITLE_MATCH_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "for",
    "with",
    "to",
    "in",
    "on",
    "all",
    "you",
    "need",
}


def normalize_query_for_lookup(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return ""
    lower = query.lower()
    if lower.startswith("10.") or lower.startswith("arxiv:") or lower.startswith("10.48550/arxiv."):
        return query
    if "/" in query and not query.endswith(".pdf"):
        return query
    query = re.sub(r"\.pdf$", "", query, flags=re.I)
    query = query.replace("_", " ")
    query = re.sub(r"\s+", " ", query).strip()
    return query


def normalize_title_match_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    without_marks = without_marks.replace("_", " ")
    without_marks = re.sub(r"[^a-zA-Z0-9]+", " ", without_marks).lower()
    return re.sub(r"\s+", " ", without_marks).strip()


def title_match_tokens(text: str) -> set:
    return {
        token
        for token in normalize_title_match_text(text).split()
        if token and token not in TITLE_MATCH_STOPWORDS
    }


def title_match_score(query: str, title: str) -> float:
    query_text = normalize_title_match_text(query)
    title_text = normalize_title_match_text(title)
    if query_text and query_text == title_text:
        return 1.0
    query_tokens = title_match_tokens(query)
    title_tokens = title_match_tokens(title)
    if not query_tokens or not title_tokens:
        return 0.0
    overlap = query_tokens & title_tokens
    return len(overlap) / max(1, len(query_tokens))


def openalex_title_matches_query(query: str, title: str) -> bool:
    query_tokens = title_match_tokens(query)
    if len(query_tokens) <= 2:
        return title_match_score(query, title) >= 0.8
    return title_match_score(query, title) >= 0.55


def openalex_work_url(paper_id: str) -> str:
    paper_id = str(paper_id or "").strip()
    if paper_id.startswith("http://") or paper_id.startswith("https://"):
        return paper_id
    return f"https://openalex.org/{paper_id}" if paper_id else "https://openalex.org/"


def title_lookup_variants(query: str) -> list:
    variants = []

    def add(value: str):
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if value and value not in variants:
            variants.append(value)

    add(query)
    normalized = normalize_query_for_lookup(query)
    add(normalized)
    # Some PDF filenames drop the accent and the trailing "e" from "Moiré".
    # OpenAlex title search is stricter than Semantic Scholar, so keep a
    # narrow domain spelling variant but still validate returned titles below.
    if re.search(r"(?i)\bmoir(?:tracker|\s+pattern\b)", normalized):
        add(re.sub(r"(?i)\bmoir(?=tracker\b|\s+pattern\b)", "Moiré", normalized))
        add(re.sub(r"(?i)\bmoir(?=tracker\b|\s+pattern\b)", "Moire", normalized))
    return variants


def safe_get_openalex(url):
    """专门为 OpenAlex 准备的请求函数，同样套用重试逻辑"""
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=OPENALEX_HEADERS, timeout=20)
            if r.status_code == 200:
                return r
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return None


def build_url_with_params(url: str, params: dict) -> str:
    return f"{url}?{urllib.parse.urlencode(params)}"


def elsevier_headers():
    api_key = os.environ.get("ELSEVIER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 ELSEVIER_API_KEY，无法使用 Scopus 来源。")
    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": api_key,
        "User-Agent": HEADERS["User-Agent"],
    }
    insttoken = os.environ.get("ELSEVIER_INSTTOKEN", "").strip()
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    return headers


def safe_get_elsevier(url: str, params: dict, retries=3, sleep_sec=3):
    cache_url = build_url_with_params(url, params)
    cached = load_cached_response(cache_url)
    if cached:
        return CachedResponse(cached)

    last_err = None
    backoff_schedule = [3, 8, 15]
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=elsevier_headers(), params=params, timeout=30)
            if r.status_code == 200:
                save_cached_response(cache_url, r)
                return r
            if r.status_code == 429:
                last_err = f"[attempt {attempt}] Elsevier HTTP 429 rate limited"
                time.sleep(backoff_schedule[min(attempt - 1, len(backoff_schedule) - 1)])
                continue
            last_err = f"[attempt {attempt}] Elsevier HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            last_err = f"[attempt {attempt}] {type(e).__name__}: {e!s}" or repr(e)
            time.sleep(sleep_sec)
    raise RuntimeError(last_err or "unknown Elsevier request error")


def openalex_venue_name(work: dict):
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    return source.get("display_name")


def scopus_entry_links(entry: dict):
    links = entry.get("link") or []
    if isinstance(links, dict):
        links = [links]
    return links if isinstance(links, list) else []


def scopus_link(entry: dict, ref: str):
    for link in scopus_entry_links(entry):
        if link.get("@ref") == ref and link.get("@href"):
            return link.get("@href")
    return ""


def parse_scopus_id(entry: dict) -> str:
    identifier = entry.get("dc:identifier") or ""
    if identifier.startswith("SCOPUS_ID:"):
        return identifier.split(":", 1)[1]
    eid = entry.get("eid") or ""
    if eid.startswith("2-s2.0-"):
        return eid.rsplit("-", 1)[-1]
    return ""


def parse_scopus_year(entry: dict):
    cover_date = entry.get("prism:coverDate") or ""
    if len(cover_date) >= 4 and cover_date[:4].isdigit():
        return int(cover_date[:4])
    pub_year = entry.get("pubyear") or ""
    if str(pub_year).isdigit():
        return int(pub_year)
    return None


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def paper_doi(paper: dict) -> str:
    return ((paper.get("externalIds") or {}).get("DOI") or "").strip()


def author_name(author) -> str:
    if isinstance(author, dict):
        return (author.get("name") or "").strip()
    return str(author or "").strip()


def looks_like_abbreviated_author(name: str) -> bool:
    parts = [part for part in re.split(r"\s+", (name or "").strip()) if part]
    if len(parts) != 2:
        return False
    first, second = parts
    return (
        len(first.rstrip(".")) > 1
        and len(second.rstrip(".")) == 1
        and second.rstrip(".").isalpha()
    )


def should_enrich_authors(authors) -> bool:
    names = [author_name(author) for author in authors or [] if author_name(author)]
    if not names:
        return True
    if len(names) == 1 and looks_like_abbreviated_author(names[0]):
        return True
    return False


def fetch_openalex_work_by_doi(doi: str) -> Optional[dict]:
    doi = (doi or "").strip()
    if not doi:
        return None
    url = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}"
    response = safe_get_openalex(url)
    if not response:
        return None
    data = response.json()
    if not data.get("id"):
        return None
    return data


def openalex_author_rows(work: dict) -> list:
    rows = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = (author.get("display_name") or author.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "id": author.get("id") or "",
                "institutions": authorship.get("institutions") or [],
            }
        )
    return rows


def enrich_scopus_citing_paper_authors(citing: dict) -> dict:
    if not should_enrich_authors(citing.get("authors") or []):
        return citing
    doi = paper_doi(citing)
    if not doi:
        return citing
    enriched = fetch_openalex_work_by_doi(doi)
    author_rows = openalex_author_rows(enriched or {})
    full_names = [author["name"] for author in author_rows]
    if not full_names:
        return citing
    citing = dict(citing)
    citing["authors"] = [{"name": name} for name in full_names]
    citing["author_details"] = build_openalex_author_details(
        {"authors": author_rows}
    )
    citing["author_enrichment_source"] = "OpenAlex DOI"
    return citing


def normalize_scopus_entry(entry: dict) -> dict:
    doi = entry.get("prism:doi") or ""
    scopus_id = parse_scopus_id(entry)
    eid = entry.get("eid") or ""
    source_url = scopus_link(entry, "scopus") or entry.get("prism:url") or ""
    creator = entry.get("dc:creator") or ""
    authors = [{"name": creator}] if creator else []
    external_ids = {}
    if doi:
        external_ids["DOI"] = doi
    if scopus_id:
        external_ids["Scopus"] = scopus_id
    if eid:
        external_ids["EID"] = eid
    return {
        "title": entry.get("dc:title", ""),
        "year": parse_scopus_year(entry),
        "venue": entry.get("prism:publicationName") or entry.get("prism:aggregationType") or "Unknown Venue",
        "externalIds": external_ids,
        "authors": authors,
        "source_url": source_url,
        "citedby_count": parse_int(entry.get("citedby-count")),
    }


def is_valid_scopus_paper(paper: dict) -> bool:
    external_ids = paper.get("externalIds") or {}
    return bool((paper.get("title") or "").strip()) and bool(
        external_ids.get("DOI")
        or external_ids.get("EID")
        or external_ids.get("Scopus")
        or external_ids.get("ScopusID")
    )


def escape_scopus_title_query(title: str) -> str:
    return str(title or "").replace('"', " ")


def scopus_search(query: str, *, count: int = 25, start: int = 0, field: str = ""):
    params = {
        "query": query,
        "count": max(1, min(int(count or 25), 200)),
        "start": max(0, int(start or 0)),
        "httpAccept": "application/json",
    }
    if field:
        params["field"] = field
    r = safe_get_elsevier(ELSEVIER_SCOPUS_SEARCH_URL, params)
    return r.json().get("search-results", {})


def resolve_paper_scopus(query: str):
    query = normalize_query_for_lookup(query)
    if query.lower().startswith("10.48550/arxiv."):
        query = normalize_arxiv_id(query)
    if "/" in query or query.startswith("10."):
        scopus_queries = [f"DOI({query})"]
    else:
        scopus_queries = [
            f'TITLE("{escape_scopus_title_query(candidate)}")'
            for candidate in title_lookup_variants(query)
        ]
    fields = "dc:title,prism:doi,citedby-count,prism:coverDate,prism:publicationName,dc:identifier,eid,link"
    first_invalid_paper = None
    for scopus_query in scopus_queries:
        data = scopus_search(scopus_query, count=3, field=fields)
        entries = data.get("entry") or []
        for entry in entries:
            paper = normalize_scopus_entry(entry)
            if not is_valid_scopus_paper(paper):
                first_invalid_paper = first_invalid_paper or paper
                continue
            if not ("/" in query or query.startswith("10.")):
                title = paper.get("title", "")
                if not (
                    openalex_title_matches_query(query, title)
                    or any(openalex_title_matches_query(candidate, title) for candidate in title_lookup_variants(query))
                ):
                    continue
            return {
                "paperId": paper["externalIds"].get("EID") or paper["externalIds"].get("Scopus") or paper["externalIds"].get("DOI"),
                "title": paper.get("title", ""),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "externalIds": paper.get("externalIds", {}),
                "citationCount": paper.get("citedby_count", 0),
                "influentialCitationCount": 0,
                "source_url": paper.get("source_url", ""),
            }
    if first_invalid_paper is not None:
        raise RuntimeError(f"[Scopus] 未找到有效论文元数据: {query}")
    raise RuntimeError(f"[Scopus] 未找到论文: {query}")


def scopus_reference_queries(target: dict):
    external_ids = target.get("externalIds") or {}
    queries = []
    eid = external_ids.get("EID") or target.get("paperId", "")
    scopus_id = external_ids.get("Scopus") or external_ids.get("ScopusID") or parse_scopus_id({"eid": eid})
    doi = external_ids.get("DOI")
    title = target.get("title")
    if eid:
        queries.append(f"REFEID({eid})")
    if scopus_id and scopus_id != eid:
        queries.append(f"REFEID({scopus_id})")
    if doi:
        queries.append(f"REFDOI({doi})")
    if title:
        escaped = title.replace('"', " ")
        queries.append(f'REF("{escaped}")')
    return queries


def fetch_citations_scopus(target: dict, fetch_limit: int = 100):
    fields = "dc:title,prism:doi,prism:coverDate,prism:publicationName,dc:identifier,eid,dc:creator,citedby-count,link"
    page_size = 200
    desired = max(1, int(fetch_limit or page_size))
    last_error = None
    for scopus_query in scopus_reference_queries(target):
        rows = []
        start = 0
        try:
            while len(rows) < desired:
                batch_size = min(page_size, desired - len(rows))
                data = scopus_search(scopus_query, count=batch_size, start=start, field=fields)
                entries = data.get("entry") or []
                if not entries:
                    break
                rows.extend({"citingPaper": normalize_scopus_entry(entry)} for entry in entries)
                if len(entries) < batch_size:
                    break
                start += batch_size
            if rows:
                return rows
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise RuntimeError(f"[Scopus] cited-by list 拉取失败: {last_error}")
    return []

def resolve_paper_openalex(query: str):
    """使用 OpenAlex 查找目标论文"""
    query = normalize_query_for_lookup(query)
    
    # 尝试按 DOI 查找
    if "/" in query or query.startswith("10."):
        # OpenAlex 的 DOI 查询格式：https://api.openalex.org/works/https://doi.org/10.xxx
        url = f"https://api.openalex.org/works/https://doi.org/{query}"
        r = safe_get_openalex(url)
        if r:
            data = r.json()
            return {
                "paperId": data.get("id"), # OpenAlex 的 ID, 如 https://openalex.org/W2741809807
                "title": data.get("title", ""),
                "year": data.get("publication_year"),
                "venue": openalex_venue_name(data),
                "externalIds": {"DOI": data.get("doi", "").replace("https://doi.org/", "")},
                "citationCount": data.get("cited_by_count", 0),
            }
            
    # 按标题搜索
    for search_query in title_lookup_variants(query):
        search_url = f"https://api.openalex.org/works?search={urllib.parse.quote(search_query)}&per-page=5"
        r = safe_get_openalex(search_url)
        if not r or not r.json().get("results"):
            continue
        for data in r.json()["results"]:
            title = data.get("title", "")
            if not (
                openalex_title_matches_query(query, title)
                or openalex_title_matches_query(search_query, title)
            ):
                continue
            return {
                "paperId": data.get("id"),
                "title": title,
                "year": data.get("publication_year"),
                "venue": openalex_venue_name(data),
                "externalIds": {"DOI": data.get("doi", "").replace("https://doi.org/", "") if data.get("doi") else ""},
                "citationCount": data.get("cited_by_count", 0),
            }
    raise RuntimeError(f"[OpenAlex Fallback] 未找到论文: {query}")

def fetch_citations_openalex(openalex_id: str, fetch_limit: int = 100):
    """使用 OpenAlex 拉取引用文献"""
    all_rows = []
    # OpenAlex 使用游标 (cursor) 分页
    cursor = "*"
    
    while len(all_rows) < fetch_limit:
        url = f"https://api.openalex.org/works?filter=cites:{openalex_id}&per-page=100&cursor={cursor}"
        r = safe_get_openalex(url)
        if not r:
            break
            
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
            
        for work in results:
            # 将 OpenAlex 的数据格式映射为你原本脚本需要的格式
            all_rows.append({
                "citingPaper": {
                    "title": work.get("title", "Unknown Title"),
                    "year": work.get("publication_year"),
                    "venue": openalex_venue_name(work) or "Unknown Venue",
                    "externalIds": {"DOI": work.get("doi", "").replace("https://doi.org/", "") if work.get("doi") else ""},
                    "authors": [
                        {
                            "name": a.get("author", {}).get("display_name"),
                            "id": a.get("author", {}).get("id"),
                            "institutions": [
                                {
                                    "display_name": institution.get("display_name"),
                                    "id": institution.get("id"),
                                }
                                for institution in (a.get("institutions") or [])
                                if institution.get("display_name")
                            ],
                        }
                        for a in work.get("authorships", [])
                    ]
                }
            })
            
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
            
    return all_rows

def resolve_paper(query: str):
    query = normalize_query_for_lookup(query)

    # arXiv DOI alias
    if query.lower().startswith("10.48550/arxiv."):
        query = normalize_arxiv_id(query)

    # DOI
    if "/" in query or query.startswith("10."):
        paper_id = f"DOI:{query}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=paperId,title,year,venue,externalIds"
        r = safe_get(url)
        data = r.json()
        if data.get("paperId"):
            return {
                "paperId": data["paperId"],
                "title": data.get("title", ""),
                "year": data.get("year"),
                "venue": data.get("venue"),
                "externalIds": data.get("externalIds", {}),
                "citationCount": data.get("citationCount"),
                "influentialCitationCount": data.get("influentialCitationCount"),
            }
        raise RuntimeError(f"无法根据 DOI 定位论文: {query}")

    # arXiv
    if looks_like_arxiv_id(query):
        paper_id = f"ARXIV:{normalize_arxiv_id(query)}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=paperId,title,year,venue,externalIds,citationCount,influentialCitationCount"
        r = safe_get(url)
        data = r.json()
        if data.get("paperId"):
            return {
                "paperId": data["paperId"],
                "title": data.get("title", ""),
                "year": data.get("year"),
                "venue": data.get("venue"),
                "externalIds": data.get("externalIds", {}),
                "citationCount": data.get("citationCount"),
                "influentialCitationCount": data.get("influentialCitationCount"),
            }

    # 标题搜索
    search_url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote(query)}&limit=3&fields=title,year,venue,externalIds,citationCount,influentialCitationCount"
    )
    r = safe_get(search_url)
    data = r.json().get("data", [])
    if not data:
        raise RuntimeError(f"未找到论文: {query}")

    best = data[0]
    return {
        "paperId": best["paperId"],
        "title": best.get("title", ""),
        "year": best.get("year"),
        "venue": best.get("venue"),
        "externalIds": best.get("externalIds", {}),
        "citationCount": best.get("citationCount"),
        "influentialCitationCount": best.get("influentialCitationCount"),
    }


def fetch_citations(paper_id: str, fetch_limit: int = 100):
    page_size = 100
    desired = max(page_size, int(fetch_limit or page_size))
    all_rows = []
    offset = 0
    while len(all_rows) < desired:
        batch_limit = min(page_size, desired - len(all_rows))
        url = (
            f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
            "?fields=title,year,venue,externalIds,authors"
            f"&limit={batch_limit}&offset={offset}"
        )
        r = safe_get(url)
        data = r.json().get("data", [])
        if not data:
            break
        all_rows.extend(data)
        if len(data) < batch_limit:
            break
        offset += batch_limit
    return all_rows


def dedupe_papers(papers):
    result = []
    seen = set()
    for paper in papers:
        external_ids = paper.get("externalIds") or {}
        key = (
            external_ids.get("CorpusId")
            or external_ids.get("DOI")
            or external_ids.get("ArXiv")
            or external_ids.get("EID")
            or external_ids.get("Scopus")
            or external_ids.get("ScopusID")
            or paper.get("title", "").strip().lower()
        )
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result


def sort_papers(papers, sort_by: str = "recent"):
    sort_by = (sort_by or "recent").strip().lower()
    if sort_by == "oldest":
        return sorted(papers, key=lambda x: (x.get("year") is None, x.get("year"), x.get("title", "")))
    if sort_by == "title":
        return sorted(papers, key=lambda x: (x.get("title", "").lower(), x.get("year") is None, x.get("year")))
    return sorted(
        papers,
        key=lambda x: (x.get("year") is None, -(x.get("year") or -1), x.get("title", "").lower()),
    )


def build_semantic_scholar_author_details(citing: dict):
    details = []
    for author in citing.get("authors", []) or []:
        name = (author.get("name") or "").strip()
        if not name:
            continue
        author_id = author.get("authorId")
        source_url = (
            f"https://www.semanticscholar.org/author/{author_id}"
            if author_id else
            f"https://www.semanticscholar.org/search?q={urllib.parse.quote(name)}"
        )
        details.append({
            "name": name,
            "author_id": str(author_id) if author_id is not None else "",
            "source_url": source_url,
            "institutions": [],
        })
    return details


def build_openalex_author_details(citing: dict):
    details = []
    for author in citing.get("authors", []) or []:
        name = (author.get("name") or "").strip()
        if not name:
            continue
        source_url = author.get("id") or f"https://openalex.org/authors?search={urllib.parse.quote(name)}"
        institutions = []
        raw_institutions = author.get("institutions") or author.get("affiliations") or []
        for item in raw_institutions:
            display_name = (item.get("display_name") or item.get("name") or "").strip() if isinstance(item, dict) else str(item or "").strip()
            if display_name and display_name not in institutions:
                institutions.append(display_name)
        details.append({
            "name": name,
            "author_id": (author.get("id") or "").strip(),
            "source_url": source_url,
            "institutions": institutions,
        })
    return details


def build_scopus_author_details(citing: dict):
    details = []
    for author in citing.get("authors", []) or []:
        name = (author.get("name") or "").strip() if isinstance(author, dict) else str(author or "").strip()
        if not name:
            continue
        details.append({
            "name": name,
            "author_id": "",
            "source_url": f"https://www.scopus.com/results/authorNamesList.uri?name={urllib.parse.quote(name)}",
            "institutions": [],
        })
    return details

def list_all_citations(query: str, limit: Optional[int] = None, sort_by: str = "recent", fetch_limit: Optional[int] = None):
    #target = resolve_paper(query)
    #paper_id = target["paperId"]
    desired_limit = max(1, int(limit or 100))
    desired_fetch = max(desired_limit, int(fetch_limit or max(100, min(desired_limit * 5, 500))))
    source_preference = os.environ.get("ACADEMIC_IMPACT_CITATION_SOURCE", "auto").strip().lower()

    # ==========================================
    # 1. 选择引用论文列表数据源
    # ==========================================
    if source_preference in {"openalex", "oa"}:
        target = resolve_paper_openalex(query)
        paper_id = target["paperId"]
        data = fetch_citations_openalex(paper_id, fetch_limit=desired_fetch)
        url = openalex_work_url(paper_id)
        used_source = "OpenAlex"
    elif source_preference in {"scopus", "elsevier"}:
        target = resolve_paper_scopus(query)
        data = fetch_citations_scopus(target, fetch_limit=desired_fetch)
        url = target.get("source_url") or "https://www.scopus.com/"
        used_source = "Scopus"
    elif source_preference in {"semantic_scholar", "semanticscholar", "s2"}:
        target = resolve_paper(query)
        paper_id = target["paperId"]
        data = fetch_citations(paper_id, fetch_limit=desired_fetch)
        url = (
            f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
            "?fields=title,year,venue,externalIds,authors"
        )
        used_source = "Semantic Scholar"

    # ==========================================
    # 2. 自动模式：Semantic Scholar 失败则降级使用 OpenAlex
    # ==========================================
    else:
        try:
            target = resolve_paper(query)
            paper_id = target["paperId"]
            data = fetch_citations(paper_id, fetch_limit=desired_fetch)
            url = (
                f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
                "?fields=title,year,venue,externalIds,authors"
            )
            used_source = "Semantic Scholar"
        except Exception as e:
            print(f"[WARN] Semantic Scholar 请求失败 ({str(e)}), 自动切换至 OpenAlex 备用源...", file=sys.stderr)
            target = resolve_paper_openalex(query)
            paper_id = target["paperId"]
            data = fetch_citations_openalex(paper_id, fetch_limit=desired_fetch)
            url = openalex_work_url(paper_id)
            used_source = "OpenAlex (Fallback)"

    # ==========================================
    # 3. 统一的数据清洗与格式化 (无需修改结构)
    # ==========================================
    papers = []
    for item in data:
        citing = item.get("citingPaper")
        if not citing:
            continue
        if used_source.startswith("Scopus"):
            citing = enrich_scopus_citing_paper_authors(citing)

        papers.append({
            "title": citing.get("title", "Unknown Title"),
            "year": citing.get("year"),
            "venue": citing.get("venue", "Unknown Venue"),
            "externalIds": citing.get("externalIds", {}),
            "authors": [a.get("name") for a in citing.get("authors", []) if a.get("name")],
            "author_details": (
                citing.get("author_details")
                if citing.get("author_details")
                else
                build_openalex_author_details(citing)
                if used_source.startswith("OpenAlex")
                else build_scopus_author_details(citing)
                if used_source.startswith("Scopus")
                else build_semantic_scholar_author_details(citing)
            ),
            "source_url": citing.get("source_url", ""),
            "citedby_count": citing.get("citedby_count", 0),
        })

    papers = dedupe_papers(papers)
    papers = sort_papers(papers, sort_by=sort_by)
    papers = papers[:desired_limit]

    return {
        "ok": True,
        "target": target,
        "count": len(papers),
        "total_citation_count": target.get("citationCount", 0),
        "influential_citation_count": target.get("influentialCitationCount", 0), # OpenAlex 可能没有这个字段，默认为0
        "papers": papers,
        "query": query,
        "sort_by": sort_by,
        "fetch_limit": desired_fetch,
        "source_url": url,
        "data_provider": used_source # 记录并返回实际生效的数据源
    }

'''def list_all_citations(query: str, limit: Optional[int] = None, sort_by: str = "recent", fetch_limit: Optional[int] = None):
    target = resolve_paper(query)
    paper_id = target["paperId"]
    desired_limit = max(1, int(limit or 100))
    desired_fetch = max(desired_limit, int(fetch_limit or max(100, min(desired_limit * 5, 500))))
    data = fetch_citations(paper_id, fetch_limit=desired_fetch)
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
        "?fields=title,year,venue,externalIds,authors"
    )

    papers = []
    for item in data:
        citing = item.get("citingPaper")
        if not citing:
            continue

        papers.append({
            "title": citing.get("title", "Unknown Title"),
            "year": citing.get("year"),
            "venue": citing.get("venue", "Unknown Venue"),
            "externalIds": citing.get("externalIds", {}),
            "authors": [a.get("name") for a in citing.get("authors", []) if a.get("name")]
        })

    papers = dedupe_papers(papers)
    papers = sort_papers(papers, sort_by=sort_by)
    papers = papers[:desired_limit]

    return {
        "ok": True,
        "target": target,
        "count": len(papers),
        "total_citation_count": target.get("citationCount"),
        "influential_citation_count": target.get("influentialCitationCount"),
        "papers": papers,
        "query": query,
        "sort_by": sort_by,
        "fetch_limit": desired_fetch,
        "source_url": url,
    }
'''

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            print(json.dumps(list_all_citations(sys.argv[1]), ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": False, "error": "请提供论文标题、DOI 或 arXiv 编号。"}, ensure_ascii=False, indent=2))
