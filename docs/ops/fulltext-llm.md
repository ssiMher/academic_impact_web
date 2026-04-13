# Fulltext LLM 运维附录

本项目的 fulltext analysis 需要一套**可访问的 OpenAI-compatible LLM 服务**。

主 README 只保留以下要求：

- 项目内 `.env` 已配置
- `ACADEMIC_IMPACT_LLM_URL` 可访问
- `ACADEMIC_IMPACT_LLM_MODEL` 与服务实际暴露模型名一致

具体服务器部署、启动、重启与端口管理命令，统一维护在这一层运维附录里，而不放进主 Quick Start。

## 当前可用服务配置

### 服务器启动命令

```bash
CUDA_VISIBLE_DEVICES=2 /data1/ds/llama.cpp/build/bin/llama-server \
  -m /data1/ds/models/qwen35_27b_gguf/Qwen3.5-27B-Q4_K_M.gguf \
  --host 0.0.0.0 \
  --port 8002 \
  -c 32768 \
  -np 1 \
  -b 1024 \
  -ub 512 \
  -fa on \
  -ngl 999
```

### 模型文件路径

```bash
/data1/ds/models/qwen35_27b_gguf/Qwen3.5-27B-Q4_K_M.gguf
```

### 端口

```bash
8002
```

## 服务检查命令

### health 检查

```bash
curl http://114.212.82.168:8002/health
```

预期返回：

```json
{"status":"ok"}
```

### models 检查

```bash
curl http://114.212.82.168:8002/v1/models
```

预期至少能看到：

```json
{
  "data": [
    {
      "id": "Qwen3.5-27B-Q4_K_M.gguf"
    }
  ]
}
```

## 项目 `.env` 应填写的值

项目根目录 `.env` 中至少应包含：

```bash
ACADEMIC_IMPACT_ANALYSIS_MODE=single_model
ACADEMIC_IMPACT_LLM_URL=http://114.212.82.168:8002/v1/chat/completions
ACADEMIC_IMPACT_LLM_MODEL=Qwen3.5-27B-Q4_K_M.gguf
ACADEMIC_IMPACT_LLM_API_KEY=
ACADEMIC_IMPACT_LLM_DISABLE_THINKING=true
ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS=90000
```

说明：

- `ACADEMIC_IMPACT_ANALYSIS_MODE` 默认是 `single_model`，由一个 OpenAI-compatible 模型直接完成引用语义判断并输出结构化 JSON
- `ACADEMIC_IMPACT_LLM_URL` 应指向 **OpenAI-compatible chat completions** 地址
- `ACADEMIC_IMPACT_LLM_MODEL` 必须与 `/v1/models` 暴露出来的模型名一致
- `ACADEMIC_IMPACT_LLM_API_KEY` 本地无鉴权服务可留空；DeepSeek、DashScope/Qwen 等 API 服务需填写真实 key
- `ACADEMIC_IMPACT_LLM_DISABLE_THINKING` 默认开启，会向支持的 llama.cpp/Qwen 服务传入 `chat_template_kwargs.enable_thinking=false`
- `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS` 只影响 `fulltext_direct` 深度模式，控制单篇全文直读时送入模型的字符上限，默认 `90000`
- 旧变量 `ACADEMIC_IMPACT_LOCAL_LLM_URL` / `ACADEMIC_IMPACT_LOCAL_MODEL` 仍作为兼容 fallback 保留，不建议新部署继续使用

## 分析范围

默认 `candidate_spans` 模式会先筛选 top-k 候选段落，再送入模型，适合批量分析。

如果需要让模型直接通读单篇引用论文全文，可使用 `fulltext_direct`：

```bash
python3 skills/academic_impact_analyzer/impact_cli.py analyze <session_dir> \
  --ids P001 \
  --analysis-scope fulltext_direct
```

Web 页面也提供 `analysis scope` 下拉框。`fulltext_direct` 仍按 citing paper 逐篇请求模型，不会把多篇论文合并进同一个上下文。

如果需要临时回退旧双阶段链路：

```bash
ACADEMIC_IMPACT_ANALYSIS_MODE=legacy_two_stage
ACADEMIC_IMPACT_LOCAL_LLM_URL=http://114.212.82.168:8002/v1/chat/completions
ACADEMIC_IMPACT_LOCAL_MODEL=Qwen3.5-27B-Q4_K_M.gguf
DEEPSEEK_API_KEY=...
```

## 项目侧最小自检

```bash
cd ~/projects/academic_impact_web
make fulltext-check
```

如果要结合某个具体样本一起检查：

```bash
make fulltext-check \
  FULLTEXT_CHECK_SESSION_ID=20260406_194205_attention_is_all_you_need \
  FULLTEXT_CHECK_PAPER_ID=P002
```

## 常见失败

### 1. 服务不可达

表现：

- `fulltext-check` 返回 `服务不可达`
- `/health` 或 `/v1/models` 访问失败

优先检查：

- 服务进程是否真的在跑
- 服务器 IP / 端口是否填对
- 本机到远端 8002 端口是否可达

### 2. 模型名不匹配

表现：

- `.env` 中的 `ACADEMIC_IMPACT_LLM_MODEL` 与 `/v1/models` 返回值不同
- 请求虽然发到服务，但模型选择失败或返回异常

优先检查：

- `/v1/models` 的实际 `id`
- `.env` 中的模型名是否完全一致

### 3. PDF 缺失

表现：

- `download_status != local_available`
- 分析无法进入真正 fulltext 分支

优先处理：

- attach 本地 PDF
- 或重新获取可用 PDF

### 4. 只能 `context_only`

表现：

- `analysis_status = context_only`
- 页面/导出里出现：
  - `未获得 PDF`
  - `仅 citation context`
  - `未经全文验证`

含义：

- citation context fallback 跑通了
- 但还没有进入真正全文分析

## 运行顺序建议

推荐按下面顺序确认：

1. `/health` 可达
2. `/v1/models` 可达且模型名正确
3. 项目 `.env` 已写对
4. `make fulltext-check` 无“配置缺失 / 服务不可达”
5. 给目标 citing paper 提供 PDF
6. 再跑真实 fulltext analyze
