import json
import os
import sys
from typing import Dict, List

from pypdf import PdfReader

MIN_EXTRACTED_TEXT_CHARS = 20


def classify_pdf_extract_error(exc: Exception):
    text = str(exc or "")
    lowered = text.lower()

    if "password" in lowered or "encrypted" in lowered:
        return {
            "error_type": "pdf_encrypted",
            "error_stage": "extract_text_failed",
            "suggestion": "该 PDF 可能已加密，请先提供未加密版本。",
            "fallback_plan": "可尝试重新导出为未加密 PDF 后再上传。",
        }

    if (
        "stream has ended unexpectedly" in lowered
        or "eof marker not found" in lowered
        or "broken xref" in lowered
        or "malformed" in lowered
        or "trailer" in lowered
        or "unexpectedly" in lowered
    ):
        return {
            "error_type": "pdf_corrupted_or_malformed",
            "error_stage": "extract_text_failed",
            "suggestion": "该 PDF 更像是文件损坏、下载不完整或结构异常。",
            "fallback_plan": "建议先重新下载/重新上传；如仍失败，可尝试备用提取器做人工补救。",
        }

    return {
        "error_type": "pdf_extract_exception",
        "error_stage": "extract_text_failed",
        "suggestion": "PDF 提取阶段发生异常，请优先检查文件本身是否完整、可打开。",
        "fallback_plan": "建议先重新上传 PDF；如仍失败，再尝试备用提取器。",
    }


def _normalize_page_text(text: str):
    return (text or "").strip()


def _build_quality(pages: List[Dict]):
    nonempty_page_count = 0
    text_char_count = 0
    for page in pages:
        page_text = _normalize_page_text(page.get("text", ""))
        if page_text:
            nonempty_page_count += 1
            text_char_count += len(page_text)
    return {
        "nonempty_page_count": nonempty_page_count,
        "text_char_count": text_char_count,
    }


def _has_meaningful_text(pages: List[Dict]):
    quality = _build_quality(pages)
    return quality["text_char_count"] >= MIN_EXTRACTED_TEXT_CHARS and quality["nonempty_page_count"] > 0


def _flatten_attempt_errors(attempts: List[Dict]):
    page_errors = []
    for attempt in attempts:
        for page_error in attempt.get("page_errors", []):
            page_errors.append({
                "extractor": attempt.get("extractor"),
                **page_error,
            })
    return page_errors


def _summarize_attempt(attempt: Dict):
    return {
        "extractor": attempt.get("extractor"),
        "available": attempt.get("available", True),
        "opened": attempt.get("opened", False),
        "page_count": attempt.get("page_count", 0),
        "nonempty_page_count": attempt.get("nonempty_page_count", 0),
        "text_char_count": attempt.get("text_char_count", 0),
        "image_page_count": attempt.get("image_page_count", 0),
        "error_type": attempt.get("error_type", ""),
        "error": attempt.get("error", ""),
    }


def _extract_with_pypdf(pdf_path: str):
    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:
        return {
            "ok": False,
            "extractor": "pypdf",
            "available": True,
            "opened": False,
            "error": str(exc),
            **classify_pdf_extract_error(exc),
        }

    pages = []
    page_errors = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            text = ""
            page_errors.append({"page": i, "error": str(exc)})
        pages.append({"page": i, "text": _normalize_page_text(text)})

    quality = _build_quality(pages)
    return {
        "ok": _has_meaningful_text(pages),
        "extractor": "pypdf",
        "available": True,
        "opened": True,
        "page_count": len(pages),
        "pages": pages,
        "page_errors": page_errors,
        "image_page_count": 0,
        **quality,
    }


def _extract_with_pymupdf(pdf_path: str):
    try:
        import fitz
    except Exception as exc:
        return {
            "ok": False,
            "extractor": "pymupdf",
            "available": False,
            "opened": False,
            "error": str(exc),
            "error_type": "extractor_unavailable",
        }

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return {
            "ok": False,
            "extractor": "pymupdf",
            "available": True,
            "opened": False,
            "error": str(exc),
            **classify_pdf_extract_error(exc),
        }

    pages = []
    page_errors = []
    image_page_count = 0
    try:
        for i, page in enumerate(doc, start=1):
            try:
                text = page.get_text("text") or ""
                if page.get_images(full=True):
                    image_page_count += 1
            except Exception as exc:
                text = ""
                page_errors.append({"page": i, "error": str(exc)})
            pages.append({"page": i, "text": _normalize_page_text(text)})
    finally:
        doc.close()

    quality = _build_quality(pages)
    return {
        "ok": _has_meaningful_text(pages),
        "extractor": "pymupdf",
        "available": True,
        "opened": True,
        "page_count": len(pages),
        "pages": pages,
        "page_errors": page_errors,
        "image_page_count": image_page_count,
        **quality,
    }


def _extract_with_pdfplumber(pdf_path: str):
    try:
        import pdfplumber
    except Exception as exc:
        return {
            "ok": False,
            "extractor": "pdfplumber",
            "available": False,
            "opened": False,
            "error": str(exc),
            "error_type": "extractor_unavailable",
        }

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as exc:
        return {
            "ok": False,
            "extractor": "pdfplumber",
            "available": True,
            "opened": False,
            "error": str(exc),
            **classify_pdf_extract_error(exc),
        }

    pages = []
    page_errors = []
    image_page_count = 0
    try:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
                if getattr(page, "images", None):
                    image_page_count += 1
            except Exception as exc:
                text = ""
                page_errors.append({"page": i, "error": str(exc)})
            pages.append({"page": i, "text": _normalize_page_text(text)})
    finally:
        pdf.close()

    quality = _build_quality(pages)
    return {
        "ok": _has_meaningful_text(pages),
        "extractor": "pdfplumber",
        "available": True,
        "opened": True,
        "page_count": len(pages),
        "pages": pages,
        "page_errors": page_errors,
        "image_page_count": image_page_count,
        **quality,
    }


