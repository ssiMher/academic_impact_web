import sys
import json
import requests
import os
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_env import get_project_env, load_project_env

load_project_env(ROOT)

DEFAULT_LLM_URL = "http://127.0.0.1:8002/v1/chat/completions"
DEFAULT_LLM_MODEL = "Qwen3.5-27B-Q4_K_M.gguf"

# Default path: a single configurable OpenAI-compatible chat completions model
# directly returns the existing structured JSON schema. Legacy two-stage mode is
# kept as a rollback path via ACADEMIC_IMPACT_ANALYSIS_MODE.
ANALYSIS_MODE = (
    get_project_env("ACADEMIC_IMPACT_ANALYSIS_MODE", "single_model", project_root=ROOT)
    or "single_model"
).strip()
LLM_URL = (
    get_project_env("ACADEMIC_IMPACT_LLM_URL", "", project_root=ROOT)
    or get_project_env("ACADEMIC_IMPACT_LOCAL_LLM_URL", DEFAULT_LLM_URL, project_root=ROOT)
    or DEFAULT_LLM_URL
)
LLM_MODEL = (
    get_project_env("ACADEMIC_IMPACT_LLM_MODEL", "", project_root=ROOT)
    or get_project_env("ACADEMIC_IMPACT_LOCAL_MODEL", DEFAULT_LLM_MODEL, project_root=ROOT)
    or DEFAULT_LLM_MODEL
)
LLM_DISABLE_THINKING = (
    get_project_env("ACADEMIC_IMPACT_LLM_DISABLE_THINKING", "true", project_root=ROOT)
    or "true"
).strip().lower() not in {"0", "false", "no", "off"}

# Legacy local semantic-analysis stage defaults.
LOCAL_VLLM_URL = get_project_env(
    "ACADEMIC_IMPACT_LOCAL_LLM_URL",
    DEFAULT_LLM_URL,
    project_root=ROOT,
)
LOCAL_MODEL = get_project_env(
    "ACADEMIC_IMPACT_LOCAL_MODEL",
    DEFAULT_LLM_MODEL,
    project_root=ROOT,
)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
LOCAL_CONTEXT_WINDOW_TOKENS = 8192
MAX_LOCAL_SPANS = 4
MAX_CONTEXT_WINDOW_CHARS_PER_SPAN = 1800
MAX_RAW_TEXT_CHARS_PER_SPAN = 1200
MAX_TOTAL_PROMPT_CHARS = 9000
try:
    MAX_FULLTEXT_DIRECT_CHARS = int(
        get_project_env("ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS", "90000", project_root=ROOT)
        or "90000"
    )
except (TypeError, ValueError):
    MAX_FULLTEXT_DIRECT_CHARS = 90000
VALID_ANALYSIS_SCOPES = {"candidate_spans", "fulltext_direct"}
VALID_EVIDENCE_LABELS = {
    "positive_evaluation",
    "sota_evaluation",
    "first_or_pioneering",
    "representative_work",
    "large_context",
    "detailed_comparison",
    "baseline",
    "comparison",
    "method_foundation",
    "method_extension",
    "theory_foundation",
    "sustained_followup",
    "important_person",
    "review_comment_praise",
    "survey_or_related_work",
    "negative_or_limitation",
}

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

额外判断规则：
1. 若只是组引用（如 [9,13,2]）或“相关工作之一”的并列背景综述，通常应判为 keep=否，且更接近 grouped_literature_mention，而不是 explicit_citation。
2. 若只是弱关键词命中、泛泛提到 low-rank / attention / adaptation 等术语，但没有明确把目标论文当作方法、基线、比较对象或扩展对象，也应判为 keep=否。
3. 表格/列表中的基线行只有在该行明确点名目标方法或编号（例如 “LoRA [9]”）时，才能视为 comparison/baseline 证据；若片段本身未明确出现目标方法/编号，不要因为附近上下文或表题而误判为 keep=是。
4. 如果提供目标引用编号，评价词必须和目标编号/标题/别名处在同一句、同一子句或明确承接关系中；不能把其他编号或邻近句子的正向评价归因给目标论文。
"""

SINGLE_MODEL_SYSTEM_PROMPT = """你是一个严格的论文引用语义分析器。
你的任务是根据候选段落或全文内容判断其中哪些位置真正引用了目标论文，并直接输出严格合法的 JSON。

只输出 JSON，不要输出解释、推理过程、Markdown、代码块或任何额外文本。
如果模型支持 thinking / reasoner 模式，必须关闭 thinking。不要输出 <think> 标签或任何思考通道内容。
最终答案的第一个字符必须是 {，最后一个字符必须是 }。

JSON 格式必须严格为：
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
      "evidence_labels": ["positive_evaluation|sota_evaluation|first_or_pioneering|representative_work|large_context|detailed_comparison|baseline|comparison|method_foundation|method_extension|theory_foundation|sustained_followup|important_person|review_comment_praise|survey_or_related_work|negative_or_limitation"],
      "highlight_keywords": ["原文中最能支撑判断的关键词或短语"],
      "evidence_strength": "high|medium|low",
      "is_self_citation": false,
      "why_valuable": "中文一句话说明这条证据是否值得放入汇报",
      "function": "中文一句话总结",
      "reason": "中文解释",
      "confidence": 0.0,
      "mention_type": "explicit_citation|grouped_literature_mention|weak_body_mention"
    }
  ]
}

