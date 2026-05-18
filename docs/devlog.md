# 开发日志

## 2026-05-18：给学者页补上本地 PDF 索引状态和一键刷新

分支：`codex/organize-analysis-venue-work`

背景：
- 前一轮已经支持本地论文库命中和离线 JSON 索引，但入口还停留在命令行。
- 学者页用户虽然能受益于本地 PDF 自动命中，却看不到“当前索引有没有生效、命中了多少、要不要重建”。
- 一旦本地论文库刚刚新增 PDF，用户还需要手动回到命令行重建索引，再回网页重建队列，操作链路偏长。

本次处理：
- 在 `app/services/scholar_core.py` 中新增本地 PDF 索引状态读取和刷新入口：
  - 汇总索引条目数
  - 汇总当前 scholar 队列命中的本地 PDF 数量
  - 重建本地索引后，立即重建当前 scholar 会话的派生统计和高价值队列
- 在 `app/main.py` 中新增 `/scholars/{session_id}/refresh-local-pdf-index` 路由，并把索引状态注入学者详情页模板。
- 在 `app/templates/scholar_session.html` 中新增“本地 PDF 索引”状态面板，显示：
  - 当前索引条目数
  - 队列命中本地 PDF 数量
  - 索引路径
  - 最近刷新时间和扫描目录（如果可用）
  - 一键刷新按钮
- 在 `tests/test_scholar_web.py` 中补测试，锁定：
  - 学者页会渲染索引状态和刷新按钮
  - 刷新路由会正确重定向
  - 刷新动作会重建索引并回写 scholar 队列

当前策略：
- 刷新本地 PDF 索引时，如果当前 scholar 会话仍有后台任务在跑，会拒绝刷新，避免并发改写同一份会话文件。
- 刷新动作会沿用当前会话已有的高价值队列规模，而不是偷偷改用户之前选定的 queue limit。
- 页面上的队列命中数优先展示当前会话的真实状态，即使 helper 返回的 mock/裁剪数据不完整，也会兜底计算。

后续建议：
1. 如果后面需要更强可观测性，可以继续补“索引构建耗时”和“上次扫描到的 PDF 数量”。
2. 如果要支持多用户并发刷新，下一步要把索引写入和会话重建拆成更细的锁粒度。

## 2026-05-18：补强本地 PDF 匹配规则并建立维护骨架

分支：`codex/organize-analysis-venue-work`

背景：
- 学者影响力分析已经支持从本地论文库自动命中 PDF，但原始文件名匹配仍然偏依赖“标题接近”。
- 实际下载下来的 PDF 文件名经常带额外噪声，例如 `arxiv`、`preprint`、`accepted version`、`supplementary`。
- 项目功能线已经变多，如果没有持续的开发记录和架构概览，后续维护会越来越依赖口头上下文和 commit 回忆。

本次处理：
- 在 `skills/download_paper_pdf/download_pdf.py` 中补了一层本地 PDF 文件名规范化：
  - 统一大小写比较
  - 清洗常见下载噪声词
  - 清洗括号噪声片段
  - 匹配时同时比较原始文件名和清洗后的文件名
- 把常见下载噪声词抽到 `data/reference/pdf_filename_noise_terms.txt`，后续新增站点噪声不必改代码。
- 新增 `scripts/build_local_pdf_index.py` 和 `ACADEMIC_IMPACT_PDF_INDEX_PATH`，允许为大本地论文库预构建 JSON 索引，运行时优先查索引再回退目录扫描。
- 新增 `tests/test_download_pdf_matching.py`，锁定两类高频场景：
  - 文件名仅大小写不同
  - 文件名带下载站点噪声但仍应命中
  - 存在 index cache 时优先使用索引，而不是重复扫描目录
- 新增 `docs/architecture.md`，把当前主链路、目录职责、PDF 优先级和维护边界写下来。
- 在 `README.md` 中明确把 `architecture` / `ops` / `devlog` 作为推荐入口，避免后续只靠会话上下文理解系统。

当前策略：
- 本地 PDF 匹配优先靠 DOI / arXiv ID，其次才是标题。
- 标题匹配会忽略大小写、标点和常见下载噪声。
- Scholar 队列里 PDF 使用优先级保持为：
  1. 手动上传
  2. 本地论文库命中
  3. 自动下载

后续建议：
1. 如果 PDF 命中率继续不稳定，下一步优先补“文件名前后缀噪声词字典”和更多真实样本测试。
2. 如果需要更细粒度命中，再考虑把 DOI / arXiv hint 直接预提取到索引里。
3. 每次主流程变更后，都同步更新：
   - `docs/devlog.md`
   - `docs/architecture.md`

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
