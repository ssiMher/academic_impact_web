from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD_PATH = ROOT / "data" / "reference" / "fulltext_regression_set.json"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "runs" / "analysis_scope_benchmarks"
SUPPORTED_SCOPES = ("candidate_spans", "fulltext_direct")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.academic_impact_analyzer import impact_cli  # noqa: E402
from skills.academic_impact_analyzer import run_pipeline  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return cleaned.strip("_") or "session"


def resolve_session_dir(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    by_id = ROOT / "data" / "sessions" / value
    if by_id.exists():
        return by_id.resolve()
    raise FileNotFoundError(f"找不到 session：{value}（可传 session_id 或 session 目录）")


def load_source_session(session_dir: Path) -> dict[str, Any]:
    return impact_cli.load_session(session_dir)


def parse_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def select_paper_ids(session: dict[str, Any], ids: list[str], top_n: int) -> list[str]:
    papers = session.get("papers", [])
    if ids:
        available = {item.get("id") for item in papers}
        missing = [paper_id for paper_id in ids if paper_id not in available]
        if missing:
            raise ValueError(f"这些论文 ID 不在 session 中：{', '.join(missing)}")
        return ids
    selected = [item.get("id") for item in papers if item.get("id")]
    if top_n > 0:
        selected = selected[:top_n]
    return selected


def normalize_scopes(values: list[str]) -> list[str]:
    scopes = []
    for value in values or list(SUPPORTED_SCOPES):
        scope = run_pipeline.normalize_analysis_scope(value)
        if scope not in SUPPORTED_SCOPES:
            raise ValueError(f"不支持的 analysis scope：{value}")
        if scope not in scopes:
            scopes.append(scope)
    return scopes


def load_gold_cases(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    if not path or not path.exists():
        return {}
    payload = read_json(path)
    cases = {}
    for sample in payload.get("samples", []):
        session_id = str(sample.get("session_id") or "").strip()
        paper_id = str(sample.get("paper_id") or "").strip()
        if not session_id or not paper_id:
            continue
        cases[(session_id, paper_id)] = sample.get("expected", {}) or {}
    return cases


def session_identity(session_dir: Path, session: dict[str, Any]) -> str:
    return str(session.get("session_id") or session.get("id") or session_dir.name)


def paper_title(session: dict[str, Any], paper_id: str) -> str:
    for item in session.get("papers", []):
        if item.get("id") == paper_id:
            return item.get("title") or ""
    return ""


def copy_session(source_dir: Path, destination_dir: Path) -> None:
    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    shutil.copytree(source_dir, destination_dir)


def load_analysis_json(item: dict[str, Any]) -> dict[str, Any]:
    analysis_path = (item.get("analysis_result") or {}).get("paths", {}).get("analysis")
    if not analysis_path:
        return {}
    path = Path(analysis_path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_candidate_json(item: dict[str, Any]) -> dict[str, Any]:
    candidate_path = (item.get("analysis_result") or {}).get("paths", {}).get("candidate_spans")
    if not candidate_path:
        return {}
    path = Path(candidate_path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def detail_for_paper(session: dict[str, Any], paper_id: str) -> dict[str, Any]:
    detail_payload = impact_cli.build_session_detail_payload(session)
    for item in detail_payload.get("papers", []):
        if item.get("id") == paper_id:
            return item
    return {}


def item_for_paper(session: dict[str, Any], paper_id: str) -> dict[str, Any]:
    for item in session.get("papers", []):
        if item.get("id") == paper_id:
            return item
    return {}


def gold_labels_from_findings(findings: list[Any]) -> list[str]:
    labels = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        keep = finding.get("keep")
        aspect = str(finding.get("aspect") or "").strip()
        mention_type = str(finding.get("mention_type") or "").strip()
        is_weak = mention_type in {"grouped_literature_mention", "weak_body_mention"}
        is_semantic = keep is not False and not is_weak
        if is_semantic and aspect:
            labels.append(aspect)
        if is_weak:
            labels.append(mention_type)
    return list(dict.fromkeys(labels))


def gold_actual_observation(
    detail: dict[str, Any],
    analysis_data: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = detail.get("citation_method_summary", {}) or {}
    actual_status = detail.get("analysis_status")
    findings = []
    if isinstance(analysis_data, dict) and isinstance(analysis_data.get("findings"), list):
        findings = analysis_data.get("findings", [])
    else:
        trace = detail.get("citation_trace", {}) or {}
        finding_count = trace.get("finding_count")
        if isinstance(finding_count, int):
            findings = [{} for _ in range(finding_count)]

    labels = gold_labels_from_findings(findings)
    if not labels:
        labels = summary.get("labels", []) or []

    has_findings = bool(findings)
    normalized_status = actual_status
    if (
        expected
        and expected.get("final_status") == "fulltext_no_finding"
        and actual_status == "reference_only"
        and not has_findings
    ):
        normalized_status = "fulltext_no_finding"

    return {
        "final_status": actual_status,
        "normalized_status": normalized_status,
        "has_findings": has_findings,
        "labels": labels,
    }


def evaluate_against_gold(
    detail: dict[str, Any],
    expected: dict[str, Any] | None,
    analysis_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not expected:
        return {"available": False, "passed": None}

    actual = gold_actual_observation(detail, analysis_data, expected)
    labels = actual["labels"]
    missing_labels = [label for label in expected.get("min_labels", []) if label not in labels]

    checks = {
        "final_status": actual["normalized_status"] == expected.get("final_status"),
        "has_findings": actual["has_findings"] == expected.get("has_findings"),
        "min_labels": not missing_labels,
    }
    return {
        "available": True,
        "passed": all(checks.values()),
        "checks": checks,
        "expected": expected,
        "actual": actual,
        "missing_labels": missing_labels,
    }


def summarize_one_run(
    *,
    source_session_dir: Path,
    output_dir: Path,
    source_session: dict[str, Any],
    session_id: str,
    paper_id: str,
    scope: str,
    top_k_spans: int,
    gold_cases: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    work_dir = output_dir / "work" / f"{safe_name(scope)}__{safe_name(paper_id)}"
    started = time.perf_counter()
    copy_session(source_session_dir, work_dir)
    error = None
    result = {}
    try:
        result = impact_cli.run_analysis(work_dir, [paper_id], top_k_spans=top_k_spans, analysis_scope=scope)
        ok = bool(result.get("ok"))
    except Exception as exc:  # noqa: BLE001 - benchmark should report failures instead of aborting the batch.
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    wall_seconds = time.perf_counter() - started

    session = load_source_session(work_dir)
    item = item_for_paper(session, paper_id)
    detail = detail_for_paper(session, paper_id) if item else {}
    analysis_data = load_analysis_json(item) if item else {}
    candidate_data = load_candidate_json(item) if item else {}
    citation_trace = detail.get("citation_trace", {}) if detail else {}
    debug = citation_trace.get("debug", {}) or {}
    paths = (item.get("analysis_result") or {}).get("paths", {}) if item else {}
    findings = analysis_data.get("findings", []) if isinstance(analysis_data.get("findings"), list) else []
    candidate_spans = candidate_data.get("spans", []) if isinstance(candidate_data.get("spans"), list) else []

    expected = gold_cases.get((session_id, paper_id))
    gold = evaluate_against_gold(detail, expected, analysis_data)
    benchmark_actual = gold_actual_observation(detail, analysis_data, expected)

    return {
        "paper_id": paper_id,
        "title": paper_title(source_session, paper_id),
        "scope": scope,
        "ok": ok,
        "error": error,
        "work_dir": str(work_dir),
        "wall_seconds": round(wall_seconds, 3),
        "run_result": {
            key: result.get(key)
            for key in ["processed_papers", "analysis_scope", "summary_path", "report_json_path", "report_md_path"]
            if isinstance(result, dict) and key in result
        },
        "actual": {
            "analysis_status": detail.get("analysis_status") or (item.get("analysis_result") or {}).get("status"),
            "labels": benchmark_actual.get("labels", []),
            "has_findings": benchmark_actual.get("has_findings"),
            "finding_count": citation_trace.get("finding_count", len(findings)),
            "candidate_span_count": citation_trace.get("candidate_span_count", len(candidate_spans)),
            "fulltext_char_count": debug.get("fulltext_char_count"),
            "fulltext_page_count": debug.get("fulltext_page_count"),
            "prompt_chars": debug.get("prompt_chars"),
            "finish_reason": debug.get("finish_reason"),
            "output_source": debug.get("output_source"),
            "analysis_error_type": analysis_data.get("error_type"),
        },
        "paths": {
            key: value
            for key, value in paths.items()
            if key in {"analysis", "candidate_spans", "analyze_payload", "fulltext", "fallback_analysis"}
        },
        "gold": gold,
    }


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def summarize_by_scope(runs: list[dict[str, Any]], elapsed_seconds: float) -> dict[str, Any]:
    summary = {}
    for scope in sorted({run["scope"] for run in runs}):
        scope_runs = [run for run in runs if run["scope"] == scope]
        wall_times = [float(run["wall_seconds"]) for run in scope_runs]
        gold_runs = [run for run in scope_runs if run.get("gold", {}).get("available")]
        gold_passes = [run for run in gold_runs if run.get("gold", {}).get("passed")]
        statuses = Counter((run.get("actual") or {}).get("analysis_status") or "unknown" for run in scope_runs)
        summary[scope] = {
            "paper_count": len(scope_runs),
            "ok_count": sum(1 for run in scope_runs if run.get("ok")),
            "failed_count": sum(1 for run in scope_runs if not run.get("ok")),
            "sum_wall_seconds": round(sum(wall_times), 3),
            "avg_wall_seconds": average(wall_times),
            "median_wall_seconds": median(wall_times),
            "status_counts": dict(statuses),
            "avg_finding_count": average([float((run.get("actual") or {}).get("finding_count") or 0) for run in scope_runs]),
            "avg_candidate_span_count": average(
                [float((run.get("actual") or {}).get("candidate_span_count") or 0) for run in scope_runs]
            ),
            "gold_available_count": len(gold_runs),
            "gold_pass_count": len(gold_passes),
            "gold_pass_rate": round(len(gold_passes) / len(gold_runs), 3) if gold_runs else None,
            "batch_elapsed_seconds": round(elapsed_seconds, 3),
        }
    return summary


def compare_pairs(runs: list[dict[str, Any]], scopes: list[str]) -> list[dict[str, Any]]:
    by_paper: dict[str, dict[str, dict[str, Any]]] = {}
    for run in runs:
        by_paper.setdefault(run["paper_id"], {})[run["scope"]] = run

    comparisons = []
    if len(scopes) < 2:
        return comparisons
    left_scope, right_scope = scopes[0], scopes[1]
    for paper_id, scope_runs in sorted(by_paper.items()):
        left = scope_runs.get(left_scope, {})
        right = scope_runs.get(right_scope, {})
        left_actual = left.get("actual", {})
        right_actual = right.get("actual", {})
        comparisons.append({
            "paper_id": paper_id,
            "title": left.get("title") or right.get("title") or "",
            "left_scope": left_scope,
            "right_scope": right_scope,
            "status_changed": left_actual.get("analysis_status") != right_actual.get("analysis_status"),
            "finding_count_delta": (right_actual.get("finding_count") or 0) - (left_actual.get("finding_count") or 0),
            "wall_seconds_delta": round((right.get("wall_seconds") or 0) - (left.get("wall_seconds") or 0), 3),
            "left": {
                "ok": left.get("ok"),
                "analysis_status": left_actual.get("analysis_status"),
                "finding_count": left_actual.get("finding_count"),
                "labels": left_actual.get("labels", []),
                "gold_passed": (left.get("gold") or {}).get("passed"),
                "wall_seconds": left.get("wall_seconds"),
            },
            "right": {
                "ok": right.get("ok"),
                "analysis_status": right_actual.get("analysis_status"),
                "finding_count": right_actual.get("finding_count"),
                "labels": right_actual.get("labels", []),
                "gold_passed": (right.get("gold") or {}).get("passed"),
                "wall_seconds": right.get("wall_seconds"),
            },
        })
    return comparisons


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Analysis Scope Benchmark",
        "",
        f"- Session: `{payload['session_id']}`",
        f"- Papers: {payload['paper_count']}",
        f"- Scopes: {', '.join(payload['scopes'])}",
        f"- Concurrency: {payload['concurrency']}",
        f"- Elapsed: {payload['elapsed_seconds']}s",
        f"- Gold file: `{payload.get('gold_path') or 'none'}`",
        "",
        "## Scope Summary",
        "",
        "| Scope | OK | Failed | Avg seconds | Median seconds | Gold pass | Status counts |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for scope, item in payload.get("scope_summary", {}).items():
        gold = "-"
        if item.get("gold_available_count"):
            gold = f"{item.get('gold_pass_count')}/{item.get('gold_available_count')} ({item.get('gold_pass_rate')})"
        lines.append(
            "| {scope} | {ok} | {failed} | {avg} | {median} | {gold} | `{statuses}` |".format(
                scope=scope,
                ok=item.get("ok_count"),
                failed=item.get("failed_count"),
                avg=item.get("avg_wall_seconds"),
                median=item.get("median_wall_seconds"),
                gold=gold,
                statuses=json.dumps(item.get("status_counts", {}), ensure_ascii=False),
            )
        )

    lines.extend([
        "",
        "## Pair Comparisons",
        "",
        "| Paper | Status changed | Finding delta | Seconds delta | Left | Right |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ])
    for item in payload.get("comparisons", []):
        left = item.get("left", {})
        right = item.get("right", {})
        lines.append(
            "| `{paper}` | {changed} | {findings} | {seconds} | {left_status}/{left_gold} | {right_status}/{right_gold} |".format(
                paper=item.get("paper_id"),
                changed="yes" if item.get("status_changed") else "no",
                findings=item.get("finding_count_delta"),
                seconds=item.get("wall_seconds_delta"),
                left_status=left.get("analysis_status"),
                left_gold=left.get("gold_passed"),
                right_status=right.get("analysis_status"),
                right_gold=right.get("gold_passed"),
            )
        )
    return "\n".join(lines) + "\n"


def run_benchmark(
    *,
    session_dir: Path,
    paper_ids: list[str],
    scopes: list[str],
    top_k_spans: int,
    concurrency: int,
    output_dir: Path,
    gold_path: Path | None,
) -> dict[str, Any]:
    source_session = load_source_session(session_dir)
    session_id = session_identity(session_dir, source_session)
    gold_cases = load_gold_cases(gold_path)

    tasks = [
        {"paper_id": paper_id, "scope": scope}
        for paper_id in paper_ids
        for scope in scopes
    ]

    started = time.perf_counter()
    runs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(
                summarize_one_run,
                source_session_dir=session_dir,
                output_dir=output_dir,
                source_session=source_session,
                session_id=session_id,
                paper_id=task["paper_id"],
                scope=task["scope"],
                top_k_spans=top_k_spans,
                gold_cases=gold_cases,
            )
            for task in tasks
        ]
        for future in concurrent.futures.as_completed(futures):
            runs.append(future.result())

    runs.sort(key=lambda item: (item["paper_id"], scopes.index(item["scope"])))
    elapsed_seconds = time.perf_counter() - started
    payload = {
        "ok": all(run.get("ok") for run in runs),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "source_session_dir": str(session_dir),
        "output_dir": str(output_dir),
        "paper_count": len(paper_ids),
        "paper_ids": paper_ids,
        "scopes": scopes,
        "top_k_spans": top_k_spans,
        "concurrency": max(1, concurrency),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "gold_path": str(gold_path) if gold_path and gold_path.exists() else "",
        "scope_summary": summarize_by_scope(runs, elapsed_seconds),
        "comparisons": compare_pairs(runs, scopes),
        "runs": runs,
    }
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="隔离运行并比较 candidate_spans 与 fulltext_direct 两种全文分析方法。",
    )
    parser.add_argument(
        "session",
        help="session_id 或 session 目录路径，例如 data/sessions/<id>",
    )
    parser.add_argument(
        "--ids",
        default="",
        help="逗号分隔的候选论文 ID；不传则按 session 顺序取 --top-n。",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="未传 --ids 时选择前 N 篇；0 表示全部。",
    )
    parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        choices=SUPPORTED_SCOPES,
        help="可重复传入；默认同时跑 candidate_spans 和 fulltext_direct。",
    )
    parser.add_argument(
        "--top-k-spans",
        type=int,
        default=8,
        help="候选段落模式传给分析流程的 top_k_spans。",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="并发任务数。脚本会为每个 paper/scope 复制独立 session，避免写冲突。",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="输出目录；默认写入 data/runs/analysis_scope_benchmarks/<timestamp>_<session>。",
    )
    parser.add_argument(
        "--gold-file",
        default=str(DEFAULT_GOLD_PATH),
        help="可选 gold/regression JSON；不存在时只做性能和结果差异对比。",
    )
    parser.add_argument(
        "--no-gold",
        action="store_true",
        help="忽略默认 gold 文件。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    session_dir = resolve_session_dir(args.session)
    source_session = load_source_session(session_dir)
    paper_ids = select_paper_ids(source_session, parse_ids(args.ids), args.top_n)
    if not paper_ids:
        raise SystemExit("没有可测试的论文。请检查 session 或传入 --ids。")

    scopes = normalize_scopes(args.scopes or list(SUPPORTED_SCOPES))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else (
        DEFAULT_OUTPUT_ROOT / f"{timestamp}_{safe_name(session_identity(session_dir, source_session))}"
    )
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    gold_path = None if args.no_gold else Path(args.gold_file).expanduser()

    payload = run_benchmark(
        session_dir=session_dir,
        paper_ids=paper_ids,
        scopes=scopes,
        top_k_spans=args.top_k_spans,
        concurrency=args.concurrency,
        output_dir=output_dir,
        gold_path=gold_path,
    )

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    payload["report_json_path"] = str(json_path)
    payload["report_md_path"] = str(md_path)
    write_json(json_path, payload)
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
