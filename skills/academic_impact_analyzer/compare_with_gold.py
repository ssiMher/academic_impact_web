import argparse
import json
from pathlib import Path


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def load_json(path_arg: str):
    path = Path(path_arg).expanduser()
    return path, json.loads(path.read_text(encoding="utf-8"))


def load_summary(path_arg: str):
    path = Path(path_arg).expanduser()
    if path.is_dir():
        path = path / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到 summary.json: {path}")
    return load_json(str(path))


def build_run_index(summary: dict):
    target_title = ((summary.get("target") or {}).get("title")) or ""
    index = {}

    for item in summary.get("results", []):
        citing = item.get("citing_paper", {}) or {}
        key = (normalize(target_title), normalize(citing.get("title", "")))
        index[key] = item

    return index


def load_analysis(item: dict):
    path_str = ((item.get("paths") or {}).get("analysis")) or ""
    if not path_str:
        return {}
    path = Path(path_str).expanduser()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_predicted_function(findings: list) -> str:
    funcs = []
    for finding in findings or []:
        func = finding.get("function") or finding.get("reason") or ""
        func = func.strip()
        if func and func not in funcs:
            funcs.append(func)
    return " | ".join(funcs[:3])


def evaluate_case(case: dict, run_index: dict):
    target_title = (((case.get("target_paper") or {}).get("title")) or "")
    citing_title = (((case.get("citing_paper") or {}).get("title")) or "")
    key = (normalize(target_title), normalize(citing_title))
    item = run_index.get(key)

    if item is None:
        return {
            "id": case.get("id"),
            "matched": False,
            "gold_status": case.get("gold_status"),
            "pred_status": None,
            "status_match": False,
            "gold_function": case.get("gold_function"),
            "pred_function": "",
            "notes": "本次运行结果中未找到对应 citing paper。"
        }

    analysis = load_analysis(item)
    findings = analysis.get("findings", []) if isinstance(analysis, dict) else []
    pred_status = item.get("status")
    pred_function = summarize_predicted_function(findings)

    return {
        "id": case.get("id"),
        "matched": True,
        "gold_status": case.get("gold_status"),
        "pred_status": pred_status,
        "status_match": pred_status == case.get("gold_status"),
        "gold_function": case.get("gold_function"),
        "pred_function": pred_function,
        "citing_title": citing_title,
        "analysis_path": ((item.get("paths") or {}).get("analysis")),
        "notes": "" if pred_status == case.get("gold_status") else "状态与人工金标准不一致。"
    }


def build_report(summary: dict, gold_cases: list):
    run_index = build_run_index(summary)
    results = [evaluate_case(case, run_index) for case in gold_cases if not case.get("needs_review")]

    matched = [x for x in results if x["matched"]]
    status_match = [x for x in matched if x["status_match"]]

    return {
        "ok": True,
        "query": summary.get("query", ""),
        "target_title": ((summary.get("target") or {}).get("title")) or "",
        "gold_case_count": len(results),
        "matched_case_count": len(matched),
        "status_match_count": len(status_match),
        "status_match_rate": round(len(status_match) / len(matched), 4) if matched else 0.0,
        "results": results,
    }


def render_markdown(report: dict):
    lines = []
    lines.append("# Gold 对比报告")
    lines.append("")
    lines.append(f"- 查询：`{report.get('query', '')}`")
    lines.append(f"- 目标论文：{report.get('target_title', '')}")
    lines.append(f"- gold case 数量：{report.get('gold_case_count', 0)}")
    lines.append(f"- 命中 case 数量：{report.get('matched_case_count', 0)}")
    lines.append(f"- 状态一致数量：{report.get('status_match_count', 0)}")
    lines.append(f"- 状态一致率：{report.get('status_match_rate', 0.0)}")

    mismatches = [x for x in report.get("results", []) if not x.get("status_match")]
    if mismatches:
        lines.append("")
        lines.append("## 不一致样本")
        lines.append("")
        for item in mismatches:
            lines.append(f"### {item.get('id', '')}")
            if item.get("citing_title"):
                lines.append(f"- citing paper：{item['citing_title']}")
            lines.append(f"- gold_status：`{item.get('gold_status')}`")
            lines.append(f"- pred_status：`{item.get('pred_status')}`")
            if item.get("gold_function"):
                lines.append(f"- gold_function：{item.get('gold_function')}")
            if item.get("pred_function"):
                lines.append(f"- pred_function：{item.get('pred_function')}")
            if item.get("analysis_path"):
                lines.append(f"- analysis：`{item.get('analysis_path')}`")
            if item.get("notes"):
                lines.append(f"- notes：{item.get('notes')}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args():
    parser = argparse.ArgumentParser(description="对某次 pipeline 结果与 gold dataset 做对比")
    parser.add_argument("summary_or_run_dir", help="summary.json 路径，或某次运行目录")
    parser.add_argument(
        "--gold-file",
        default=str(Path(__file__).resolve().parent / "gold_cases.seed.json"),
        help="gold dataset JSON 文件，默认使用 gold_cases.seed.json",
    )
    parser.add_argument("--output-json", help="可选：保存 JSON 对比结果")
    parser.add_argument("--output-md", help="可选：保存 Markdown 对比结果")
    return parser.parse_args()


def main():
    args = parse_args()
    _, summary = load_summary(args.summary_or_run_dir)
    _, gold_cases = load_json(args.gold_file)
    report = build_report(summary, gold_cases)

    if args.output_json:
        Path(args.output_json).expanduser().write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.output_md:
        Path(args.output_md).expanduser().write_text(
            render_markdown(report),
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
