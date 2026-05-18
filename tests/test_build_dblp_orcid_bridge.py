from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_dblp_orcid_bridge.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildDblpOrcidBridgeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT_PATH, "test_build_dblp_orcid_bridge")

    def test_builds_bridge_candidates_from_registry_and_dblp_csvs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "registry.json"
            alias_path = tmp / "by_alias.csv"
            orcid_path = tmp / "by_orcid.csv"
            output_path = tmp / "bridge.csv"
            summary_path = tmp / "summary.csv"

            registry_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "name": "Grace Hopper",
                                "tag_type": "acm_fellow",
                                "aliases": ["G. Hopper"],
                                "source_links": ["https://example.com/acm"],
                                "known_institutions": ["Yale University"],
                            },
                            {
                                "name": "Wei Wang",
                                "tag_type": "ieee_fellow",
                                "aliases": [],
                                "source_links": ["https://example.com/ieee"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            alias_path.write_text(
                "alias,orcid,acm_id,scopus_id\n"
                "\"Grace Hopper\",\"['0000-0001-2345-6789']\",,\n"
                "\"Wei Wang\",\"['0000-0002-0000-0001', '0000-0002-0000-0002']\",,\n",
                encoding="utf-8",
            )
            orcid_path.write_text(
                "orcid,alias,dblp_key,acm_id,scopus_id\n"
                "\"0000-0001-2345-6789\",\"['Grace Hopper', 'G. Hopper']\",\"['h/GraceHopper']\",,\n"
                "\"0000-0002-0000-0001\",\"['Wei Wang']\",\"['w/WeiWang1']\",,\n"
                "\"0000-0002-0000-0002\",\"['Wei Wang']\",\"['w/WeiWang2']\",,\n",
                encoding="utf-8",
            )

            exit_code = self.module.main(
                [
                    "--registry-path",
                    str(registry_path),
                    "--tag-type",
                    "acm_fellow",
                    "--dblp-alias-csv",
                    str(alias_path),
                    "--dblp-orcid-csv",
                    str(orcid_path),
                    "--output-csv",
                    str(output_path),
                    "--summary-csv",
                    str(summary_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "Grace Hopper")
            self.assertEqual(rows[0]["matched_alias"], "Grace Hopper")
            self.assertEqual(rows[0]["orcid"], "orcid:0000-0001-2345-6789")
            self.assertEqual(rows[0]["dblp_author_ids"], "h/GraceHopper")
            self.assertEqual(rows[0]["bridge_status"], "unique_orcid")

    def test_marks_multiple_orcids_as_multi_orcid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "registry.json"
            alias_path = tmp / "by_alias.csv"
            orcid_path = tmp / "by_orcid.csv"
            output_path = tmp / "bridge.csv"
            summary_path = tmp / "summary.csv"

            registry_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "name": "Wei Wang",
                                "tag_type": "ieee_fellow",
                                "aliases": [],
                                "source_links": ["https://example.com/ieee"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            alias_path.write_text(
                "alias,orcid,acm_id,scopus_id\n"
                "\"Wei Wang\",\"['0000-0002-0000-0001', '0000-0002-0000-0002']\",,\n",
                encoding="utf-8",
            )
            orcid_path.write_text(
                "orcid,alias,dblp_key,acm_id,scopus_id\n"
                "\"0000-0002-0000-0001\",\"['Wei Wang']\",\"['w/WeiWang1']\",,\n"
                "\"0000-0002-0000-0002\",\"['Wei Wang']\",\"['w/WeiWang2']\",,\n",
                encoding="utf-8",
            )

            exit_code = self.module.main(
                [
                    "--registry-path",
                    str(registry_path),
                    "--tag-type",
                    "ieee_fellow",
                    "--dblp-alias-csv",
                    str(alias_path),
                    "--dblp-orcid-csv",
                    str(orcid_path),
                    "--output-csv",
                    str(output_path),
                    "--summary-csv",
                    str(summary_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["bridge_status"] == "multi_orcid" for row in rows))


if __name__ == "__main__":
    unittest.main()
