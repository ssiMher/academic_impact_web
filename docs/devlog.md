# 开发日志

## 2026-05-23：修复高价值队列自引误标排查结果

分支：`codex/organize-analysis-venue-work`

背景：
- 服务器已更新到“把当前学者加入自引判断”的版本后，部分高价值队列项仍显示 `self_citation:non_self`。
- 典型例子是同一篇引用论文命中多篇目标论文时，页面展示的是合并后的队列项。

本次处理：
- 自引判断会先拆分 `Jingyi Ning; Lei Xie` 这类被保存成单个字符串的作者列表，避免作者元数据格式不统一导致误判。
- 队列合并多条引用边时，只要任意一条边判为自引，合并后的队列项保守显示为自引。
- 增加 `scripts/debug_scholar_self_citation.py`，用于对单个高价值队列项输出：
  - 页面已存的自引状态
  - 当前代码重新计算的自引状态
  - 当前学者名、引用作者、目标论文作者、命中的边数量
- 增加回归测试覆盖：
  - 分号分隔作者字符串的自引识别
  - 同一引用论文合并后自引状态优先保留

排查建议：
- 如果页面仍显示异常，优先查看对应 session 的 `data/scholar_sessions/<session_id>/session.json` 中该队列项的 `citing_authors`、`source_publication_authors`、`self_citation_status` 和 `self_citation_overlap_authors`，确认问题是在作者元数据缺失、重建未生效，还是页面缓存。

## 2026-05-23：自引判断补充当前学者口径

分支：`codex/organize-analysis-venue-work`

背景：
- 高价值引用队列中的论文都是引用当前学者论文的论文。
- 之前自引判断只比较“引用论文作者”和“被引用目标论文作者”的交集。
- 如果目标论文作者列表缺失或不完整，而引用论文作者中出现当前学者本人，会误标为非自引。

本次处理：
- 高价值队列构建时把当前会话学者姓名加入自引判断目标作者集合。
- 自引论文仍保留在队列中，但降权并显示 `self_citation:self`，方便筛选和解释。
- 非自引论文继续加分并显示 `self_citation:non_self`。

当前策略：
- 自引判断口径是：`引用论文作者 ∩ (被引用目标论文作者 + 当前会话学者)`。
- 仍然只按姓名匹配，不使用 ORCID/OpenAlex/Scopus 作者 ID。

## 2026-05-23：创建学者分析时识别错误的 DBLP ID

分支：`codex/organize-analysis-venue-work`

背景：
- 创建学者分析时，如果把 ORCID 填进 DBLP ID 输入框，后端会请求 `https://dblp.org/pid/<ORCID>.xml`。
- DBLP 对这种地址返回 404，之前异常没有转换，页面表现为 500 Internal Server Error。

本次处理：
- 新增 DBLP ID 规范化：
  - 支持直接填写 `94/1247-1`
  - 支持粘贴 DBLP 作者主页链接并自动提取 PID
  - 明确拒绝 ORCID 格式
- DBLP XML 请求返回 404 时，转换为可读的 `ValueError`，提示用户确认不是 ORCID/OpenAlex/Scopus ID。
- `/scholars/create` 捕获该错误并返回 400，不再让服务端 500。
- 首页输入框文案明确标注“DBLP ID（不是 ORCID / OpenAlex）”。

当前策略：
- 当前学者分析仍以 DBLP 作为论文列表来源，因此创建会话必须有 DBLP PID。
- OpenAlex / Scopus Author ID 仍作为辅助字段保存，不用于替代 DBLP 拉取论文列表。

## 2026-05-20：把高价值队列和强引用证据转向“汇报可用证据”

分支：`codex/organize-analysis-venue-work`

背景：
- 组会反馈强调系统核心不应只是引用数量统计，而是找出“别人如何评价我的工作”的第三方证据。
- 现有强引用证据只粗略记录 aspect、stance、长引用和 Fellow 强引用，难以直接服务 PPT 汇报。
- 高价值队列缺少自引状态和更贴近“先分析哪些论文”的筛选口径。

本次处理：
- 新增 `scholar_evidence.py`，集中维护：
  - 自引判断
  - 证据标签规范化
  - 高亮关键词提取
  - 强引用分数和强度等级
