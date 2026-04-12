from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGGREGATE_REPORT_PATH = ROOT / 'skills' / 'academic_impact_analyzer' / 'aggregate_report.py'


def load_aggregate_report_module():
    spec = importlib.util.spec_from_file_location('test_aggregate_report_module', AGGREGATE_REPORT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AggregateReportStatusTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_aggregate_report_module()

    def test_report_entries_keep_paper_id_and_analysis_status(self):
        report = self.module.build_report({
            'ok': True,
            'query': 'MoireVision',
            'processed_papers': 1,
            'results': [
                {
                    'id': 'P001',
                    'paper_id': 'P001',
                    'status': 'fulltext_analyzed',
                    'analysis_status': 'fulltext_analyzed',
                    'citing_paper': {'title': 'Fine-Grained Head Orientation Tracking'},
                    'analysis': {
                        'final_status': 'fulltext_analyzed',
                        'findings_count': 1,
                    },
                    'paths': {},
                }
            ],
        })

        entry = report['entries'][0]
        self.assertEqual(entry['id'], 'P001')
        self.assertEqual(entry['paper_id'], 'P001')
        self.assertEqual(entry['status'], 'fulltext_analyzed')
        self.assertEqual(entry['analysis_status'], 'fulltext_analyzed')
        self.assertEqual(entry['findings_count'], 1)

    def test_report_analysis_status_falls_back_to_status(self):
        report = self.module.build_report({
            'ok': True,
            'query': 'MoiréVision',
            'processed_papers': 1,
            'results': [
                {
                    'id': 'P002',
                    'status': 'context_only',
                    'citing_paper': {'title': 'Fallback Paper'},
                    'fallback_analysis': {'fallback_contexts': []},
                    'paths': {},
                }
            ],
        })

        entry = report['entries'][0]
        self.assertEqual(entry['id'], 'P002')
        self.assertEqual(entry['analysis_status'], 'context_only')


if __name__ == '__main__':
    unittest.main()