判断规则：
1. 只有候选段落明确把目标论文作为方法、基线、比较对象、扩展对象、应用对象或核心背景时，才允许 keep=true。
   先判断目标论文的主要贡献类型：架构、算法、机制、模型组件、工具、数据集、基准、理论或综述。
   如果引用论文在自己的方法、模型、实验设置、消融、基线或数据处理中采用、复现、改造、配置或对比了目标论文的核心贡献，且正文或引用编号能对应到目标论文，应判为 keep=true；aspect 根据用途选择 method/baseline/comparison/extension/application。
   例：目标论文若是 Transformer 类架构论文，引用论文自己的模型采用 Transformer encoder、self-attention、multi-head attention、feed-forward network、positional encoding 等被归因于目标论文的组件，通常属于 method。
   如果只是介绍目标论文提出了某类架构/机制/概念的来源或领域背景，而不是引用论文自己的方法组件，应判为 keep=true 且 aspect=background。
2. 若只是组引用（如 [9,13,2]）或“相关工作之一”的并列背景综述，通常 keep=false，mention_type=grouped_literature_mention。
3. 若只是弱关键词命中、泛泛提到 low-rank / attention / adaptation 等术语，但没有明确把目标论文当作方法、基线、比较对象或扩展对象，keep=false，mention_type=weak_body_mention。
4. 表格/列表中的基线行只有在 citation_text 内明确出现目标方法名或对应编号时，才允许 keep=true；否则优先 keep=false。
5. 参考文献列表 / References / Bibliography / Works Cited 中的目标论文条目不算语义引用；如果唯一证据来自参考文献列表，findings 必须是空数组。
6. 如果没有找到明确引用，findings 必须是空数组。
7. confidence 必须是 0 到 1 之间的小数。
8. 所有 findings 都必须包含 page 和 span_index。fulltext_direct 模式下 span_index 可表示该页内第几个命中片段，从 1 开始。
9. evidence_labels 用于标注证据价值，可多选：
   - positive_evaluation：原文明确正向评价目标论文或其方法。
   - sota_evaluation：原文明确称目标工作 state-of-the-art / SOTA / best / advanced / leading / superior 或最先进。
   - first_or_pioneering：原文称目标论文 first、pioneering、seminal、首次、开创性等。
   - representative_work：原文把目标论文作为 representative / canonical / unique / only example / 代表性工作。
   - large_context：原文对目标论文有大篇幅解释，而不是一句话带过。
   - detailed_comparison：引用论文在实验、评估、表格、系统讨论中与目标论文做 detailed comparison；比泛泛 comparison 更强。
   - baseline：引用论文把目标论文作为 baseline。
   - comparison：旧标签兼容；引用论文与目标论文做实验/性能/方法对比，但优先使用 detailed_comparison 表示可汇报的详细对比。
   - method_foundation：引用论文采用、复现或基于目标论文方法。
   - method_extension：引用论文扩展、改造、适配或泛化目标论文方法。
   - theory_foundation：引用论文把目标论文作为理论、定理、证明或分析基础。
   - sustained_followup：同一作者/团队在多篇后续工作中持续引用目标论文；只在上下文能支撑时使用。
   - important_person：引用作者/团队有 Fellow、院士、重要奖项或顶尖机构标签时使用。
   - review_comment_praise：导入的审稿意见明确 praise / excellent / novel / highly rated 目标工作时使用。
   - survey_or_related_work：主要出现在相关工作或综述中。
   - negative_or_limitation：原文指出目标论文局限、失败或不足。
10. SOTA/representative/detailed comparison/template priority 判断：
   - SOTA 只在原文有 state-of-the-art、SOTA、best、advanced、leading、superior、最先进等明确措辞时标注。
   - representative_work 只在原文把目标工作作为代表性、典型、canonical、unique 或 only example 时标注。
   - detailed_comparison 需要实验/评估/表格/系统设计中的具体对比；related work 中一笔带过仍应使用 survey_or_related_work 或旧 comparison。
   - 如果用户或模板给出目标标签优先级，优先寻找这些 template priority 标签，但不要为了满足模板而捏造标签。
