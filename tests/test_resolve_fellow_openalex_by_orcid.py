from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "resolve_fellow_openalex_by_orcid.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResolveFellowOpenAlexByOrcidTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT_PATH, "test_resolve_fellow_openalex_by_orcid")

    def test_accepts_unique_orcid_with_institution_match_and_emits_seed_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bridge_path = tmp / "bridge.csv"
            resolved_path = tmp / "resolved.csv"
            summary_path = tmp / "summary.csv"
            seed_path = tmp / "seed.csv"

            bridge_path.write_text(
                "name,tag_type,matched_alias,bridge_status,orcid,dblp_author_ids,known_institutions,source_links,note\n"
                "Grace Hopper,acm_fellow,Grace Hopper,unique_orcid,orcid:0000-0001-2345-6789,h/GraceHopper,Yale University,https://example.com/acm,ACM Fellow\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                self.module,
                "fetch_openalex_author_by_orcid",
                return_value={
                    "id": "https://openalex.org/A123",
                    "display_name": "Grace Hopper",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                    "display_name_alternatives": ["Grace B. Hopper"],
                    "last_known_institutions": [{"display_name": "Yale University"}],
                    "affiliations": [],
                },
            ):
                exit_code = self.module.main(
                    [
                        "--bridge-csv",
                        str(bridge_path),
                        "--resolved-csv",
                        str(resolved_path),
                        "--summary-csv",
                        str(summary_path),
                        "--seed-csv",
                        str(seed_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            with resolved_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["decision"], "accepted")
            self.assertEqual(rows[0]["selected_openalex_id"], "https://openalex.org/a123")
            self.assertEqual(rows[0]["selected_orcid"], "orcid:0000-0001-2345-6789")
            self.assertIn("institution_match", rows[0]["reason"])

            with seed_path.open("r", encoding="utf-8-sig", newline="") as handle:
                seed_rows = list(csv.DictReader(handle))
            self.assertEqual(seed_rows[0]["name"], "Grace Hopper")
            self.assertEqual(seed_rows[0]["openalex_author_ids"], "https://openalex.org/a123")
            self.assertEqual(seed_rows[0]["orcid_ids"], "orcid:0000-0001-2345-6789")
            self.assertEqual(seed_rows[0]["dblp_author_ids"], "h/GraceHopper")

    def test_leaves_multi_orcid_name_unresolved_without_strong_disambiguation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bridge_path = tmp / "bridge.csv"
            resolved_path = tmp / "resolved.csv"
            summary_path = tmp / "summary.csv"

            bridge_path.write_text(
                "name,tag_type,matched_alias,bridge_status,orcid,dblp_author_ids,known_institutions,source_links,note\n"
                "Wei Wang,ieee_fellow,Wei Wang,multi_orcid,orcid:0000-0002-0000-0001,w/WeiWang1,,https://example.com/ieee,IEEE Fellow\n"
                "Wei Wang,ieee_fellow,Wei Wang,multi_orcid,orcid:0000-0002-0000-0002,w/WeiWang2,,https://example.com/ieee,IEEE Fellow\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                self.module,
                "fetch_openalex_author_by_orcid",
                side_effect=[
                    {
                        "id": "https://openalex.org/A1",
                        "display_name": "Wei Wang",
                        "orcid": "https://orcid.org/0000-0002-0000-0001",
                        "display_name_alternatives": [],
                        "last_known_institutions": [],
                        "affiliations": [],
                    },
                    {
                        "id": "https://openalex.org/A2",
                        "display_name": "Wei Wang",
                        "orcid": "https://orcid.org/0000-0002-0000-0002",
                        "display_name_alternatives": [],
                        "last_known_institutions": [],
                        "affiliations": [],
                    },
                ],
            ):
                exit_code = self.module.main(
                    [
                        "--bridge-csv",
                        str(bridge_path),
                        "--resolved-csv",
                        str(resolved_path),
                        "--summary-csv",
                        str(summary_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            with resolved_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["decision"], "unresolved")
            self.assertEqual(rows[0]["selected_openalex_id"], "")


if __name__ == "__main__":
    unittest.main()
