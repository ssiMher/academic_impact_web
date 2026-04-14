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

    def test_refresh_imports_ieee_cs_copied_page_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / 'person_tag_registry.json'
            source_dir = tmp / 'source_lists'
            source_dir.mkdir()
            registry_path.write_text('{"items": []}', encoding='utf-8')
            (source_dir / 'ieee_cs_fellows_2026.txt').write_text(
                'IEEE Computer Society Announces 2026 Class of Fellows\n'
                '* Tamim Asfour - for contributions to humanoid robotics and robot learning\n'
                '* Anupam Chattopadhyay for contributions to embedded systems security\n',
                encoding='utf-8',
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = refresh_person_tag_registry.main([
                    '--registry-path', str(registry_path),
                    '--source-dir', str(source_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn('"source_entry_count": 2', output.getvalue())
            payload = json.loads(registry_path.read_text(encoding='utf-8'))
            items = {(item['tag_type'], item['name']): item for item in payload['items']}
            self.assertIn(('ieee_fellow', 'Tamim Asfour'), items)
            self.assertIn(('ieee_fellow', 'Anupam Chattopadhyay'), items)
            self.assertIn('class 2026', items[('ieee_fellow', 'Tamim Asfour')]['note'])
            self.assertIn('https://www.computer.org/press-room/2026-class-fellows', items[('ieee_fellow', 'Tamim Asfour')]['source_links'])

    def test_refresh_imports_ieee_cs_wikipedia_table_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / 'person_tag_registry.json'
            source_dir = tmp / 'source_lists'
            source_dir.mkdir()
            registry_path.write_text('{"items": []}', encoding='utf-8')
            (source_dir / 'ieee_cs_wikipedia.txt').write_text(
                'Year\tFellow\tCitation\n'
                '2020\tHussein Abbass\tFor contributions to evolutionary learning and optimization\n'
                '2026\t\tWei Zhang\tFor contributions to agile design flow for FPGA and software-hardware co-design for embedded system security\n'
                '2014\tKrste Asanović\tFor contributions to computer architecture\n',
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
            self.assertIn(('ieee_fellow', 'Hussein Abbass'), items)
            self.assertIn(('ieee_fellow', 'Wei Zhang'), items)
            self.assertIn(('ieee_fellow', 'Krste Asanović'), items)
            self.assertIn('class 2026', items[('ieee_fellow', 'Wei Zhang')]['note'])
            self.assertIn('Wikipedia secondary source', items[('ieee_fellow', 'Wei Zhang')]['note'])
            self.assertIn('agile design flow', items[('ieee_fellow', 'Wei Zhang')]['note'])

    def test_parse_ieee_cs_wikipedia_html_extracts_table_rows(self):
        html = """
        <table class="wikitable">
          <tr><th>Year</th><th>Fellow</th><th>Citation</th></tr>
          <tr><td>2023</td><td>Gail-Joon Ahn</td><td>For development of applications of information and systems security</td></tr>
          <tr><td>2017</td><td>Todd Austin [de]</td><td>For contributions to simulation techniques</td></tr>
        </table>
        """

        entries = refresh_person_tag_registry.parse_ieee_cs_wikipedia_table(html)

        self.assertEqual([entry['name'] for entry in entries], ['Gail-Joon Ahn', 'Todd Austin'])
        self.assertIn('class 2023', entries[0]['note'])
        self.assertEqual(entries[0]['source_links'], ['https://en.wikipedia.org/wiki/List_of_fellows_of_IEEE_Computer_Society'])

    def test_ieee_wikipedia_parser_uses_society_from_source_url(self):
        html = """
        <table class="wikitable">
          <tr><th>Year</th><th>Fellow</th><th>Citation</th></tr>
          <tr><td>2022</td><td>Ada Example</td><td>For contributions to wireless networks</td></tr>
        </table>
        """

        entries = refresh_person_tag_registry.parse_ieee_cs_wikipedia_table(
            html,
            source_url='https://en.wikipedia.org/wiki/List_of_fellows_of_IEEE_Communications_Society',
        )

        self.assertIn('IEEE Communications Society Fellow', entries[0]['note'])

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

    def test_short_top_institution_aliases_require_token_boundaries(self):
        institutions = [
            {
                'name': 'Massachusetts Institute of Technology',
                'aliases': ['MIT'],
            }
        ]

        self.assertIsNone(person_candidates.match_top_institution('Smith College', institutions))
        self.assertEqual(
            person_candidates.match_top_institution('MIT Computer Science and Artificial Intelligence Laboratory', institutions)['name'],
            'Massachusetts Institute of Technology',
        )


if __name__ == '__main__':
    unittest.main()
