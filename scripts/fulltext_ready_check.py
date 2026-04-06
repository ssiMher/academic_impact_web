from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import impact_core
from project_env import load_project_env


REQUIRED_ENV_KEYS = [
    "DEEPSEEK_API_KEY",
    "ACADEMIC_IMPACT_LOCAL_LLM_URL",
    "ACADEMIC_IMPACT_LOCAL_MODEL",
]


def env_status() -> dict[str, Any]:
    load_project_env(ROOT)
    values = {}
    missing = []
    for key in REQUIRED_ENV_KEYS:
        raw = (os.getenv(key) or "").strip()
        configured = bool(raw)
        values[key] = {"configured": configured}
        if configured and key == "ACADEMIC_IMPACT_LOCAL_LLM_URL":
            values[key]["value"] = raw
        elif configured and key == "ACADEMIC_IMPACT_LOCAL_MODEL":
            values[key]["value"] = raw
        if not configured:
            missing.append(key)
    return {"items": values, "missing_keys": missing}


def candidate_probe_urls(local_llm_url: str) -> list[str]:
    value = (local_llm_url or "").strip()
    if not value:
        return []

    urls = []
    if value.endswith("/chat/completions"):
        urls.append(value[: -len("/chat/completions")] + "/models")
    urls.append(value)

    parsed = urlparse(value)
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if base:
        urls.append(base)

    unique = []
    seen = set()
    for item in urls:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def service_status(local_llm_url: str) -> dict[str, Any]:
    value = (local_llm_url or "").strip()
    if not value:
        return {
            "configured": False,
            "reachable": False,
            "status": "config_missing",
            "message": "未配置 ACADEMIC_IMPACT_LOCAL_LLM_URL，未执行服务连通性检查。",
        }

    errors = []
    for url in candidate_probe_urls(value):
        try:
            response = requests.get(url, timeout=5)
            return {
                "configured": True,
                "reachable": True,
                "status": "reachable",
                "probe_url": url,
                "http_status": response.status_code,
                "message": f"本地 LLM 服务可连通（{url} -> HTTP {response.status_code}）。",
            }
        except requests.RequestException as exc:
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "configured": True,
        "reachable": False,
        "status": "service_unreachable",
        "probe_url": candidate_probe_urls(value)[0] if candidate_probe_urls(value) else value,
        "errors": errors,
        "message": "本地 LLM 服务不可达，请确认服务进程、地址和端口。",
    }


def paper_status(session_id: str, paper_id: str) -> dict[str, Any]:
    session, _status_payload, detail_payload, _report_md = impact_core.load_status(session_id)
    paper_map = {item.get("id"): item for item in session.get("papers", [])}
    detail_map = {item.get("id"): item for item in detail_payload.get("papers", [])}
    raw_item = paper_map.get(paper_id)
    detail_item = detail_map.get(paper_id)
    if raw_item is None or detail_item is None:
        raise ValueError(f"未找到论文: {paper_id}")

    download_probe = raw_item.get("download_probe", {}) or {}
    analysis_result = raw_item.get("analysis_result", {}) or {}
    analysis_reason = detail_item.get("analysis_reason") or {}

    blockers = []
    if download_probe.get("status") != "local_available":
        blockers.append("pdf_missing")
    if analysis_result.get("status") == "context_only":
        blockers.append("context_only")

    return {
        "session_id": session_id,
        "paper_id": paper_id,
        "title": raw_item.get("title", ""),
        "download_status": download_probe.get("status"),
        "local_file_path": download_probe.get("local_file_path"),
        "analysis_status": analysis_result.get("status"),
        "analysis_reason": analysis_reason,
        "blockers": blockers,
    }


def overall_summary(env: dict[str, Any], service: dict[str, Any], paper: Optional[dict[str, Any]]) -> dict[str, Any]:
    blockers = []
    if env.get("missing_keys"):
        blockers.append("配置缺失")
    if service.get("status") == "service_unreachable":
        blockers.append("服务不可达")
    if paper:
        if "pdf_missing" in paper.get("blockers", []):
            blockers.append("PDF 缺失")
        if "context_only" in paper.get("blockers", []):
            blockers.append("只能 context_only")

    return {
        "ok": not blockers,
        "blockers": blockers,
    }


def main():
    parser = argparse.ArgumentParser(description="Check whether fulltext analysis is minimally ready.")
    parser.add_argument("--session-id", default="", help="Optional session id for paper-level readiness inspection.")
    parser.add_argument("--paper-id", default="", help="Optional paper id for paper-level readiness inspection.")
    args = parser.parse_args()

    env = env_status()
    local_llm_url = os.getenv("ACADEMIC_IMPACT_LOCAL_LLM_URL", "")
    service = service_status(local_llm_url)
    paper = None
    if args.session_id and args.paper_id:
        paper = paper_status(args.session_id, args.paper_id.strip().upper())

    payload = {
        "env": env,
        "service": service,
        "paper": paper,
    }
    payload["summary"] = overall_summary(env, service, paper)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
