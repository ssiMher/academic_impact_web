from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "enrich_person_tag_registry_openalex.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenAlexPersonEnrichmentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT_PATH, "test_openalex_person_enrichment")

    def test_enrich_registry_adds_identity_and_institutions_for_unique_match(self):
        registry = {
            "items": [
                {
                    "name": "Grace Hopper",
                    "tag_type": "acm_fellow",
                    "aliases": ["Hopper, Grace"],
                    "source_links": ["https://example.test/grace"],
                    "matched_affiliations": [],
                    "note": "seed",
                }
            ]
        }
        author_payload = {
            "results": [
                {
                    "id": "https://openalex.org/A123",
                    "display_name": "Grace Hopper",
                    "display_name_alternatives": ["Hopper, Grace"],
                    "ids": {"orcid": "https://orcid.org/0000-0001-2345-6789"},
                    "last_known_institutions": [
                        {"display_name": "Yale University"},
                        {"display_name": "Harvard University"},
                    ],
                    "affiliations": [
                        {"institution": {"display_name": "Yale University"}},
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "registry.json"
            registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

            with mock.patch.object(self.module, "fetch_openalex_authors", return_value=author_payload["results"]):
                report = self.module.enrich_registry(
                    registry_path=registry_path,
                    target_names=["Grace Hopper"],
                )

            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item["openalex_author_ids"], ["https://openalex.org/a123"])
            self.assertEqual(item["orcid_ids"], ["orcid:0000-0001-2345-6789"])
            self.assertIn("Yale University", item["known_institutions"])
            self.assertIn("Harvard University", item["known_institutions"])
            self.assertEqual(report["updated"], 1)
            self.assertEqual(report["skipped"], 0)

    def test_enrich_registry_skips_ambiguous_match(self):
        registry = {
            "items": [
                {
                    "name": "Wei Wang",
                    "tag_type": "cae_academician",
                    "aliases": [],
                    "source_links": ["https://example.test/wei"],
                    "matched_affiliations": [],
                    "note": "seed",
                }
            ]
        }
        results = [
            {
                "id": "https://openalex.org/A111",
                "display_name": "Wei Wang",
                "display_name_alternatives": [],
                "ids": {},
                "last_known_institutions": [{"display_name": "Example University"}],
                "affiliations": [],
            },
            {
                "id": "https://openalex.org/A222",
                "display_name": "Wei Wang",
                "display_name_alternatives": [],
                "ids": {},
                "last_known_institutions": [{"display_name": "Second University"}],
                "affiliations": [],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "registry.json"
            registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

            with mock.patch.object(self.module, "fetch_openalex_authors", return_value=results):
                report = self.module.enrich_registry(
                    registry_path=registry_path,
                    target_names=["Wei Wang"],
                )

            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item.get("openalex_author_ids", []), [])
            self.assertEqual(report["updated"], 0)
            self.assertEqual(report["skipped"], 1)
            self.assertEqual(report["decisions"][0]["decision"], "skipped")

    def test_load_target_names_from_review_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            zip_path = tmp / "review.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "manual_review_top50.csv",
                    "display_name,norm_author\nGrace Hopper,grace hopper\nWei Wang,wei wang\n",
                )
                archive.writestr(
                    "missing_from_candidate_matching.csv",
                    "raw_author_names,norm_author\nAlex X. Liu,alex x liu\n",
                )

            names = self.module.load_target_names_from_review_zip(zip_path)

            self.assertEqual(names, ["Grace Hopper", "Wei Wang", "Alex X. Liu"])

    def test_find_registry_targets_can_select_items_missing_external_ids_without_name_input(self):
        items = [
            {
                "name": "Grace Hopper",
                "tag_type": "acm_fellow",
                "aliases": [],
                "openalex_author_ids": [],
                "orcid_ids": [],
            },
            {
                "name": "Alan Turing",
                "tag_type": "acm_fellow",
                "aliases": [],
                "openalex_author_ids": ["https://openalex.org/A1"],
                "orcid_ids": [],
            },
            {
                "name": "Wei Wang",
                "tag_type": "cae_academician",
                "aliases": [],
                "openalex_author_ids": [],
                "orcid_ids": [],
            },
            {
                "name": "Top School Person",
                "tag_type": "top_school",
                "aliases": [],
                "openalex_author_ids": [],
                "orcid_ids": [],
            },
        ]

        targets = self.module.find_registry_targets(
            items,
            target_names=[],
            tag_types={"acm_fellow", "ieee_fellow"},
            missing_external_ids_only=True,
        )

        self.assertEqual([item["name"] for item in targets], ["Grace Hopper"])

    def test_enrich_registry_can_batch_select_missing_external_ids(self):
        registry = {
            "items": [
                {
                    "name": "Grace Hopper",
                    "tag_type": "acm_fellow",
                    "aliases": ["Hopper, Grace"],
                    "source_links": ["https://example.test/grace"],
                    "matched_affiliations": [],
                    "openalex_author_ids": [],
                    "orcid_ids": [],
                    "note": "seed",
                },
                {
                    "name": "Alan Turing",
                    "tag_type": "acm_fellow",
                    "aliases": [],
                    "source_links": ["https://example.test/turing"],
                    "matched_affiliations": [],
                    "openalex_author_ids": ["https://openalex.org/a999"],
                    "orcid_ids": [],
                    "note": "existing id",
                },
            ]
        }

        author_results = {
            "Grace Hopper": [
                {
                    "id": "https://openalex.org/A123",
                    "display_name": "Grace Hopper",
                    "display_name_alternatives": ["Hopper, Grace"],
                    "ids": {"orcid": "https://orcid.org/0000-0001-2345-6789"},
                    "last_known_institutions": [{"display_name": "Yale University"}],
                    "affiliations": [],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "registry.json"
            registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

            def fake_fetch(name, **kwargs):
                return author_results.get(name, [])

            with mock.patch.object(self.module, "fetch_openalex_authors", side_effect=fake_fetch) as fetch_mock:
                report = self.module.enrich_registry(
                    registry_path=registry_path,
                    target_names=[],
                    tag_types={"acm_fellow"},
                    missing_external_ids_only=True,
                )

            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            grace, alan = payload["items"]
            self.assertEqual(grace["openalex_author_ids"], ["https://openalex.org/a123"])
            self.assertEqual(alan["openalex_author_ids"], ["https://openalex.org/a999"])
            self.assertEqual(fetch_mock.call_count, 1)
            self.assertEqual(report["target_count"], 1)
            self.assertEqual(report["updated"], 1)

    def test_enrich_registry_respects_max_targets_for_batch_runs(self):
        registry = {
            "items": [
                {
                    "name": "Grace Hopper",
                    "tag_type": "acm_fellow",
                    "aliases": [],
                    "source_links": [],
                    "matched_affiliations": [],
                    "openalex_author_ids": [],
                    "orcid_ids": [],
                    "note": "",
                },
                {
                    "name": "Barbara Liskov",
                    "tag_type": "acm_fellow",
                    "aliases": [],
                    "source_links": [],
                    "matched_affiliations": [],
                    "openalex_author_ids": [],
                    "orcid_ids": [],
                    "note": "",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "registry.json"
            registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

            with mock.patch.object(self.module, "fetch_openalex_authors", return_value=[] ) as fetch_mock:
                report = self.module.enrich_registry(
                    registry_path=registry_path,
                    target_names=[],
                    tag_types={"acm_fellow"},
                    missing_external_ids_only=True,
                    max_targets=1,
                )

            self.assertEqual(fetch_mock.call_count, 1)
            self.assertEqual(report["target_count"], 1)


if __name__ == "__main__":
    unittest.main()
