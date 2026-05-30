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

## 先看哪些文档

如果你是第一次接手这个仓库，推荐顺序：

1. [`README.md`](README.md)：启动、测试、环境变量
2. [`docs/architecture.md`](docs/architecture.md)：当前系统结构和主链路
3. [`docs/ops/scholar-impact.md`](docs/ops/scholar-impact.md)：学者影响力分析操作流程
4. [`docs/devlog.md`](docs/devlog.md)：近期关键改动和决策背景

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

建议优先使用 conda 环境：

```bash
cd ~/projects/academic_impact_web
conda create -n academic-impact-web python=3.10 -y
conda activate academic-impact-web
pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后打开：

- `http://127.0.0.1:8000`

## 运行测试

安装依赖后，在项目根目录运行统一测试入口：

```bash
cd ~/projects/academic_impact_web
pip install -r requirements.txt
make test
```

等价的原生命令是：

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -q
```

说明：

- 页面层测试会导入 FastAPI / Starlette / Jinja2，需先安装 `requirements.txt`。
- fulltext 相关单元测试只检查本地函数语义，不会用“跳过测试”掩盖服务或配置问题。
- 需要检查模型服务配置、PDF 可用性时，单独运行 `make fulltext-check`。

## 项目内环境配置

全文分析相关配置统一走**项目内环境变量**，不再默认回退到 `~/.openclaw/.env`。

先复制示例文件：

```bash
cd ~/projects/academic_impact_web
cp .env.example .env
```

最小配置项：

```bash
ACADEMIC_IMPACT_ANALYSIS_MODE=single_model
ACADEMIC_IMPACT_LLM_URL=http://127.0.0.1:8002/v1/chat/completions
ACADEMIC_IMPACT_LLM_MODEL=Qwen3.5-27B-Q4_K_M.gguf
ACADEMIC_IMPACT_LLM_API_KEY=
ACADEMIC_IMPACT_LLM_DISABLE_THINKING=true
ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS=90000
ACADEMIC_IMPACT_CITATION_SOURCE=auto
ACADEMIC_IMPACT_CONTEXTS_ENABLED=false
ELSEVIER_API_KEY=
ELSEVIER_INSTTOKEN=
```

这些值都需要人工确认/填写：

- `ACADEMIC_IMPACT_ANALYSIS_MODE`：默认 `single_model`，由一个模型直接完成语义判断并输出结构化 JSON
- `ACADEMIC_IMPACT_LLM_URL`：必须填成实际可访问的 OpenAI-compatible `/chat/completions` 地址
- `ACADEMIC_IMPACT_LLM_MODEL`：必须填成该服务实际加载/暴露的模型名
- `ACADEMIC_IMPACT_LLM_API_KEY`：本地无鉴权服务可留空；DeepSeek、DashScope/Qwen 等 API 服务需填真实 key
- `ACADEMIC_IMPACT_LLM_DISABLE_THINKING`：默认 `true`，会在支持的 llama.cpp/Qwen 服务上关闭 thinking，避免只返回 `reasoning_content` 而没有最终 JSON
- `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`：可选，`fulltext_direct` 深度模式一次送入模型的全文字符上限，默认 `90000`
- `ACADEMIC_IMPACT_CITATION_SOURCE`：可选，引用论文列表来源；`auto` 会先试 Semantic Scholar、失败后回退 OpenAlex，`openalex` 会直接使用 OpenAlex，`scopus` 会使用 Elsevier Scopus Search API
- `ACADEMIC_IMPACT_CONTEXTS_ENABLED`：可选，是否拉取 Semantic Scholar citation contexts；默认 `false`，因为 contexts 只是排序/快速置信度辅助，全文分析不依赖它
- `ELSEVIER_API_KEY`：可选，仅 `ACADEMIC_IMPACT_CITATION_SOURCE=scopus` 时需要；只放在服务端 `.env`，不要提交到 git 或写进前端
- `ELSEVIER_INSTTOKEN`：可选；如果学校订阅权限无法通过机构 IP 自动识别，Elsevier/学校可能会提供 Institutional Token
- `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS`：可选，本地论文库目录列表；使用系统路径分隔符连接多个目录（Linux/macOS 用 `:`，Windows 用 `;`）。学者影响力分析会在这些目录和 `ACADEMIC_IMPACT_DOWNLOAD_DIR` 中自动尝试匹配已有 PDF
- `ACADEMIC_IMPACT_PDF_INDEX_PATH`：可选，本地 PDF 轻量索引 JSON 路径。存在时，项目会优先查索引，再回退目录扫描

说明：

- `ACADEMIC_IMPACT_LLM_URL` 示例：
  - `http://127.0.0.1:8002/v1/chat/completions`
  - `https://api.deepseek.com/chat/completions`
  - `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- `ACADEMIC_IMPACT_LLM_MODEL` 示例：`Qwen3.5-27B-Q4_K_M.gguf`、`deepseek-chat`、`qwen-plus`
- 旧变量仍兼容：未设置 `ACADEMIC_IMPACT_LLM_URL` / `ACADEMIC_IMPACT_LLM_MODEL` 时，会读取 `ACADEMIC_IMPACT_LOCAL_LLM_URL` / `ACADEMIC_IMPACT_LOCAL_MODEL`
- 如果 URL 是 DeepSeek 且未设置 `ACADEMIC_IMPACT_LLM_API_KEY`，会兼容读取 `DEEPSEEK_API_KEY`
- 临时回退旧两段链路时，可设置 `ACADEMIC_IMPACT_ANALYSIS_MODE=legacy_two_stage`
- `ACADEMIC_IMPACT_DOWNLOAD_DIR`：推荐显式配置为你自己有写权限的 PDF 存储目录
- `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS` 示例：
  - Linux/macOS：`/data/papers:/data/archive_pdfs`
  - Windows：`D:\\papers;E:\\pdf_archive`
- `ACADEMIC_IMPACT_PDF_INDEX_PATH` 示例：
  - Linux/macOS：`/data/academic_impact/local_pdf_index.json`
  - Windows：`D:\\academic_impact\\local_pdf_index.json`

如果你的本地论文库比较大，建议先构建一次索引：

```bash
python3 scripts/build_local_pdf_index.py \
  --search-dir /data/papers \
  --search-dir /data/archive_pdfs \
  --index-path /data/academic_impact/local_pdf_index.json
