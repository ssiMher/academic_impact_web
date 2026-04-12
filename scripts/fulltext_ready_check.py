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


VALID_ANALYSIS_MODES = {"single_model", "legacy_two_stage"}


def is_deepseek_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return "deepseek.com" in (parsed.netloc or "").lower()


def is_dashscope_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return "dashscope.aliyuncs.com" in (parsed.netloc or "").lower()


def normalized_analysis_mode() -> str:
    return (os.getenv("ACADEMIC_IMPACT_ANALYSIS_MODE") or "single_model").strip() or "single_model"


def effective_llm_config() -> dict[str, Any]:
    load_project_env(ROOT)
    mode = normalized_analysis_mode()
    if mode == "legacy_two_stage":
        url = (os.getenv("ACADEMIC_IMPACT_LOCAL_LLM_URL") or "").strip()
        model = (os.getenv("ACADEMIC_IMPACT_LOCAL_MODEL") or "").strip()
        api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
        url_source = "ACADEMIC_IMPACT_LOCAL_LLM_URL" if url else ""
        model_source = "ACADEMIC_IMPACT_LOCAL_MODEL" if model else ""
        api_key_source = "DEEPSEEK_API_KEY" if api_key else ""
        api_key_required = True
    else:
        url = (os.getenv("ACADEMIC_IMPACT_LLM_URL") or "").strip()
        url_source = "ACADEMIC_IMPACT_LLM_URL" if url else ""
        if not url:
            url = (os.getenv("ACADEMIC_IMPACT_LOCAL_LLM_URL") or "").strip()
            url_source = "ACADEMIC_IMPACT_LOCAL_LLM_URL" if url else ""

        model = (os.getenv("ACADEMIC_IMPACT_LLM_MODEL") or "").strip()
        model_source = "ACADEMIC_IMPACT_LLM_MODEL" if model else ""
        if not model:
            model = (os.getenv("ACADEMIC_IMPACT_LOCAL_MODEL") or "").strip()
            model_source = "ACADEMIC_IMPACT_LOCAL_MODEL" if model else ""

        api_key = (os.getenv("ACADEMIC_IMPACT_LLM_API_KEY") or "").strip()
        api_key_source = "ACADEMIC_IMPACT_LLM_API_KEY" if api_key else ""
        if not api_key and is_deepseek_url(url):
            api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
            api_key_source = "DEEPSEEK_API_KEY" if api_key else ""
        api_key_required = is_deepseek_url(url) or is_dashscope_url(url)
    return {
        "analysis_mode": mode,
        "analysis_mode_valid": mode in VALID_ANALYSIS_MODES,
        "url": url,
        "url_source": url_source,
        "model": model,
        "model_source": model_source,
        "api_key_configured": bool(api_key),
        "api_key_source": api_key_source,
        "api_key_required": api_key_required,
    }


def env_status() -> dict[str, Any]:
    config = effective_llm_config()
    keys = [
        "ACADEMIC_IMPACT_LLM_URL",
        "ACADEMIC_IMPACT_LLM_MODEL",
        "ACADEMIC_IMPACT_LLM_API_KEY",
        "ACADEMIC_IMPACT_ANALYSIS_MODE",
        "ACADEMIC_IMPACT_LOCAL_LLM_URL",
        "ACADEMIC_IMPACT_LOCAL_MODEL",
        "DEEPSEEK_API_KEY",
    ]
    values = {}
    missing = []
    for key in keys:
        raw = (os.getenv(key) or "").strip()
        configured = bool(raw)
        values[key] = {"configured": configured}
        if configured and key in {"ACADEMIC_IMPACT_LLM_URL", "ACADEMIC_IMPACT_LOCAL_LLM_URL"}:
            values[key]["value"] = raw
        elif configured and key in {"ACADEMIC_IMPACT_LLM_MODEL", "ACADEMIC_IMPACT_LOCAL_MODEL", "ACADEMIC_IMPACT_ANALYSIS_MODE"}:
            values[key]["value"] = raw

    if not config["analysis_mode_valid"]:
        missing.append("ACADEMIC_IMPACT_ANALYSIS_MODE")
    elif config["analysis_mode"] == "legacy_two_stage":
        if not config["url"]:
            missing.append("ACADEMIC_IMPACT_LOCAL_LLM_URL")
        if not config["model"]:
            missing.append("ACADEMIC_IMPACT_LOCAL_MODEL")
        if not config["api_key_configured"]:
            missing.append("DEEPSEEK_API_KEY")
    else:
        if not config["url"]:
            missing.append("ACADEMIC_IMPACT_LLM_URL")
        if not config["model"]:
            missing.append("ACADEMIC_IMPACT_LLM_MODEL")
        if config["api_key_required"] and not config["api_key_configured"]:
            missing.append("ACADEMIC_IMPACT_LLM_API_KEY")

    return {"items": values, "missing_keys": missing, "effective": config}


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
            "message": "未配置有效 LLM URL，未执行服务连通性检查。",
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
                "message": f"LLM 服务可连通（{url} -> HTTP {response.status_code}）。",
            }
        except requests.RequestException as exc:
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "configured": True,
        "reachable": False,
        "status": "service_unreachable",
        "probe_url": candidate_probe_urls(value)[0] if candidate_probe_urls(value) else value,
        "errors": errors,
        "message": "LLM 服务不可达，请确认服务进程、地址、端口和网络。",
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
    service = service_status((env.get("effective") or {}).get("url", ""))
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
