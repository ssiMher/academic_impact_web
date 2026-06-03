import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime
from time import monotonic
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "skills"
DEFAULT_RUNS_DIR = ROOT / "data" / "runs"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LIST_PAPERS = load_module(
    "list_papers_module",
    SKILLS_ROOT / "list_all_citations" / "list_papers.py"
)
FETCH_CONTEXTS = load_module(
    "fetch_contexts_module",
    SKILLS_ROOT / "academic_impact_analyzer" / "fetch_contexts.py"
)
DOWNLOAD_PDF = load_module(
    "download_pdf_module",
    SKILLS_ROOT / "download_paper_pdf" / "download_pdf.py"
)
EXTRACT_TEXT = load_module(
    "extract_text_module",
    SKILLS_ROOT / "extract_pdf_text" / "extract_text.py"
)
FIND_SPANS = load_module(
    "find_candidate_spans_module",
    SKILLS_ROOT / "analyze_fulltext_citation" / "find_candidate_spans.py"
)
ANALYZE_FULLTEXT = load_module(
    "analyze_fulltext_module",
    SKILLS_ROOT / "analyze_fulltext_citation" / "analyze_fulltext.py"
)
AGGREGATE_REPORT = load_module(
    "aggregate_report_module",
    SKILLS_ROOT / "academic_impact_analyzer" / "aggregate_report.py"
)

VALID_ANALYSIS_SCOPES = {"candidate_spans", "fulltext_direct"}


def slugify(text: str, limit: int = 80) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:limit] or "paper"


