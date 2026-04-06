import sys
import requests
import time
import urllib.parse
import json
import re
import hashlib
from pathlib import Path

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

            last_err = f"[attempt {attempt}] HTTP {r.status_code}: {r.text[:500]}"
        except Exception as e:
            last_err = f"[attempt {attempt}] {type(e).__name__}: {e}"
            time.sleep(sleep_sec)

    raise RuntimeError(last_err or "unknown request error")

def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_keywords(title: str):
    title_n = normalize_text(title)
    words = [w for w in title_n.split() if len(w) >= 4]
    stop = {
        "with", "from", "into", "that", "this", "using", "based",
        "generalized", "mechanism", "proceeding", "annual",
        "international", "conference", "journal", "letters",
        "transactions", "mobile", "computing", "networking",
        "system", "method", "methods", "approach", "model",
        "models", "study", "analysis", "design", "toward",
        "towards"
    }
    words = [w for w in words if w not in stop]
    return list(dict.fromkeys(words))[:10]

def extract_title_phrases(title: str):
    """
    从标题里提取 2~4 词短语，用来增强比单词更稳的匹配。
    """
    title_n = normalize_text(title)
    words = [w for w in title_n.split() if len(w) >= 3]

    stop = {
        "with", "from", "into", "that", "this", "using", "based",
        "generalized", "mechanism", "proceeding", "annual",
        "international", "conference", "journal", "letters",
        "transactions", "system", "method", "methods", "approach",
        "model", "models", "study", "analysis", "design"
    }
    words = [w for w in words if w not in stop]

    phrases = []
    for n in [2, 3, 4]:
        for i in range(len(words) - n + 1):
            phrases.append(" ".join(words[i:i+n]))

    # 只保留长度更有辨识度的短语
    phrases = [p for p in phrases if len(p) >= 8]
    return list(dict.fromkeys(phrases))[:12]

def resolve_paper(query: str):
    query = query.strip()

    if query.lower().startswith("10.48550/arxiv."):
        query = normalize_arxiv_id(query)

    # DOI
    if "/" in query or query.startswith("10."):
        paper_id = f"DOI:{query.strip()}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=paperId,title,year,venue,externalIds"
        print(f"[DEBUG] GET {url}", file=sys.stderr)
        r = safe_get(url)
        data = r.json()
        if data.get("paperId"):
            return {
                "paperId": data["paperId"],
                "title": data.get("title", ""),
                "year": data.get("year"),
                "venue": data.get("venue"),
                "externalIds": data.get("externalIds", {})
            }
        raise RuntimeError(f"无法根据 DOI 定位论文: {query}")

    # arXiv
    if looks_like_arxiv_id(query):
        paper_id = f"ARXIV:{normalize_arxiv_id(query)}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=paperId,title,year,venue,externalIds"
        print(f"[DEBUG] GET {url}", file=sys.stderr)
        r = safe_get(url)
        data = r.json()
        if data.get("paperId"):
            return {
                "paperId": data["paperId"],
                "title": data.get("title", ""),
                "year": data.get("year"),
                "venue": data.get("venue"),
                "externalIds": data.get("externalIds", {})
            }

    # 标题搜索
    search_url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote(query)}&limit=3&fields=title,year,venue,externalIds"
    )
    print(f"[DEBUG] GET {search_url}", file=sys.stderr)
    r = safe_get(search_url)
    data = r.json().get("data", [])
    if not data:
        raise RuntimeError(f"未找到论文: {query}")

    # 默认取第一条，但保留更多信息可扩展
    best = data[0]
    return {
        "paperId": best["paperId"],
        "title": best.get("title", ""),
        "year": best.get("year"),
        "venue": best.get("venue"),
        "externalIds": best.get("externalIds", {})
    }


def score_context(context: str, target_title: str, target_doi: str = "", target_year=None, target_venue: str = ""):
    ctx_n = normalize_text(context)
    kws = extract_keywords(target_title)
    phrases = extract_title_phrases(target_title)

    flags = {
        "title_keyword_hits": [],
        "title_phrase_hits": [],
        "mentions_doi": False,
        "mentions_year": False,
        "mentions_venue_token": False
    }

    score = 0

    # 1) 标题关键词命中
    kw_hits = []
    for kw in kws:
        if kw in ctx_n:
            kw_hits.append(kw)
    flags["title_keyword_hits"] = kw_hits
    score += min(len(kw_hits), 5)

    # 2) 标题短语命中（比单关键词更强）
    phrase_hits = []
    for ph in phrases:
        if ph in ctx_n:
            phrase_hits.append(ph)
    flags["title_phrase_hits"] = phrase_hits
    score += min(len(phrase_hits) * 2, 6)

    # 3) DOI 命中
    doi_n = normalize_text(target_doi or "")
    if doi_n and doi_n in ctx_n:
        flags["mentions_doi"] = True
        score += 6

    # 4) 年份命中（弱信号）
    if target_year and str(target_year) in ctx_n:
        flags["mentions_year"] = True
        score += 1

    # 5) venue 中抽一个较有辨识度的 token 做弱匹配
    venue_n = normalize_text(target_venue or "")
    venue_tokens = [w for w in venue_n.split() if len(w) >= 5 and w not in {
        "journal", "international", "conference", "transactions"
    }]
    for vt in venue_tokens[:3]:
        if vt in ctx_n:
            flags["mentions_venue_token"] = True
            score += 1
            break

    return score, flags

def get_citation_contexts(query):
    target = resolve_paper(query)
    paper_id = target["paperId"]
    target_title = target["title"]

    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
        "?fields=contexts,title,year,venue,authors"
        "&limit=100"
    )
    print(f"[DEBUG] GET {url}", file=sys.stderr)
    r = safe_get(url)
    data = r.json().get("data", [])

    results = []
    for item in data:
        citing = item.get("citingPaper")
        contexts = item.get("contexts") or []
        if not citing or not contexts:
            continue
        
        scored_contexts = []
                
        for c in contexts:
            c = c.replace("\n", " ").strip()
            if not c:
                continue
            score, flags = score_context(
                c,
                target_title=target_title,
                target_doi=target.get("externalIds", {}).get("DOI", ""),
                target_year=target.get("year"),
                target_venue=target.get("venue", "")
            )

            scored_contexts.append({
                "text": c,
                "score": score,
                "flags": flags
            })
        if not scored_contexts:
            continue

        # 取最高分的一条作为代表
        best_ctx = sorted(scored_contexts, key=lambda x: x["score"], reverse=True)[0]

        results.append({
            "target_query": query,
            "target_title": target_title,
            "target_year": target.get("year"),
            "target_venue": target.get("venue"),
            "target_externalIds": target.get("externalIds", {}),
            "citing_title": citing.get("title", "Unknown"),
            "citing_year": citing.get("year"),
            "citing_venue": citing.get("venue", "Unknown"),
            "contexts": scored_contexts,
            "best_context": best_ctx,
            "confidence": "high" if best_ctx["score"] >= 4 else "medium" if best_ctx["score"] >= 2 else "low"
        })

    # 按最佳 context 分数排序
    results = sorted(results, key=lambda x: x["best_context"]["score"], reverse=True)

    if not results:
        return {"ok": False, "message": "未找到带上下文的引用记录。", "results": []}

    return {
        "ok": True,
        "target": target,
        "count": len(results),
        "results": results[:20]
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            print(json.dumps(get_citation_contexts(sys.argv[1]), ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": False, "error": "请提供论文标题、DOI 或 arXiv 编号。"}, ensure_ascii=False, indent=2))