11. highlight_keywords 必须来自 citation_text 原文，优先选择 SOTA、representative、first、pioneering、baseline、compare、detailed comparison、outperform、based on、inspired by、extend 等能支撑标签的词。
12. why_valuable 要面向项目汇报，说明这条证据为什么有价值；普通弱引用可写“证据较弱，不建议用于汇报”。
13. 目标引用锚定规则：
   - 如果 user prompt 提供了目标引用编号/锚点或目标参考文献条目，必须先用它定位目标论文。
   - positive_evaluation、sota_evaluation、first_or_pioneering、baseline、comparison、method_foundation、method_extension 等强标签只能归因给同一句、同一子句或明确承接到目标编号/标题/别名的内容。
   - 不能把其他编号、其他作者或相邻句子的评价转嫁给目标论文。例如目标是 [16]，而 “high accuracy” 只连接到 [18]，则不得把 high accuracy 当作 [16] 的正向评价。
   - 目标编号只在 [15], [16], [17] 这类组引用里出现时，通常是 grouped_literature_mention；除非原文随后单独解释目标论文，否则不要输出强证据。
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
      "evidence_labels": ["positive_evaluation|sota_evaluation|first_or_pioneering|representative_work|large_context|detailed_comparison|baseline|comparison|method_foundation|method_extension|theory_foundation|sustained_followup|important_person|review_comment_praise|survey_or_related_work|negative_or_limitation"],
      "highlight_keywords": ["原文中最能支撑判断的关键词或短语"],
      "evidence_strength": "high|medium|low",
      "is_self_citation": false,
      "why_valuable": "中文一句话说明这条证据是否值得放入汇报",
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
6. 如果是组引用（如 [9,13,2]）且目标论文未被单独展开说明，优先设为 keep=false + grouped_literature_mention。
7. 如果是表格/列表基线行，只有在 citation_text 内明确出现目标方法名或对应编号时，才允许 keep=true；否则优先 keep=false。
8. 对 weak_body_mention，默认 keep=false；不要因为术语相似或邻近上下文而提升为 explicit_citation。
9. evidence_labels 允许的标签为：positive_evaluation, sota_evaluation, first_or_pioneering, representative_work, large_context, detailed_comparison, baseline, comparison, method_foundation, method_extension, theory_foundation, sustained_followup, important_person, review_comment_praise, survey_or_related_work, negative_or_limitation。
10. SOTA 只在原文明确写 state-of-the-art / SOTA / best / advanced / leading / superior / 最先进时使用；representative_work 只在原文表示 representative / canonical / unique / only example / 代表性时使用；detailed_comparison 需要实验、评估、表格或系统讨论中的具体对比。若模板给出 template priority，优先保留这些标签，但不得捏造。
11. 若提供目标引用编号/锚点，强标签只能归因给同一句、同一子句或明确承接到目标编号/标题/别名的内容；不能把其他编号或邻近句子的评价转嫁给目标论文。
"""

def load_deepseek_key():
    key = get_project_env("DEEPSEEK_API_KEY", "", project_root=ROOT)
    if key:
        return key
    return None


def normalized_analysis_mode() -> str:
    mode = (get_project_env("ACADEMIC_IMPACT_ANALYSIS_MODE", ANALYSIS_MODE, project_root=ROOT) or "").strip()
    return mode or "single_model"


def normalize_analysis_scope(value: Optional[str]) -> str:
    scope = (value or "candidate_spans").strip().lower().replace("-", "_")
    if scope in {"candidate", "candidate_span", "spans"}:
        return "candidate_spans"
    if scope in {"fulltext", "full_text", "direct", "fulltext_direct"}:
        return "fulltext_direct"
    return "candidate_spans"


def is_deepseek_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return "deepseek.com" in (parsed.netloc or "").lower()


def load_analysis_api_key(url: Optional[str] = None):
    key = get_project_env("ACADEMIC_IMPACT_LLM_API_KEY", "", project_root=ROOT)
    if key:
        return key
    if is_deepseek_url(url or LLM_URL):
        return load_deepseek_key()
    return None


def normalize_analysis_model_profile(value: Optional[str]) -> str:
    profile = (value or "default").strip().lower().replace("-", "_")
    aliases = {
        "": "default",
        "env": "default",
        "current": "default",
        "local_model": "local",
        "local_llm": "local",
        "本地模型": "local",
        "deepseek_chat": "deepseek",
    }
    profile = aliases.get(profile, profile)
    if profile not in {"default", "local", "deepseek"}:
        return "default"
    return profile


def resolve_analysis_model_profile(profile_name: Optional[str] = None):
    profile = normalize_analysis_model_profile(profile_name)
    if profile == "local":
        return {
            "profile": "local",
            "label": "本地模型",
            "mode": "single_model",
            "url": LOCAL_VLLM_URL or DEFAULT_LLM_URL,
            "model": LOCAL_MODEL or DEFAULT_LLM_MODEL,
            "api_key": load_analysis_api_key(LOCAL_VLLM_URL),
            "disable_thinking": LLM_DISABLE_THINKING,
        }
    if profile == "deepseek":
        return {
            "profile": "deepseek",
            "label": "DeepSeek",
            "mode": "single_model",
            "url": DEEPSEEK_URL,
            "model": DEEPSEEK_MODEL,
            "api_key": load_analysis_api_key(DEEPSEEK_URL),
            "disable_thinking": False,
        }
    mode = normalized_analysis_mode()
    return {
        "profile": "default",
        "label": "跟随环境配置",
        "mode": mode,
        "url": LLM_URL,
        "model": LLM_MODEL,
        "api_key": load_analysis_api_key(LLM_URL),
        "disable_thinking": LLM_DISABLE_THINKING,
    }


def generate_target_aliases(title: str):
    aliases = []
    seen = set()

    def add_alias(value: str):
        raw = (value or "").strip()
        if not raw:
            return
        compact_key = re.sub(r"[^a-z0-9]+", "", raw.lower())
        key = re.sub(r"\s+", " ", raw.lower())
        if len(compact_key) < 2 or key in seen:
            return
        seen.add(key)
        aliases.append(raw)

    raw_title = (title or "").strip()
    prefix = raw_title.split(":", 1)[0].strip() if ":" in raw_title else ""
    if prefix and len(prefix) <= 24 and len(prefix.split()) <= 4:
        add_alias(prefix)

    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", raw_title.lower())
    acronym_stop = {"a", "an", "the", "of", "and", "to", "in", "on", "for", "with", "is"}
    significant = [w for w in words if w and w not in acronym_stop]

    initials = []
    for word in significant:
        parts = [part for part in word.split("-") if part]
        if len(parts) > 1:
            initials.extend(part[0] for part in parts)
        elif parts:
            initials.append(parts[0][0])
    acronym = "".join(initials)
    if 2 <= len(acronym) <= 12:
        add_alias(acronym.upper())

    if significant and "-" in significant[0] and len(significant) >= 3:
        lead = "".join(part[0] for part in significant[0].split("-") if part).upper()
        tail = "".join(word[0] for word in significant[1:] if word).upper()
        if lead and tail:
            add_alias(f"{lead}-{tail}")
            add_alias(lead + tail)

    return aliases

def extract_local_analysis_output(response_json):
    return extract_chat_analysis_output(response_json, use_reasoning_fallback=True)


def extract_chat_analysis_output(response_json, *, use_reasoning_fallback: bool):
    choices = response_json.get("choices") or []
    first_choice = choices[0] if choices else {}
    message = first_choice.get("message") or {}
    content = (message.get("content") or "").strip()
    reasoning_content = (message.get("reasoning_content") or "").strip()

    analysis_text = content
    output_source = "content"
    if not analysis_text and reasoning_content and use_reasoning_fallback:
        analysis_text = reasoning_content
        output_source = "reasoning_content"
    elif not analysis_text and reasoning_content:
        output_source = "reasoning_content_ignored"
    elif not analysis_text:
        output_source = "blank"

    return {
        "analysis_text": analysis_text,
        "content": content,
        "reasoning_content": reasoning_content,
        "output_source": output_source,
        "finish_reason": first_choice.get("finish_reason"),
        "content_len": len(content),
        "reasoning_len": len(reasoning_content),
    }


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
    return extract_local_analysis_output(data)


def call_openai_compatible_chat(
    messages,
    *,
    url: str,
    model: str,
    api_key: Optional[str] = None,
    max_tokens=1200,
    response_format_json=True,
    use_reasoning_fallback=True,
    disable_thinking=False,
):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if response_format_json:
        req["response_format"] = {"type": "json_object"}
    if disable_thinking:
        req["chat_template_kwargs"] = {"enable_thinking": False}

    try:
        r = requests.post(url, headers=headers, json=req, timeout=240)
        r.raise_for_status()
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        if response is not None and response.status_code == 400 and (
            "response_format" in req or "chat_template_kwargs" in req
        ):
            fallback_req = dict(req)
            if "response_format" in fallback_req:
                fallback_req.pop("response_format", None)
                try:
                    r = requests.post(url, headers=headers, json=fallback_req, timeout=240)
                    r.raise_for_status()
                except requests.HTTPError as fallback_exc:
                    fallback_response = getattr(fallback_exc, "response", None)
                    if (
                        fallback_response is None
                        or fallback_response.status_code != 400
                        or "chat_template_kwargs" not in fallback_req
                    ):
                        raise
                    fallback_req.pop("chat_template_kwargs", None)
                    r = requests.post(url, headers=headers, json=fallback_req, timeout=240)
                    r.raise_for_status()
            else:
                fallback_req.pop("chat_template_kwargs", None)
                r = requests.post(url, headers=headers, json=fallback_req, timeout=240)
                r.raise_for_status()
        else:
            raise
    data = r.json()
    return extract_chat_analysis_output(data, use_reasoning_fallback=use_reasoning_fallback)


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
    response_text = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            response_text = str(getattr(response, "text", "") or "")
        except Exception:
            response_text = ""
    text = " ".join(part for part in [str(exc), response_text] if part)
    lowered = text.lower()
    if (
        "exceeds the available context size" in lowered
        or "available context size" in lowered
        or "maximum context length" in lowered
        or "context length exceeded" in lowered
    ):
        return (
            "context_length_exceeded",
            f"分析模型请求超过上下文上限（约 {LOCAL_CONTEXT_WINDOW_TOKENS} tokens），已命中长度限制，不是模型没启动。",
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
            "无法连接分析模型服务，请确认服务进程、地址、端口和 API key 配置是否正常。",
        )
    if "400 client error" in lowered or "status code 400" in lowered:
        return (
            "bad_request",
            "分析模型服务返回了 400，请检查请求长度、请求格式或模型配置。",
        )
    return (
        "request_failed",
        f"分析模型服务请求失败：{text}",
    )

def strip_thinking_blocks(text: str) -> str:
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    text = re.sub(r"(?is)<think>.*$", "", text)
    return text.strip()


def choose_json_candidate(values):
    if not values:
        return None
    for value in reversed(values):
        if isinstance(value, dict) and isinstance(value.get("findings"), list):
            return value
    for value in reversed(values):
        if isinstance(value, dict):
            return value
    return values[-1]


def parse_json_candidates(candidates):
    values = []
    for candidate in candidates:
        candidate = (candidate or "").strip()
        if not candidate:
            continue
        try:
            values.append(json.loads(candidate))
        except Exception:
            continue
    return choose_json_candidate(values)


def parse_embedded_json_values(text: str):
    decoder = json.JSONDecoder()
    values = []
    for match in re.finditer(r"[\{\[]", text):
        try:
            value, _end = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        values.append(value)
    return values


def try_parse_json(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    cleaned = strip_thinking_blocks(text)
    fenced_blocks = re.findall(r"(?is)```(?:json)?\s*(.*?)```", cleaned)
    parsed = parse_json_candidates(fenced_blocks)
    if parsed is not None:
        return parsed

    return choose_json_candidate(parse_embedded_json_values(cleaned))

def build_local_prompt(payload):
    spans = payload.get("candidate_spans", [])[:MAX_LOCAL_SPANS]
    target_aliases = payload.get("target_aliases") or generate_target_aliases(payload.get("target_title", ""))
    anchor_section = build_target_citation_anchor_section(payload, target_aliases)
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
目标论文别名/缩写：{", ".join(target_aliases) if target_aliases else "无"}
引用论文标题：{payload.get('citing_title', '')}
{anchor_section}

下面是从引用论文全文中筛出的候选段落：
{joined}

请根据这些段落判断是否真正引用了目标论文，并按指定格式输出自然语言分析。
如果 payload 或后续模板提供 template priority / 目标标签优先级，请优先寻找这些证据类型，但仍必须以原文为准。
"""