def sanitize_json_value(value):
    if isinstance(value, str):
        return re.sub(r"[\ud800-\udfff]", "", value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    return value


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_json_value(data)
    path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")


def make_failure_note(error_type: str, error: str = "") -> Dict:
    messages = {
        "extract_text_failed": "PDF 已获得，但全文提取失败，无法进入全文分析。",
        "pdf_parse_failed": "PDF 已获得，但多个解析器都未能稳定解析文本。",
        "empty_text_pdf": "PDF 已获得，但提取到的文本几乎为空，无法进入全文分析。",
        "likely_scanned_pdf": "PDF 已获得，但更像扫描版/图片版，当前无法直接进入全文分析。",
        "candidate_span_failed": "全文已提取，但候选段落定位失败，无法进入全文分析。",
        "single_model_request_failed": "候选段落已生成，但分析模型请求失败，无法完成全文分析。",
        "single_model_json_parse_failed": "分析模型已返回结果，但 JSON 解析失败。",
        "single_model_schema_invalid": "分析模型已返回 JSON，但结构不符合全文分析 schema。",
        "local_model_request_failed": "候选段落已生成，但本地模型请求失败，无法完成全文分析。",
        "blank_model_output": "候选段落已生成，但分析模型返回空输出，无法完成全文分析。",
        "deepseek_request_failed": "本地模型已返回分析结果，但 DeepSeek 整理阶段请求失败。",
        "deepseek_json_parse_failed": "本地模型与 DeepSeek 已返回结果，但 JSON 解析失败。",
        "write_output_failed": "分析过程完成了一部分，但写出结果文件失败。",
    }
    return {
        "evidence_label": error_type,
        "message": messages.get(error_type, "全文分析流程失败。") + (f" 详情：{error}" if error else ""),
    }


def safe_write_json(path: Path, data) -> Tuple[bool, str]:
    try:
        write_json(path, data)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def normalize_title_key(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def choose_download_queries(paper: dict) -> List[str]:
    external_ids = paper.get("externalIds") or {}
    candidates = [
        external_ids.get("DOI"),
        external_ids.get("ArXiv"),
        paper.get("title", ""),
    ]
    queries = []
    seen = set()
    for candidate in candidates:
        value = (candidate or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(value)
    return queries or [paper.get("title", "").strip() or "unknown"]


def should_prioritize_result(result: dict) -> bool:
    status = result.get("status")
    return status not in {"context_only", "fulltext_extract_failed", "analysis_failed"}


def normalize_analysis_scope(value: str = "") -> str:
    scope = (value or "fulltext_direct").strip().lower().replace("-", "_")
    if scope in {"candidate", "candidate_span", "spans"}:
        return "candidate_spans"
    if scope in {"fulltext", "full_text", "direct", "fulltext_direct"}:
        return "fulltext_direct"
    return "fulltext_direct"


def build_fulltext_direct_pages(fulltext_result: dict) -> List[dict]:
    pages = fulltext_result.get("pages", []) if isinstance(fulltext_result, dict) else []
    if not isinstance(pages, list):
        return []

    normalized = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        page_number = page.get("page")
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            page_number = index
        normalized.append({"page": page_number, "text": text})
    return normalized


def classify_fulltext_status(candidate_result: dict, analysis_result: dict) -> Tuple[str, Dict]:
    spans = candidate_result.get("spans", []) if isinstance(candidate_result, dict) else []
    findings = analysis_result.get("findings", []) if isinstance(analysis_result, dict) else []

    has_findings = isinstance(findings, list) and len(findings) > 0
    only_weak_findings = has_findings and all(
        x.get("mention_type") in {"grouped_literature_mention", "weak_body_mention"}
        for x in findings
    )
    has_citation_index = bool(candidate_result.get("citation_index"))
    has_index_hits = any(
        s.get("match_type") in {"citation_index_exact", "citation_index_grouped", "citation_index_neighbor"}
        for s in spans
    )
    top_span = spans[0] if spans else None
    top_evidence = top_span.get("evidence", []) if isinstance(top_span, dict) else []
    top_score = top_span.get("score", 0) if isinstance(top_span, dict) else 0

    if has_findings and not only_weak_findings:
        return "fulltext_analyzed", {
            "evidence_label": "semantic_finding",
            "message": "已在全文中识别出可解释的引用语义段落。"
        }

    if only_weak_findings:
        return "mention_only", {
            "evidence_label": "weak_body_mention",
            "message": "正文中存在弱提及，已保留为轻量引用结论，但不足以支撑更强的语义判断。"
        }

    if has_citation_index and not has_index_hits:
        return "reference_only", {
            "evidence_label": "reference_only",
            "message": "已在参考文献中定位到目标论文条目，但正文中未找到可复核的对应引用段落。"
        }

    if (
        "citation_index_exact" in top_evidence
        or "citation_index_grouped" in top_evidence
        or "citation_index_neighbor" in top_evidence
    ):
        return "mention_only", {
            "evidence_label": "weak_body_mention",
            "message": "正文中存在与目标论文编号相关的弱命中，但未形成可分析的明确引用语义。"
        }

    if top_score and top_score >= 3:
        return "mention_only", {
            "evidence_label": "weak_keyword_mention",
            "message": "正文中存在弱关键词命中，但未形成可分析的明确引用语义。"
        }

    return "fulltext_no_finding", {
        "evidence_label": "no_reliable_evidence",
        "message": "已完成全文扫描，但未找到足够可靠的正文引用证据。"
    }


def make_context_fallback_result(citing_paper: dict, contexts_data: dict):
    best_match = None
    citing_title = (citing_paper.get("title") or "").strip().lower()

    for item in contexts_data.get("results", []):
        item_title = (item.get("citing_title") or "").strip().lower()
        if item_title == citing_title:
            best_match = item
            break

    contexts = []
    if best_match:
        if best_match.get("best_context"):
            contexts.append(best_match["best_context"])
        for ctx in best_match.get("contexts", []):
            if ctx not in contexts:
                contexts.append(ctx)

    return {
        "ok": True,
        "mode": "context_only",
        "verified_by_fulltext": False,
        "citing_title": citing_paper.get("title", ""),
        "citing_year": citing_paper.get("year"),
        "citing_venue": citing_paper.get("venue"),
        "fallback_contexts": contexts[:5],
        "message": "未获得全文 PDF，当前结果仅基于 citation contexts，未经全文验证。"
    }


def reorder_papers_by_context_signal(all_papers: List[dict], contexts_data: dict) -> List[dict]:
    if not isinstance(contexts_data, dict):
        return all_papers

    context_rank = {}
    for rank, item in enumerate(contexts_data.get("results", [])):
        title_key = normalize_title_key(item.get("citing_title", ""))
        if not title_key:
            continue

        best_context = item.get("best_context") or {}
        score = best_context.get("score", 0) or 0
        confidence = item.get("confidence", "")
        confidence_rank = {"high": 2, "medium": 1, "low": 0}.get(confidence, 0)
        context_rank[title_key] = {
            "score": score,
            "confidence_rank": confidence_rank,
            "context_rank": rank,
        }

    indexed_papers = list(enumerate(all_papers))

    def sort_key(item):
        original_index, paper = item
        title_key = normalize_title_key(paper.get("title", ""))
        ctx = context_rank.get(title_key)
        if not ctx:
            return (1, 0, 0, original_index)
        return (
            0,
            -ctx["score"],
            -ctx["confidence_rank"],
            ctx["context_rank"],
        )

    reordered = [paper for _, paper in sorted(indexed_papers, key=sort_key)]
    return reordered


def process_citing_paper(
    target: dict,
    citing_paper: dict,
    contexts_data: dict,
    item_dir: Path,
    top_k_spans: int,
    local_pdf_path: str = "",
    analysis_scope: str = "fulltext_direct",
    analysis_model_profile: str = "",
    template_prompt_fragment: str = "",
    progress_callback=None,
):
    analysis_scope = normalize_analysis_scope(analysis_scope)
    result = {
        "citing_paper": citing_paper,
        "analysis_scope": analysis_scope,
        "paths": {},
    }

    def report_stage(stage: str, stage_message: str) -> None:
        if progress_callback:
            progress_callback({"stage": stage, "stage_message": stage_message})

    download_queries = choose_download_queries(citing_paper)
    result["download_query"] = download_queries[0]
    result["download_queries"] = download_queries

    download_attempts = []
    download_result = None
    local_pdf = Path(local_pdf_path).expanduser() if local_pdf_path else None
    if local_pdf and local_pdf.exists():
        download_result = {
            "ok": True,
            "query": citing_paper.get("title", ""),
            "title": citing_paper.get("title", ""),
            "pdf_url": "",
            "pdf_candidates": [str(local_pdf)],
            "file_path": str(local_pdf),
            "source": "attached_local_pdf",
            "paper": citing_paper,
        }
    for download_query in download_queries:
        if download_result is not None:
            break
        report_stage("downloading_pdf", "正在下载 PDF")
        attempt_result = DOWNLOAD_PDF.download_paper(download_query)
        attempt_result = dict(attempt_result)
        attempt_result["requested_via"] = download_query
        download_attempts.append(attempt_result)
        if attempt_result.get("ok"):
            download_result = dict(attempt_result)
            break

    if download_result is None:
        download_result = dict(download_attempts[-1]) if download_attempts else {
            "ok": False,
            "query": "",
            "error": "未生成任何下载尝试。"
        }

    download_result["attempts"] = download_attempts
    result["download"] = download_result
    download_path = item_dir / "download.json"
    ok, write_error = safe_write_json(download_path, download_result)
    if not ok:
        result["status"] = "write_output_failed"
        result["status_note"] = make_failure_note("write_output_failed", write_error)
        result["analysis"] = {
            "ok": False,
            "error_type": "write_output_failed",
            "error": write_error,
            "message": result["status_note"]["message"],
        }
        return result
    result["paths"]["download"] = str(download_path)

    if not download_result.get("ok"):
        fallback_result = make_context_fallback_result(citing_paper, contexts_data)
        fallback_path = item_dir / "context_fallback.json"
        ok, write_error = safe_write_json(fallback_path, fallback_result)
        if not ok:
            result["status"] = "write_output_failed"
            result["status_note"] = make_failure_note("write_output_failed", write_error)
            result["analysis"] = {
                "ok": False,
                "error_type": "write_output_failed",
                "error": write_error,
                "message": result["status_note"]["message"],
            }
            return result
        result["fallback_analysis"] = fallback_result
        result["paths"]["fallback_analysis"] = str(fallback_path)
        result["status"] = "context_only"
        return result

    try:
        report_stage("extracting_fulltext", "正在抽取 PDF 全文")
        fulltext_result = EXTRACT_TEXT.extract_pdf_text(download_result["file_path"])
    except Exception as exc:
        fulltext_result = {
            "ok": False,
            "error": str(exc),
            "error_type": "pdf_parse_failed",
            "error_stage": "extract_text_failed",
        }
    fulltext_path = item_dir / "fulltext.json"
    ok, write_error = safe_write_json(fulltext_path, fulltext_result)
    if not ok:
        result["status"] = "write_output_failed"
        result["status_note"] = make_failure_note("write_output_failed", write_error)
        result["analysis"] = {
            "ok": False,
            "error_type": "write_output_failed",
            "error": write_error,
            "message": result["status_note"]["message"],
        }
        return result
    result["fulltext"] = {
        "ok": fulltext_result.get("ok"),
        "page_count": fulltext_result.get("page_count"),
    }
    result["paths"]["fulltext"] = str(fulltext_path)

    if not fulltext_result.get("ok"):
        failure_error_type = fulltext_result.get("error_type") or "extract_text_failed"
        failure_analysis = {
            "ok": False,
            "citing_title": citing_paper.get("title", ""),
            "findings": [],
            "error_type": failure_error_type,
            "error_stage": fulltext_result.get("error_stage", "extract_text_failed"),
            "error": fulltext_result.get("error", ""),
        }
        analysis_path = item_dir / "fulltext_analysis.json"
        ok, write_error = safe_write_json(analysis_path, failure_analysis)
        if not ok:
            result["status"] = "write_output_failed"
            result["status_note"] = make_failure_note("write_output_failed", write_error)
            result["analysis"] = {
                "ok": False,
                "error_type": "write_output_failed",
                "error": write_error,
                "message": result["status_note"]["message"],
            }
            return result
        result["paths"]["analysis"] = str(analysis_path)
        result["status"] = "fulltext_extract_failed"
        result["status_note"] = make_failure_note(failure_error_type, fulltext_result.get("error", ""))
        result["analysis"] = {
            "ok": False,
            "error_type": failure_error_type,
            "error": fulltext_result.get("error", ""),
            "message": result["status_note"]["message"],
        }
        return result

    try:
        report_stage("finding_candidate_spans", "正在定位候选引用片段")
        candidate_result = FIND_SPANS.find_candidate_spans(
            fulltext_result,
            target_title=target.get("title", ""),
            target_doi=(target.get("externalIds") or {}).get("DOI"),
            contexts_json_path=str(item_dir.parent / "contexts.json"),
            citing_title=citing_paper.get("title"),
        )
    except Exception as exc:
        candidate_result = {
            "ok": False,
            "error": str(exc),
            "error_type": "candidate_span_failed",
            "error_stage": "candidate_span_failed",
            "spans": [],
        }
    candidate_path = item_dir / "candidate_spans.json"
    ok, write_error = safe_write_json(candidate_path, candidate_result)
    if not ok:
        result["status"] = "write_output_failed"
        result["status_note"] = make_failure_note("write_output_failed", write_error)
        result["analysis"] = {
            "ok": False,
            "error_type": "write_output_failed",
            "error": write_error,
            "message": result["status_note"]["message"],
        }
        return result
    result["candidate_spans"] = {
        "ok": candidate_result.get("ok"),
        "count": candidate_result.get("count"),
        "mode": candidate_result.get("mode"),
        "citation_index": candidate_result.get("citation_index"),
    }
    result["paths"]["candidate_spans"] = str(candidate_path)

    if not candidate_result.get("ok") and analysis_scope != "fulltext_direct":
        failure_analysis = {
            "ok": False,
            "citing_title": citing_paper.get("title", ""),
            "findings": [],
            "error_type": "candidate_span_failed",
            "error_stage": "candidate_span_failed",
            "error": candidate_result.get("error", ""),
        }
        analysis_path = item_dir / "fulltext_analysis.json"
        ok, write_error = safe_write_json(analysis_path, failure_analysis)
        if not ok:
            result["status"] = "write_output_failed"
            result["status_note"] = make_failure_note("write_output_failed", write_error)
            result["analysis"] = {
                "ok": False,
                "error_type": "write_output_failed",
                "error": write_error,
                "message": result["status_note"]["message"],
            }
            return result
        result["paths"]["analysis"] = str(analysis_path)
        result["status"] = "analysis_failed"
        result["status_note"] = make_failure_note("candidate_span_failed", candidate_result.get("error", ""))
        result["analysis"] = {
            "ok": False,
            "error_type": "candidate_span_failed",
            "error": candidate_result.get("error", ""),
            "message": result["status_note"]["message"],
        }
        return result

    candidate_spans = candidate_result.get("spans", [])[:top_k_spans] if candidate_result.get("ok") else []
    payload = {
        "target_title": target.get("title", ""),
        "target_year": target.get("year"),
        "citing_title": citing_paper.get("title", ""),
        "analysis_scope": analysis_scope,
        "candidate_spans": candidate_spans,
    }
    if analysis_model_profile:
        payload["analysis_model_profile"] = analysis_model_profile
    if candidate_result.get("citation_index"):
        payload["target_citation_index"] = candidate_result.get("citation_index")
    citation_meta = candidate_result.get("citation_meta") if isinstance(candidate_result, dict) else {}
    if isinstance(citation_meta, dict):
        reference_text = citation_meta.get("reference_text")
        if reference_text:
            payload["target_reference_text"] = reference_text
        payload["citation_meta"] = citation_meta
    if template_prompt_fragment:
        payload["template_prompt_fragment"] = template_prompt_fragment
    if analysis_scope == "fulltext_direct":
        fulltext_pages = build_fulltext_direct_pages(fulltext_result)
        payload["fulltext_pages"] = fulltext_pages
        payload["fulltext_page_count"] = len(fulltext_pages)
        payload["fulltext_char_count"] = sum(len(page.get("text", "")) for page in fulltext_pages)
    payload_path = item_dir / "analyze_payload.json"
    ok, write_error = safe_write_json(payload_path, payload)
    if not ok:
        result["status"] = "write_output_failed"
        result["status_note"] = make_failure_note("write_output_failed", write_error)
        result["analysis"] = {
            "ok": False,
            "error_type": "write_output_failed",
            "error": write_error,
            "message": result["status_note"]["message"],
        }
        return result
    result["paths"]["analyze_payload"] = str(payload_path)

    analysis_started = monotonic()
    report_stage("analyzing_fulltext", "正在调用模型分析全文")
    analysis_result = ANALYZE_FULLTEXT.analyze_payload(payload)
    analysis_duration_seconds = round(monotonic() - analysis_started, 2)
    analysis_path = item_dir / "fulltext_analysis.json"
    ok, write_error = safe_write_json(analysis_path, analysis_result)
    if not ok:
        result["status"] = "write_output_failed"
        result["status_note"] = make_failure_note("write_output_failed", write_error)
        result["analysis"] = {
            "ok": False,
            "candidate_span_count": len(payload.get("candidate_spans", [])),
            "analysis_scope": analysis_scope,
            "findings_count": len(analysis_result.get("findings", [])) if isinstance(analysis_result.get("findings"), list) else 0,
            "duration_seconds": analysis_duration_seconds,
            "error_type": "write_output_failed",
            "error": write_error,
            "message": result["status_note"]["message"],
        }
        return result
    final_status, final_note = classify_fulltext_status(candidate_result, analysis_result)
    result["analysis"] = {
        "ok": analysis_result.get("ok"),
        "candidate_span_count": len(payload.get("candidate_spans", [])),
        "analysis_scope": analysis_scope,
        "analysis_model_profile": analysis_model_profile,
        "fulltext_page_count": len(payload.get("fulltext_pages", [])),
        "fulltext_char_count": payload.get("fulltext_char_count", 0),
        "findings_count": len(analysis_result.get("findings", [])) if isinstance(analysis_result.get("findings"), list) else 0,
        "duration_seconds": analysis_duration_seconds,
        "final_status": final_status,
        "message": final_note["message"],
        "error_type": analysis_result.get("error_type"),
        "error_stage": analysis_result.get("error_stage"),
        "error": analysis_result.get("error", ""),
    }
    result["paths"]["analysis"] = str(analysis_path)
    result["status"] = final_status if analysis_result.get("ok") else "analysis_failed"
    if analysis_result.get("ok"):
        result["status_note"] = final_note
    else:
        error_type = analysis_result.get("error_type") or "analysis_failed"
        result["status_note"] = make_failure_note(error_type, analysis_result.get("error", ""))
    return result


def run_pipeline(
    query: str,
    output_dir: Path,
    max_papers: int,
    top_k_spans: int,
    scan_limit: int,
    analysis_scope: str = "fulltext_direct",
    analysis_model_profile: str = "",
):
    analysis_scope = normalize_analysis_scope(analysis_scope)
    started_at = datetime.now().isoformat(timespec="seconds")
    output_dir.mkdir(parents=True, exist_ok=True)

    list_result = LIST_PAPERS.list_all_citations(query)
    write_json(output_dir / "list_papers.json", list_result)
    if not list_result.get("ok"):
        return list_result

    contexts_result = FETCH_CONTEXTS.get_citation_contexts(query)
    write_json(output_dir / "contexts.json", contexts_result)

    target = list_result.get("target", {})
    all_papers = reorder_papers_by_context_signal(
        list_result.get("papers", []),
        contexts_result if isinstance(contexts_result, dict) else {},
    )
    effective_scan_limit = min(len(all_papers), max(max_papers, scan_limit))
    prioritized_results = []
    deferred_results = []
    scanned_papers = 0

    for index, paper in enumerate(all_papers[:effective_scan_limit], start=1):
        scanned_papers += 1
        item_dir = output_dir / f"{index:03d}_{slugify(paper.get('title', ''))}"
        paper_result = process_citing_paper(
            target=target,
            citing_paper=paper,
            contexts_data=contexts_result if isinstance(contexts_result, dict) else {},
            item_dir=item_dir,
            top_k_spans=top_k_spans,
            analysis_scope=analysis_scope,
            analysis_model_profile=analysis_model_profile,
        )
        if should_prioritize_result(paper_result):
            prioritized_results.append(paper_result)
        else:
            deferred_results.append(paper_result)

        if len(prioritized_results) >= max_papers:
            break

    per_paper_results = prioritized_results[:max_papers]
    if len(per_paper_results) < max_papers:
        need = max_papers - len(per_paper_results)
        per_paper_results.extend(deferred_results[:need])

    summary = {
        "ok": True,
        "query": query,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_dir),
        "target": target,
        "list_papers_count": list_result.get("count", 0),
        "scan_limit": effective_scan_limit,
        "scanned_papers": scanned_papers,
        "processed_papers": len(per_paper_results),
        "analysis_scope": analysis_scope,
        "analysis_model_profile": analysis_model_profile,
        "prioritized_results": len(prioritized_results),
        "deferred_results": len(deferred_results),
        "contexts_ok": contexts_result.get("ok") if isinstance(contexts_result, dict) else False,
        "results": per_paper_results,
    }
    summary_path = output_dir / "summary.json"
    write_json(summary_path, summary)

    report = AGGREGATE_REPORT.build_report(summary)
    report_json_path, report_md_path = AGGREGATE_REPORT.write_outputs(output_dir, report)
    summary["status_counts"] = report.get("status_counts", {})
    summary["papers"] = per_paper_results
    summary["report"] = {
        "json_path": str(report_json_path),
        "md_path": str(report_md_path),
    }
    write_json(summary_path, summary)
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="运行学术影响力分析总控流水线")
    parser.add_argument("query", help="目标论文 DOI、arXiv 编号或标题")
    parser.add_argument("--output-dir", help="输出目录，默认写入 /tmp/academic_impact_runs/<时间戳>_<slug>")
    parser.add_argument("--max-papers", type=int, default=5, help="最多处理多少篇 citing paper，默认 5")
    parser.add_argument("--scan-limit", type=int, help="最多向前扫描多少篇 citing paper，默认 max-papers 的 3 倍")
    parser.add_argument("--top-k-spans", type=int, default=8, help="送入 analyze_fulltext 的候选段落数，默认 8")
    parser.add_argument(
        "--analysis-scope",
        choices=sorted(VALID_ANALYSIS_SCOPES),
        default="fulltext_direct",
        help="分析范围：fulltext_direct 为默认单篇全文直读模式，candidate_spans 为候选段落模式",
    )
    parser.add_argument(
        "--analysis-model-profile",
        choices=["default", "local", "deepseek"],
        default="",
        help="分析模型：default 跟随环境配置，local 使用本地模型，deepseek 使用 DeepSeek。",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_RUNS_DIR / f"{timestamp}_{slugify(args.query, limit=50)}"

    max_papers = max(1, args.max_papers)
    scan_limit = max_papers * 3 if args.scan_limit is None else max(max_papers, args.scan_limit)

    try:
        result = run_pipeline(
            query=args.query,
            output_dir=output_dir,
            max_papers=max_papers,
            top_k_spans=max(1, args.top_k_spans),
            scan_limit=scan_limit,
            analysis_scope=args.analysis_scope,
            analysis_model_profile=args.analysis_model_profile,
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