- 高价值引用队列新增自引状态，并在优先级中：
  - 非自引加分
  - 明确自引降权
  - 高引用数、重要人物、顶会和可分析标识继续作为队列线索
- 全文分析输出 schema 增加：
  - `evidence_labels`
  - `highlight_keywords`
  - `evidence_strength`
  - `is_self_citation`
  - `why_valuable`
- 强引用证据页面新增：
  - 证据标签筛选
  - 证据强度筛选
  - 自引筛选
  - 关键词高亮
  - 汇报价值说明
  - 强度分展示
- Markdown 报告的 Top 强引用证据改为按强度分排序，并补充证据标签、自引状态和汇报价值。

当前策略：
- 证据标签是可扩展集合，后续导师新增模板时优先改 `scholar_evidence.py` 和 prompt，不要把规则继续散落到页面里。
- 自引判断只基于作者姓名签名，支持常见的 `Chen Tian` / `Tian Chen` 顺序差异；没有作者信息时标为未知，不强行判断。
- 本轮不继续扩大外部 ID 补全范围，避免把主线从“引用语义证据”拉回“名单清洗”。

## 2026-05-19：上传 PDF 后返回原队列行

分支：`codex/organize-analysis-venue-work`

背景：
- 高价值引用队列很长，用户在后面页码上传 PDF 后，页面会跳回队列第一页/顶部，连续补 PDF 时非常低效。

本次处理：
- 给每个队列行增加稳定锚点，例如 `queue-Q042`。
- 上传表单带上当前队列页码、每页数量、筛选原因和行锚点。
- 上传成功后重定向回原筛选/分页 URL，并跳到刚上传的行。

当前策略：
- 如果缺少返回参数，仍回到队列区域。
- 不把滚动位置存在服务端，所有返回状态都随表单提交，避免会话状态被浏览行为污染。

## 2026-05-19：优化批量下载待补 PDF

分支：`codex/organize-analysis-venue-work`

背景：
- 批量下载待补 PDF 初版是串行执行，失败论文会把多个外部源和 timeout 都跑完，整体耗时长。
- 只有 `source_url` 的队列项会被底层下载器误判成 DOI/标题查询，既慢又容易失败。
- `pdf_download_report.csv` 只记录成功/失败，不够解释为什么下载不到。

本次处理：
- 批量下载改为小并发执行，默认最多 4 个 worker，可通过 `ACADEMIC_IMPACT_PDF_DOWNLOAD_WORKERS` 调整，内部限制为 1 到 8。
- 对 `source_url` 单独处理：
  - 如果它本身像 PDF URL，直接下载。
  - 否则解析 HTML 落地页中的 PDF 候选链接，再逐个尝试。
- 扩展 `pdf_download_report.csv` 诊断字段：
  - `source_strategy`
  - `candidate_count`
  - `attempted_count`
  - `failure_type`
  - `elapsed_ms`
  - `download_errors`
- 失败类型会粗分为无候选、超时、权限/登录需求、404、非 PDF、元数据未找到等。

当前策略：
- 并发只加在下载层，不并发写 session，避免多个线程同时改同一个会话 JSON。
- 报告按原队列顺序输出，方便和页面上的高价值队列对照。

## 2026-05-19：批量下载待补 PDF

分支：`codex/organize-analysis-venue-work`

背景：
- `missing_pdfs.csv` 只能给出待补 PDF 清单，用户仍需要自己逐条下载或上传。
- 更顺的流程是让网页直接按队列中缺 PDF 的条目批量尝试下载，并把成功文件写入全局本地论文库。

本次处理：
- 新增“批量下载待补 PDF”按钮，触发后台任务，不阻塞页面。
- 下载顺序按队列项可用线索选择：arXiv ID、DOI、source URL、标题。
- 复用现有 `download_pdf.download_paper()` 下载链路，仍走 Semantic Scholar、Unpaywall、DOI 落地页、OpenAlex、arXiv、CORE 等候选源。
- 成功下载的条目会立即写入队列 `library_pdf`，并在任务结束后重建本地 PDF 索引。
- 新增 `pdf_download_report.csv` 导出，记录每个队列项的下载状态、查询方式、文件路径、PDF URL 和失败原因。

当前策略：
- 已有手动 PDF 或本地库 PDF 的队列项会跳过，避免重复下载。
- 下载失败不会中断整个批次，而是写入报告，方便后续只处理失败项。

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
