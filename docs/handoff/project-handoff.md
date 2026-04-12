# Academic Impact Web 交接说明

更新时间：2026-04-12

## 1. 项目定位

这个项目当前的目标不是做一个通用 agent 系统，而是把“单篇论文的学术影响力分析”收口成一个可运行、可演示、可维护的传统 Web 应用。

当前主路径是：

- 首页输入目标论文
- 创建 session
- `discover / refresh / download / analyze`
- 上传本地 PDF
- 查看分析结果
- 导出 Markdown / JSON

项目已经明确不再依赖 OpenClaw runtime 或 `~/.openclaw` 目录作为主路径，只复用仓库内保留下来的 Python 能力层。

---

## 2. 阶段目标

### 阶段 A：旧能力收口

目标：

- 把旧 OpenClaw / 飞书 / plugin 主链路收缩成独立 Web 项目
- 保留已经验证过的 Python 能力层
- 去掉对 `~/.openclaw` 和旧运行时的主依赖

状态：

- 已完成

### 阶段 B：Phase 1 单篇论文引用分析页面

目标：

- 只做单篇论文引用分析，不做组级总览
- 页面围绕 5 个核心区块：
  - 目标论文基本信息与总览统计
  - 引用论文列表与状态
  - 单篇引用方式分析结果
  - 人物标签候选区
  - 导出与汇总

状态：

- 基本完成

### 阶段 C：演示/部署稳定化

目标：

- Web 上传 PDF
- 后台任务 + 状态轮询
- 固定 fulltext regression set
- 内网共享服务器可部署、可演示
- 失败诊断更清楚，页面尽量中文化

状态：

- 基本完成

### 阶段 D：后续扩展

候选方向：

- 组级论文总览
- 先进论文推荐
- 更强的人物身份识别
- 去掉 DeepSeek，改为本地模型直接结构化
- 更完整的任务系统（队列 / 取消 / 跨进程恢复）

状态：

- 尚未开始

---

## 3. 当前进展

## 已完成

- Web 主流程已打通：`discover / refresh / download / analyze`
- session 详情页已重构为 Phase 1 主视图
- 支持网页上传 PDF 并绑定到既有下载目录
- 4 个核心动作已后台化，并有 `task_state` 轮询
- 页面已加入任务状态展示、按钮禁用、失败提示
- fulltext analysis 已在多个真实样本上验证跑通
- 已建立固定回归集和回归脚本
- 已补共享服务器无 sudo 的部署说明与启动脚本
- 页面主要用户可见文案已中文化

## 仍然存在的限制

- `discover` 仍可能因为外部学术 API 限流而变慢
- 任务系统仍是最小版：
  - 无队列
  - 无取消
  - 无跨进程恢复
  - 页面轮询后整页 reload
- fulltext 分析仍依赖两段模型链：
  - 本地 OpenAI-compatible LLM 做语义分析
  - DeepSeek 做 JSON 结构化
- OCR 不是当前主路径，扫描版 PDF 仍可能失败

---

## 4. 当前架构

### 表现层

- `/home/withe/projects/academic_impact_web/app/main.py`
- `/home/withe/projects/academic_impact_web/app/templates/index.html`
- `/home/withe/projects/academic_impact_web/app/templates/session.html`
- `/home/withe/projects/academic_impact_web/app/static/style.css`

职责：

- FastAPI 路由
- 页面渲染
- 上传 PDF
- 后台任务轮询入口

### Web 服务适配层

- `/home/withe/projects/academic_impact_web/app/services/impact_core.py`

职责：

- 管理 session / downloads / exports
- 把 Web 动作转发到 skills 层
- 组装页面消费的派生 payload

### 核心工作流层

- `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/impact_cli.py`
- `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/run_pipeline.py`

职责：

- discover / status / refresh / download / analyze
- session.json 维护
- summary / report / structured export 生成

### 能力脚本层

- `/home/withe/projects/academic_impact_web/skills/list_all_citations/list_papers.py`
- `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/fetch_contexts.py`
- `/home/withe/projects/academic_impact_web/skills/download_paper_pdf/download_pdf.py`
- `/home/withe/projects/academic_impact_web/skills/extract_pdf_text/extract_text.py`
- `/home/withe/projects/academic_impact_web/skills/analyze_fulltext_citation/find_candidate_spans.py`
- `/home/withe/projects/academic_impact_web/skills/analyze_fulltext_citation/analyze_fulltext.py`

---

## 5. 运行前提

### 必需环境变量

至少需要这些：

- `ACADEMIC_IMPACT_ANALYSIS_MODE=single_model`
- `ACADEMIC_IMPACT_LLM_URL`
- `ACADEMIC_IMPACT_LLM_MODEL`
- `ACADEMIC_IMPACT_LLM_API_KEY`（本地无鉴权模型可留空；DeepSeek / DashScope 等 API 需要）
- `ACADEMIC_IMPACT_DOWNLOAD_DIR`

说明：

- 当前默认链路是单个 OpenAI-compatible 模型直接输出结构化 JSON
- 如果 Web 和模型在同一台机器上，建议 `ACADEMIC_IMPACT_LLM_URL` 指向 `127.0.0.1`
- 旧变量 `ACADEMIC_IMPACT_LOCAL_LLM_URL` / `ACADEMIC_IMPACT_LOCAL_MODEL` 仍作为兼容 fallback 保留

### 模型链说明

当前默认 fulltext analysis 是 single-model：

