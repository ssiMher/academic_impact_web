import argparse
import importlib.util
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "skills"
DEFAULT_BATCH_DIR = Path("/tmp/academic_impact_batch_runs")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN_PIPELINE = load_module(
    "run_pipeline_module",
    SKILLS_ROOT / "academic_impact_analyzer" / "run_pipeline.py"
)


def read_queries(args):
    queries = []
    for q in args.queries:
        q = (q or "").strip()
        if q:
            queries.append(q)

    if args.query_file:
        for line in Path(args.query_file).expanduser().read_text(encoding="utf-8").splitlines():
            q = line.strip()
            if q and not q.startswith("#"):
                queries.append(q)

    deduped = []
    seen = set()
    for q in queries:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped


def build_batch_report(batch_dir: Path, runs: list):
    status_counter = Counter()
    run_outcome_counter = Counter()
    for run in runs:
        result = run.get("result", {})
        run_outcome_counter["ok" if result.get("ok") else "failed"] += 1
        for item in result.get("results", []):
            status_counter[item.get("status", "unknown")] += 1

    report = {
        "ok": True,
        "batch_dir": str(batch_dir),
        "started_at": runs[0]["started_at"] if runs else None,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "query_count": len(runs),
        "run_outcomes": dict(run_outcome_counter),
        "status_counts": dict(status_counter),
        "runs": runs,
    }

    report_json = batch_dir / "batch_summary.json"
    report_md = batch_dir / "batch_summary.md"
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(render_batch_markdown(report), encoding="utf-8")
    return report, report_json, report_md


def render_batch_markdown(report: dict):
    lines = []
    lines.append("# 学术影响力分析批量回归报告")
    lines.append("")
    lines.append(f"- 批量目录：`{report.get('batch_dir', '')}`")
    lines.append(f"- query 数量：{report.get('query_count', 0)}")
    lines.append("")
    lines.append("## 运行结果")
    lines.append("")
    run_outcomes = report.get("run_outcomes", {})
    for key, count in sorted(run_outcomes.items()):
        lines.append(f"- `{key}`：{count}")
    lines.append("")
    lines.append("## 总体状态统计")
    lines.append("")
    status_counts = report.get("status_counts", {})
    if status_counts:
        for status, count in sorted(status_counts.items()):
            lines.append(f"- `{status}`：{count}")
    else:
        lines.append("- 无成功产出的论文级状态统计")

    lines.append("")
    lines.append("## 各 query 结果")
    lines.append("")
    for run in report.get("runs", []):
        result = run.get("result", {})
        lines.append(f"### {run.get('query', '')}")
        lines.append(f"- 运行目录：`{run.get('run_dir', '')}`")
        lines.append(f"- ok：{result.get('ok')}")
        lines.append(f"- processed_papers：{result.get('processed_papers', 0)}")
        if result.get("error"):
            err = str(result["error"]).replace("\n", " ").strip()
            if len(err) > 240:
                err = err[:237] + "..."
            lines.append(f"- error：{err}")
        report_info = result.get("report", {})
        if report_info.get("md_path"):
            lines.append(f"- report：`{report_info['md_path']}`")
        local_counts = Counter(item.get("status", "unknown") for item in result.get("results", []))
        if local_counts:
            lines.append("- 状态分布：")
            for status, count in sorted(local_counts.items()):
                lines.append(f"  - `{status}`：{count}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args():
    parser = argparse.ArgumentParser(description="批量运行学术影响力分析回归")
    parser.add_argument("queries", nargs="*", help="多个目标论文 query（DOI/arXiv/标题）")
    parser.add_argument("--query-file", help="每行一个 query 的文本文件")
    parser.add_argument("--output-dir", help="批量输出目录")
    parser.add_argument("--max-papers", type=int, default=3, help="每个 query 最多处理多少篇 citing paper，默认 3")
    parser.add_argument("--scan-limit", type=int, help="每个 query 最多向前扫描多少篇 citing paper，默认 max-papers 的 3 倍")
    parser.add_argument("--top-k-spans", type=int, default=8, help="每个 citing paper 送入分析的候选段落数，默认 8")
    parser.add_argument("--sleep-seconds", type=int, default=6, help="相邻 query 之间的基础等待秒数，默认 6")
    return parser.parse_args()


def main():
    args = parse_args()
    queries = read_queries(args)
    if not queries:
        print(json.dumps({"ok": False, "error": "请至少提供一个 query 或 --query-file"}, ensure_ascii=False, indent=2))
        return

    if args.output_dir:
        batch_dir = Path(args.output_dir).expanduser()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = DEFAULT_BATCH_DIR / timestamp
    batch_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for idx, query in enumerate(queries, start=1):
        run_dir = batch_dir / f"{idx:03d}_{RUN_PIPELINE.slugify(query, limit=50)}"
        started_at = datetime.now().isoformat(timespec="seconds")
        max_papers = max(1, args.max_papers)
        scan_limit = max_papers * 3 if args.scan_limit is None else max(max_papers, args.scan_limit)
        try:
            result = RUN_PIPELINE.run_pipeline(
                query=query,
                output_dir=run_dir,
                max_papers=max_papers,
                top_k_spans=max(1, args.top_k_spans),
                scan_limit=scan_limit,
            )
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        runs.append({
            "query": query,
            "started_at": started_at,
            "run_dir": str(run_dir),
            "result": result,
        })

        if idx < len(queries):
            sleep_sec = max(0, args.sleep_seconds)
            err_text = str(result.get("error", "")) if isinstance(result, dict) else ""
            if "429" in err_text or "rate limited" in err_text.lower():
                sleep_sec = max(sleep_sec, 15)
            if sleep_sec:
                time.sleep(sleep_sec)

    report, report_json, report_md = build_batch_report(batch_dir, runs)
    print(json.dumps({
        "ok": True,
        "batch_dir": str(batch_dir),
        "batch_summary_json": str(report_json),
        "batch_summary_md": str(report_md),
        "query_count": report.get("query_count", 0),
        "status_counts": report.get("status_counts", {}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
