import sys
import json
import re
from typing import List, Dict, Tuple, Optional


def normalize_text(s: str) -> str:
    if not s:
        return ""
    return (
        s.lower()
        .replace("´", "")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("ﬁ", "fi")
        .replace("ﬀ", "ff")
        .replace("–", "-")
        .replace("—", "-")
    )


def split_paragraphs(text: str) -> List[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paras = re.split(r"\n\s*\n", text)

    cleaned = []
    for p in paras:
        p = re.sub(r"[ \t]+", " ", p).strip()
        if p:
            cleaned.append(p)

    if len(cleaned) <= 1 and len(text) > 300:
        rough = re.split(r"(?<=[\.\!\?])\s+(?=[A-Z0-9\[])", text)
        merged = []
        buf = []
        length = 0
        for s in rough:
            s = s.strip()
            if not s:
                continue
            buf.append(s)
            length += len(s)
            if length >= 350:
                merged.append(" ".join(buf))
                buf, length = [], 0
        if buf:
            merged.append(" ".join(buf))
        if merged:
            cleaned = merged

    return cleaned


def extract_title_keywords(title: str) -> List[str]:
    text = normalize_text(title)
    raw_words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text)
    words = []
    for word in raw_words:
        word = word.strip("-")
        if not word:
            continue
        if word.startswith("pre-") or word.endswith("-based"):
            continue
        words.append(word)
    stop = {
        "a", "an", "the", "for", "of", "and", "to", "in", "on", "with",
        "based", "using", "generalized", "mechanism", "proceeding",
        "annual", "international", "conference", "toward", "towards",
        "from", "into", "via", "over", "under", "study", "system",
        "method", "methods", "approach", "model", "models",
        "vision", "learning", "tracking"
    }
    words = [w for w in words if len(w) >= 4 and w not in stop]
    return list(dict.fromkeys(words))[:10]


def is_usable_context(context_obj: Dict) -> bool:
    if not isinstance(context_obj, dict):
        return False

    text = (context_obj.get("text") or "").strip()
    if not text:
        return False

    score = context_obj.get("score")
    if isinstance(score, (int, float)) and score >= 2:
        return True

    flags = context_obj.get("flags") or {}
    if flags.get("mentions_doi"):
        return True
    if flags.get("title_phrase_hits"):
        return True
    if len(flags.get("title_keyword_hits") or []) >= 2:
        return True

    return False


def load_citation_contexts(path: Optional[str], citing_title: Optional[str] = None) -> List[str]:
    if not path:
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    results = data.get("results", []) if isinstance(data, dict) else []
    contexts = []

    for item in results:
        item_citing_title = item.get("citing_title", "")
        if citing_title and item_citing_title:
            if item_citing_title.strip().lower() != citing_title.strip().lower():
                continue

        best_context = item.get("best_context") or {}
        if is_usable_context(best_context):
            contexts.append(best_context["text"])

        for c in item.get("contexts", []):
            if is_usable_context(c):
                contexts.append(c["text"])

    deduped = []
    seen = set()
    for c in contexts:
        key = normalize_text(c)
        if key and key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped[:20]


def tokenize_for_overlap(text: str) -> List[str]:
    t = normalize_text(text)
    toks = re.findall(r"[a-z0-9\-]+", t)
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "into",
        "were", "have", "has", "had", "been", "their", "they", "than",
        "then", "using", "based", "method", "system", "approach"
    }
    return [x for x in toks if len(x) >= 3 and x not in stop]


def overlap_score(a: str, b: str) -> float:
    ta = set(tokenize_for_overlap(a))
    tb = set(tokenize_for_overlap(b))
    if not ta or not tb:
        return 0.0

    inter = len(ta & tb)
    denom = max(1, min(len(ta), len(tb)))
    return inter / denom


def count_ocr_noise_markers(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"/uni[0-9a-f]{6,}", text, flags=re.I))


def is_noisy_analysis_text(text: str) -> bool:
    if not text:
        return True

    noise_markers = count_ocr_noise_markers(text)
    if noise_markers >= 3:
        return True

    visible_chars = [ch for ch in text if not ch.isspace()]
    if not visible_chars:
        return True

    alpha_num_chars = sum(ch.isalnum() for ch in visible_chars)
    alpha_num_ratio = alpha_num_chars / max(1, len(visible_chars))

    if len(visible_chars) >= 400 and alpha_num_ratio < 0.45:
        return True

    return False


