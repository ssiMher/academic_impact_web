from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUN_PIPELINE_PATH = ROOT / 'skills' / 'academic_impact_analyzer' / 'run_pipeline.py'
IMPACT_CLI_PATH = ROOT / 'skills' / 'academic_impact_analyzer' / 'impact_cli.py'


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AnalysisScopeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_pipeline = load_module(RUN_PIPELINE_PATH, 'test_run_pipeline_analysis_scope')
        cls.impact_cli = load_module(IMPACT_CLI_PATH, 'test_impact_cli_analysis_scope')

    def test_impact_cli_analyze_defaults_to_candidate_spans(self):
        args = self.impact_cli.build_parser().parse_args([
            'analyze',
            '/tmp/session',
            '--ids',
            'P001',
        ])

        self.assertEqual(args.analysis_scope, 'candidate_spans')
        self.assertEqual(args.top_k_spans, 8)

    def test_impact_cli_analyze_accepts_fulltext_direct(self):
        args = self.impact_cli.build_parser().parse_args([
            'analyze',
            '/tmp/session',
            '--ids',
            'P001',
            '--analysis-scope',
            'fulltext_direct',
        ])

        self.assertEqual(args.analysis_scope, 'fulltext_direct')

    def test_process_citing_paper_writes_fulltext_direct_payload(self):
        captured_payloads = []

        def fake_analyze_payload(payload):
            captured_payloads.append(payload)
            return {
                'ok': True,
                'citing_title': payload.get('citing_title', ''),
                'findings': [
                    {
                        'page': 2,
                        'span_index': 1,
                        'citation_text': 'Chen et al. (2025)',
                        'keep': True,
                        'aspect': 'baseline',
                        'stance': 'neutral',
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch.object(self.run_pipeline.DOWNLOAD_PDF, 'download_paper', return_value={
                    'ok': True,
                    'file_path': str(Path(tmpdir) / 'paper.pdf'),
                    'source': 'test',
                    'pdf_candidates': [],
                }), \
                mock.patch.object(self.run_pipeline.EXTRACT_TEXT, 'extract_pdf_text', return_value={
                    'ok': True,
                    'page_count': 2,
                    'pages': [
                        {'page': 1, 'text': 'Intro text.'},
                        {'page': 2, 'text': 'We compare with Chen et al. (2025).'},
                    ],
                }), \
                mock.patch.object(self.run_pipeline.FIND_SPANS, 'find_candidate_spans', return_value={
                    'ok': True,
                    'count': 0,
                    'mode': 'no_candidates',
                    'citation_index': None,
                    'spans': [],
                }), \
                mock.patch.object(self.run_pipeline.ANALYZE_FULLTEXT, 'analyze_payload', side_effect=fake_analyze_payload):
            item_dir = Path(tmpdir) / 'analysis' / 'P001_test'
            item_dir.mkdir(parents=True)
            result = self.run_pipeline.process_citing_paper(
                target={'title': 'Target Paper', 'year': 2025, 'externalIds': {}},
                citing_paper={'title': 'Citing Paper'},
                contexts_data={},
                item_dir=item_dir,
                top_k_spans=8,
                analysis_scope='fulltext_direct',
            )

            payload = captured_payloads[0]
            payload_on_disk = json.loads((item_dir / 'analyze_payload.json').read_text(encoding='utf-8'))

        self.assertEqual(result['analysis_scope'], 'fulltext_direct')
        self.assertEqual(result['analysis']['analysis_scope'], 'fulltext_direct')
        self.assertEqual(result['status'], 'fulltext_analyzed')
        self.assertEqual(payload['analysis_scope'], 'fulltext_direct')
        self.assertEqual(payload['candidate_spans'], [])
        self.assertEqual(payload['fulltext_page_count'], 2)
        self.assertIn('We compare with Chen et al. (2025).', payload['fulltext_pages'][1]['text'])
        self.assertEqual(payload_on_disk['analysis_scope'], 'fulltext_direct')


if __name__ == '__main__':
    unittest.main()
