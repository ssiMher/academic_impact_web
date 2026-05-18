from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_PDF_PATH = ROOT / "skills" / "download_paper_pdf" / "download_pdf.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(description="Build a lightweight local PDF filename index.")
    parser.add_argument(
        "--search-dir",
        action="append",
        default=[],
        help="Local PDF directory to scan. Repeat this flag for multiple directories.",
    )
    parser.add_argument(
        "--index-path",
        default="",
        help="Where to write the JSON index. Defaults to ACADEMIC_IMPACT_PDF_INDEX_PATH or project default.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    download_pdf = load_module(DOWNLOAD_PDF_PATH, "build_local_pdf_index_download_pdf")
    search_dirs = args.search_dir or []
    if not search_dirs:
        env_dirs = os.getenv("ACADEMIC_IMPACT_PDF_LIBRARY_DIRS", "")
        if env_dirs:
            search_dirs.extend(
                entry.strip()
                for entry in env_dirs.split(os.pathsep)
                if entry.strip()
            )
    if not search_dirs:
        search_dirs = [download_pdf.DEFAULT_LOCAL_PDF_DIR]

    index_path = args.index_path or download_pdf.DEFAULT_LOCAL_PDF_INDEX_PATH
    payload = download_pdf.build_local_pdf_index(search_dirs, index_path=index_path)
    print(
        json.dumps(
            {
                "index_path": str(Path(index_path).expanduser()),
                "search_dirs": payload.get("search_dirs", []),
                "entry_count": payload.get("entry_count", 0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