def page_reference_features(text: str) -> Dict[str, int]:
    t = text or ""
    tn = normalize_text(t)
    return {
        "has_header": int(bool(re.search(r"\b(references|bibliography)\b", tn))),
        "bracket_refs": len(re.findall(r"\[\s*\d+\s*\]", t)),
        "numbered_refs": len(re.findall(r"(?m)^\s*\[?\d+\]?[\.\)]\s+[A-Z]", t)),
        "doi_hits": len(re.findall(r"10\.\d{4,9}/\S+", t, flags=re.I)),
        "year_hits": len(re.findall(r"\b(?:19|20)\d{2}\b", t)),
        "proc_hits": len(re.findall(r"\b(?:proc\.?|proceedings|vol\.?|no\.?|pp\.?|doi:)\b", tn)),
    }


def find_reference_start_page(pages: List[Dict]) -> Optional[int]:
    if not pages:
        return None

    total_pages = max(p.get("page", 0) for p in pages) or len(pages)
    min_heading_page = max(2, int(total_pages * 0.45))
    min_density_page = max(2, int(total_pages * 0.6))

    heading_patterns = [
        r'(?mi)^\s*(references|bibliography)\s*$',
        r'(?mi)^\s*[ivxlcdm\.\s]*references\s*$',
        r'(?mi)^\s*[ivxlcdm\.\s]*bibliography\s*$',
    ]

    for page in pages:
        pg = page.get("page", 0)
        if pg < min_heading_page:
            continue
        txt = page.get("text", "") or ""
        if any(re.search(pat, txt) for pat in heading_patterns):
            return pg

    candidates = []
    for page in pages:
        pg = page.get("page", 0)
        if pg < min_density_page:
            continue

        f = page_reference_features(page.get("text", ""))
        strong_ref_like = (
            (f["bracket_refs"] >= 20 and f["year_hits"] >= 15) or
            (f["numbered_refs"] >= 20 and f["year_hits"] >= 15) or
            (f["doi_hits"] >= 2 and f["year_hits"] >= 10) or
            ((f["bracket_refs"] + f["numbered_refs"]) >= 30 and f["proc_hits"] >= 20)
        )
        if strong_ref_like:
            candidates.append(pg)

    if candidates:
        return min(candidates)

    return None


def is_probable_reference_entry(text: str) -> bool:
    t = text or ""
    tn = normalize_text(t)
    score = 0

    if re.search(r"^\s*\[\s*\d+\s*\]", t):
        score += 4
    if re.search(r"^\s*\d+[\.\)]\s+", t):
        score += 4

    score += len(re.findall(r"10\.\d{4,9}/\S+", t, flags=re.I)) * 3
    score += len(re.findall(r"\b(?:vol\.?|no\.?|pp\.?|proc\.?|proceedings|doi:)\b", tn)) * 2
    score += len(re.findall(r"\b[A-Z]\.\s*[A-Z][a-z]+", t)) * 1

    if len(re.findall(r"\b(?:19|20)\d{2}\b", t)) >= 2:
        score += 2

    if len(t) < 500 and (re.search(r"^\s*\[\s*\d+\s*\]", t) or "doi:" in tn):
        score += 2

    return score >= 6


def collect_reference_paragraphs(fulltext_json: Dict) -> Tuple[List[Dict], Optional[int]]:
    pages = fulltext_json.get("pages", [])
    ref_start = find_reference_start_page(pages)
    if ref_start is None:
        return [], None

    ref_paras = []
    for page in pages:
        if page["page"] < ref_start:
            continue
        paras = split_paragraphs(page.get("text", ""))
        for i, para in enumerate(paras, start=1):
            ref_paras.append({
                "page": page["page"],
                "span_index": i,
                "text": para
            })
    return ref_paras, ref_start


def collect_body_paragraphs(fulltext_json: Dict) -> Tuple[List[Dict], Optional[int]]:
    pages = fulltext_json.get("pages", [])
    ref_start = find_reference_start_page(pages)

    body_paras = []
    for page in pages:
        if ref_start is not None and page["page"] >= ref_start:
            continue
        paras = split_paragraphs(page.get("text", ""))
        for i, para in enumerate(paras, start=1):
            body_paras.append({
                "page": page["page"],
                "span_index": i,
                "text": para
            })

    return body_paras, ref_start


