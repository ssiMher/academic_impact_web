import sys
import json
import requests
import os
from pathlib import Path
from typing import Tuple

# Local analysis model defaults to the llama.cpp OpenAI-compatible endpoint.
# These can be overridden via env vars when switching runtimes/models.
LOCAL_VLLM_URL = os.getenv(
    "ACADEMIC_IMPACT_LOCAL_LLM_URL",
    "http://114.212.82.168:8002/v1/chat/completions",
)
LOCAL_MODEL = os.getenv(
    "ACADEMIC_IMPACT_LOCAL_MODEL",
    "Qwen3.5-27B-Q4_K_M.gguf",
)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
LOCAL_CONTEXT_WINDOW_TOKENS = 8192
MAX_LOCAL_SPANS = 4
MAX_CONTEXT_WINDOW_CHARS_PER_SPAN = 1800
MAX_RAW_TEXT_CHARS_PER_SPAN = 1200
MAX_TOTAL_PROMPT_CHARS = 9000

LOCAL_SYSTEM_PROMPT = """你是一个论文引用语义分析助手。
你的任务是根据候选段落，判断其中哪些段落真正引用了目标论文，并给出自然语言分析。

不要输出JSON。
不要输出代码块。
不要输出Thinking Process。
直接输出简洁、清楚的中文分析。

请严格按下面格式输出：

引用论文标题：...
候选结论：
1. 页码：...
   段落编号：...
   是否应保留：是/否
   引用原文：...
   引用性质：background/method/baseline/comparison/extension/application/other
   引用态度：positive/neutral/negative
   分析说明：...
   置信度：0.xx

如果没有找到明确引用，请明确写“未找到明确引用”。
"""

DEEPSEEK_SYSTEM_PROMPT = """你是一个严格的JSON整理器。
你会把给定的自然语言分析整理成严格合法的JSON。

只输出JSON，不要输出解释、Thinking Process、Markdown、代码块或任何额外文本。

JSON格式必须严格为：
{
  "ok": true,
  "citing_title": "引用论文标题",
  "findings": [
    {
      "page": 1,
      "span_index": 1,
      "citation_text": "原文摘录",
      "keep": true,
      "aspect": "background|method|baseline|comparison|extension|application|other",
      "stance": "positive|neutral|negative",
      "function": "中文一句话总结",
      "reason": "中文解释",
      "confidence": 0.0,
      "mention_type": "explicit_citation|grouped_literature_mention|weak_body_mention"
    }
  ]
}

要求：
1. 如果原文写的是“是否应保留：是”，则 keep=true，否则 keep=false。
2. 如果未找到明确引用，则 findings 为空数组。
3. confidence 必须是 0 到 1 之间的小数。
4. 所有 findings 都必须包含 page 和 span_index。
5. 若只是正文中的组引用/弱提及，而不足以支撑强语义判断，可保留为 keep=false，并将 mention_type 设为 grouped_literature_mention 或 weak_body_mention。
"""

def load_deepseek_key():
    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        return key

    env_path = Path.home() / ".openclaw" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def call_local_27b(messages, max_tokens=900):
    req = {
        "model": LOCAL_MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens
    }
    r = requests.post(LOCAL_VLLM_URL, json=req, timeout=240)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]

def call_deepseek(messages, api_key, max_tokens=800):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    req = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}
    }
    r = requests.post(DEEPSEEK_URL, headers=headers, json=req, timeout=180)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def classify_request_exception(exc: Exception) -> Tuple[str, str]:
    text = str(exc)
    lowered = text.lower()
    if (
        "exceeds the available context size" in lowered
        or "available context size" in lowered
        or "maximum context length" in lowered
        or "context length exceeded" in lowered
    ):
        return (
            "context_length_exceeded",
            f"本地 27B 分析请求超过上下文上限（约 {LOCAL_CONTEXT_WINDOW_TOKENS} tokens），已命中长度限制，不是模型没启动。",
        )
    if (
        "connection refused" in lowered
        or "max retries exceeded" in lowered
        or "failed to establish a new connection" in lowered
        or "name or service not known" in lowered
        or "timed out" in lowered
    ):
        return (
            "service_unreachable",
            "无法连接本地 27B 分析服务，请确认服务进程和地址配置是否正常。",
        )
    if "400 client error" in lowered or "status code 400" in lowered:
        return (
            "bad_request",
            "本地 27B 分析服务返回了 400，请检查请求长度或请求格式。",
        )
    return (
        "request_failed",
        f"本地 27B 分析服务请求失败：{text}",
    )

def try_parse_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except:
            pass
    return None

def build_local_prompt(payload):
    spans = payload.get("candidate_spans", [])[:MAX_LOCAL_SPANS]
    chunks = []
    total_chars = 0
    for s in spans:
        context_window_text = s.get("context_window_text", "").strip()
        block = (
            f"[Page {s['page']} | Span {s['span_index']} | score={s.get('score')} | "
            f"type={s.get('match_type')} | evidence={s.get('evidence', [])} | "
            f"hits={s.get('keyword_hits', [])}]\n"
        )
        if context_window_text:
            block += "局部上下文如下：\n" + context_window_text[:MAX_CONTEXT_WINDOW_CHARS_PER_SPAN]
        else:
            block += s['text'][:MAX_RAW_TEXT_CHARS_PER_SPAN]

        if total_chars + len(block) > MAX_TOTAL_PROMPT_CHARS:
            remaining = MAX_TOTAL_PROMPT_CHARS - total_chars
            if remaining <= 0:
                break
            chunks.append(block[:remaining])
            total_chars += min(len(block), remaining)
            break

        chunks.append(block)
        total_chars += len(block)

    joined = "\n\n".join(chunks)

    return f"""目标论文标题：{payload.get('target_title', '')}
目标论文年份：{payload.get('target_year', '')}
引用论文标题：{payload.get('citing_title', '')}

下面是从引用论文全文中筛出的候选段落：
{joined}

请根据这些段落判断是否真正引用了目标论文，并按指定格式输出自然语言分析。
"""

