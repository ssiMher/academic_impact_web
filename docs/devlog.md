# 开发日志

## 2026-05-19：导出待补 PDF 清单

分支：`codex/organize-analysis-venue-work`

背景：
- 高价值引用队列里逐篇手动上传 PDF 很慢。
- 更合理的流程是先刷新本地 PDF 索引，让本地库自动命中；剩余未命中的项目再导出清单，批量去 arXiv、DOI 页面、机构权限入口或开放获取源查找 PDF。

本次处理：
- 新增 `missing_pdfs.csv` 导出，位于 scholar 会话导出区。
- CSV 只包含当前高价值引用队列中尚未绑定手动 PDF、也尚未命中本地库 PDF 的项目。
- 导出字段包括 `queue_id`、优先级、原因、标题、DOI、DOI URL、建议文件名、arXiv URL、venue、年份、作者、命中目标论文、source URL 和下载优先级。
- 对 ACM ePDF 常见的 DOI suffix 文件名，建议文件名会给出类似 `3689031.3696065.pdf`，方便批量下载后直接放入本地论文库。

推荐流程：
1. 先点击“刷新本地 PDF 索引”，让本地库尽量自动命中。
2. 再导出 `missing_pdfs.csv`。
3. 根据 `download_priority` 批量找 PDF。
4. 下载后放入本地库，再刷新索引。
5. 只对仍未命中的少量论文手动上传。

## 2026-05-19：识别 ACM ePDF 的 DOI 后缀文件名

分支：`codex/organize-analysis-venue-work`

背景：
- ACM Digital Library 的 ePDF 下载文件名常见为 DOI 后缀，例如 `3689031.3696065.pdf`。
- 手动上传 PDF 时文件名不影响绑定，因为上传动作按队列项保存；但本地论文库自动识别依赖 DOI / arXiv / 标题等线索，旧规则只覆盖 `10.1145_3689031.3696065` 这类完整 DOI 文件名，容易漏掉 ACM 的默认命名。

本次处理：
- 在 `download_pdf.py` 中补充 DOI 文件名 hint：
  - 完整 DOI
  - `/` 替换为 `_` 的完整 DOI
  - DOI suffix
  - `/` 替换为 `_` 的 DOI suffix
- 增加回归测试，确保 `10.1145/3689031.3696065` 能命中本地文件 `3689031.3696065.pdf`。

## 2026-05-18：把首页 recent sessions 和本地 PDF 刷新链路从重型路径上挪开

分支：`codex/organize-analysis-venue-work`

背景：
- 首页“最近会话”返回很慢，实测大头并不在 scholar 会话，而在普通 citation impact 会话列表。
- `impact_core.list_sessions()` 之前会对每个 session 调 `impact_cli.load_session()`，而 `load_session()` 又会触发 `sync_session_derivatives()` 和 `rebuild_person_candidates()`，导致首页只是列摘要也会重算人物候选。
- “刷新本地 PDF 索引”按钮之前除了重建索引，还会整套重跑 scholar 派生统计、人物候选和高价值队列，和按钮语义不符，也是长耗时来源。

本次处理：
- 在 `app/services/impact_core.py` 中新增轻量摘要读取逻辑，`list_sessions()` 只直接读取 `session.json` 中已有字段，不再触发 `impact_cli.load_session()`。
- 在 `app/services/scholar_core.py` 中把 `refresh_scholar_local_pdf_index()` 改成真正的轻量刷新：
  - 只重建本地 PDF 索引
  - 只对当前高价值队列做本地 PDF 重匹配
  - 不再重跑人物候选、venue 统计和高价值队列生成
- 在 scholar 索引状态面板中补充分阶段耗时：
  - 索引构建耗时
  - 队列重匹配耗时
  - 本次刷新总耗时
  - 上次按钮刷新时间
- 在 `download_pdf.py` 中允许 `find_local_pdf_with_metadata()` 直接复用已加载的 `index_data`，避免队列重匹配时每条记录重复从磁盘读索引文件。

实测结果：
- 优化前：首页 `impact_core.list_sessions(limit=20)` 约 `7.3s ~ 8.1s`。
- 优化后：首页 `impact_core.list_sessions(limit=20)` 约 `0.18s ~ 0.20s`，`merged_recent_sessions(limit=20)` 约 `0.18s`。
- 合成 300 条高价值队列场景下：
  - 旧版 refresh 路径重建整套派生，profile 显示时间主要花在 `build_person_candidates_from_citation_edges()` / `person_candidates.build_candidates()`。
  - 新版 refresh 路径只做索引 + 队列重匹配，实测总耗时约 `0.47s ~ 1.12s`，其中索引构建约 `3ms`，队列重匹配约 `1.07s`。

当前策略：
- 首页只读最近会话摘要；真正进入详情页时再走重型会话加载。
- “刷新本地 PDF 索引”只刷新本地 PDF 相关状态，不再顺带刷新无关统计。
- 队列重匹配优先复用内存里的本地索引，减少重复文件读取。

## 2026-05-18：给学者页补上本地 PDF 索引状态和一键刷新

分支：`codex/organize-analysis-venue-work`

背景：
- 前一轮已经支持本地论文库命中和离线 JSON 索引，但入口还停留在命令行。
- 学者页用户虽然能受益于本地 PDF 自动命中，却看不到“当前索引有没有生效、命中了多少、要不要重建”。
- 一旦本地论文库刚刚新增 PDF，用户还需要手动回到命令行重建索引，再回网页重建队列，操作链路偏长。

本次处理：
- 在 `app/services/scholar_core.py` 中新增本地 PDF 索引状态读取和刷新入口：
  - 汇总索引条目数
  - 汇总上次扫描到的 PDF 数量
  - 汇总索引构建耗时
  - 汇总当前 scholar 队列命中的本地 PDF 数量
  - 重建本地索引后，立即重建当前 scholar 会话的派生统计和高价值队列
- 在 `app/main.py` 中新增 `/scholars/{session_id}/refresh-local-pdf-index` 路由，并把索引状态注入学者详情页模板。
- 在 `app/templates/scholar_session.html` 中新增“本地 PDF 索引”状态面板，显示：
  - 当前索引条目数
  - 上次扫描 PDF 数量
  - 索引构建耗时
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