def unique_clean_strings(values):
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def payload_target_citation_indices(payload):
    indices = []
    for value in payload.get("target_citation_indices") or []:
        indices.append(value)
    for key in ["target_citation_index", "citation_index"]:
        if payload.get(key):
            indices.append(payload.get(key))
    for span in payload.get("candidate_spans") or []:
        if isinstance(span, dict) and span.get("citation_index"):
            indices.append(span.get("citation_index"))
    return unique_clean_strings(indices)


def build_target_citation_anchor_section(payload, target_aliases=None):
    target_aliases = target_aliases or payload.get("target_aliases") or generate_target_aliases(payload.get("target_title", ""))
    indices = payload_target_citation_indices(payload)
    reference_text = str(
        payload.get("target_reference_text")
        or (payload.get("citation_meta") or {}).get("reference_text")
        or ""
    ).strip()
    lines = [
        "",
        "目标引用锚定信息：",
        f"- 目标论文引用编号/锚点：{', '.join(indices) if indices else '未知；需要先从全文参考文献和目标标题/DOI自行定位'}",
        f"- 目标论文标题/别名：{', '.join(target_aliases) if target_aliases else payload.get('target_title', '')}",
    ]
    if reference_text:
        lines.append(f"- 目标论文参考文献条目：{reference_text[:900]}")
    lines.extend(
        [
            "- 判断 positive / SOTA / first / pioneering / baseline / comparison / based on 等标签时，评价词必须和目标论文标题、别名或目标引用编号处在同一句、同一子句或明确承接关系中。",
            "- 如果目标编号只出现在组引用（例如 [15], [16], [17]）中，而正向评价或方法描述实际连到其他编号（例如 [18]），不能把其他编号的评价归因给目标论文。",
            "- 如果不能确认评价词锚定到目标论文，保守输出 grouped_literature_mention 或 weak_body_mention，并在 reason 中说明目标只是并列/邻近提及。",
        ]
    )
    return "\n".join(lines)