def build_deepseek_prompt(payload, raw_analysis):
    return f"""请把下面这段自然语言分析整理成严格JSON。

目标论文标题：{payload.get('target_title', '')}
目标论文年份：{payload.get('target_year', '')}
引用论文标题：{payload.get('citing_title', '')}

自然语言分析如下：
{raw_analysis}
"""


def build_weak_mention_finding(span, mention_type: str):
    if mention_type == "grouped_literature_mention":
        function = "在背景综述式组引用中与多篇相关工作并列提及目标论文。"
        reason = "正文包含目标论文编号，但呈现为多篇文献并列引用，缺少更具体的方法比较或功能说明。"
    else:
        function = "正文中出现了与目标论文相关的弱提及。"
        reason = "正文存在编号或关键词弱命中，但不足以支撑更强的引用语义判断。"

    return {
        "page": span.get("page"),
        "span_index": span.get("span_index"),
        "citation_text": span.get("text", "")[:1200],
        "keep": False,
        "aspect": "background",
        "stance": "neutral",
        "function": function,
        "reason": reason,
        "confidence": 0.35,
        "mention_type": mention_type,
    }


def maybe_add_weak_mention_findings(payload, parsed):
    if not isinstance(parsed, dict):
        return parsed

    findings = parsed.get("findings")
    if not isinstance(findings, list) or findings:
        return parsed

    spans = payload.get("candidate_spans", [])
    if not spans:
        return parsed

    top_span = spans[0]
    match_type = top_span.get("match_type")
    if match_type == "citation_index_grouped":
        parsed["findings"] = [build_weak_mention_finding(top_span, "grouped_literature_mention")]
    elif match_type in {"citation_index_exact", "citation_index_neighbor"}:
        parsed["findings"] = [build_weak_mention_finding(top_span, "weak_body_mention")]
    return parsed


def load_payload(payload_arg: str):
    payload_arg = (payload_arg or "").strip()
    if not payload_arg:
        raise ValueError("payload_json参数为空")

    if payload_arg.startswith("@"):
        payload_path = Path(payload_arg[1:]).expanduser()
        return json.loads(payload_path.read_text(encoding="utf-8"))

    candidate_path = Path(payload_arg).expanduser()
    if candidate_path.exists() and candidate_path.is_file():
        return json.loads(candidate_path.read_text(encoding="utf-8"))

    return json.loads(payload_arg)


def analyze_payload(payload):
    api_key = load_deepseek_key()
    if not api_key:
        return {
            "ok": False,
            "error": "未找到 DEEPSEEK_API_KEY。请先 export，或写入 ~/.openclaw/.env"
        }

    if not payload.get("candidate_spans"):
        return {
            "ok": True,
            "citing_title": payload.get("citing_title", ""),
            "findings": [],
            "_debug": {
                "candidate_span_count": 0
            }
        }

    local_user_prompt = build_local_prompt(payload)
    try:
        raw_analysis = call_local_27b([
            {"role": "system", "content": LOCAL_SYSTEM_PROMPT},
            {"role": "user", "content": local_user_prompt}
        ], max_tokens=900)
    except requests.RequestException as exc:
        error_type, error_message = classify_request_exception(exc)
        return {
            "ok": False,
            "error": error_message,
            "error_type": error_type,
            "_debug": {
                "candidate_span_count": len(payload.get("candidate_spans", [])),
                "prompt_chars": len(local_user_prompt),
            },
        }

    deepseek_user_prompt = build_deepseek_prompt(payload, raw_analysis)
    try:
        raw_json = call_deepseek([
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {"role": "user", "content": deepseek_user_prompt}
        ], api_key=api_key, max_tokens=800)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": f"DeepSeek JSON 整理阶段请求失败：{exc}",
            "error_type": "deepseek_request_failed",
            "_debug": {
                "candidate_span_count": len(payload.get("candidate_spans", [])),
                "local_analysis_preview": raw_analysis[:500],
            },
        }

    parsed = try_parse_json(raw_json)
    if parsed is None:
        return {
            "ok": False,
            "error": "DeepSeek 输出无法解析为 JSON",
            "local_raw_analysis_preview": raw_analysis[:800],
            "deepseek_raw_preview": raw_json[:800]
        }

    parsed = maybe_add_weak_mention_findings(payload, parsed)

    parsed["_debug"] = {
        "candidate_span_count": len(payload.get("candidate_spans", [])),
        "candidate_pages": sorted(list({s["page"] for s in payload.get("candidate_spans", [])})),
        "local_analysis_preview": raw_analysis[:500],
        "prompt_chars": len(local_user_prompt),
    }
    return parsed

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "缺少payload_json参数"}, ensure_ascii=False, indent=2))
        return

    try:
        payload = load_payload(sys.argv[1])
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": f"payload_json 解析失败: {e}"
        }, ensure_ascii=False, indent=2))
        return

    print(json.dumps(analyze_payload(payload), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