def score_reference_paragraph(para: str, title_keywords: List[str], target_doi: Optional[str]) -> Dict:
    para_n = normalize_text(para)
    score = 0
    keyword_hits = []

    target_doi_n = normalize_text(target_doi or "")
    doi_pos = -1
    if target_doi_n and target_doi_n in para_n:
        score += 15
        doi_pos = para_n.find(target_doi_n)

    for kw in title_keywords:
        if kw in para_n:
            keyword_hits.append(kw)
            score += 2

    if is_probable_reference_entry(para):
        score += 2

    return {
        "score": score,
        "keyword_hits": keyword_hits,
        "doi_pos": doi_pos,
    }


def extract_possible_indices(text: str) -> List[Dict]:
    results = []

    for m in re.finditer(r"\[\s*(\d+)\s*\]", text):
        results.append({
            "index": m.group(1),
            "pos": m.start(),
            "style": "bracket"
        })

    for m in re.finditer(r"(?m)^\s*(\d+)[\.\)]\s+", text):
        results.append({
            "index": m.group(1),
            "pos": m.start(),
            "style": "leading_number"
        })

    seen = set()
    uniq = []
    for x in sorted(results, key=lambda z: z["pos"]):
        key = (x["index"], x["pos"], x["style"])
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq


def find_signal_positions(para: str, title_keywords: List[str], target_doi: Optional[str]) -> List[int]:
    para_n = normalize_text(para)
    signal_positions = []

    if target_doi:
        doi_n = normalize_text(target_doi)
        pos = para_n.find(doi_n)
        if pos != -1:
            signal_positions.append(pos)

    for kw in title_keywords:
        start = 0
        while True:
            pos = para_n.find(kw, start)
            if pos == -1:
                break
            signal_positions.append(pos)
            start = pos + len(kw)

    return sorted(set(signal_positions))


def pick_best_index_near_signal(
    para: str,
    indices: List[Dict],
    title_keywords: List[str],
    target_doi: Optional[str]
) -> Optional[Dict]:
    if not indices:
        return None

    signal_positions = find_signal_positions(para, title_keywords, target_doi)
    if not signal_positions:
        return indices[0]

    best = None
    for idx_obj in indices:
        d = min(abs(idx_obj["pos"] - sp) for sp in signal_positions)
        cand = dict(idx_obj)
        cand["distance_to_signal"] = d

        nearest_signal = min(signal_positions, key=lambda sp: abs(idx_obj["pos"] - sp))
        if nearest_signal < idx_obj["pos"]:
            gap = idx_obj["pos"] - nearest_signal
            if 5 <= gap <= 260:
                try:
                    inferred_prev = str(int(idx_obj["index"]) - 1)
                    if int(inferred_prev) > 0:
                        cand["inferred_previous_index"] = inferred_prev
                        cand["inference_reason"] = "signal_before_next_index"
                        cand["gap_after_signal"] = gap
                except Exception:
                    pass

        if best is None or cand["distance_to_signal"] < best["distance_to_signal"]:
            best = cand

    return best


