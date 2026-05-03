from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
AUTHOR_SOURCES_PATH = ROOT / "skills" / "scholar_impact_analyzer" / "author_sources.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScholarAuthorSourcesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = load_module(AUTHOR_SOURCES_PATH, "test_scholar_author_sources")

    def test_normalize_dblp_author_hit(self):
        hit = {
            "info": {
                "author": "Chen Tian",
                "url": "https://dblp.org/pid/94/1247-1.html",
                "notes": {"note": "Nanjing University"},
            }
        }

        candidate = self.sources.normalize_dblp_author_hit(hit)

        self.assertEqual(candidate["display_name"], "Chen Tian")
        self.assertEqual(candidate["dblp_id"], "94/1247-1")
        self.assertEqual(candidate["affiliations"], ["Nanjing University"])
        self.assertEqual(candidate["source"], "DBLP")

    def test_normalize_dblp_author_hit_handles_multiple_notes(self):
        hit = {
            "info": {
                "author": "Chen Tian",
                "url": "https://dblp.org/pid/94/1247-2.html",
                "notes": {"note": ["Huawei America Research Center", "Santa Clara"]},
            }
        }

        candidate = self.sources.normalize_dblp_author_hit(hit)

        self.assertEqual(candidate["dblp_id"], "94/1247-2")
        self.assertEqual(
            candidate["affiliations"], ["Huawei America Research Center", "Santa Clara"]
        )

    def test_normalize_dblp_author_hit_handles_dict_notes(self):
        hit = {
            "info": {
                "author": "Chen Tian",
                "url": "https://dblp.org/pid/94/1247-3.html",
                "notes": {
                    "note": [
                        {
                            "@type": "affiliation",
                            "text": "Nanjing University, China",
                        },
                        {
                            "@type": "affiliation",
                            "#text": "State Key Laboratory for Novel Software Technology",
                        },
                    ]
                },
            }
        }

        candidate = self.sources.normalize_dblp_author_hit(hit)

        self.assertEqual(
            candidate["affiliations"],
            [
                "Nanjing University, China",
                "State Key Laboratory for Novel Software Technology",
            ],
        )

    def test_normalize_dblp_publication(self):
        entry = {
            "info": {
                "title": "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.",
                "year": "2024",
                "venue": "EuroSys",
                "doi": "10.1145/3627703.3629574",
                "authors": {
                    "author": ["Songyuan Bai", "Hao Zheng", "Chen Tian", "A. Coauthor"]
                },
                "key": "conf/eurosys/BaiZTWLXXD024",
            }
        }

        publication = self.sources.normalize_dblp_publication(
            entry, selected_author_name="Chen Tian"
        )

        self.assertEqual(
            publication["title"],
            "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.",
        )
        self.assertEqual(publication["year"], 2024)
        self.assertEqual(publication["venue"], "EuroSys")
        self.assertEqual(publication["doi"], "10.1145/3627703.3629574")
        self.assertEqual(
            publication["authors"],
            ["Songyuan Bai", "Hao Zheng", "Chen Tian", "A. Coauthor"],
        )
        self.assertEqual(publication["author_position"], "middle_author")
        self.assertEqual(
            publication["unique_ids"]["DBLP"], "conf/eurosys/BaiZTWLXXD024"
        )

    def test_author_position_identifies_multi_author_last_author(self):
        position = self.sources.author_position(
            ["Songyuan Bai", "Hao Zheng", "Chen Tian"], "Chen Tian"
        )

        self.assertEqual(position, "last_author")

    def test_author_position_ignores_dblp_disambiguation_suffix(self):
        self.assertEqual(
            self.sources.author_position(
                ["A. Coauthor", "Chen Tian 0001"], "Chen Tian"
            ),
            "last_author",
        )
        self.assertEqual(
            self.sources.author_position(
                ["A. Coauthor", "Chen Tian"], "Chen Tian 0001"
            ),
            "last_author",
        )

    def test_fetch_dblp_publications_parses_xml_publications(self):
        class Response:
            text = """<dblpperson>
                <r>
                    <inproceedings key="conf/eurosys/BaiZTWLXXD024">
                        <author>Songyuan Bai</author>
                        <author>Hao Zheng</author>
                        <author>Chen Tian</author>
                        <author>A. Coauthor</author>
                        <title>Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.</title>
                        <year>2024</year>
                        <booktitle>EuroSys</booktitle>
                        <ee>https://doi.org/10.1145/3627703.3629574</ee>
                    </inproceedings>
                </r>
            </dblpperson>"""

            def raise_for_status(self):
                pass

        with patch.object(self.sources.requests, "get", return_value=Response()) as get:
            publications = self.sources.fetch_dblp_publications(
                "94/1247-1", "Chen Tian"
            )

        get.assert_called_once_with(
            "https://dblp.org/pid/94/1247-1.xml", timeout=20
        )
        self.assertEqual(len(publications), 1)
        publication = publications[0]
        self.assertEqual(
            publication["title"],
            "Unison: A Parallel-Efficient and User-Transparent Network Simulation Kernel.",
        )
        self.assertEqual(publication["year"], 2024)
        self.assertEqual(publication["venue"], "EuroSys")
        self.assertEqual(publication["doi"], "10.1145/3627703.3629574")
        self.assertEqual(
            publication["authors"],
            ["Songyuan Bai", "Hao Zheng", "Chen Tian", "A. Coauthor"],
        )
        self.assertEqual(publication["author_position"], "middle_author")
        self.assertEqual(
            publication["unique_ids"]["DBLP"], "conf/eurosys/BaiZTWLXXD024"
        )
        self.assertEqual(
            publication["unique_ids"]["DOI"], "10.1145/3627703.3629574"
        )


if __name__ == "__main__":
    unittest.main()