def build_single_model_prompt(payload):
    target_aliases = payload.get("target_aliases") or generate_target_aliases(payload.get("target_title", ""))
    template_prompt_fragment = str(payload.get("template_prompt_fragment") or "").strip()
    if normalize_analysis_scope(payload.get("analysis_scope")) == "fulltext_direct":
        return build_fulltext_direct_prompt(payload, target_aliases)

    local_prompt = build_local_prompt(payload)
    template_section = f"\n\n{template_prompt_fragment}" if template_prompt_fragment else ""
    return f"""{local_prompt}
{template_section}

请不要输出自然语言报告。请直接输出符合 system 指定 schema 的严格 JSON。
如果你支持 thinking 模式，请使用 /no_think，并且不要输出任何推理过程。
最终答案必须只包含一个 JSON object。
目标论文别名/缩写再次确认：{", ".join(target_aliases) if target_aliases else "无"}
证据标签优先级：优先标注可用于汇报的 refined labels，包括 SOTA、representative work、detailed comparison、method extension、sustained follow-up、review comment praise；旧标签 comparison 仍兼容。
/no_think
"""


def normalize_fulltext_pages(payload):
    pages = payload.get("fulltext_pages")
    if not isinstance(pages, list):
        pages = []

    normalized = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        page_number = coerce_int(page.get("page")) or index
        normalized.append({"page": page_number, "text": text})

    if normalized:
        return normalized

    fulltext_text = str(payload.get("fulltext_text") or "").strip()
    if fulltext_text:
        return [{"page": 1, "text": fulltext_text}]
    return []


