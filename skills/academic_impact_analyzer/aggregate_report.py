import argparse
import json
from collections import Counter
from pathlib import Path


STATUS_LABELS = {
    "fulltext_analyzed": "全文确认引用",
    "reference_only": "仅参考文献命中",
    "mention_only": "正文弱命中",
    "fulltext_no_finding": "全文未发现可靠证据",
    "context_only": "仅 context 推断",
    "fulltext_extract_failed": "全文提取失败",
    "analysis_failed": "语义分析失败",
}


def load_summary(path_arg: str):
    path = Path(path_arg).expanduser()
    if path.is_dir():
        path = path / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到 summary.json: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    return path, data


def infer_run_dir(summary_path: Path) -> Path:
    return summary_path.parent


def load_optional_json(path_str: str):
    if not path_str:
        return None
    path = Path(path_str).expanduser()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_entry(item: dict):
    citing = item.get("citing_paper", {})
    analysis = item.get("analysis", {})
    fallback = item.get("fallback_analysis", {})
    status = item.get("status", "unknown")
    status_note = item.get("status_note", {})

    entry = {
        "id": item.get("id") or item.get("paper_id"),
        "paper_id": item.get("paper_id") or item.get("id"),
        "title": citing.get("title", ""),
        "year": citing.get("year"),
        "venue": citing.get("venue"),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "status_message": status_note.get("message") or analysis.get("message") or fallback.get("message"),
        "download_ok": item.get("download", {}).get("ok"),
        "paths": item.get("paths", {}),
        "authors": citing.get("authors", []),
        "externalIds": citing.get("externalIds", {}),
    }

    analysis_data = load_optional_json(entry["paths"].get("analysis", ""))
    if analysis_data and isinstance(analysis_data.get("findings"), list):
        entry["findings"] = analysis_data.get("findings", [])

    if analysis:
        entry["findings_count"] = analysis.get("findings_count", 0)
        entry["analysis_status"] = analysis.get("final_status") or item.get("analysis_status") or status
    else:
        entry["analysis_status"] = item.get("analysis_status") or status

    if fallback:
        entry["fallback_context_count"] = len(fallback.get("fallback_contexts", []))
        entry["fallback_contexts"] = fallback.get("fallback_contexts", [])

    return entry


def build_report(summary: dict):
    results = summary.get("results", [])
    entries = [build_entry(item) for item in results]
    counts = Counter(entry["status"] for entry in entries)

    return {
        "ok": True,
        "query": summary.get("query", ""),
        "target": summary.get("target", {}),
        "output_dir": summary.get("output_dir", ""),
        "processed_papers": summary.get("processed_papers", 0),
        "status_counts": dict(counts),
        "status_labels": STATUS_LABELS,
        "entries": entries,
    }


def render_markdown(report: dict):
    target = report.get("target", {})
    lines = []
    lines.append("# 学术影响力分析汇总报告")
    lines.append("")
    lines.append(f"- 目标论文：{target.get('title', '')}")
    lines.append(f"- 查询：`{report.get('query', '')}`")
    lines.append(f"- 处理篇数：{report.get('processed_papers', 0)}")
    lines.append("")
    lines.append("## 状态统计")
    lines.append("")
    for status, label in STATUS_LABELS.items():
        count = report.get("status_counts", {}).get(status, 0)
        if count:
            lines.append(f"- {label}（`{status}`）：{count}")

    grouped = {}
    for entry in report.get("entries", []):
        grouped.setdefault(entry["status"], []).append(entry)

    for status in STATUS_LABELS:
        items = grouped.get(status, [])
        if not items:
            continue
        lines.append("")
        lines.append(f"## {STATUS_LABELS[status]}")
        lines.append("")
        for item in items:
            title = item.get("title", "")
            year = item.get("year")
            venue = item.get("venue", "")
            lines.append(f"### {title}")
            lines.append(f"- 年份/会议：{year} / {venue}")
            lines.append(f"- 状态：`{item.get('status')}`")
            if item.get("status_message"):
                lines.append(f"- 说明：{item['status_message']}")
            if item.get("findings_count") is not None:
                lines.append(f"- findings_count：{item.get('findings_count', 0)}")
            if item.get("fallback_context_count") is not None:
                lines.append(f"- fallback_context_count：{item.get('fallback_context_count', 0)}")
            paths = item.get("paths", {})
            if paths.get("analysis"):
                lines.append(f"- analysis：`{paths['analysis']}`")
            elif paths.get("fallback_analysis"):
                lines.append(f"- fallback：`{paths['fallback_analysis']}`")
            findings = item.get("findings", [])
            if findings:
                lines.append("- findings 摘要：")
                for finding in findings[:5]:
                    aspect = finding.get("aspect", "other")
                    stance = finding.get("stance", "neutral")
                    func = finding.get("function") or finding.get("reason") or ""
                    mention_type = finding.get("mention_type")
                    prefix = f"{mention_type} | " if mention_type else ""
                    lines.append(
                        f"  - p{finding.get('page')} span{finding.get('span_index')} | {prefix}{aspect} / {stance} | {func}"
                    )
            fallback_contexts = item.get("fallback_contexts", [])
            if fallback_contexts:
                lines.append("- context 摘要：")
                for ctx in fallback_contexts[:2]:
                    text = (ctx.get("text") or "").replace("\n", " ").strip()
                    if len(text) > 160:
                        text = text[:157] + "..."
                    lines.append(f"  - {text}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_outputs(run_dir: Path, report: dict):
    json_path = run_dir / "report_summary.json"
    md_path = run_dir / "report_summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def parse_args():
    parser = argparse.ArgumentParser(description="根据 pipeline summary 生成汇总报告")
    parser.add_argument("summary_or_run_dir", help="summary.json 路径，或某次运行目录")
    return parser.parse_args()


def main():
    args = parse_args()
    summary_path, summary = load_summary(args.summary_or_run_dir)
    run_dir = infer_run_dir(summary_path)
    report = build_report(summary)
    json_path, md_path = write_outputs(run_dir, report)
    print(json.dumps({
        "ok": True,
        "summary_path": str(summary_path),
        "report_json": str(json_path),
        "report_md": str(md_path),
        "status_counts": report.get("status_counts", {}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
