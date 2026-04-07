from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGRESSION_SET_PATH = ROOT / "data" / "reference" / "fulltext_regression_set.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_regression_set() -> dict[str, Any]:
    return json.loads(REGRESSION_SET_PATH.read_text(encoding="utf-8"))


def main():
    from app.services import impact_core

    regression_set = load_regression_set()
    results = []
    all_passed = True

    for sample in regression_set.get("samples", []):
        session_id = sample["session_id"]
        paper_id = sample["paper_id"]
        expected = sample["expected"]

        impact_core.analyze_papers(session_id, [paper_id], top_k_spans=8)
        _session, _status_payload, detail_payload, _report_md = impact_core.load_status(session_id)
        paper = next(item for item in detail_payload["papers"] if item["id"] == paper_id)

        actual_status = paper.get("analysis_status")
        labels = paper.get("citation_method_summary", {}).get("labels", [])
        has_findings = bool(paper.get("citation_method_summary", {}).get("evidence_excerpt"))

        missing_labels = [label for label in expected.get("min_labels", []) if label not in labels]
        passed = (
            actual_status == expected.get("final_status")
            and has_findings == expected.get("has_findings")
            and not missing_labels
        )
        all_passed = all_passed and passed

        results.append(
            {
                "target_query": sample["target_query"],
                "session_id": session_id,
                "paper_id": paper_id,
                "title": sample["title"],
                "expected": expected,
                "actual": {
                    "final_status": actual_status,
                    "has_findings": has_findings,
                    "labels": labels,
                },
                "missing_labels": missing_labels,
                "passed": passed,
            }
        )

    payload = {
        "ok": all_passed,
        "regression_set_path": str(REGRESSION_SET_PATH),
        "sample_count": len(results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
