import sys
import requests
import os
import urllib.parse
import json
import re
import time
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

USER_EMAIL = "youdeng78@gmail.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OPENALEX_EMAIL = USER_EMAIL
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_PDF_DIR = os.getenv(
    "ACADEMIC_IMPACT_DOWNLOAD_DIR",
    str(ROOT / "data" / "downloads"),
)


def safe_get(url, timeout=15, retries=3, backoff_schedule=None):
    last_res = None
    last_err = None
    schedule = backoff_schedule or [2, 5, 10]
    for attempt in range(retries):
        try:
            res = requests.get(url, headers=HEADERS, timeout=timeout)
            last_res = res
            if res.status_code != 429:
                return res
            if attempt < retries - 1:
                sleep_sec = schedule[min(attempt, len(schedule) - 1)]
                time.sleep(sleep_sec)
        except Exception as exc:
            last_err = exc
            if attempt < retries - 1:
                sleep_sec = schedule[min(attempt, len(schedule) - 1)]
                time.sleep(sleep_sec)
    if last_res is not None:
        return last_res
    if last_err is not None:
        raise last_err
    return last_res


def sanitize_filename(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r'[\:\*\?\"\<\>\|]', "_", name)
    return name.strip()[:180] or "paper"


def normalize_arxiv_id(arxiv_id: str) -> str:
    arxiv_id = (arxiv_id or "").strip()
    arxiv_id = arxiv_id.replace("10.48550/arXiv.", "")
    arxiv_id = arxiv_id.replace("10.48550/arxiv.", "")
    arxiv_id = re.sub(r"^arxiv\s*:\s*", "", arxiv_id, flags=re.I)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.I)
    return arxiv_id.strip()


def looks_like_arxiv_id(query: str) -> bool:
    query = normalize_arxiv_id(query)
    return bool(re.fullmatch(r"\d{4}\.\d{4,5}", query))


def normalize_title(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_similarity(query: str, candidate_title: str) -> float:
    query_n = normalize_title(query)
    candidate_n = normalize_title(candidate_title)
    if not query_n or not candidate_n:
        return 0.0
    if query_n == candidate_n:
        return 1.0

    q_words = set(query_n.split())
    c_words = set(candidate_n.split())
    if not q_words or not c_words:
        return 0.0

    overlap = len(q_words & c_words)
    return overlap / max(len(q_words), len(c_words))


def list_local_pdf_files(search_dir: str):
    base = os.path.expanduser(search_dir)
    if not os.path.isdir(base):
        return []
    return [
        os.path.join(base, name)
        for name in os.listdir(base)
        if name.lower().endswith(".pdf")
    ]


def find_local_pdf(query: str = "", title: str = "", doi: str = "", arxiv_id: str = "", search_dir: str = DEFAULT_LOCAL_PDF_DIR):
    pdf_files = list_local_pdf_files(search_dir)
    if not pdf_files:
        return None

    candidates = []
    for file_path in pdf_files:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        score = 0.0

        if arxiv_id:
            normalized_arxiv = normalize_arxiv_id(arxiv_id)
            if normalized_arxiv and normalize_title(base_name) == normalize_title(normalized_arxiv):
                score = max(score, 1.0)

        for text in [title, query]:
            if not text:
                continue
            if sanitize_filename(text).lower() == os.path.basename(file_path).lower().replace(".pdf", ""):
                score = max(score, 1.0)
            score = max(score, title_similarity(text, base_name))

        if doi:
            doi_hint = doi.lower().replace("/", "_")
            if doi_hint in file_path.lower():
                score = max(score, 0.95)

        if score >= 0.75:
            candidates.append((score, file_path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]


def inspect_pdf_file(file_path: str):
    path = Path(file_path).expanduser()
    if not path.exists():
        return {
            "ok": False,
            "error_type": "pdf_file_missing",
            "error": f"未找到 PDF 文件: {path}",
        }
    if not path.is_file():
        return {
            "ok": False,
            "error_type": "pdf_path_not_file",
            "error": f"PDF 路径不是文件: {path}",
        }
    if path.suffix.lower() != ".pdf":
        return {
            "ok": False,
            "error_type": "unsupported_file_type",
            "error": "当前只支持 .pdf 文件。",
        }
    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "pdf_read_failed",
            "error": f"读取 PDF 文件失败: {type(exc).__name__}: {exc}",
        }
    if not header.startswith(b"%PDF-"):
        return {
            "ok": False,
            "error_type": "downloaded_non_pdf",
            "error": "该文件扩展名是 PDF，但内容不是有效 PDF 文件。",
        }
    return {
        "ok": True,
        "file_path": str(path),
        "size_bytes": path.stat().st_size,
    }


def is_probable_pdf_url(url: str) -> bool:
    url_n = (url or "").strip().lower()
    return bool(url_n) and (
        ".pdf" in url_n
        or "download" in url_n
        or "pdf" in url_n
    )


def extract_pdf_candidates_from_html_page(page_url: str):
    if not page_url:
        return []

    try:
        res = requests.get(page_url, headers=HEADERS, timeout=20, allow_redirects=True)
    except Exception:
        return []

    if res.status_code != 200:
        return []

    html = res.text or ""
    base_url = res.url or page_url
    candidates = []

    patterns = [
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:pdf["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']dc\.identifier["\'][^>]+content=["\']([^"\']+\.pdf[^"\']*)["\']',
        r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, flags=re.I):
            url = urljoin(base_url, unescape(match).strip())
            if url and url not in candidates:
                candidates.append(url)

    return candidates


def search_paper_by_title(query: str):
    search_url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote(query)}&limit=3&fields=title,externalIds,openAccessPdf,year,venue"
    )
    res = safe_get(search_url)
    if res.status_code != 200:
        return None, f"搜索失败，状态码: {res.status_code}"

    data = res.json().get("data", [])
    if not data:
        return None, None

    ranked = sorted(
        data,
        key=lambda item: (
            title_similarity(query, item.get("title", "")),
            item.get("year") or 0,
        ),
        reverse=True,
    )
    return ranked[0], None


