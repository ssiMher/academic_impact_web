import sys
import json
import os
import time
import requests
import urllib.parse
import hashlib
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


def openalex_venue_name(work: dict):
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    return source.get("display_name")

def resolve_paper_openalex(query: str):
    """使用 OpenAlex 查找目标论文"""
    query = query.strip()
    
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
    search_url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&per-page=1"
    r = safe_get_openalex(search_url)
    if r and r.json().get("results"):
        data = r.json()["results"][0]
        return {
            "paperId": data.get("id"),
            "title": data.get("title", ""),
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
    query = query.strip()

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
        url = f"https://openalex.org/{paper_id}"
        used_source = "OpenAlex"
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
            url = f"https://openalex.org/{paper_id}"
            used_source = "OpenAlex (Fallback)"

    # ==========================================
    # 3. 统一的数据清洗与格式化 (无需修改结构)
    # ==========================================
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
            # 注意：OpenAlex 映射后也是相同的 authors 列表结构，直接解析即可
            "authors": [a.get("name") for a in citing.get("authors", []) if a.get("name")],
            "author_details": (
                build_openalex_author_details(citing)
                if used_source.startswith("OpenAlex")
                else build_semantic_scholar_author_details(citing)
            ),
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