def find_citation_index_in_references(fulltext_json: Dict, target_title: str, target_doi: Optional[str] = None):
    ref_paras, ref_start = collect_reference_paragraphs(fulltext_json)
    if ref_start is None or not ref_paras:
        return None, None

    title_keywords = extract_title_keywords(target_title)
    best = None

    for para_obj in ref_paras:
        para = para_obj["text"]
        s = score_reference_paragraph(para, title_keywords, target_doi)
        if s["score"] <= 0:
            continue

        indices = extract_possible_indices(para)
        best_idx = pick_best_index_near_signal(para, indices, title_keywords, target_doi)

        picked_index = None
        picked_index_style = None
        distance_to_signal = None
        inference_reason = None
        gap_after_signal = None

        if best_idx:
            distance_to_signal = best_idx.get("distance_to_signal")
            gap_after_signal = best_idx.get("gap_after_signal")

            if best_idx.get("inferred_previous_index"):
                picked_index = best_idx["inferred_previous_index"]
                picked_index_style = "inferred_previous_from_" + best_idx.get("style", "unknown")
                inference_reason = best_idx.get("inference_reason")
            else:
                picked_index = best_idx["index"]
                picked_index_style = best_idx.get("style")

        candidate = {
            "page": para_obj["page"],
            "span_index": para_obj["span_index"],
            "reference_text": para,
            "score": s["score"],
            "keyword_hits": s["keyword_hits"],
            "possible_indices": indices,
            "picked_index": picked_index,
            "picked_index_style": picked_index_style,
            "distance_to_signal": distance_to_signal,
            "inference_reason": inference_reason,
            "gap_after_signal": gap_after_signal,
        }

        rank_score = candidate["score"] + (8 if candidate["picked_index"] else 0)
        if candidate["inference_reason"] == "signal_before_next_index":
            rank_score += 5

        if best is None or rank_score > best["rank_score"]:
            candidate["rank_score"] = rank_score
            best = candidate

    if best and best["picked_index"]:
        return best["picked_index"], {
            "reference_page": best["page"],
            "reference_span_index": best["span_index"],
            "reference_text": best["reference_text"],
            "keyword_hits": best["keyword_hits"],
            "score": best["score"],
            "possible_indices": best["possible_indices"],
            "picked_index_style": best["picked_index_style"],
            "distance_to_signal": best["distance_to_signal"],
            "inference_reason": best["inference_reason"],
            "gap_after_signal": best["gap_after_signal"],
        }

    return None, None


def paragraph_score_fallback(text: str, target_title: str, target_doi: Optional[str] = None) -> Tuple[int, List[str]]:
    text_n = normalize_text(text)
    kws = extract_title_keywords(target_title)

    score = 0
    hits = []
    for kw in kws:
        if kw in text_n:
            score += 2
            hits.append(kw)

    if target_doi and normalize_text(target_doi) in text_n:
        score += 8

    if re.search(r"\[\d+\]", text):
        score += 1

    if len(text) > 120:
        score += 1

    return score, hits


def contains_citation_index(text: str, citation_index: str) -> Tuple[bool, str]:
    if not citation_index:
        return False, ""

    exact_patterns = [
        rf"\[\s*{re.escape(citation_index)}\s*\]",
        rf"\(\s*{re.escape(citation_index)}\s*\)",
    ]
    for pat in exact_patterns:
        if re.search(pat, text):
            return True, "citation_index_exact"

    grouped_patterns = [
        r"\[([^\[\]]+)\]",
        r"\(([^\(\)]+)\)",
    ]

    target_num = None
    try:
        target_num = int(citation_index)
    except Exception:
        pass

    for pat in grouped_patterns:
        for m in re.finditer(pat, text):
            content = m.group(1)
            if not re.search(r"\d", content):
                continue

            nums = {int(x) for x in re.findall(r"\d+", content)}
            if target_num is not None and target_num in nums and len(nums) > 1:
                return True, "citation_index_grouped"

            for a, b in re.findall(r"(\d+)\s*[-–—]\s*(\d+)", content):
                try:
                    a_i = int(a)
                    b_i = int(b)
                    if target_num is not None and min(a_i, b_i) <= target_num <= max(a_i, b_i):
                        return True, "citation_index_grouped"
                except Exception:
                    continue

    return False, ""


def find_spans_by_citation_index(body_paras: List[Dict], citation_index: str) -> List[Dict]:
    candidates = []
    if not citation_index:
        return candidates

    hit_positions = []
    hit_kinds = {}
    for idx, para in enumerate(body_paras):
        matched, match_type = contains_citation_index(para["text"], citation_index)
        if matched:
            hit_positions.append(idx)
            hit_kinds[idx] = match_type

    seen = set()
    for pos in hit_positions:
        for nb in [pos - 1, pos, pos + 1]:
            if 0 <= nb < len(body_paras) and nb not in seen:
                seen.add(nb)
                para = body_paras[nb]
                center_match_type = hit_kinds.get(pos, "citation_index_exact")
                if nb == pos:
                    match_type = center_match_type
                    base_score = 100 if center_match_type == "citation_index_exact" else 85
                else:
                    match_type = "citation_index_neighbor"
                    base_score = 60

                if is_probable_reference_entry(para["text"]):
                    base_score -= 50

                candidates.append({
                    "page": para["page"],
                    "span_index": para["span_index"],
                    "text": para["text"],
                    "score": base_score,
                    "match_type": match_type,
                    "citation_index": citation_index,
                    "keyword_hits": [],
                    "evidence": [match_type]
                })

    candidates.sort(key=lambda x: (-x["score"], x["page"], x["span_index"]))
    return candidates


