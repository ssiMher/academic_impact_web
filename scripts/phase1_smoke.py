from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_env import load_project_env
from app.services import impact_core

load_project_env(ROOT)


def parse_ids(raw: str) -> list[str]:
    return [item.strip().upper() for item in (raw or "").split(",") if item.strip()]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_session(session_id: str, output_dir: Path, label: str):
    session, status_payload, detail_payload, report_md = impact_core.load_status(session_id)
    snapshot = {
        "session": session,
        "status_payload": status_payload,
        "detail_payload": detail_payload,
        "report_md_path": detail_payload.get("exports", {}).get("report_md_path", ""),
        "structured_json_path": detail_payload.get("exports", {}).get("structured_json_path", ""),
    }
    write_json(output_dir / f"{label}.json", snapshot)
    (output_dir / f"{label}.report.md").write_text(report_md or "", encoding="utf-8")
    return session, status_payload, detail_payload


def collect_paper_state(session: dict, paper_ids: list[str]) -> list[dict[str, Any]]:
    papers = {item.get("id"): item for item in session.get("papers", [])}
    states = []
    for paper_id in paper_ids:
        item = papers.get(paper_id, {})
        states.append(
            {
                "id": paper_id,
                "title": item.get("title", ""),
                "download_status": (item.get("download_probe") or {}).get("status"),
                "download_error": (item.get("download_result") or {}).get("error"),
                "analysis_status": (item.get("analysis_result") or {}).get("status"),
                "analysis_paths": (item.get("analysis_result") or {}).get("paths", {}),
            }
        )
    return states


def step_failure_reasons(step_name: str, result: Any, session: dict, detail_payload: dict, paper_ids: list[str]) -> list[str]:
    reasons: list[str] = []
    if isinstance(result, dict):
        error = result.get("error")
        if error:
            reasons.append(str(error))
        for key in ("updated", "refreshed", "results"):
            for item in result.get(key, []) or []:
                if isinstance(item, dict) and item.get("error"):
                    reasons.append(str(item.get("error")))

    detail_by_id = {item.get("id"): item for item in detail_payload.get("papers", [])}
    for paper_id in paper_ids:
        detail_item = detail_by_id.get(paper_id, {})
        analysis_reason = detail_item.get("analysis_reason") or {}
        if analysis_reason.get("message"):
            reasons.append(str(analysis_reason.get("message")))
        for error in analysis_reason.get("errors", []) or []:
            reasons.append(str(error))

    unique = []
    seen = set()
    for item in reasons:
        text = (item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def run_step(name: str, output_dir: Path, session_id: str, paper_ids: list[str], fn):
    started_at = time.time()
    error = None
    try:
        result = fn()
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
    except Exception as exc:  # pragma: no cover - smoke path
        result = None
        ok = False
        error = f"{type(exc).__name__}: {exc}"

    elapsed_sec = round(time.time() - started_at, 2)
    session, status_payload, detail_payload = snapshot_session(session_id, output_dir, f"after_{name}")
    summary = {
        "name": name,
        "ok": ok and not error,
        "elapsed_sec": elapsed_sec,
        "paper_ids": paper_ids,
        "result": result,
        "exception": error,
        "paper_states": collect_paper_state(session, paper_ids),
        "failure_reasons": step_failure_reasons(name, result, session, detail_payload, paper_ids),
    }
    write_json(output_dir / f"step_{name}.json", summary)
    return summary


def render_markdown(summary: dict) -> str:
    lines = [
        "# Phase 1 Smoke Test",
        "",
        f"- 时间：{summary.get('started_at')}",
        f"- Query：{summary.get('query')}",
        f"- Session：`{summary.get('session_id')}`",
        f"- 目标论文：{', '.join(summary.get('paper_ids', [])) or '-'}",
        "",
        "## Steps",
        "",
    ]
    for step in summary.get("steps", []):
        lines.extend(
            [
                f"### {step.get('name')}",
                f"- ok：{step.get('ok')}",
                f"- 耗时：{step.get('elapsed_sec')}s",
                f"- 目标：{', '.join(step.get('paper_ids') or []) or '-'}",
            ]
        )
        if step.get("failure_reasons"):
            lines.append(f"- 失败原因：{'；'.join(step.get('failure_reasons')[:5])}")
        if step.get("paper_states"):
            lines.append("- 当前论文状态：")
            for item in step.get("paper_states", []):
                lines.append(
                    f"  - {item.get('id')}: download={item.get('download_status')} | "
                    f"analysis={item.get('analysis_status')} | error={item.get('download_error') or '-'}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Run a repeatable Phase 1 smoke test.")
    parser.add_argument("--query", required=True, help="Target paper query for discover.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--sort-preference", default="recent", choices=["recent", "context"])
    parser.add_argument("--probe-downloads", action="store_true")
    parser.add_argument("--paper-ids", default="", help="Comma-separated paper ids to run refresh/download/analyze on.")
    parser.add_argument("--top-k-spans", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        default="",
        help="Optional output directory. Defaults to .omx/logs/phase1_smoke/<timestamp>_<slug>/",
    )
    args = parser.parse_args()

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else ROOT / ".omx" / "logs" / "phase1_smoke" / f"{now_stamp()}_{impact_core.run_pipeline().slugify(args.query, limit=40)}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now().isoformat(timespec="seconds")
    discover_started = time.time()
    session_id, session = impact_core.create_session(
        query=args.query,
        limit=max(1, args.limit),
        probe_downloads=bool(args.probe_downloads),
        auto_refresh_top=0,
        sort_preference=args.sort_preference,
    )
    discover_elapsed = round(time.time() - discover_started, 2)

    session, status_payload, detail_payload = snapshot_session(session_id, output_dir, "after_discover")
    paper_ids = parse_ids(args.paper_ids)
    if not paper_ids:
        first_paper = next((item.get("id") for item in session.get("papers", []) if item.get("id")), "")
        paper_ids = [first_paper] if first_paper else []

    steps = [
        {
            "name": "discover",
            "ok": True,
            "elapsed_sec": discover_elapsed,
            "paper_ids": paper_ids,
            "result": {
                "session_id": session_id,
                "paper_count": len(session.get("papers", [])),
                "warnings": session.get("warnings", []),
            },
            "exception": None,
            "paper_states": collect_paper_state(session, paper_ids),
            "failure_reasons": step_failure_reasons("discover", session, session, detail_payload, paper_ids),
        }
    ]

    if paper_ids:
        steps.append(
            run_step(
                "refresh",
                output_dir,
                session_id,
                paper_ids,
                lambda: impact_core.refresh_probes(session_id, paper_ids, force=True),
            )
        )
        steps.append(
            run_step(
                "download",
                output_dir,
                session_id,
                paper_ids,
                lambda: impact_core.download_papers(session_id, paper_ids, auto_only=False),
            )
        )
        steps.append(
            run_step(
                "analyze",
                output_dir,
                session_id,
                paper_ids,
                lambda: impact_core.analyze_papers(session_id, paper_ids, top_k_spans=max(1, args.top_k_spans)),
            )
        )

    final_session, final_status_payload, final_detail_payload = snapshot_session(session_id, output_dir, "final")
    summary = {
        "started_at": started_at,
        "query": args.query,
        "session_id": session_id,
        "paper_ids": paper_ids,
        "steps": steps,
        "final_overview": {
            "warnings": final_session.get("warnings", []),
            "overview_stats": final_status_payload.get("overview_stats", {}),
            "exports": final_detail_payload.get("exports", {}),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")

    print(json.dumps({"ok": True, "output_dir": str(output_dir), "session_id": session_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
