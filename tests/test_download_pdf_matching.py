from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_PDF_PATH = ROOT / "skills" / "download_paper_pdf" / "download_pdf.py"


def load_download_pdf_module():
    spec = importlib.util.spec_from_file_location(
        "test_download_pdf_matching_module",
        DOWNLOAD_PDF_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DownloadPdfMatchingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_download_pdf_module()

    def test_find_local_pdf_is_case_insensitive_for_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "MY IMPORTANT PAPER.PDF"
            pdf_path.write_bytes(b"%PDF-1.4\n% test\n")

            matched = self.module.find_local_pdf(
                query="my important paper",
                search_dir=tmpdir,
            )

        self.assertEqual(matched, str(pdf_path))

    def test_find_local_pdf_matches_noisy_downloaded_filename(self):
        title = "Achieving Fairness Generalizability for Learning based Congestion Control with Jury"
        noisy_name = (
            "Achieving Fairness Generalizability for Learning based Congestion Control "
            "with Jury arxiv preprint accepted version supplementary material"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / f"{noisy_name}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% test\n")

            matched = self.module.find_local_pdf(
                title=title,
                search_dir=tmpdir,
            )

        self.assertEqual(matched, str(pdf_path))

    def test_find_local_pdf_with_metadata_prefers_index_cache(self):
        title = "A Study on Cache Friendly Congestion Control"
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / f"{title}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
            index_path = Path(tmpdir) / "local_pdf_index.json"

            self.module.build_local_pdf_index(
                [tmpdir],
                index_path=str(index_path),
            )

            with mock.patch.object(
                self.module,
                "list_local_pdf_files",
                side_effect=AssertionError("index cache should avoid directory scan"),
            ):
                match = self.module.find_local_pdf_with_metadata(
                    title=title,
                    search_dirs=[tmpdir],
                    index_path=str(index_path),
                )

        self.assertIsNotNone(match)
        self.assertEqual(match["local_file_path"], str(pdf_path))
        self.assertEqual(match["match_source"], "index_cache")

    def test_find_local_pdf_with_metadata_falls_back_when_index_misses_directory(self):
        title = "A Study on Directory Coverage"
        with tempfile.TemporaryDirectory() as indexed_dir, tempfile.TemporaryDirectory() as actual_dir:
            index_path = Path(actual_dir) / "local_pdf_index.json"
            pdf_path = Path(actual_dir) / f"{title}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% test\n")

            self.module.build_local_pdf_index(
                [indexed_dir],
                index_path=str(index_path),
            )

            match = self.module.find_local_pdf_with_metadata(
                title=title,
                search_dirs=[actual_dir],
                index_path=str(index_path),
            )

        self.assertIsNotNone(match)
        self.assertEqual(match["local_file_path"], str(pdf_path))
        self.assertEqual(match["match_source"], "directory_scan")


if __name__ == "__main__":
    unittest.main()