def get_paper_by_doi(doi: str):
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,externalIds,openAccessPdf,year,venue"
    res = safe_get(url)
    if res.status_code != 200:
        return None, f"DOI 查询失败，状态码: {res.status_code}"
    data = res.json()
    if not data.get("paperId") and not data.get("title"):
        return None, "DOI 未定位到论文"
    return data, None


def get_paper_by_arxiv(arxiv_id: str):
    arxiv_id = normalize_arxiv_id(arxiv_id)
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}?fields=title,externalIds,openAccessPdf,year,venue"
    res = safe_get(url)
    if res.status_code != 200:
        return None, f"arXiv 查询失败，状态码: {res.status_code}"
    data = res.json()
    if not data.get("paperId") and not data.get("title"):
        return None, "arXiv 未定位到论文"
    return data, None


def get_pdf_url_from_semantic_scholar(paper_data: dict):
    pdf_info = paper_data.get("openAccessPdf")
    if pdf_info and pdf_info.get("url"):
        return pdf_info["url"]
    return ""


def get_pdf_url_from_unpaywall(doi: str):
    if not doi:
        return []

    url = f"https://api.unpaywall.org/v2/{doi}?email={USER_EMAIL}"
    try:
        res = safe_get(url, timeout=15)
        if res.status_code == 200:
            data = res.json()
            urls = []
            for location in [data.get("best_oa_location")] + list(data.get("oa_locations") or []):
                if not isinstance(location, dict):
                    continue
                for key in ("url_for_pdf", "url"):
                    value = (location.get(key) or "").strip()
                    if value and value not in urls:
                        urls.append(value)
            return urls
    except:
        pass
    return []


def get_pdf_url_from_arxiv(arxiv_id: str):
    arxiv_id = normalize_arxiv_id(arxiv_id)
    if not arxiv_id:
        return ""
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