def _build_parse_failure(pdf_path: str, attempts: List[Dict]):
    error_parts = []
    for attempt in attempts:
        error = (attempt.get("error") or "").strip()
        if error:
            error_parts.append(f"{attempt.get('extractor')}: {error}")
    return {
        "ok": False,
        "pdf_path": pdf_path,
        "error": "；".join(error_parts) or "所有提取器都未能完成 PDF 解析。",
        "error_type": "pdf_parse_failed",
        "error_stage": "extract_text_failed",
        "suggestion": "当前 PDF 更像是结构异常、兼容性较差，或解析器均无法稳定读取。",
        "fallback_plan": "已依次尝试 pypdf、PyMuPDF、pdfplumber；当前版本不把 OCR 作为主路径。建议优先更换 PDF 源或重新导出文本版 PDF。",
        "extractor_attempts": [_summarize_attempt(attempt) for attempt in attempts],
        "page_errors": _flatten_attempt_errors(attempts),
    }


def _build_empty_text_failure(pdf_path: str, attempts: List[Dict]):
    opened_attempts = [attempt for attempt in attempts if attempt.get("opened")]
    likely_scanned = any((attempt.get("image_page_count") or 0) > 0 for attempt in opened_attempts)
    error_type = "likely_scanned_pdf" if likely_scanned else "empty_text_pdf"
    suggestion = (
        "PDF 可以打开，但看起来更像扫描版/图片版，缺少可提取文本层。"
        if likely_scanned
        else "PDF 可以打开，但提取到的文本几乎为空，可能是特殊编码、轮廓字形或不完整文本层。"
    )
    fallback_plan = (
        "已依次尝试 pypdf、PyMuPDF、pdfplumber；当前版本暂不把 OCR 作为主路径。后续如确认是扫描件，再单独接 OCR 补救。"
        if likely_scanned
        else "已依次尝试 pypdf、PyMuPDF、pdfplumber；建议优先更换来源更好的文本版 PDF。"
    )
    total_pages = max((attempt.get("page_count") or 0) for attempt in opened_attempts) if opened_attempts else 0
    return {
        "ok": False,
        "pdf_path": pdf_path,
        "error": "PDF 可打开，但提取文本几乎为空。",
        "error_type": error_type,
        "error_stage": "extract_text_failed",
        "suggestion": suggestion,
        "fallback_plan": fallback_plan,
        "page_count": total_pages,
        "extractor_attempts": [_summarize_attempt(attempt) for attempt in attempts],
        "page_errors": _flatten_attempt_errors(attempts),
    }


def extract_pdf_text(pdf_path: str):
    pdf_path = os.path.expanduser(pdf_path)

    if not os.path.exists(pdf_path):
        return {
            "ok": False,
            "error": f"文件不存在: {pdf_path}",
            "error_type": "pdf_file_missing",
            "error_stage": "extract_text_failed",
            "suggestion": "服务器上未找到该 PDF 文件，请确认上传或下载是否成功。",
            "fallback_plan": "重新上传 PDF，或检查下载目录配置是否正确。",
        }

    attempts = []

    primary_result = _extract_with_pypdf(pdf_path)
    attempts.append(primary_result)
    if primary_result.get("ok"):
        return {
            "ok": True,
            "pdf_path": pdf_path,
            "extractor": "pypdf",
            "page_count": primary_result.get("page_count", 0),
            "pages": primary_result.get("pages", []),
            "page_errors": primary_result.get("page_errors", []),
            "text_char_count": primary_result.get("text_char_count", 0),
        }

    if primary_result.get("error_type") == "pdf_encrypted":
        return {
            "ok": False,
            "pdf_path": pdf_path,
            "error": primary_result.get("error", ""),
            "error_type": "pdf_encrypted",
            "error_stage": primary_result.get("error_stage", "extract_text_failed"),
            "suggestion": primary_result.get("suggestion", "该 PDF 可能已加密，请先提供未加密版本。"),
            "fallback_plan": primary_result.get("fallback_plan", "可尝试重新导出为未加密 PDF 后再上传。"),
            "extractor_attempts": [_summarize_attempt(primary_result)],
            "page_errors": primary_result.get("page_errors", []),
        }

    for extractor in (_extract_with_pymupdf, _extract_with_pdfplumber):
        attempt = extractor(pdf_path)
        attempts.append(attempt)
        if attempt.get("ok"):
            return {
                "ok": True,
                "pdf_path": pdf_path,
                "extractor": attempt.get("extractor"),
                "page_count": attempt.get("page_count", 0),
                "pages": attempt.get("pages", []),
                "page_errors": attempt.get("page_errors", []),
                "text_char_count": attempt.get("text_char_count", 0),
                "fallback_used": True,
                "extractor_attempts": [_summarize_attempt(item) for item in attempts],
            }

    if any(attempt.get("opened") for attempt in attempts):
        return _build_empty_text_failure(pdf_path, attempts)

    return _build_parse_failure(pdf_path, attempts)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(extract_pdf_text(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": False, "error": "请提供 PDF 路径"}, ensure_ascii=False, indent=2))
