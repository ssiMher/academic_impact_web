from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD_PATH = ROOT / "data" / "reference" / "fulltext_regression_set.json"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "runs" / "gold_reviews"
SUPPORTED_SCOPES = ("candidate_spans", "fulltext_direct")
ALLOWED_FINAL_STATUSES = {
    "fulltext_analyzed",
    "mention_only",
    "fulltext_no_finding",
    "context_only",
    "fulltext_extract_failed",
    "analysis_failed",
    "write_output_failed",
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.academic_impact_analyzer import impact_cli  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return cleaned.strip("_") or "gold_review"


def resolve_session_dir(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    by_id = ROOT / "data" / "sessions" / value
    if by_id.exists():
        return by_id.resolve()
    raise FileNotFoundError(f"找不到 session：{value}（可传 session_id 或 session 目录）")


def parse_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def session_identity(session_dir: Path, session: dict[str, Any]) -> str:
    return str(session.get("session_id") or session.get("id") or session_dir.name)


def normalize_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels = []
    for item in value:
        label = str(item or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def load_optional_analysis(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def compact_findings(analysis_payload: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    findings = analysis_payload.get("findings")
    if not isinstance(findings, list):
        return []
    compacted = []
    for item in findings[:limit]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                key: item.get(key)
                for key in [
                    "label",
                    "aspect",
                    "citation_function",
                    "evidence",
                    "evidence_excerpt",
                    "reason",
                    "confidence",
                ]
                if item.get(key) not in (None, "", [])
            }
        )
    return compacted


def empty_scope_snapshot() -> dict[str, Any]:
    return {
        "available": False,
        "analysis_status": "",
        "labels": [],
        "has_findings": None,
        "finding_count": 0,
        "wall_seconds": None,
        "findings": [],
        "paths": {},
    }


def snapshot_from_benchmark_run(run: dict[str, Any]) -> dict[str, Any]:
    paths = run.get("paths") if isinstance(run.get("paths"), dict) else {}
    actual = run.get("actual") if isinstance(run.get("actual"), dict) else {}
    analysis_payload = load_optional_analysis(paths.get("analysis"))
    return {
        "available": bool(run.get("ok")),
        "analysis_status": actual.get("analysis_status") or "",
        "labels": normalize_labels(actual.get("labels")),
        "has_findings": actual.get("has_findings"),
        "finding_count": actual.get("finding_count") or 0,
        "wall_seconds": run.get("wall_seconds"),
        "findings": compact_findings(analysis_payload),
        "paths": {
            key: value
            for key, value in paths.items()
            if key in {"analysis", "candidate_spans", "analyze_payload", "fulltext", "fallback_analysis"}
        },
    }


def snapshot_from_session_item(detail: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    paths = (item.get("analysis_result") or {}).get("paths", {}) if isinstance(item, dict) else {}
    analysis_payload = load_optional_analysis(paths.get("analysis"))
    summary = detail.get("citation_method_summary", {}) if isinstance(detail, dict) else {}
    trace = detail.get("citation_trace", {}) if isinstance(detail, dict) else {}
    return {
        "available": bool(item.get("analysis_result")),
        "analysis_status": detail.get("analysis_status") or (item.get("analysis_result") or {}).get("status") or "",
        "labels": normalize_labels(summary.get("labels")),
        "has_findings": bool(summary.get("evidence_excerpt")) if summary else None,
        "finding_count": trace.get("finding_count") or len(compact_findings(analysis_payload)),
        "wall_seconds": None,
        "findings": compact_findings(analysis_payload),
        "paths": {
            key: value
            for key, value in paths.items()
            if key in {"analysis", "candidate_spans", "analyze_payload", "fulltext", "fallback_analysis"}
        },
    }


def infer_scope_from_session_item(item: dict[str, Any]) -> str:
    paths = (item.get("analysis_result") or {}).get("paths", {}) if isinstance(item, dict) else {}
    analysis_payload = load_optional_analysis(paths.get("analysis"))
    debug = analysis_payload.get("_debug") if isinstance(analysis_payload.get("_debug"), dict) else {}
    value = (
        (item.get("analysis_result") or {}).get("analysis_scope")
        or analysis_payload.get("analysis_scope")
        or debug.get("analysis_scope")
    )
    return value if value in SUPPORTED_SCOPES else "candidate_spans"


def expected_placeholder() -> dict[str, Any]:
    return {
        "final_status": "",
        "has_findings": None,
        "min_labels": [],
    }


def build_sample(
    *,
    target_query: str,
    session_id: str,
    paper_id: str,
    title: str,
    scopes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "target_query": target_query,
        "session_id": session_id,
        "paper_id": paper_id,
        "title": title,
        "candidate_spans": scopes.get("candidate_spans") or empty_scope_snapshot(),
        "fulltext_direct": scopes.get("fulltext_direct") or empty_scope_snapshot(),
        "expected": expected_placeholder(),
        "reviewer_notes": "",
    }


def select_papers_from_session(session: dict[str, Any], ids: list[str], top_n: int) -> list[dict[str, Any]]:
    papers = session.get("papers", [])
    if ids:
        by_id = {item.get("id"): item for item in papers}
        missing = [paper_id for paper_id in ids if paper_id not in by_id]
        if missing:
            raise ValueError(f"这些论文 ID 不在 session 中：{', '.join(missing)}")
        return [by_id[paper_id] for paper_id in ids]
    selected = [item for item in papers if item.get("id")]
    if top_n > 0:
        selected = selected[:top_n]
    return selected


def build_template_from_benchmark(report_path: Path, ids: list[str], top_n: int) -> dict[str, Any]:
    report = read_json(report_path)
    if not isinstance(report.get("runs"), list):
        raise ValueError(f"{report_path} 不是 analysis scope benchmark report.json")

    session_id = str(report.get("session_id") or "").strip()
    target_query = ""
    source_session_dir = report.get("source_session_dir")
    if source_session_dir and Path(source_session_dir).exists():
        try:
            source_session = impact_cli.load_session(Path(source_session_dir))
            target_query = str(source_session.get("query") or "")
        except Exception:  # noqa: BLE001 - source metadata is helpful but not required for review.
            target_query = ""

    grouped: dict[str, dict[str, Any]] = {}
    titles: dict[str, str] = {}
    for run in report.get("runs", []):
        paper_id = str(run.get("paper_id") or "").strip()
        scope = str(run.get("scope") or "").strip()
        if not paper_id or scope not in SUPPORTED_SCOPES:
            continue
        grouped.setdefault(paper_id, {})[scope] = snapshot_from_benchmark_run(run)
        titles[paper_id] = str(run.get("title") or titles.get(paper_id) or "")

    ordered_ids = [paper_id for paper_id in report.get("paper_ids", []) if paper_id in grouped]
    ordered_ids.extend(paper_id for paper_id in sorted(grouped) if paper_id not in ordered_ids)
    if ids:
        missing = [paper_id for paper_id in ids if paper_id not in grouped]
        if missing:
            raise ValueError(f"这些论文 ID 不在 benchmark report 中：{', '.join(missing)}")
        ordered_ids = ids
    elif top_n > 0:
        ordered_ids = ordered_ids[:top_n]

    samples = [
        build_sample(
            target_query=target_query,
            session_id=session_id,
            paper_id=paper_id,
            title=titles.get(paper_id, ""),
            scopes=grouped.get(paper_id, {}),
        )
        for paper_id in ordered_ids
    ]
    return build_template_payload(
        source={"type": "benchmark_report", "path": str(report_path), "session_id": session_id},
        samples=samples,
    )


def build_template_from_session(session_value: str, ids: list[str], top_n: int) -> dict[str, Any]:
    session_dir = resolve_session_dir(session_value)
    session = impact_cli.load_session(session_dir)
    detail_payload = impact_cli.build_session_detail_payload(session)
    details = {item.get("id"): item for item in detail_payload.get("papers", [])}
    session_id = session_identity(session_dir, session)
    samples = []
    for item in select_papers_from_session(session, ids, top_n):
        paper_id = item.get("id")
        scope = infer_scope_from_session_item(item)
        samples.append(
            build_sample(
                target_query=str(session.get("query") or ""),
                session_id=session_id,
                paper_id=paper_id,
                title=item.get("title") or (item.get("paper") or {}).get("title") or "",
                scopes={scope: snapshot_from_session_item(details.get(paper_id, {}), item)},
            )
        )
    return build_template_payload(
        source={"type": "session", "path": str(session_dir), "session_id": session_id},
        samples=samples,
    )


def build_template_payload(source: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "instructions": [
            "人工审核 candidate_spans 与 fulltext_direct 输出后，只填写 expected。",
            "expected.final_status 必须是 fulltext_analyzed、mention_only、fulltext_no_finding、context_only、fulltext_extract_failed、analysis_failed 或 write_output_failed。",
            "expected.has_findings 必须是 true 或 false；expected.min_labels 可为空数组。",
            "不要把未经人工确认的模板直接 append 到 regression set。",
        ],
        "samples": samples,
    }


def normalize_expected(raw: Any, *, sample_ref: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors = []
    if not isinstance(raw, dict):
        return None, [f"{sample_ref}: expected 必须是对象"]

    final_status = str(raw.get("final_status") or "").strip()
    if not final_status:
        errors.append(f"{sample_ref}: expected.final_status 不能为空")
    elif final_status not in ALLOWED_FINAL_STATUSES:
        errors.append(
            f"{sample_ref}: expected.final_status={final_status!r} 不支持；可选 {sorted(ALLOWED_FINAL_STATUSES)}"
        )

    has_findings = raw.get("has_findings")
    if not isinstance(has_findings, bool):
        errors.append(f"{sample_ref}: expected.has_findings 必须是 true/false")

    min_labels = raw.get("min_labels")
    if not isinstance(min_labels, list) or any(not isinstance(item, str) or not item.strip() for item in min_labels):
        errors.append(f"{sample_ref}: expected.min_labels 必须是字符串数组")

    if errors:
        return None, errors

    return {
        "final_status": final_status,
        "has_findings": has_findings,
        "min_labels": normalize_labels(min_labels),
    }, []


def normalize_review_sample(sample: Any, index: int) -> tuple[dict[str, Any] | None, list[str]]:
    sample_ref = f"samples[{index}]"
    if not isinstance(sample, dict):
        return None, [f"{sample_ref}: 必须是对象"]

    errors = []
    target_query = str(sample.get("target_query") or "").strip()
    session_id = str(sample.get("session_id") or "").strip()
    paper_id = str(sample.get("paper_id") or "").strip()
    title = str(sample.get("title") or "").strip()
    if not session_id:
        errors.append(f"{sample_ref}: session_id 不能为空")
    if not paper_id:
        errors.append(f"{sample_ref}: paper_id 不能为空")
    if not title:
        errors.append(f"{sample_ref}: title 不能为空")

    expected, expected_errors = normalize_expected(sample.get("expected"), sample_ref=sample_ref)
    errors.extend(expected_errors)
    if errors:
        return None, errors

    return {
        "target_query": target_query,
        "session_id": session_id,
        "paper_id": paper_id,
        "title": title,
        "expected": expected,
    }, []


def validate_review_template(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    samples = payload.get("samples")
    if not isinstance(samples, list):
        return [], ["samples 必须是数组"]

    normalized = []
    errors = []
    seen: set[tuple[str, str]] = set()
    for index, sample in enumerate(samples):
        item, item_errors = normalize_review_sample(sample, index)
        if item_errors:
            errors.extend(item_errors)
            continue
        key = (item["session_id"], item["paper_id"])
        if key in seen:
            errors.append(f"samples[{index}]: 重复样本 {key[0]}/{key[1]}")
            continue
        seen.add(key)
        normalized.append(item)
    return normalized, errors


def load_gold_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "1.0",
            "description": "Fixed real-sample fulltext regression set for web/CLI attach+analyze validation.",
            "samples": [],
        }
    payload = read_json(path)
    if not isinstance(payload.get("samples"), list):
        raise ValueError(f"{path} 中 samples 必须是数组")
    return payload


def append_review_samples(
    *,
    review_path: Path,
    gold_path: Path,
    output_path: Path | None,
    replace_existing: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    review_payload = read_json(review_path)
    incoming, errors = validate_review_template(review_payload)
    if errors:
        return {
            "ok": False,
            "review_path": str(review_path),
            "gold_path": str(gold_path),
            "errors": errors,
        }

    gold_payload = load_gold_payload(gold_path)
    existing_by_key = {}
    existing_order = []
    for sample in gold_payload.get("samples", []):
        key = (str(sample.get("session_id") or ""), str(sample.get("paper_id") or ""))
        if key in existing_by_key:
            continue
        existing_by_key[key] = sample
        existing_order.append(key)

    appended = []
    appended_samples = []
    replaced = []
    skipped_duplicates = []
    for sample in incoming:
        key = (sample["session_id"], sample["paper_id"])
        if key in existing_by_key:
            if replace_existing:
                existing_by_key[key] = sample
                replaced.append({"session_id": key[0], "paper_id": key[1]})
            else:
                skipped_duplicates.append({"session_id": key[0], "paper_id": key[1]})
            continue
        existing_by_key[key] = sample
        appended_samples.append(sample)
        appended.append({"session_id": key[0], "paper_id": key[1]})

    stable_samples = [existing_by_key[key] for key in existing_order]
    stable_samples.extend(
        sorted(appended_samples, key=lambda item: (item.get("session_id", ""), item.get("paper_id", "")))
    )
    new_payload = {
        "schema_version": str(gold_payload.get("schema_version") or "1.0"),
        "description": str(
            gold_payload.get("description")
            or "Fixed real-sample fulltext regression set for web/CLI attach+analyze validation."
        ),
        "samples": stable_samples,
    }
    destination = output_path or gold_path
    if not dry_run:
        write_json(destination, new_payload)

    return {
        "ok": True,
        "review_path": str(review_path),
        "gold_path": str(gold_path),
        "output_path": str(destination),
        "dry_run": dry_run,
        "input_sample_count": len(incoming),
        "appended_count": len(appended),
        "replaced_count": len(replaced),
        "skipped_duplicate_count": len(skipped_duplicates),
        "total_sample_count": len(stable_samples),
        "appended": appended,
        "replaced": replaced,
        "skipped_duplicates": skipped_duplicates,
    }


def render_markdown_review(payload: dict[str, Any]) -> str:
    lines = [
        "# Fulltext Gold Review",
        "",
        f"- Source: `{payload.get('source', {}).get('type', '')}`",
        f"- Session: `{payload.get('source', {}).get('session_id', '')}`",
        "",
        "Fill the `expected.*` fields in the JSON template, then run `validate` and `append`.",
        "",
    ]
    for sample in payload.get("samples", []):
        lines.extend([
            f"## {sample.get('paper_id')} - {sample.get('title')}",
            "",
            f"- session_id: `{sample.get('session_id')}`",
            f"- target_query: `{sample.get('target_query')}`",
            "",
            "| Scope | Available | Status | Labels | Findings | Seconds |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ])
        for scope in SUPPORTED_SCOPES:
            snap = sample.get(scope, {}) or {}
            lines.append(
                "| {scope} | {available} | {status} | `{labels}` | {findings} | {seconds} |".format(
                    scope=scope,
                    available="yes" if snap.get("available") else "no",
                    status=snap.get("analysis_status") or "-",
                    labels=json.dumps(snap.get("labels", []), ensure_ascii=False),
                    findings=snap.get("finding_count"),
                    seconds=snap.get("wall_seconds"),
                )
            )
        lines.extend([
            "",
            "Expected:",
            "",
            "```json",
            json.dumps(sample.get("expected", {}), ensure_ascii=False, indent=2),
            "```",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成、校验并合并全文分析人工 gold 标注。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    template = subparsers.add_parser("template", help="从 session 或 benchmark report 生成人工 review 模板。")
    source = template.add_mutually_exclusive_group(required=True)
    source.add_argument("--benchmark-report", help="analysis scope benchmark 的 report.json。")
    source.add_argument("--session", help="session_id 或 session 目录。")
    template.add_argument("--ids", default="", help="逗号分隔 paper_id；不传则按顺序取 --top-n。")
    template.add_argument("--top-n", type=int, default=0, help="0 表示全部。")
    template.add_argument("--output", default="", help="输出 JSON；默认写入 data/runs/gold_reviews。")
    template.add_argument("--markdown-output", default="", help="可选 Markdown review 摘要输出路径。")

    validate = subparsers.add_parser("validate", help="校验人工填写后的 review 模板。")
    validate.add_argument("review_template", help="template 子命令生成并经人工填写后的 JSON。")

    append = subparsers.add_parser("append", help="校验并合并人工确认样本到 regression set。")
    append.add_argument("review_template", help="template 子命令生成并经人工填写后的 JSON。")
    append.add_argument("--gold-file", default=str(DEFAULT_GOLD_PATH), help="目标 regression set JSON。")
    append.add_argument("--output", default="", help="可写到新文件；不传则原地更新 --gold-file。")
    append.add_argument("--replace-existing", action="store_true", help="同 session_id/paper_id 已存在时替换。")
    append.add_argument("--dry-run", action="store_true", help="只报告将会追加/跳过的样本，不写文件。")
    return parser


def default_template_output(payload: dict[str, Any]) -> Path:
    source = payload.get("source", {})
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = safe_name(str(source.get("session_id") or "session"))
    return DEFAULT_OUTPUT_ROOT / f"{timestamp}_{session_id}_gold_review.json"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "template":
        ids = parse_ids(args.ids)
        if args.benchmark_report:
            payload = build_template_from_benchmark(Path(args.benchmark_report).expanduser(), ids, args.top_n)
        else:
            payload = build_template_from_session(args.session, ids, args.top_n)
        output_path = Path(args.output).expanduser() if args.output else default_template_output(payload)
        write_json(output_path, payload)
        result = {
            "ok": True,
            "output_path": str(output_path),
            "sample_count": len(payload.get("samples", [])),
        }
        if args.markdown_output:
            md_path = Path(args.markdown_output).expanduser()
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(render_markdown_review(payload), encoding="utf-8")
            result["markdown_output_path"] = str(md_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "validate":
        payload = read_json(Path(args.review_template).expanduser())
        samples, errors = validate_review_template(payload)
        result = {
            "ok": not errors,
            "review_template": args.review_template,
            "valid_sample_count": len(samples),
            "errors": errors,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not errors else 1

    if args.command == "append":
        result = append_review_samples(
            review_path=Path(args.review_template).expanduser(),
            gold_path=Path(args.gold_file).expanduser(),
            output_path=Path(args.output).expanduser() if args.output else None,
            replace_existing=args.replace_existing,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