# ==========================================
# 新增：CORE API 备用下载源
# ==========================================
def get_pdf_candidates_from_core_api(query: str, doi: str = ""):
    """从 CORE API v3 获取开放获取的 PDF 下载链接"""
    # 尝试从环境变量读取 API Key (如果没有配置也可以裸连，只是容易被限流)
    core_api_key = os.environ.get("CORE_API_KEY", "")
    headers = {"Authorization": f"Bearer {core_api_key}"} if core_api_key else {}
    
    # 优先用 DOI 搜索，因为最准确；没有则用标题
    if doi:
        search_query = f'doi:"{doi}"'
    else:
        search_query = f'title:"{query}"'
        
    url = f"https://api.core.ac.uk/v3/search/works?q={urllib.parse.quote(search_query)}&limit=3"
    
    candidates = []
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            results = res.json().get("results", [])
            for item in results:
                # CORE API 会在 downloadUrl 字段直接提供 PDF 直链
                download_url = item.get("downloadUrl")
                if download_url and download_url not in candidates:
                    candidates.append(download_url)
    except Exception as e:
        print(f"[WARN] CORE API 请求失败: {e}", file=sys.stderr)
        
    return candidates

def get_work_from_openalex_by_doi(doi: str):
    if not doi:
        return None

    work_url = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}"
    if OPENALEX_EMAIL:
        work_url += f"?mailto={urllib.parse.quote(OPENALEX_EMAIL)}"

    try:
        res = safe_get(work_url, timeout=20)
        if res.status_code != 200:
            return None
        data = res.json()
        if not isinstance(data, dict) or not data.get("id"):
            return None
        return data
    except Exception:
        return None


def get_pdf_candidates_from_openalex(work_data: dict):
    if not isinstance(work_data, dict):
        return []

    candidates = []

    def add_candidate(value: str):
        url = (value or "").strip()
        if url and url not in candidates:
            candidates.append(url)

    locations = []
    best_oa = work_data.get("best_oa_location")
    if isinstance(best_oa, dict):
        locations.append(best_oa)
    for location in work_data.get("locations") or []:
        if isinstance(location, dict) and location not in locations:
            locations.append(location)

    for location in locations:
        if not location.get("is_oa", True):
            continue
        add_candidate(location.get("pdf_url"))
        add_candidate(location.get("landing_page_url"))

    primary = work_data.get("primary_location")
    if isinstance(primary, dict):
        add_candidate(primary.get("pdf_url"))
        add_candidate(primary.get("landing_page_url"))

    return candidates


def get_pdf_candidates_from_doi_landing_page(doi: str):
    if not doi:
        return []

    landing_url = f"https://doi.org/{doi}"
    return extract_pdf_candidates_from_html_page(landing_url)


def build_minimal_paper_data(query: str, doi: str = "", arxiv_id: str = ""):
    external_ids = {}
    if doi:
        external_ids["DOI"] = doi
    if arxiv_id:
        external_ids["ArXiv"] = arxiv_id
    return {
        "title": query,
        "year": None,
        "venue": None,
        "externalIds": external_ids,
    }


