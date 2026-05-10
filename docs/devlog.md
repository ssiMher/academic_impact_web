# 开发日志

## 2026-05-10：整合学者页主线和人物来源数据

分支：`codex/organize-analysis-venue-work`

背景：
- 学者影响力页面的主体功能在 `codex/organize-analysis-venue-work`。
- `master` 上另有一批人物来源数据和 registry 刷新脚本。
- 两个分支没有完全同步，导致服务器上的学者页可以运行，但 `person_tag_registry.json` 只有少量 seed，人物统计基本没有结果。

本次处理：
- 保留 `codex/organize-analysis-venue-work` 作为 demo 主线。
- 从 `master` 选择性整合人物来源目录 `data/reference/source_lists/`。
- 整合 `scripts/refresh_person_tag_registry.py` 和 `make person-registry-refresh` 入口。
- 整合 `data/reference/top_institutions.json`，用于后续国外高校作者候选。
- 更新 `person_tag_registry.json`，由本地来源列表生成 2899 条人物标签记录。
- 修复刷新脚本，让它同时兼容旧的 `tag_type` 格式和新的 `tags` 数组格式，避免刷新时丢失多标签 seed。

当前统计口径：
- 快速统计只使用 DBLP / OpenAlex / Scopus 元数据、本地 venue registry 和本地人物 registry。
- 快速统计不会下载 PDF，也不会调用大模型。
- 人物命中默认是 `pending`，需要人工确认，避免同名误判直接计入 confirmed。
- 深度语义分析仍然通过高价值引用队列执行 PDF 下载、全文抽取和 `fulltext_direct` 模型分析。

服务器部署建议：
1. 不要在服务器上手动 merge `master`。
2. 服务器保持在 `codex/organize-analysis-venue-work`。
3. 等本分支 push 后，在服务器执行：

```bash
cd ~/projects/academic_impact_web
git pull --ff-only origin codex/organize-analysis-venue-work
```

4. 如果服务器存在未跟踪的 `data/reference/source_lists/acm_fellows_paste.txt`，它不会被本次提交覆盖。后续如需纳入 ACM Fellow，可先保留该文件，再运行：

```bash
make person-registry-refresh
```

注意事项：
- `data/scholar_sessions/` 是服务器运行数据，不应该提交到代码仓库。
- 以后新线程不要直接把功能写到 `master`，除非它就是最终集成分支。
- 新数据源先放入 `data/reference/source_lists/`，再用刷新脚本生成 `person_tag_registry.json`。