def build_fulltext_direct_prompt(payload, target_aliases=None):
    target_aliases = target_aliases or payload.get("target_aliases") or generate_target_aliases(payload.get("target_title", ""))
    template_prompt_fragment = str(payload.get("template_prompt_fragment") or "").strip()
    template_section = f"\n{template_prompt_fragment}" if template_prompt_fragment else ""
    anchor_section = build_target_citation_anchor_section(payload, target_aliases)
    pages = normalize_fulltext_pages(payload)
    chunks = []
    total_chars = 0
    truncated = False

    for page in pages:
        block = f"[Page {page['page']}]\n{page['text']}\n"
        if total_chars + len(block) > MAX_FULLTEXT_DIRECT_CHARS:
            remaining = MAX_FULLTEXT_DIRECT_CHARS - total_chars
            if remaining <= 0:
                truncated = True
                break
            chunks.append(block[:remaining])
            total_chars += remaining
            truncated = True
            break
        chunks.append(block)
        total_chars += len(block)

    joined = "\n\n".join(chunks)
    truncation_note = ""
    if truncated:
        truncation_note = (
            "\n\n[系统提示] 全文文本已按字符预算截断，"
            f"本次最多发送 {MAX_FULLTEXT_DIRECT_CHARS} 个字符。"
            "若需要更完整上下文，请调高 ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS "
            "并确认本地模型上下文足够。"
        )

    return f"""目标论文标题：{payload.get('target_title', '')}
目标论文年份：{payload.get('target_year', '')}
目标论文别名/缩写：{", ".join(target_aliases) if target_aliases else "无"}
引用论文标题：{payload.get('citing_title', '')}
分析范围：fulltext_direct
{anchor_section}

下面是引用论文全文文本，请直接通读全文判断目标论文是否被真正引用：
{joined}
{truncation_note}
{template_section}

请输出严格 JSON，不要输出自然语言报告。
判断时请特别注意：
1. References / Bibliography / Works Cited / 参考文献 区域中的目标论文条目只说明该论文在文末列表中出现，不构成语义引用 finding。
2. 只有正文、图表说明、实验设置、方法介绍或数据集说明中明确使用目标论文时，才输出 keep=true 的 finding。
   先判断目标论文的主要贡献类型：架构、算法、机制、模型组件、工具、数据集、基准、理论或综述。
   如果引用论文在自己的方法、模型、实验设置、消融、基线或数据处理中采用、复现、改造、配置或对比了目标论文的核心贡献，并且正文或引用编号能对应到目标论文，这属于语义 finding，不要降级为 mention_only。
   例如目标论文是 Transformer 类架构论文时，引用论文自己的模型采用 Transformer encoder、self-attention、multi-head attention、feed-forward network、positional encoding 等被归因于目标论文的组件，通常属于 method finding。
   如果只是说某个架构/机制/概念起源于目标论文，或把目标论文作为该领域基础文献，这属于 background finding。
3. 对每个 finding，page 使用原始页码，span_index 使用该页内第几个命中片段，从 1 开始。
4. 如果唯一命中来自参考文献列表，findings 必须是空数组。
5. 证据标签优先级：优先标注可用于汇报的 refined labels，包括 SOTA、representative work、detailed comparison、method extension、sustained follow-up、review comment praise；旧标签 comparison 仍兼容。SOTA、representative、detailed comparison 必须由原文明确支撑。
如果你支持 thinking 模式，请使用 /no_think，并且不要输出任何推理过程。
最终答案必须只包含一个 JSON object。
/no_think
"""