```

之后在 `.env` 里配置：

```bash
ACADEMIC_IMPACT_PDF_INDEX_PATH=/data/academic_impact/local_pdf_index.json
```

### Scopus 试验来源

如需尝试 Elsevier Scopus API，先在 Elsevier Developer Portal 创建 API key，然后在 `.env` 中配置：

```bash
ACADEMIC_IMPACT_CITATION_SOURCE=scopus
ELSEVIER_API_KEY=your_elsevier_api_key
ELSEVIER_INSTTOKEN=
```

Scopus 接入当前是试验来源：目标论文 DOI 查询、`citedby-count` 和 Scopus Search cited-reference 查询会映射到项目的引用论文列表 schema；如果学校权限不允许拉取 cited-by list，可切回 `openalex`，并把 Scopus 作为引用数/元数据校验源。

如果未配置 LLM 服务或拿不到 PDF，分析会退化为 `context_only`，并在页面与导出中注明原因。

## 让 fulltext analysis 真正可用

在项目根目录配置好 `.env` 后，还需要一个**可访问的 OpenAI-compatible LLM 服务**。默认 `single_model` 模式要求该模型直接返回符合现有 schema 的 JSON；具体服务部署/启动命令统一放到 [`docs/ops/fulltext-llm.md`](docs/ops/fulltext-llm.md)。

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

### 分析范围

默认分析范围是 `candidate_spans`：先从全文筛出 top-k 候选段落，再让模型判断引用语义，适合批量处理。

需要让模型直接通读单篇引用论文全文时，可以改用 `fulltext_direct`：

```bash
python3 skills/academic_impact_analyzer/impact_cli.py analyze <session_dir> \
  --ids P001 \
  --analysis-scope fulltext_direct
```

Web 页面同样提供 `analysis scope` 下拉框。`fulltext_direct` 仍然是一篇 citing paper 一次请求，不会把多篇论文一起塞进模型上下文。

要比较两种分析范围的速度、稳定性和有 gold 样本时的命中情况，可以跑隔离 benchmark。脚本会为每个 `paper_id + scope` 复制一份临时 session，避免覆盖原始结果：

```bash
python3 scripts/compare_analysis_scopes.py <session_id_or_session_dir> \
  --ids P001,P002 \
  --concurrency 2
```

也可以通过 Makefile 调用：

```bash
make analysis-scope-bench \
  ANALYSIS_SCOPE_BENCH_SESSION=<session_id_or_session_dir> \
  ANALYSIS_SCOPE_BENCH_IDS=P001,P002 \
  ANALYSIS_SCOPE_BENCH_CONCURRENCY=2
```

默认输出到 `data/runs/analysis_scope_benchmarks/`，包含 `report.json` 和 `report.md`。没有 gold 文件时只比较性能、失败率和结果差异；默认存在的 `data/reference/fulltext_regression_set.json` 会用于计算状态/标签命中。

### 期刊/会议统计与等级

Discover 阶段会保存每篇引用论文的 `venue` 字段，来源取决于 `ACADEMIC_IMPACT_CITATION_SOURCE`：默认 `auto` 会先试 Semantic Scholar、失败后回退 OpenAlex；也可以显式使用 OpenAlex 或 Scopus。详情页会基于当前 session 自动汇总：

- 已识别 venue 数、唯一 venue 数
- top venue 及对应论文 ID
- venue 等级分布

venue 等级不由模型判断，而是用本地白名单 [`data/reference/venue_tiers.json`](data/reference/venue_tiers.json) 做别名匹配。当前文件只是可审计的项目种子，不是完整 CCF/CORE/JCR 官方目录；正式使用前应补充带来源的权威条目。未命中的 venue 会显示为 `未匹配等级`。

## 当前 MVP 按钮

- `Discover`
- `Refresh Probe`
- `Download Selected`
- `Analyze Selected`

## Scholar Impact Mode

Scholar impact mode extends the paper-level workflow from one target paper to one target researcher. It first builds metadata statistics for the researcher's publications and citation network, then performs fulltext semantic analysis on selected high-value citing papers.

Operational notes: [docs/ops/scholar-impact.md](docs/ops/scholar-impact.md)

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
