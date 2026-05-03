from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
