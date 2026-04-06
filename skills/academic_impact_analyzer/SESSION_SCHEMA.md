# session.json Schema

## 目的

`session.json` 是 OpenClaw、CLI 和未来飞书卡片共享的会话状态文件。

这份 schema 的目标是固定字段语义，避免后续接入层因为字段频繁变化而反复改代码。

当前版本：

- `schema_version = "1.0"`
- `session_kind = "academic_impact_analysis"`

## 顶层字段

```json
{
  "ok": true,
  "schema_version": "1.0",
  "session_kind": "academic_impact_analysis",
  "query": "...",
  "created_at": "...",
  "updated_at": "...",
  "session_dir": "...",
  "target": {...},
  "paths": {
    "list_papers": "...",
    "contexts": "..."
  },
  "analysis_mode_last": "quick",
  "paper_count": 2,
  "paper_aliases": [...],
  "quick_analysis": {...},
  "evidence_index": {...},
  "analysis": {...},
  "overview_stats": {...},
  "person_candidates": [...],
  "exports": {...},
  "papers": [...]
}
```

### 字段说明

- `ok`
  当前会话是否成功初始化。
- `schema_version`
  会话 schema 版本号。
- `session_kind`
  会话类型，当前固定为 `academic_impact_analysis`。
- `query`
  用户发起会话时输入的目标论文查询串。
- `created_at`
  会话创建时间。
- `updated_at`
  会话最近更新时间。
- `session_dir`
  当前会话目录。
- `target`
  目标论文元信息。
- `paths`
  discover 阶段的核心产物路径。
- `paper_count`
  当前会话里 citing paper 数量。
- `analysis_mode_last`
  最近一次会话级分析模式，可取 `list / quick / full / null`。
- `paper_aliases`
  会话内每篇论文的编号、别名、标题关键词，用于自然语言匹配。
- `quick_analysis`
  基于 citation contexts 的快速分析摘要。
- `evidence_index`
  全面分析后生成的问答证据索引。
- `analysis`
  最近一次 analyze 阶段的汇总路径与统计。
- `overview_stats`
  页面级总览统计，如已下载数、已分析数、人物候选数、已确认人物数。
- `person_candidates`
  会话级人物/机构候选聚合视图，记录 pending / confirmed / rejected 状态。
- `exports`
  页面导出产物路径（Markdown 报告、结构化 JSON）。
- `papers`
  citing paper 列表。

## papers[] 字段

```json
{
  "id": "P001",
  "title": "...",
  "year": 2022,
  "venue": "...",
  "authors": ["..."],
  "externalIds": {...},
  "download_queries": ["doi", "title"],
  "download_probe": {...},
  "best_context": {...},
  "context_confidence": "medium",
  "context_count": 3,
  "analysis_result": {
    "status": null,
    "paths": {}
  },
  "qa_ready": false,
  "selection": {
    "selected_for_download": false,
    "selected_for_analysis": false
  },
  "paper": {...}
}
```

### 字段说明

- `id`
  会话内稳定编号，供 OpenClaw/飞书按钮引用。
- `download_queries`
  下载阶段会尝试的 query 列表。
- `download_probe`
  下载可达性探测结果。
- `best_context`
  最强 citation context。
- `context_confidence`
  `high / medium / low / null`
- `analysis_result.status`
  最近一次分析状态。
- `qa_ready`
  是否已经具备可直接回答细节追问的全文证据。
- `selection`
  用户是否曾经选择该论文用于下载或分析。
- `paper`
  原始 citing paper 元信息。

## download_probe 字段

```json
{
  "ok": true,
  "status": "not_probed",
  "source": "",
  "queries": ["doi", "title"],
  "attempts": [],
  "candidate_count": null,
  "local_file_path": null,
  "pdf_candidates": [],
  "error": null
}
```

### `download_probe.status`

- `not_probed`
- `local_available`
- `auto_downloadable`
- `manual_required`
- `probe_failed`

## analysis 字段

```json
{
  "summary_path": "...",
  "report_json_path": "...",
  "report_md_path": "...",
  "processed_papers": 2
}
```

该字段只在执行过 `analyze` 后出现有效内容。

## paper_aliases 字段

```json
[
  {
    "id": "P001",
    "title": "...",
    "normalized_title": "...",
    "aliases": ["..."],
    "normalized_aliases": ["..."],
    "keywords": ["penguin", "firered"]
  }
]
```

用于把“下载 Penguin-VL”“论文 FireRed 是怎么引用的”这类自然语言映射到会话内论文编号。

## quick_analysis 字段

```json
{
  "schema_version": "1.0",
  "status": "ready",
  "analysis_mode": "quick",
  "impact_level": "medium",
  "impact_label": "中等",
  "summary": "...",
  "highlights": [...]
}
```

## evidence_index 字段

```json
{
  "schema_version": "1.0",
  "status": "ready",
  "qa_ready_count": 2,
  "items": [
    {
      "id": "P002",
      "title": "...",
      "status": "fulltext_analyzed",
      "qa_ready": true,
      "candidate_span_count": 4,
      "findings_count": 1,
      "primary_evidence": {
        "page": 14,
        "span_index": 5,
        "char_length": 186,
        "sentence_count": 2,
        "excerpt": "..."
      }
    }
  ]
}
```

## 兼容策略

`impact_cli.py` 当前会在读取旧会话时自动补齐以下默认字段：

- `schema_version`
- `session_kind`
- `session_dir`
- `analysis`
- `download_probe`
- `analysis_result`
- `selection`

这意味着后续小版本演进可以保持向后兼容。


## overview_stats 字段

```json
{
  "downloaded_count": 2,
  "analyzed_count": 2,
  "candidate_people_count": 1,
  "confirmed_people_count": 1
}
```

## person_candidates 字段

```json
[
  {
    "candidate_id": "acm_fellow::alice-example",
    "name": "Alice Example",
    "tag_type": "acm_fellow",
    "tag_label": "ACM Fellow",
    "matched_paper_ids": ["P001"],
    "source_links": ["https://example.com/alice"],
    "status": "pending",
    "review_note": "",
    "reviewed_at": null,
    "evidence": [
      {
        "paper_id": "P001",
        "matched_author": "Alice Example",
        "match_type": "exact_name"
      }
    ]
  }
]
```

## exports 字段

```json
{
  "report_md_path": ".../exports/phase1_report.md",
  "structured_json_path": ".../exports/phase1_structured.json"
}
```
