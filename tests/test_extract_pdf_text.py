from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXTRACT_TEXT_PATH = ROOT / 'skills' / 'extract_pdf_text' / 'extract_text.py'


def load_extract_text_module():
    spec = importlib.util.spec_from_file_location('test_extract_text_module', EXTRACT_TEXT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ExtractPdfTextTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_extract_text_module()

    def test_classify_corrupted_pdf_error(self):
        info = self.module.classify_pdf_extract_error(RuntimeError('Stream has ended unexpectedly'))
        self.assertEqual(info['error_type'], 'pdf_corrupted_or_malformed')
        self.assertEqual(info['error_stage'], 'extract_text_failed')
        self.assertIn('文件损坏', info['suggestion'])

    def test_extract_pdf_text_preserves_encrypted_error(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            with mock.patch.object(self.module, '_extract_with_pypdf', return_value={
                'ok': False,
                'extractor': 'pypdf',
                'available': True,
                'opened': False,
                'error_type': 'pdf_encrypted',
                'error_stage': 'extract_text_failed',
                'error': 'File has not been decrypted',
                'suggestion': '该 PDF 可能已加密，请先提供未加密版本。',
                'fallback_plan': '可尝试重新导出为未加密 PDF 后再上传。',
                'page_errors': [],
            }), mock.patch.object(self.module, '_extract_with_pymupdf') as pymupdf, mock.patch.object(self.module, '_extract_with_pdfplumber') as pdfplumber:
                result = self.module.extract_pdf_text(tmp.name)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'pdf_encrypted')
        self.assertEqual(len(result['extractor_attempts']), 1)
        pymupdf.assert_not_called()
        pdfplumber.assert_not_called()

    def test_extract_pdf_text_falls_back_to_pymupdf(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            with mock.patch.object(self.module, '_extract_with_pypdf', return_value={
                'ok': False,
                'extractor': 'pypdf',
                'available': True,
                'opened': False,
                'error_type': 'pdf_corrupted_or_malformed',
                'error': 'broken xref',
            }), mock.patch.object(self.module, '_extract_with_pymupdf', return_value={
                'ok': True,
                'extractor': 'pymupdf',
                'available': True,
                'opened': True,
                'page_count': 1,
                'pages': [{'page': 1, 'text': 'fallback text'}],
                'page_errors': [],
                'text_char_count': 13,
            }), mock.patch.object(self.module, '_extract_with_pdfplumber') as pdfplumber:
                result = self.module.extract_pdf_text(tmp.name)

        self.assertTrue(result['ok'])
        self.assertEqual(result['extractor'], 'pymupdf')
        self.assertTrue(result['fallback_used'])
        self.assertEqual(len(result['extractor_attempts']), 2)
        pdfplumber.assert_not_called()

    def test_extract_pdf_text_reports_parse_failed_after_all_extractors_fail(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            with mock.patch.object(self.module, '_extract_with_pypdf', return_value={
                'ok': False,
                'extractor': 'pypdf',
                'available': True,
                'opened': False,
                'error_type': 'pdf_corrupted_or_malformed',
                'error': 'broken xref',
            }), mock.patch.object(self.module, '_extract_with_pymupdf', return_value={
                'ok': False,
                'extractor': 'pymupdf',
                'available': True,
                'opened': False,
                'error_type': 'pdf_extract_exception',
                'error': 'cannot open broken document',
            }), mock.patch.object(self.module, '_extract_with_pdfplumber', return_value={
                'ok': False,
                'extractor': 'pdfplumber',
                'available': True,
                'opened': False,
                'error_type': 'pdf_extract_exception',
                'error': 'unexpected eof',
            }):
                result = self.module.extract_pdf_text(tmp.name)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'pdf_parse_failed')
        self.assertEqual(result['error_stage'], 'extract_text_failed')
        self.assertEqual(len(result['extractor_attempts']), 3)
        self.assertIn('pypdf: broken xref', result['error'])

    def test_extract_pdf_text_reports_empty_text_pdf(self):
        empty_attempt = {
            'ok': False,
            'available': True,
            'opened': True,
            'page_count': 2,
            'pages': [{'page': 1, 'text': ''}, {'page': 2, 'text': ''}],
            'page_errors': [],
            'text_char_count': 0,
            'nonempty_page_count': 0,
            'image_page_count': 0,
        }
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            with mock.patch.object(self.module, '_extract_with_pypdf', return_value={
                **empty_attempt,
                'extractor': 'pypdf',
            }), mock.patch.object(self.module, '_extract_with_pymupdf', return_value={
                **empty_attempt,
                'extractor': 'pymupdf',
            }), mock.patch.object(self.module, '_extract_with_pdfplumber', return_value={
                **empty_attempt,
                'extractor': 'pdfplumber',
            }):
                result = self.module.extract_pdf_text(tmp.name)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'empty_text_pdf')
        self.assertIn('几乎为空', result['error'])

    def test_extract_pdf_text_reports_likely_scanned_pdf(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            with mock.patch.object(self.module, '_extract_with_pypdf', return_value={
                'ok': False,
                'extractor': 'pypdf',
                'available': True,
                'opened': True,
                'page_count': 1,
                'pages': [{'page': 1, 'text': ''}],
                'page_errors': [],
                'text_char_count': 0,
                'nonempty_page_count': 0,
                'image_page_count': 0,
            }), mock.patch.object(self.module, '_extract_with_pymupdf', return_value={
                'ok': False,
                'extractor': 'pymupdf',
                'available': True,
                'opened': True,
                'page_count': 1,
                'pages': [{'page': 1, 'text': ''}],
                'page_errors': [],
                'text_char_count': 0,
                'nonempty_page_count': 0,
                'image_page_count': 1,
            }), mock.patch.object(self.module, '_extract_with_pdfplumber', return_value={
                'ok': False,
                'extractor': 'pdfplumber',
                'available': True,
                'opened': True,
                'page_count': 1,
                'pages': [{'page': 1, 'text': ''}],
                'page_errors': [],
                'text_char_count': 0,
                'nonempty_page_count': 0,
                'image_page_count': 1,
            }):
                result = self.module.extract_pdf_text(tmp.name)

        self.assertFalse(result['ok'])
        self.assertEqual(result['error_type'], 'likely_scanned_pdf')
        self.assertIn('扫描版', result['suggestion'])


if __name__ == '__main__':
    unittest.main()