def enrich_arxiv_metadata(arxiv_id: str, paper_data: dict):
    arxiv_id = normalize_arxiv_id(arxiv_id)
    if not arxiv_id:
        return paper_data

    try:
        api_url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
        res = safe_get(api_url, timeout=20, retries=2, backoff_schedule=[2, 4])
        if res.status_code != 200:
            return paper_data

        root = ET.fromstring(res.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return paper_data

        title_el = entry.find("atom:title", ns)
        published_el = entry.find("atom:published", ns)

        title = " ".join((title_el.text or "").split()) if title_el is not None else ""
        published = (published_el.text or "").strip() if published_el is not None else ""
        year = int(published[:4]) if published[:4].isdigit() else None

        enriched = dict(paper_data or {})
        external_ids = dict(enriched.get("externalIds", {}))
        external_ids["ArXiv"] = arxiv_id
        enriched["externalIds"] = external_ids
        if title:
            enriched["title"] = title
        if year:
            enriched["year"] = year
        return enriched
    except Exception:
        return paper_data


def download_file(pdf_url: str, file_path: str):
    try:
        res = safe_get(pdf_url, timeout=30)
    except Exception as exc:
        return False, f"下载请求失败: {type(exc).__name__}: {exc}"
    if res.status_code != 200:
        return False, f"下载失败，状态码: {res.status_code}"

    content_type = (res.headers.get("Content-Type") or "").lower()
    if "pdf" not in content_type and not is_probable_pdf_url(pdf_url):
        return False, f"下载内容不是 PDF: {content_type or 'unknown'}"

    with open(file_path, "wb") as f:
        f.write(res.content)
    return True, None


def resolve_download_plan(query: str):
    query = query.strip()
    paper_data = None
    doi = ""
    arxiv_id = ""
    title = query

    local_file_path = find_local_pdf(query=query)
    if local_file_path:
        resolved_title = os.path.splitext(os.path.basename(local_file_path))[0]
        return {
            "ok": True,
            "query": query,
            "title": resolved_title,
            "doi": "",
            "arxiv_id": normalize_arxiv_id(query) if looks_like_arxiv_id(query) else "",
            "paper": {
                "title": resolved_title,
                "year": None,
                "venue": None,
                "externalIds": {}
            },
            "local_file_path": local_file_path,
            "pdf_candidates": [],
            "source": "local_manual_pdf",
        }

    # 1. 优先按 DOI
    if "/" in query or query.startswith("10."):
        doi = query
        paper_data, err = get_paper_by_doi(doi)
        if err:
            return {
                "ok": False,
                "error": err,
                "query": query
            }
        title = paper_data.get("title", query)

    # 2. 其次按 arXiv
    elif looks_like_arxiv_id(query) or query.lower().startswith("arxiv:"):
        arxiv_id = normalize_arxiv_id(query)
        paper_data = build_minimal_paper_data(query=query, arxiv_id=arxiv_id)
        paper_data = enrich_arxiv_metadata(arxiv_id, paper_data)
        title = paper_data.get("title", query)

    # 3. 否则按标题搜索
    else:
        paper_data, err = search_paper_by_title(query)
        if err:
            return {
                "ok": False,
                "error": err,
                "query": query
            }
        if not paper_data:
            return {
                "ok": False,
                "error": f"未找到论文《{query}》。",
                "query": query
            }
        title = paper_data.get("title", query)
        doi = paper_data.get("externalIds", {}).get("DOI", "")
        arxiv_id = normalize_arxiv_id(paper_data.get("externalIds", {}).get("ArXiv", ""))

    if paper_data and not arxiv_id:
        arxiv_id = normalize_arxiv_id(paper_data.get("externalIds", {}).get("ArXiv", ""))

    local_file_path = find_local_pdf(query=query, title=title, doi=doi, arxiv_id=arxiv_id)
    if local_file_path:
        return {
            "ok": True,
            "query": query,
            "title": title,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "paper": {
                "title": title,
                "year": paper_data.get("year") if paper_data else None,
                "venue": paper_data.get("venue") if paper_data else None,
                "externalIds": paper_data.get("externalIds", {}) if paper_data else {}
            },
            "local_file_path": local_file_path,
            "pdf_candidates": [],
            "source": "local_manual_pdf",
        }

    pdf_candidates = []

    def add_pdf_candidate(url: str):
        value = (url or "").strip()
        if value and value not in pdf_candidates:
            pdf_candidates.append(value)

    def add_pdf_source(url: str):
        value = (url or "").strip()
        if not value:
            return
        if is_probable_pdf_url(value):
            add_pdf_candidate(value)
            return
        for candidate in extract_pdf_candidates_from_html_page(value):
            add_pdf_candidate(candidate)

    # 4. 先找 Semantic Scholar 的 openAccessPdf
    if paper_data.get("openAccessPdf"):
        add_pdf_source(get_pdf_url_from_semantic_scholar(paper_data))

    # 5. 再试 Unpaywall 暴露出的多个候选地址
    if doi:
        for candidate in get_pdf_url_from_unpaywall(doi):
            add_pdf_source(candidate)

    # 6. DOI 落地页里的常见 PDF 链接
    if doi:
        for candidate in get_pdf_candidates_from_doi_landing_page(doi):
            add_pdf_candidate(candidate)

    # 6.5 OpenAlex 的 OA location / landing page 线索
    if doi:
        openalex_work = get_work_from_openalex_by_doi(doi)
        if openalex_work:
            for candidate in get_pdf_candidates_from_openalex(openalex_work):
                add_pdf_source(candidate)

    # 7. 还没有的话，尝试直接拼 arXiv PDF 地址
    if arxiv_id:
        add_pdf_source(get_pdf_url_from_arxiv(arxiv_id))

    # -----------------------------------------------------------
    # [新增] 8. 从 CORE API 获取全球 Open Access 库的 PDF 直链
    # -----------------------------------------------------------
    for candidate in get_pdf_candidates_from_core_api(query=title, doi=doi):
        add_pdf_candidate(candidate)

    return {
        "ok": True,
        "query": query,
        "title": title,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "paper": {
            "title": title,
            "year": paper_data.get("year"),
            "venue": paper_data.get("venue"),
            "externalIds": paper_data.get("externalIds", {})
        },
        "local_file_path": None,
        "pdf_candidates": pdf_candidates,
        "source": "auto_download" if pdf_candidates else "manual_required",
    }


def probe_download(query: str):
    plan = resolve_download_plan(query)
    if not plan.get("ok"):
        return plan

    local_file_path = plan.get("local_file_path")
    pdf_candidates = plan.get("pdf_candidates", [])
    if local_file_path:
        status = "local_available"
    elif pdf_candidates:
        status = "auto_downloadable"
    else:
        status = "manual_required"

    return {
        "ok": True,
        "query": plan.get("query", query),
        "title": plan.get("title", query),
        "doi": plan.get("doi", ""),
        "arxiv_id": plan.get("arxiv_id", ""),
        "status": status,
        "source": plan.get("source"),
        "local_file_path": local_file_path,
        "pdf_candidates": pdf_candidates,
        "candidate_count": len(pdf_candidates),
        "paper": plan.get("paper", {}),
    }


def download_paper(query: str):
    plan = resolve_download_plan(query)
    if not plan.get("ok"):
        return plan

    if plan.get("local_file_path"):
        return {
            "ok": True,
            "query": plan.get("query", query),
            "title": plan.get("title", query),
            "doi": plan.get("doi", ""),
            "arxiv_id": plan.get("arxiv_id", ""),
            "pdf_url": "",
            "pdf_candidates": [],
            "file_path": plan.get("local_file_path"),
            "source": "local_manual_pdf",
            "paper": plan.get("paper", {}),
        }

    pdf_candidates = plan.get("pdf_candidates", [])
    if not pdf_candidates:
        return {
            "ok": False,
            "query": plan.get("query", query),
            "title": plan.get("title", query),
            "doi": plan.get("doi", ""),
            "arxiv_id": plan.get("arxiv_id", ""),
            "error": "未找到合法开源 PDF 链接。",
            "pdf_candidates": [],
            "paper": plan.get("paper", {}),
        }

    save_dir = DEFAULT_LOCAL_PDF_DIR
    os.makedirs(save_dir, exist_ok=True)
    file_name = sanitize_filename(plan.get("title", query)) + ".pdf"
    file_path = os.path.join(save_dir, file_name)

    download_errors = []
    pdf_url = ""
    ok = False
    err = None
    for candidate in pdf_candidates:
        pdf_url = candidate
        ok, err = download_file(candidate, file_path)
        if ok:
            break
        download_errors.append({"url": candidate, "error": err})

    if not ok:
        return {
            "ok": False,
            "query": plan.get("query", query),
            "title": plan.get("title", query),
            "doi": plan.get("doi", ""),
            "arxiv_id": plan.get("arxiv_id", ""),
            "pdf_url": pdf_url,
            "pdf_candidates": pdf_candidates,
            "download_errors": download_errors,
            "error": err
        }

    return {
        "ok": True,
        "query": plan.get("query", query),
        "title": plan.get("title", query),
        "doi": plan.get("doi", ""),
        "arxiv_id": plan.get("arxiv_id", ""),
        "pdf_url": pdf_url,
        "pdf_candidates": pdf_candidates,
        "file_path": file_path,
        "paper": plan.get("paper", {})
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(download_paper(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": False, "error": "请提供论文标题、DOI 或 arXiv 编号。"}, ensure_ascii=False, indent=2))