def build_deepseek_prompt(payload, raw_analysis):
    target_aliases = payload.get("target_aliases") or generate_target_aliases(payload.get("target_title", ""))
    anchor_section = build_target_citation_anchor_section(payload, target_aliases)
    return f"""请把下面这段自然语言分析整理成严格JSON。

目标论文标题：{payload.get('target_title', '')}
目标论文年份：{payload.get('target_year', '')}
目标论文别名/缩写：{", ".join(target_aliases) if target_aliases else "无"}
引用论文标题：{payload.get('citing_title', '')}
{anchor_section}

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


def normalize_finding_consistency(parsed):
    if not isinstance(parsed, dict):
        return parsed

    findings = parsed.get("findings")
    if not isinstance(findings, list):
        return parsed

    grouped_pattern = re.compile(r"\[\s*\d+\s*(?:[,，;；]\s*\d+\s*)+\]")

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if finding.get("keep") is False and finding.get("mention_type") == "explicit_citation":
            citation_text = finding.get("citation_text", "") or ""
            if grouped_pattern.search(citation_text):
                finding["mention_type"] = "grouped_literature_mention"
            else:
                finding["mention_type"] = "weak_body_mention"
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


def coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "是"}:
            return True
        if normalized in {"false", "no", "n", "0", "否"}:
            return False
    return default


def coerce_optional_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "是"}:
            return True
        if normalized in {"false", "no", "n", "0", "否"}:
            return False
    return None


def coerce_float(value, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, result))


def coerce_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_string_list(value):
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    result = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def normalize_model_finding(finding: dict, index: int):
    if not isinstance(finding, dict):
        raise ValueError(f"findings[{index}] 必须是对象。")

    page = coerce_int(finding.get("page"))
    span_index = coerce_int(finding.get("span_index"))
    if page is None or span_index is None:
        raise ValueError(f"findings[{index}] 缺少合法的 page 或 span_index。")

    keep = coerce_bool(finding.get("keep"), default=False)
    citation_text = str(finding.get("citation_text") or "").strip()
    aspect = str(finding.get("aspect") or ("other" if keep else "background")).strip()
    stance = str(finding.get("stance") or "neutral").strip()
    function = str(finding.get("function") or "").strip()
    reason = str(finding.get("reason") or "").strip()
    confidence = coerce_float(finding.get("confidence"), default=0.6 if keep else 0.35)

    valid_aspects = {"background", "method", "baseline", "comparison", "extension", "application", "other"}
    if aspect not in valid_aspects:
        aspect = "other" if keep else "background"

    valid_stances = {"positive", "neutral", "negative"}
    if stance not in valid_stances:
        stance = "neutral"

    mention_type = str(finding.get("mention_type") or "").strip()
    valid_mentions = {"explicit_citation", "grouped_literature_mention", "weak_body_mention"}
    if mention_type not in valid_mentions:
        mention_type = "explicit_citation" if keep else "weak_body_mention"
    if keep:
        mention_type = "explicit_citation"

    evidence_labels = [
        label for label in coerce_string_list(finding.get("evidence_labels"))
        if label in VALID_EVIDENCE_LABELS
    ]
    highlight_keywords = coerce_string_list(finding.get("highlight_keywords"))[:12]
    evidence_strength = str(finding.get("evidence_strength") or "").strip().lower()
    if evidence_strength not in {"high", "medium", "low"}:
        evidence_strength = ""

    return {
        "page": page,
        "span_index": span_index,
        "citation_text": citation_text,
        "keep": keep,
        "aspect": aspect,
        "stance": stance,
        "evidence_labels": evidence_labels,
        "highlight_keywords": highlight_keywords,
        "evidence_strength": evidence_strength,
        "is_self_citation": coerce_optional_bool(finding.get("is_self_citation")),
        "why_valuable": str(finding.get("why_valuable") or "").strip(),
        "function": function,
        "reason": reason,
        "confidence": confidence,
        "mention_type": mention_type,
    }


def finalize_parsed_result(payload, parsed):
    if not isinstance(parsed, dict):
        raise ValueError("模型输出 JSON 顶层必须是对象。")

    parsed.setdefault("ok", True)
    parsed.setdefault("citing_title", payload.get("citing_title", ""))
    findings = parsed.get("findings", [])
    if findings is None:
        parsed["findings"] = []
    elif not isinstance(findings, list):
        raise ValueError("模型输出 JSON 中的 findings 必须是数组。")
    else:
        parsed["findings"] = [
            normalize_model_finding(finding, index)
            for index, finding in enumerate(findings)
        ]

    parsed = maybe_add_weak_mention_findings(payload, parsed)
    parsed = normalize_finding_consistency(parsed)
    return parsed


def analyze_payload_single_model(payload):
    model_profile = resolve_analysis_model_profile(payload.get("analysis_model_profile"))
    analysis_scope = normalize_analysis_scope(payload.get("analysis_scope"))
    fulltext_pages = normalize_fulltext_pages(payload) if analysis_scope == "fulltext_direct" else []
    fulltext_chars = sum(len(page.get("text", "")) for page in fulltext_pages)

    if analysis_scope == "candidate_spans" and not payload.get("candidate_spans"):
        return {
            "ok": True,
            "citing_title": payload.get("citing_title", ""),
            "findings": [],
            "_debug": {
                "analysis_mode": "single_model",
                "analysis_scope": analysis_scope,
                "analysis_model_profile": model_profile["profile"],
                "analysis_model_label": model_profile["label"],
                "candidate_span_count": 0,
            },
        }

    if analysis_scope == "fulltext_direct" and not fulltext_pages:
        return {
            "ok": False,
            "citing_title": payload.get("citing_title", ""),
            "findings": [],
            "error": "fulltext_direct 模式缺少可分析的全文文本。",
            "error_type": "fulltext_direct_empty_text",
            "error_stage": "fulltext_direct_empty_text",
            "_debug": {
                "analysis_mode": "single_model",
                "analysis_scope": analysis_scope,
                "analysis_model_profile": model_profile["profile"],
                "analysis_model_label": model_profile["label"],
                "candidate_span_count": len(payload.get("candidate_spans", [])),
                "fulltext_page_count": 0,
                "fulltext_chars": 0,
            },
        }

    user_prompt = build_single_model_prompt(payload)
    debug = {
        "analysis_mode": "single_model",
        "analysis_scope": analysis_scope,
        "candidate_span_count": len(payload.get("candidate_spans", [])),
        "fulltext_page_count": len(fulltext_pages),
        "fulltext_chars": fulltext_chars,
        "prompt_chars": len(user_prompt),
        "analysis_model_profile": model_profile["profile"],
        "analysis_model_label": model_profile["label"],
        "llm_url": model_profile["url"],
        "llm_model": model_profile["model"],
        "output_source": None,
        "finish_reason": None,
        "content_len": 0,
        "reasoning_len": 0,
    }

    try:
        model_result = call_openai_compatible_chat(
            [
                {"role": "system", "content": SINGLE_MODEL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            url=model_profile["url"],
            model=model_profile["model"],
            api_key=model_profile["api_key"],
            max_tokens=4096,
            response_format_json=True,
            use_reasoning_fallback=False,
            disable_thinking=model_profile["disable_thinking"],
        )
    except requests.RequestException as exc:
        error_detail_type, error_message = classify_request_exception(exc)
        return {
            "ok": False,
            "error": error_message,
            "error_type": "single_model_request_failed",
            "error_stage": "single_model_request_failed",
            "error_detail_type": error_detail_type,
            "_debug": debug,
        }

    debug.update({
        "output_source": model_result.get("output_source"),
        "finish_reason": model_result.get("finish_reason"),
        "content_len": model_result.get("content_len", 0),
        "reasoning_len": model_result.get("reasoning_len", 0),
    })
    raw_json = model_result.get("analysis_text", "")
    raw_json_source = model_result.get("output_source")
    reasoning_content = model_result.get("reasoning_content", "")
    if not raw_json:
        debug["model_raw_preview"] = ""
        debug["reasoning_preview"] = reasoning_content[:800]
        error = "分析模型没有返回最终 JSON content，无法解析结构化 JSON。"
        if reasoning_content:
            error = (
                "分析模型只返回了 reasoning_content，没有返回最终 JSON content。"
                "请确认 thinking 已关闭，或模型输出预算足够生成最终答案。"
            )
        return {
            "ok": False,
            "error": error,
            "error_type": "blank_model_output",
            "error_stage": "blank_model_output",
            "_debug": debug,
        }

    parsed = try_parse_json(raw_json)
    if parsed is None:
        return {
            "ok": False,
            "error": "分析模型输出无法解析为 JSON",
            "error_type": "single_model_json_parse_failed",
            "error_stage": "single_model_json_parse_failed",
            "model_raw_preview": raw_json[:800],
            "model_raw_source": raw_json_source,
            "_debug": debug,
        }

    try:
        parsed = finalize_parsed_result(payload, parsed)
    except ValueError as exc:
        return {
            "ok": False,
            "error": f"分析模型输出 JSON schema 不合法：{exc}",
            "error_type": "single_model_schema_invalid",
            "error_stage": "single_model_schema_invalid",
            "model_raw_preview": raw_json[:800],
            "_debug": debug,
        }

    parsed["_debug"] = {
        **debug,
        "candidate_pages": sorted(list({s.get("page") for s in payload.get("candidate_spans", []) if isinstance(s, dict) and s.get("page") is not None})),
        "fulltext_pages": sorted(list({page.get("page") for page in fulltext_pages if page.get("page") is not None})),
        "model_raw_preview": raw_json[:500],
    }
    return parsed


def analyze_payload_legacy_two_stage(payload):
    api_key = load_deepseek_key()
    if not api_key:
        return {
            "ok": False,
            "error": "未找到 DEEPSEEK_API_KEY。请先 export，或写入项目根目录的 .env / .env.local",
            "error_type": "deepseek_request_failed",
            "error_stage": "deepseek_request_failed",
        }

    if not payload.get("candidate_spans"):
        return {
            "ok": True,
            "citing_title": payload.get("citing_title", ""),
            "findings": [],
            "_debug": {
                "analysis_mode": "legacy_two_stage",
                "candidate_span_count": 0
            }
        }

    local_user_prompt = build_local_prompt(payload)
    local_debug = {
        "candidate_span_count": len(payload.get("candidate_spans", [])),
        "prompt_chars": len(local_user_prompt),
        "output_source": None,
        "finish_reason": None,
        "content_len": 0,
        "reasoning_len": 0,
    }
    try:
        local_result = call_local_27b([
            {"role": "system", "content": LOCAL_SYSTEM_PROMPT},
            {"role": "user", "content": local_user_prompt}
        ], max_tokens=900)
    except requests.RequestException as exc:
        error_detail_type, error_message = classify_request_exception(exc)
        return {
            "ok": False,
            "error": error_message,
            "error_type": "local_model_request_failed",
            "error_stage": "local_model_request_failed",
            "error_detail_type": error_detail_type,
            "_debug": local_debug,
        }

    local_debug.update({
        "output_source": local_result.get("output_source"),
        "finish_reason": local_result.get("finish_reason"),
        "content_len": local_result.get("content_len", 0),
        "reasoning_len": local_result.get("reasoning_len", 0),
    })
    raw_analysis = local_result.get("analysis_text", "")

    if not raw_analysis:
        local_debug["local_analysis_preview"] = ""
        return {
            "ok": False,
            "error": "本地 27B 分析服务返回空输出，无法进入 JSON 整理阶段。",
            "error_type": "blank_model_output",
            "error_stage": "blank_model_output",
            "_debug": local_debug,
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
            "error_stage": "deepseek_request_failed",
            "_debug": {
                **local_debug,
                "local_analysis_preview": raw_analysis[:500],
            },
        }

    parsed = try_parse_json(raw_json)
    if parsed is None:
        return {
            "ok": False,
            "error": "DeepSeek 输出无法解析为 JSON",
            "error_type": "deepseek_json_parse_failed",
            "error_stage": "deepseek_json_parse_failed",
            "local_raw_analysis_preview": raw_analysis[:800],
            "deepseek_raw_preview": raw_json[:800]
        }

    try:
        parsed = finalize_parsed_result(payload, parsed)
    except ValueError as exc:
        return {
            "ok": False,
            "error": f"DeepSeek 输出 JSON schema 不合法：{exc}",
            "error_type": "deepseek_json_parse_failed",
            "error_stage": "deepseek_json_parse_failed",
            "local_raw_analysis_preview": raw_analysis[:800],
            "deepseek_raw_preview": raw_json[:800],
        }

    parsed["_debug"] = {
        "analysis_mode": "legacy_two_stage",
        **local_debug,
        "candidate_pages": sorted(list({s["page"] for s in payload.get("candidate_spans", [])})),
        "local_analysis_preview": raw_analysis[:500],
    }
    return parsed


def analyze_payload(payload):
    model_profile = resolve_analysis_model_profile(payload.get("analysis_model_profile"))
    mode = model_profile.get("mode") or normalized_analysis_mode()
    if mode == "legacy_two_stage":
        return analyze_payload_legacy_two_stage(payload)
    if mode != "single_model":
        return {
            "ok": False,
            "error": f"未知 ACADEMIC_IMPACT_ANALYSIS_MODE: {mode}",
            "error_type": "invalid_analysis_mode",
            "error_stage": "config",
        }
    return analyze_payload_single_model(payload)

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
