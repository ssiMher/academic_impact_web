# 项目架构概览

这份文档只描述**当前主链路**，不记录历史废案。

## 1. 系统目标

`academic_impact_web` 把旧的学术影响力分析脚本收束成一个可运行、可回放、可审计的 Web 应用：

- Web 层负责发起任务、展示状态、保存会话
- `skills/` 目录保留核心分析能力
- `data/` 目录保存 session、下载的 PDF 和中间结果

原则：

- 元数据统计和全文分析分层
- 先快后深
- 能复用本地数据时，不强迫重复上传或重复下载

## 2. 主要目录职责

- `app/`
  - FastAPI 入口、页面路由、Jinja 模板
  - 将 `skills/` 能力包装成 Web 可用的服务
- `skills/`
  - 论文检索、PDF 下载、正文抽取、全文分析、学者统计
  - 这里是业务逻辑主层
- `data/`
  - `downloads/`：下载或绑定的 PDF
  - `sessions/`：普通论文分析会话
  - `scholar_sessions/`：学者影响力分析会话
  - `reference/`：venue、人物标签、外部名单等本地基准数据
- `docs/`
  - 部署、操作说明、开发日志、架构说明
- `tests/`
  - 面向 skill 和 web service 的回归测试

## 3. 两条主链路

### 3.1 普通论文分析

1. Discover / 获取候选引用论文
2. Probe / Download PDF
3. Extract text
4. Analyze citation
5. 汇总统计与页面展示

### 3.2 学者影响力分析

1. 用 DBLP author 入口创建 scholar session
2. 拉取作者论文列表
3. 扩展引用网络
4. 基于 venue / 人物标签构建高价值引用队列
5. 按用户选择的分析模板和排除配置筛选优先级
6. 对选中的 citing papers 做全文分析
7. 输出强引用证据、亮点评价卡片、人物统计、报告摘要

## 4. Scholar 页关键对象

学者页当前主要围绕这几类对象运转：

- `publications`
  - 目标学者本人论文
- `citation_edges`
  - 谁引用了这些论文
- `person_candidates`
  - 从 citing authors 命中的本地人物候选
- `deep_analysis_queue`
  - 值得做全文分析的高价值引用队列
- `scholar_fulltext_results`
  - 队列项的全文分析结果
- `strong_evidence`
  - 从全文分析中抽出的强引用证据
- `analysis_templates`
  - 用户希望优先寻找的证据模板，例如首次评价、详细对比、理论基础、方法来源
- `exclusion_profile`
  - 自引、本组作者、长期合作者和机构排除口径
- `highlight_cards`
  - 由强引用证据派生的汇报卡片，不直接落 session，按需从 `strong_evidence` 生成

## 5. PDF 获取优先级

当前项目对 citing paper PDF 的优先级是：

1. 用户手动上传的 PDF
2. 本地论文库命中的 PDF
3. 自动下载的 PDF

学者队列中的本地论文库自动匹配依赖：

- `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS`
- `ACADEMIC_IMPACT_DOWNLOAD_DIR`
- `ACADEMIC_IMPACT_PDF_INDEX_PATH`

本地文件匹配策略当前是：

- 优先用 DOI / arXiv ID
- 再做标题规范化匹配
- 文件名比较时忽略大小写
- 会清洗常见下载噪声，例如 `arxiv`、`preprint`、`accepted version`、`supplementary`
- 如果存在本地 PDF 索引，则优先查索引，再回退到目录扫描

如果未来本地库规模很大，优先考虑**加本地索引缓存**，不要直接跳到数据库。

## 6. 维护边界

为了避免后续越来越难维护，默认遵守这些边界：

- 不在 Web 路由里堆业务逻辑
- session schema 改动必须带测试
- 新的数据源先落到 `data/reference/`，再通过脚本刷新 registry
- 新的 PDF 匹配规则先补测试，再改实现
- 优先复用现有 `skills/`，不要平行再造一套逻辑

## 7. 推荐读法

第一次接手时，建议按这个顺序看：

1. `README.md`
2. `docs/architecture.md`
3. `docs/ops/scholar-impact.md`
4. `docs/devlog.md`
5. 相关测试文件