def find_spans_by_context_similarity(body_paras: List[Dict], contexts: List[str]) -> List[Dict]:
    candidates = []

    for ctx in contexts:
        for para in body_paras:
            if is_probable_reference_entry(para["text"]):
                continue

            score = overlap_score(ctx, para["text"])
            if score < 0.18:
                continue

            candidates.append({
                "page": para["page"],
                "span_index": para["span_index"],
                "text": para["text"],
                "score": round(score * 100, 2),
                "match_type": "context_similarity",
                "citation_index": None,
                "keyword_hits": [],
                "matched_context": ctx[:300],
                "context_overlap_score": round(score, 4),
                "evidence": ["context_similarity"]
            })

    candidates.sort(key=lambda x: (-x["score"], x["page"], x["span_index"]))
    return candidates[:30]


def find_spans_by_fallback_keywords(body_paras: List[Dict], target_title: str, target_doi: Optional[str] = None) -> List[Dict]:
    candidates = []
    for para in body_paras:
        score, hits = paragraph_score_fallback(para["text"], target_title, target_doi)
        if score <= 0:
            continue
        if is_probable_reference_entry(para["text"]):
            continue

        candidates.append({
            "page": para["page"],
            "span_index": para["span_index"],
            "text": para["text"],
            "score": score,
            "match_type": "keyword_fallback",
            "citation_index": None,
            "keyword_hits": hits,
            "evidence": ["keyword_fallback"]
        })

    candidates.sort(key=lambda x: (-x["score"], x["page"], x["span_index"]))
    return candidates[:20]


def dedup_candidates(candidates: List[Dict]) -> List[Dict]:
    merged = {}

    priority = {
        "citation_index_exact": 0,
        "citation_index_grouped": 1,
        "context_similarity": 2,
        "citation_index_neighbor": 3,
        "keyword_fallback": 4,
    }

    for c in candidates:
        key = (c["page"], c["span_index"])
        if key not in merged:
            copied = dict(c)
            if "evidence" not in copied:
                copied["evidence"] = [copied.get("match_type", "unknown")]
            merged[key] = copied
            continue

        old = merged[key]

        old_evidence = set(old.get("evidence", []))
        new_evidence = set(c.get("evidence", [c.get("match_type", "unknown")]))
        old["evidence"] = sorted(old_evidence | new_evidence)

        if c.get("context_overlap_score") is not None:
            old["context_overlap_score"] = max(
                old.get("context_overlap_score", 0),
                c.get("context_overlap_score", 0)
            )
            if c.get("matched_context") and not old.get("matched_context"):
                old["matched_context"] = c["matched_context"]

        old_match = old.get("match_type", "")
        new_match = c.get("match_type", "")

        old_rank = priority.get(old_match, 99)
        new_rank = priority.get(new_match, 99)

        replace = False
        if new_rank < old_rank:
            replace = True
        elif new_rank == old_rank and c.get("score", 0) > old.get("score", 0):
            replace = True

        if replace:
            preserved_evidence = old["evidence"]
            preserved_context_overlap_score = old.get("context_overlap_score")
            preserved_matched_context = old.get("matched_context")

            new_item = dict(c)
            new_item["evidence"] = preserved_evidence

            if preserved_context_overlap_score is not None and new_item.get("context_overlap_score") is None:
                new_item["context_overlap_score"] = preserved_context_overlap_score
            if preserved_matched_context and not new_item.get("matched_context"):
                new_item["matched_context"] = preserved_matched_context

            merged[key] = new_item

    return list(merged.values())


def filter_noisy_candidates(candidates: List[Dict]) -> Tuple[List[Dict], Dict[str, int]]:
    kept = []
    filtered = 0
    filtered_by_match_type = {}

    for cand in candidates:
        if is_noisy_analysis_text(cand.get("text", "")):
            filtered += 1
            match_type = cand.get("match_type", "unknown")
            filtered_by_match_type[match_type] = filtered_by_match_type.get(match_type, 0) + 1
            continue
        kept.append(cand)

    return kept, {
        "filtered_total": filtered,
        "filtered_by_match_type": filtered_by_match_type,
    }


