# Academic Impact Web

把旧的 OpenClaw 学术影响力分析项目收缩成一个传统 Web 应用：

- 前台是按钮和状态页
- 后台复用已经验证过的 Python 能力层
- 不再把主链路强依赖在 agent、飞书插件或运行时补丁上

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

## 先跑 CLI 内核

```bash
cd ~/projects/academic_impact_web
python3 skills/academic_impact_analyzer/impact_cli.py capabilities
python3 skills/academic_impact_analyzer/impact_cli.py discover "Attention Is All You Need" --limit 5
```

`discover` 如果碰到上游限流，仍然可能慢，但当前项目已经修过一处 OpenAlex 备用源空值崩溃。

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

## 当前 MVP 按钮

- `Discover`
- `Refresh Probe`
- `Download Selected`
- `Analyze Selected`

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
$plan "为 academic_impact_web 制定一个 3 天迭代计划，目标是把 discover / refresh / download / analyze 做成稳定的 Web 工作流，并逐步替换旧的 OpenClaw 依赖"
```

```text
请检查 skills/list_all_citations/list_papers.py、skills/download_paper_pdf/download_pdf.py 和 skills/analyze_fulltext_citation/analyze_fulltext.py，列出最可能导致 Web 版不稳定的外部依赖和兜底方案。
```

## 旧资料

旧项目接口手册在：

- `docs/legacy/学术影响力分析项目接口手册v2.md`

它适合拿来理解能力来源，但不要再把新的主链路设计成 OpenClaw / 飞书 / agent 驱动。
