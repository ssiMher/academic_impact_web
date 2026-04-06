import sys
import os
import json
from pypdf import PdfReader

def extract_pdf_text(pdf_path: str):
    pdf_path = os.path.expanduser(pdf_path)

    if not os.path.exists(pdf_path):
        return {
            "ok": False,
            "error": f"文件不存在: {pdf_path}"
        }

    reader = PdfReader(pdf_path)
    pages = []

    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            text = f"[page extract failed: {e}]"

        pages.append({
            "page": i,
            "text": text.strip()
        })

    return {
        "ok": True,
        "pdf_path": pdf_path,
        "page_count": len(pages),
        "pages": pages
    }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(extract_pdf_text(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": False, "error": "请提供 PDF 路径"}, ensure_ascii=False, indent=2))