1. 一个 OpenAI-compatible 模型完成全文引用语义判断
2. 同一个模型直接返回现有 schema JSON

旧双阶段链路仍作为临时回退保留：

1. 设置 `ACADEMIC_IMPACT_ANALYSIS_MODE=legacy_two_stage`
2. 本地模型做全文引用语义分析
3. DeepSeek 把结果整理成稳定 JSON，此时仍需要 `DEEPSEEK_API_KEY`

### 部署文档

共享服务器最小部署说明见：

- `/home/withe/projects/academic_impact_web/docs/deploy/internal-demo.md`

模型服务相关运维说明见：

- `/home/withe/projects/academic_impact_web/docs/ops/fulltext-llm.md`

---

## 6. 当前最可信的回归资产

### 固定回归集

- `/home/withe/projects/academic_impact_web/data/reference/fulltext_regression_set.json`

### 回归脚本

- `/home/withe/projects/academic_impact_web/scripts/run_fulltext_regression.py`

### 其他检查脚本

- `/home/withe/projects/academic_impact_web/scripts/fulltext_ready_check.py`
- `/home/withe/projects/academic_impact_web/scripts/phase1_smoke.py`
- `/home/withe/projects/academic_impact_web/scripts/check_demo_env.sh`
- `/home/withe/projects/academic_impact_web/scripts/start_web_demo.sh`

---

## 7. 推荐接手阅读顺序

1. `/home/withe/projects/academic_impact_web/README.md`
2. `/home/withe/projects/academic_impact_web/.omx/plans/prd-20260406-phase1-single-paper-impact.md`
3. `/home/withe/projects/academic_impact_web/docs/deploy/internal-demo.md`
4. `/home/withe/projects/academic_impact_web/app/services/impact_core.py`
5. `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/impact_cli.py`
6. `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/run_pipeline.py`
7. `/home/withe/projects/academic_impact_web/data/reference/fulltext_regression_set.json`

不要把下面这个旧文档当成当前主路径：

- `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/HANDOFF.md`

它描述的是更早的 OpenClaw/飞书链路，不再等同于当前 Web 项目的主运行方式。

---

## 8. 建议演示样本

优先展示：

- session: `20260407_150900_training_free_group_relative_policy_optimization`
- paper: `P004`

原因：

- 已验证是 `fulltext_analyzed`
- 结果相对稳定
- 适合演示上传 PDF、全文分析、导出整条链路

备用成功样本：

- `20260407_143000_lora_goal_fulltext_smoke / P020`

不建议作为主演示样本：

- `P002`：更适合作为“没拿到 PDF 时退化到 context_only”的边界样本
- `P003`：更适合作为“假 PDF / HTML 拦截页”的边界样本

---

## 9. 当前已知风险

### 风险 1：上游 API 不稳定

- `discover`
- `fetch_contexts`
- PDF 下载探测

都受外部源限流影响，特别是 429。

### 风险 2：PDF 质量差异很大

常见情况：

- 真 PDF 可正常分析
- 扫描版/图片版 PDF 提取不到文本
- 某些“PDF”实际上是 HTML 拦截页

### 风险 3：fulltext 仍依赖 DeepSeek

如果未来要完全本地化，还需要额外改造和回归验证。

### 风险 4：任务系统不是生产级

当前设计适合：

- 组内演示
- 小规模内网试用

不适合直接视为公网生产方案。

---

## 10. 当前非常重要的一点

截至本交接文档更新时，工作区里还有一组**未提交改动**，主要是：

- 假 PDF / HTML 拦截页识别
- attach 时拒绝绑定无效 PDF
- 页面上更直接展示“假 PDF / HTML 拦截页”原因

涉及文件包括：

- `/home/withe/projects/academic_impact_web/app/main.py`
- `/home/withe/projects/academic_impact_web/app/templates/session.html`
- `/home/withe/projects/academic_impact_web/skills/academic_impact_analyzer/impact_cli.py`
- `/home/withe/projects/academic_impact_web/skills/download_paper_pdf/download_pdf.py`
- `/home/withe/projects/academic_impact_web/tests/test_phase1_detail.py`
- `/home/withe/projects/academic_impact_web/tests/test_download_pdf_validation.py`

所以交接时必须明确：

- `origin/master` 已经能演示
- 但本地工作区还有一组“假 PDF 防护”增强尚未 checkpoint

建议接手人第一件事就是先确认：

1. 是否把这组本地改动整理并提交
2. 再继续做后续开发

---

## 11. 建议接手后的优先级

### 如果目标是继续演示/试用

优先级：

1. 先收口并提交当前未提交的 fake PDF 防护改动
2. 保持回归集可运行
3. 继续补更清楚的失败提示和边界处理

### 如果目标是继续做产品化

优先级：

1. 改善 `discover` 慢和限流可见性
2. 强化 PDF 质量识别与 fallback
3. 进一步整理部署/日志/排障路径

### 如果目标是 Phase 2

优先级：

1. 先稳定 Phase 1
2. 再做组级总览与先进论文推荐
3. 最后再考虑去掉 DeepSeek

---

## 12. 交接时建议直接口头说明的三句话

1. 这个项目当前已经不是旧 OpenClaw 技术栈的主链路，而是一个独立 Web 项目。
2. `origin/master` 基本能跑演示，但本地还有一组“假 PDF 防护”改动没提交，接手前最好先处理掉。
3. 下一步最值得做的不是继续加新功能，而是先把现有链路的稳定性和边界诊断收口。
