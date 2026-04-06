# Academic Impact Web

把旧的 OpenClaw 学术影响力分析项目收缩成一个传统 Web 应用：

- 前台是按钮和状态页
- 后台复用已经验证过的 Python 能力层
- 不再把主链路强依赖在 agent、飞书插件或运行时补丁上
- **本项目不依赖 OpenClaw 运行时，也不依赖 `~/.openclaw` 目录；仅复用仓库内保留下来的历史 Python 脚本能力层**

## 当前目录

```text
academic_impact_web/
├── app/                # FastAPI + 模板页面
├── data/
│   ├── downloads/      # 下载的 PDF
│   ├── runs/           # 分析中间产物
│   └── sessions/       # discover / download / analyze 的会话数据
├── docs/
│   └── legacy/         # 从旧项目拷来的交接文档
├── skills/             # 从旧项目提取的可复用 Python 核心
├── requirements.txt
└── README.md
```

## 复用来源

当前主要复用了这些旧脚本：

- `skills/academic_impact_analyzer/impact_cli.py`
- `skills/academic_impact_analyzer/run_pipeline.py`
- `skills/academic_impact_analyzer/fetch_contexts.py`
- `skills/list_all_citations/list_papers.py`
- `skills/download_paper_pdf/download_pdf.py`
- `skills/extract_pdf_text/extract_text.py`
- `skills/analyze_fulltext_citation/find_candidate_spans.py`
- `skills/analyze_fulltext_citation/analyze_fulltext.py`

## 启动 Web

建议先建虚拟环境：

```bash
cd ~/projects/academic_impact_web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后打开：

- `http://127.0.0.1:8000`

## 项目内环境配置

全文分析相关配置统一走**项目内环境变量**，不再默认回退到 `~/.openclaw/.env`。

先复制示例文件：

```bash
cd ~/projects/academic_impact_web
cp .env.example .env
```

最小配置项：

```bash
DEEPSEEK_API_KEY=...
ACADEMIC_IMPACT_LOCAL_LLM_URL=http://127.0.0.1:8002/v1/chat/completions
ACADEMIC_IMPACT_LOCAL_MODEL=Qwen3.5-27B-Q4_K_M.gguf
```

这 3 个值都需要人工确认/填写：

- `DEEPSEEK_API_KEY`：必须手工填入真实 key
- `ACADEMIC_IMPACT_LOCAL_LLM_URL`：必须填成你本地实际可访问的 OpenAI-compatible 服务地址
- `ACADEMIC_IMPACT_LOCAL_MODEL`：必须填成该服务实际加载的模型名

说明：

- `DEEPSEEK_API_KEY`：用于 JSON 整理阶段
- `ACADEMIC_IMPACT_LOCAL_LLM_URL`：本地全文语义分析服务地址
- `ACADEMIC_IMPACT_LOCAL_MODEL`：本地模型名

如果未配置本地 LLM 服务或拿不到 PDF，分析会退化为 `context_only`，并在页面与导出中注明原因。

## 让 fulltext analysis 真正可用

在项目根目录配置好 `.env` 后，还需要一个**可访问的 OpenAI-compatible LLM 服务**。主 Quick Start 只保留连通性要求，具体服务部署/启动命令统一放到 [`docs/ops/fulltext-llm.md`](docs/ops/fulltext-llm.md)。

准备好后，可先运行最小自检：

```bash
cd ~/projects/academic_impact_web
make fulltext-check
```

如果还想结合某个 session / paper 一起检查：

```bash
make fulltext-check \
  FULLTEXT_CHECK_SESSION_ID=20260406_194205_attention_is_all_you_need \
  FULLTEXT_CHECK_PAPER_ID=P002
```

自检会明确区分：

- 配置缺失
- 服务不可达
- PDF 缺失
- 只能 context_only

## 当前 MVP 按钮

- `Discover`
- `Refresh Probe`
- `Download Selected`
- `Analyze Selected`

## Legacy / 调试入口（非主流程）

以下入口仅用于调试或兼容历史能力层，不属于当前推荐主路径：

```bash
cd ~/projects/academic_impact_web
python3 skills/academic_impact_analyzer/impact_cli.py capabilities
python3 skills/academic_impact_analyzer/impact_cli.py discover "Attention Is All You Need" --limit 5
python3 skills/academic_impact_analyzer/impact_cli.py feishu-card <session_dir>
```

说明：

- Web 页面 + 项目内 `.env` 才是当前主流程
- `feishu-card` / card-style 输出仅作为 legacy surface 保留
- `discover` 如果碰到上游限流，仍然可能慢；当前仓库保留这些 CLI 主要是为了调试能力层

## 用 OMX 接手这个项目

第一次在这个项目里启用 OMX：

```bash
cd ~/projects/academic_impact_web
omx setup --scope project
omx
```

进入 `omx` 后，推荐先用这些提示词：

```text
先阅读 README.md、app/main.py、app/services/impact_core.py 和 skills/ 下的核心脚本。
告诉我这个项目当前的分层结构、最脆弱的外部依赖，以及下一步最应该先补的 3 个点。
```

```text
$plan "为 academic_impact_web 制定一个 3 天迭代计划，目标是把 discover / refresh / download / analyze 做成稳定的 Web 工作流，并继续收口历史遗留依赖"
```

```text
请检查 skills/list_all_citations/list_papers.py、skills/download_paper_pdf/download_pdf.py 和 skills/analyze_fulltext_citation/analyze_fulltext.py，列出最可能导致 Web 版不稳定的外部依赖和兜底方案。
```

## 旧资料

旧项目接口手册在：

- `docs/legacy/学术影响力分析项目接口手册v2.md`

它适合拿来理解能力来源，但里面仍保留大量 OpenClaw / 飞书 / 旧运行时背景信息。当前仓库的运行方式以本项目自身配置为准，不再要求 OpenClaw runtime。
