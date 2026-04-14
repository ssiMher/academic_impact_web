from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts import refresh_person_tag_registry
from skills.academic_impact_analyzer import person_candidates


class PersonRegistryRefreshTestCase(unittest.TestCase):
    def test_refresh_imports_csv_and_json_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / 'person_tag_registry.json'
            source_dir = tmp / 'source_lists'
            source_dir.mkdir()
            registry_path.write_text(
                json.dumps(
                    {
                        'items': [
                            {
                                'name': 'Grace Hopper',
                                'tag_type': 'ieee_fellow',
                                'source_links': ['https://example.com/old'],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding='utf-8',
            )
            (source_dir / 'fellows.csv').write_text(
                'name,tag_type,aliases,source_links,matched_affiliations,note\n'
                'Grace Hopper,ieee_fellow,G. Hopper,https://example.com/new,,updated source\n'
                'Alan Turing,acm_fellow,A. Turing,https://example.com/acm,Princeton University,acm source\n',
                encoding='utf-8',
            )
            (source_dir / 'academicians.json').write_text(
                json.dumps(
                    {
                        'items': [
                            {
                                'name': '钱学森',
                                'tag_type': 'cas_academician',
                                'aliases': ['Qian Xuesen'],
                                'source_links': ['https://example.com/cas'],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding='utf-8',
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = refresh_person_tag_registry.main([
                    '--registry-path', str(registry_path),
                    '--source-dir', str(source_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn('"source_entry_count": 3', output.getvalue())
            payload = json.loads(registry_path.read_text(encoding='utf-8'))
            items = {(item['tag_type'], item['name']): item for item in payload['items']}
            self.assertIn(('ieee_fellow', 'Grace Hopper'), items)
            self.assertIn(('acm_fellow', 'Alan Turing'), items)
            self.assertIn(('cas_academician', '钱学森'), items)
            self.assertIn('https://example.com/old', items[('ieee_fellow', 'Grace Hopper')]['source_links'])
            self.assertIn('https://example.com/new', items[('ieee_fellow', 'Grace Hopper')]['source_links'])
            self.assertIn('G. Hopper', items[('ieee_fellow', 'Grace Hopper')]['aliases'])

    def test_parse_acm_fellows_html_extracts_official_rows(self):
        html = """
        <table>
          <tr><td><a>Gupta, Aarti</a></td><td>ACM Fellows</td><td>2017</td><td>North America</td></tr>
          <tr><td><a>Akella, Aditya</a></td><td>ACM Fellows</td><td>2023</td><td>North America</td></tr>
        </table>
        """

        entries = refresh_person_tag_registry.parse_acm_fellows_html(html, source_url='https://example.com/acm')

        self.assertEqual([entry['name'] for entry in entries], ['Gupta, Aarti', 'Akella, Aditya'])
        self.assertEqual(entries[0]['tag_type'], 'acm_fellow')
        self.assertEqual(entries[0]['source_links'], ['https://example.com/acm'])
        self.assertIn('2017', entries[0]['note'])

    def test_refresh_imports_acm_copied_table_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / 'person_tag_registry.json'
            source_dir = tmp / 'source_lists'
            source_dir.mkdir()
            registry_path.write_text('{"items": []}', encoding='utf-8')
            (source_dir / 'acm_fellows_paste.txt').write_text(
                'Name\nAward\nYear\nRegion\nDL\n'
                'Adar, Eytan\tACM Fellows\t2025\tNorth America\tDigital Library\n'
                'Bengio, Yoshua\tACM Fellows\t2023\tNorth America\tDigital Library\n'
                'Li, Fei-Fei ACM Fellows 2018 North America Digital Library\n',
                encoding='utf-8',
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = refresh_person_tag_registry.main([
                    '--registry-path', str(registry_path),
                    '--source-dir', str(source_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn('"source_entry_count": 3', output.getvalue())
            payload = json.loads(registry_path.read_text(encoding='utf-8'))
            items = {(item['tag_type'], item['name']): item for item in payload['items']}
            self.assertIn(('acm_fellow', 'Adar, Eytan'), items)
            self.assertIn(('acm_fellow', 'Bengio, Yoshua'), items)
            self.assertIn(('acm_fellow', 'Li, Fei-Fei'), items)
            self.assertIn('2025', items[('acm_fellow', 'Adar, Eytan')]['note'])

    def test_top_institution_candidates_use_author_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / 'registry.json'
            top_institutions_path = tmp / 'top_institutions.json'
            registry_path.write_text('{"items": []}', encoding='utf-8')
            top_institutions_path.write_text(
                json.dumps(
                    {
                        'items': [
                            {
                                'name': 'Massachusetts Institute of Technology',
                                'aliases': ['MIT'],
                                'source_links': ['https://www.mit.edu/'],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding='utf-8',
            )
            papers = [
                {
                    'id': 'P001',
                    'title': 'Citing Paper',
                    'authors': ['Jane Doe'],
                    'author_details': [
                        {
                            'name': 'Jane Doe',
                            'source_url': 'https://openalex.org/A1',
                            'institutions': ['MIT Computer Science and Artificial Intelligence Laboratory'],
                        }
                    ],
                }
            ]

            candidates = person_candidates.build_candidates(
                papers,
                registry_path=str(registry_path),
                top_institutions_path=str(top_institutions_path),
            )

            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate['tag_type'], 'top_school')
            self.assertEqual(candidate['name'], 'Jane Doe')
            self.assertEqual(candidate['matched_paper_ids'], ['P001'])
            self.assertEqual(candidate['matched_affiliations'], ['Massachusetts Institute of Technology'])
            self.assertEqual(candidate['evidence'][0]['match_type'], 'top_institution_affiliation')


if __name__ == '__main__':
    unittest.main()