def attach_local_context(candidates: List[Dict], body_paras: List[Dict]) -> List[Dict]:
    if not candidates or not body_paras:
        return candidates

    index_map = {}
    for idx, para in enumerate(body_paras):
        index_map[(para["page"], para["span_index"])] = idx

    enriched = []
    for cand in candidates:
        idx = index_map.get((cand.get("page"), cand.get("span_index")))
        if idx is None:
            enriched.append(cand)
            continue

        radius = 2 if cand.get("match_type") in {"citation_index_exact", "citation_index_grouped"} else 1
        bundle = []
        for nb in range(max(0, idx - radius), min(len(body_paras), idx + radius + 1)):
            para = body_paras[nb]
            if para["page"] == cand.get("page") and para["span_index"] == cand.get("span_index"):
                role = "focus"
            else:
                role = "context"

            bundle.append({
                "page": para["page"],
                "span_index": para["span_index"],
                "role": role,
                "text": para["text"],
                "noisy": is_noisy_analysis_text(para["text"]),
            })

        copied = dict(cand)
        copied["context_window"] = bundle
        copied["context_window_text"] = "\n\n".join(
            f"[Page {x['page']} | Span {x['span_index']} | {x['role']}{' | noisy' if x.get('noisy') else ''}]\n{x['text']}"
            for x in bundle
            if not x.get("noisy") or x["role"] == "focus"
        )
        enriched.append(copied)

    return enriched


def find_candidate_spans(
    fulltext_json: Dict,
    target_title: str,
    target_doi: Optional[str] = None,
    contexts_json_path: Optional[str] = None,
    citing_title: Optional[str] = None
):
    if not fulltext_json.get("ok"):
        return {"ok": False, "error": "输入 fulltext JSON 不可用"}

    body_paras, ref_start = collect_body_paragraphs(fulltext_json)

    contexts = load_citation_contexts(contexts_json_path, citing_title=citing_title)
    context_candidates = find_spans_by_context_similarity(body_paras, contexts) if contexts else []

    citation_index, citation_meta = find_citation_index_in_references(
        fulltext_json,
        target_title=target_title,
        target_doi=target_doi
    )
    index_candidates = find_spans_by_citation_index(body_paras, citation_index) if citation_index else []

    fallback_candidates = find_spans_by_fallback_keywords(body_paras, target_title, target_doi)

    all_candidates = []
    all_candidates.extend(index_candidates)
    all_candidates.extend(context_candidates)
    all_candidates.extend(fallback_candidates)

    all_candidates = dedup_candidates(all_candidates)
    all_candidates, filter_stats = filter_noisy_candidates(all_candidates)
    all_candidates = attach_local_context(all_candidates, body_paras)

    priority = {
        "citation_index_exact": 0,
        "citation_index_grouped": 1,
        "context_similarity": 2,
        "citation_index_neighbor": 3,
        "keyword_fallback": 4,
    }

    all_candidates.sort(
        key=lambda x: (
            priority.get(x.get("match_type", ""), 99),
            -x.get("score", 0),
            x.get("page", 9999),
            x.get("span_index", 9999),
        )
    )

    mode_parts = []
    if citation_index:
        mode_parts.append("citation_index")
    if contexts:
        mode_parts.append("context_similarity")
    if not mode_parts:
        mode_parts.append("keyword_fallback")

    return {
        "ok": True,
        "mode": "+".join(mode_parts),
        "reference_start_page": ref_start,
        "citation_index": citation_index,
        "citation_meta": citation_meta,
        "context_count": len(contexts),
        "context_candidate_count": len(context_candidates),
        "filtered_noisy_candidate_count": filter_stats["filtered_total"],
        "filtered_noisy_candidates_by_match_type": filter_stats["filtered_by_match_type"],
        "count": len(all_candidates),
        "spans": all_candidates[:20]
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({
            "ok": False,
            "error": "用法: python3 find_candidate_spans.py <fulltext_json_path> <target_title> [target_doi] [contexts_json_path] [citing_title]"
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    fulltext_path = sys.argv[1]
    target_title = sys.argv[2]
    target_doi = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    contexts_json_path = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != "-" else None
    citing_title = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] != "-" else None

    with open(fulltext_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = find_candidate_spans(
        data,
        target_title=target_title,
        target_doi=target_doi,
        contexts_json_path=contexts_json_path,
        citing_title=citing_title
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
