from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "import_external_fellow_sources.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ImportExternalFellowSourcesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT_PATH, "test_import_external_fellow_sources")

    def test_imports_acm_academic_awards_json_into_registry_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "acm.json"
            output_path = tmp / "acm.csv"
            input_path.write_text(
                json.dumps(
                    [
                        {"name": "Gupta, Aarti", "year": 2017},
                        {"name": "Aditya Akella", "year": 2023},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = self.module.main(
                [
                    "--dataset",
                    "academic-awards-acm",
                    "--input",
                    str(input_path),
                    "--output-csv",
                    str(output_path),
                    "--source-url",
                    "https://github.com/xiaohk/academic-awards",
                ]
            )

            self.assertEqual(exit_code, 0)
            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["name"], "Aarti Gupta")
            self.assertEqual(rows[0]["tag_type"], "acm_fellow")
            self.assertIn("Gupta, Aarti", rows[0]["aliases"])
            self.assertIn("2017", rows[0]["note"])
            self.assertEqual(rows[1]["name"], "Aditya Akella")

    def test_imports_ieee_academic_awards_json_with_category_and_citation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "ieee.json"
            output_path = tmp / "ieee.csv"
            input_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Murat Tekalp",
                            "year": 2024,
                            "region": "Region 8",
                            "category": "Signal Processing",
                            "citation": "for contributions to video processing",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = self.module.main(
                [
                    "--dataset",
                    "academic-awards-ieee",
                    "--input",
                    str(input_path),
                    "--output-csv",
                    str(output_path),
                    "--source-url",
                    "https://github.com/xiaohk/academic-awards",
                ]
            )

            self.assertEqual(exit_code, 0)
            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["name"], "Murat Tekalp")
            self.assertEqual(rows[0]["tag_type"], "ieee_fellow")
            self.assertIn("2024", rows[0]["note"])
            self.assertIn("Signal Processing", rows[0]["note"])
            self.assertIn("Region 8", rows[0]["note"])
            self.assertIn("video processing", rows[0]["note"])


if __name__ == "__main__":
    unittest.main()
