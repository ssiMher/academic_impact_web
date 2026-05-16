from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "cross_validate_openalex_candidates.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenAlexCandidateCrossValidationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT_PATH, "test_openalex_candidate_cross_validation")

    def test_cross_validate_uses_raw_metadata_to_select_institution_overlap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            zip_path = tmp / "resolution.zip"
            candidates_path = tmp / "candidates.csv"
            raw_path = tmp / "raw.csv"
            out_path = tmp / "cross.csv"
            summary_path = tmp / "summary.csv"

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "openalex_ai_resolved_ids.csv",
                    "name,tag_type,resolution_status,selected_openalex_id,selected_orcid,selected_display_name,selected_institutions,confidence_label,evidence_summary,source_decision,candidate_count\n"
                    "Wei Wang,ieee_fellow,unresolved,,,,,,skipped,2\n",
                )

            with candidates_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "name",
                        "tag_type",
                        "decision",
                        "reason",
                        "candidate_count",
                        "rank",
                        "score",
                        "score_percent",
                        "openalex_id",
                        "display_name",
                        "orcid",
                        "institutions",
                        "reasons",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "Wei Wang",
                        "tag_type": "ieee_fellow",
                        "decision": "skipped",
                        "reason": "ambiguous",
                        "candidate_count": "2",
                        "rank": "1",
                        "score": "12",
                        "score_percent": "100",
                        "openalex_id": "https://openalex.org/a1",
                        "display_name": "Wei Wang",
                        "orcid": "",
                        "institutions": "Example University;Wireless Lab",
                        "reasons": "display_name_exact",
                    }
                )
                writer.writerow(
                    {
                        "name": "Wei Wang",
                        "tag_type": "ieee_fellow",
                        "decision": "skipped",
                        "reason": "ambiguous",
                        "candidate_count": "2",
                        "rank": "2",
                        "score": "12",
                        "score_percent": "100",
                        "openalex_id": "https://openalex.org/a2",
                        "display_name": "Wei Wang",
                        "orcid": "",
                        "institutions": "Second University",
                        "reasons": "display_name_exact",
                    }
                )

            with raw_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["author_name", "author_institutions", "author_source_url"])
                writer.writeheader()
                writer.writerow(
                    {
                        "author_name": "Wei Wang",
                        "author_institutions": "Example University | Wireless Lab",
                        "author_source_url": "https://openalex.org/Araw",
                    }
                )

            report = self.module.cross_validate(
                resolution_zip_path=zip_path,
                candidates_csv_path=candidates_path,
                raw_citing_authors_csv_path=raw_path,
                output_csv_path=out_path,
                summary_csv_path=summary_path,
                use_dblp=False,
                use_scopus=False,
            )

            with out_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(report["candidate_rows"], 2)
            self.assertEqual(rows[0]["cross_validation_status"], "cross_validated_suggestion")
            self.assertEqual(rows[0]["openalex_id"], "https://openalex.org/a1")
            self.assertIn("raw_institution_overlap", rows[0]["evidence_reasons"])
            self.assertEqual(rows[1]["cross_validation_status"], "candidate_evidence_only")

    def test_cross_validate_records_dblp_and_scopus_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            zip_path = tmp / "resolution.zip"
            candidates_path = tmp / "candidates.csv"
            out_path = tmp / "cross.csv"
            summary_path = tmp / "summary.csv"

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "openalex_ai_resolved_ids.csv",
                    "name,tag_type,resolution_status,selected_openalex_id,selected_orcid,selected_display_name,selected_institutions,confidence_label,evidence_summary,source_decision,candidate_count\n"
                    "Grace Hopper,acm_fellow,unresolved,,,,,,skipped,1\n",
                )

            with candidates_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "name",
                        "tag_type",
                        "decision",
                        "reason",
                        "candidate_count",
                        "rank",
                        "score",
                        "score_percent",
                        "openalex_id",
                        "display_name",
                        "orcid",
                        "institutions",
                        "reasons",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "Grace Hopper",
                        "tag_type": "acm_fellow",
                        "decision": "skipped",
                        "reason": "ambiguous",
                        "candidate_count": "1",
                        "rank": "1",
                        "score": "12",
                        "score_percent": "100",
                        "openalex_id": "https://openalex.org/a3",
                        "display_name": "Grace Hopper",
                        "orcid": "orcid:0000-0001-2345-6789",
                        "institutions": "Yale University",
                        "reasons": "display_name_exact",
                    }
                )

            with mock.patch.object(
                self.module,
                "fetch_dblp_authors",
                return_value=[{"pid": "h/GraceHopper", "name": "Grace Hopper", "url": "https://dblp.org/pid/h/GraceHopper"}],
            ), mock.patch.object(
                self.module,
                "fetch_scopus_authors",
                return_value=[{"scopus_author_id": "123", "name": "Grace Hopper", "affiliation": "Yale University", "document_count": "42"}],
            ):
                self.module.cross_validate(
                    resolution_zip_path=zip_path,
                    candidates_csv_path=candidates_path,
                    raw_citing_authors_csv_path=None,
                    output_csv_path=out_path,
                    summary_csv_path=summary_path,
                    use_dblp=True,
                    use_scopus=True,
                )

            with out_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["dblp_pids"], "h/GraceHopper")
            self.assertEqual(rows[0]["scopus_author_ids"], "123")
            self.assertIn("dblp_exact_name", rows[0]["evidence_reasons"])
            self.assertIn("scopus_exact_name", rows[0]["evidence_reasons"])


if __name__ == "__main__":
    unittest.main()
