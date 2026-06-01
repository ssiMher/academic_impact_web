# 开发日志

## 2026-06-01：显示模板命中词并修复模块折叠

分支：`codex/organize-analysis-venue-work`

背景：
- 结构化判断明细里只显示“命中当前模板 / 未命中当前模板”，无法看出当前模板到底在找哪些关键词，也无法判断是哪个词或标签触发命中。
- 页面模块“收起”按钮在部分环境下没有实际隐藏内容，主要因为折叠只依赖 CSS 类，前端缓存或选择器兼容性会让按钮状态和页面显示不同步。

本次处理：
- 模板匹配结果会显示具体命中的模板标签/关键词，例如 `模板命中：最先进 / SOTA / state-of-the-art`。
- 未命中时也显示当前模板正在检查的前几个关键词，例如 `模板未命中：首次 / 开创性评价 / first / first work`。
- 模块折叠改为 JS 直接设置模块正文的 `hidden` 状态，同时继续保留本地记忆。
- `localStorage` 不可用时也能正常折叠，只是不保存状态。

当前策略：
- 弱提及、组引用和 `keep=false` 仍不会算作模板命中，即使它们带有模板标签或关键词。
- “未命中”展示的是当前模板的检查范围，不代表模型没有看到这些词，而是该 finding 没有满足模板命中条件。

## 2026-06-01：优化单篇论文分析页的筛选入口和模块折叠

分支：`codex/organize-analysis-venue-work`

背景：
- “仅看模板命中”原本只在“引用论文列表与状态”的筛选栏里，用户查看“深度语义分析结果”时不容易发现。
- 单篇论文分析页模块较多，深度分析卡片和明细较长，连续浏览时页面噪音偏高。

本次处理：
- 在“深度语义分析结果”模块标题右侧增加“仅看模板命中 / 显示全部分析结果”快捷入口。
- 给带标题的主模块自动增加“收起 / 展开”按钮。
- 每个模块的折叠状态会保存在浏览器本地，下次打开同一会话页仍保持用户上次选择。
- 优化 `details summary` 的键盘焦点样式，避免默认黑框看起来像页面异常。

当前策略：
- 模板筛选仍复用同一套后端过滤参数，快捷入口只是把这个筛选放到更靠近深度分析结果的位置。
- 默认不折叠任何模块，避免用户第一次打开页面时看不到内容。

## 2026-06-01：单篇论文列表支持只看模板命中

分支：`codex/organize-analysis-venue-work`

背景：
- 分析模板用于指导系统优先寻找特定证据，但用户需要把结果进一步收窄到“当前模板真正命中的证据”。
- 之前列表只能按强证据筛选，无法区分“模板关注的证据”和“其他引用语义”。

本次处理：
- 单篇论文详情的结构化 finding 会标记 `template_matched`，依据是当前已编译模板的目标标签或关键词是否命中该 finding。
- 弱提及、组引用、`keep=false` 的 finding 不会被算作模板命中，避免普通背景句因为含有关键词而混入模板结果。
- 引用论文列表增加“仅看模板命中”筛选开关，并在论文卡片和结构化判断明细中显示模板命中数量/状态。

当前策略：
- 模板仍是分析优先级，不是全局白名单；未开启“仅看模板命中”时，页面继续展示其他引用语义。
- 开启“仅看模板命中”后，只保留至少一条结构化 finding 命中当前模板的论文。

## 2026-06-01：弱提及不再派生强证据关键词

分支：`codex/organize-analysis-venue-work`

背景：
- 用户只配置了“首次 / SOTA / first”等模板，但弱提及结果中仍出现 `experiment` 等模板外高亮词。
- 根因是结构化结果统一走全局证据标签派生：即使 finding 是 `grouped_literature_mention` 或 `keep=false`，只要原文里有 `experimental`、`state-of-the-art` 等词，也会被派生成 `detailed_comparison` / `sota_evaluation`，并进入高亮。

本次处理：
- `derive_evidence_labels()` 对弱提及和组引用只保留弱标签，例如 `survey_or_related_work` / `negative_or_limitation`。
- `derive_highlight_keywords()` 对弱提及和组引用不再自动派生高亮关键词，也不会保留模型给出的强关键词。
- 单篇论文结果详情中，弱提及和组引用的强度分固定为 0，避免“弱提及”明细里仍显示高分。

当前策略：
- 模板仍是“优先关注”，不是严格白名单；真正强证据仍可由全文分析识别出模板外的可靠证据。
- 但弱提及 / 组引用不再因为上下文里有强词而显示成强证据。

## 2026-05-31：加强全文分析的引用编号锚定

分支：`codex/organize-analysis-venue-work`

背景：
- 单篇论文全文分析中，模型会看到同一段内的组引用和相邻引用，例如目标论文是 `[16]`，但正向描述实际连接到 `[18]`。
- 页面展示的是宽上下文片段，容易让用户误以为自定义关键词没有生效，或模型把邻近句子的评价误归给目标论文。

本次处理：
- `process_citing_paper()` 会把候选段落定位得到的目标引用编号和目标参考文献条目写入 `analyze_payload.json`。
- 单模型、全文直读和旧两阶段分析 prompt 都新增“目标引用锚定信息”，要求强标签只能归因给同一句、同一子句或明确承接到目标编号/标题/别名的内容。
- 明确要求不能把其他编号或邻近句子的 positive / SOTA / first / based on 等评价转嫁给目标论文。
- 分析模板 UI 增加说明：自定义关键词只影响后续分析关注点，结果页只高亮原文实际命中且锚定到目标论文的词。

当前策略：
- 已生成的 `fulltext_analysis.json` 不会自动重算；需要重新分析对应论文，新的引用锚定 prompt 才会生效。
- 如果目标论文只在组引用中出现，系统应优先保守输出 `grouped_literature_mention` / `weak_body_mention`，而不是强证据。

## 2026-05-31：保留自定义分析需求里的显式关键词

分支：`codex/organize-analysis-venue-work`

背景：
- 用户在自定义分析需求中写入 `seminal`、`开创性` 等词后，已编译模板只显示系统固定关键词，容易误以为自定义关键词没有生效。

本次处理：
- 自定义模板编译时会提取并保留显式关键词，例如 `seminal`、`开创性`、`baseline`、`based on` 等。
- “查看当前已编译模板”同时展示关键词和编译后的要求，方便确认后续全文分析会关注什么。
- 旧会话加载时会按当前编译器重新同步 `compiled_templates`，避免继续展示历史保存的旧关键词列表。

当前策略：
- 已经完成的全文分析结果不会因为模板变化自动重算；保存模板后需要重新分析目标论文，新的关键词才会影响后续结果。

## 2026-05-31：给自定义分析需求增加写法提示

分支：`codex/organize-analysis-venue-work`

背景：
- 分析模板支持逐行输入自定义需求，但页面没有说明应该写什么，容易让用户不知道如何描述“想找的证据”。

本次处理：
- 单篇论文分析和学者影响力分析的“自定义需求”输入框都增加写法说明。
- textarea 增加可直接照抄的 placeholder 示例，覆盖第三方正向评价、baseline/实验对比、方法来源/拓展、首次/开创性评价。
- 增加可展开的“自定义需求怎么写”说明，提示一行一个目标、可写关键词、可写排除条件。

当前策略：
- 提示只影响页面写法引导，不改变模板编译和全文分析逻辑。

## 2026-05-31：修正文件名式标题导致引用发现失败

分支：`codex/organize-analysis-venue-work`

背景：
- 用户用 `MoirTracker_Continuous_Camera-to-Screen_6-DoF_Pose_Tracking_Based_on_Moir_Pattern` 这类文件名/slug 作为目标论文查询时，引用发现可能返回 0 篇或定位到错误目标。
- 根因是检索 query 带下划线且缺少重音/标点；Semantic Scholar 可在正常空格标题下找到目标，但 OpenAlex fallback 对低相似度标题可能误命中其它 “All You Need” 论文。
- 二次复查发现，部分环境下 Semantic Scholar 失败后会走 OpenAlex fallback；OpenAlex 对 `MoirTracker` / `Moir Pattern` 这种少了 `é/e` 的标题更严格，会直接搜不到目标。
- 三次复查发现，服务器环境可能强制 `ACADEMIC_IMPACT_CITATION_SOURCE=scopus`；Scopus 对该文件名式标题会返回空 entry，旧逻辑没有验证元数据完整性，导致 `ok=true` 但目标论文为空。

本次处理：
- 标题检索前把文件名式下划线 query 规范化为空格标题，并去掉末尾 `.pdf`。
- OpenAlex 标题搜索从单条结果改为多条候选，并加入标题相似度校验。
- 低相似度 OpenAlex 结果会被拒绝，避免生成看似成功但目标论文错误的会话。
- OpenAlex fallback 增加窄范围标题变体：`MoirTracker` / `Moir Pattern` 会额外尝试 `MoiréTracker` / `Moiré Pattern`，但仍需通过标题相似度校验。
- Scopus 目标解析增加有效性校验：没有标题且没有 DOI/EID/Scopus ID 的 entry 不再算成功；标题搜索也会尝试 Moiré 变体并做相似度校验。
- 增加回归测试覆盖下划线标题规范化、OpenAlex 低相似度拒绝、Moiré 标题变体、OpenAlex 链接生成和 Scopus 空元数据拒绝。

当前策略：
- DOI 仍是最稳入口；例如 `10.1109/JSAC.2024.3414619` 可以直接定位 MoiréTracker。
- 当 Semantic Scholar 限流或环境强制 OpenAlex/Scopus 时，系统也应尽量定位该 MoiréTracker 文件名式输入；如果仍没有可靠标题命中，系统应失败并提示，而不是静默创建空目标或错误目标。

## 2026-05-31：把学者强证据能力复用到单篇论文分析

分支：`codex/organize-analysis-venue-work`

背景：
- 学者影响力分析已经具备分析模板、强引用证据过滤和亮点评价卡片。
- 单篇论文分析仍主要展示基础全文分析结果，缺少可汇报证据的统一筛选和导出。

本次处理：
- 单篇论文 session 增加分析模板状态，复用 `scholar_evidence_templates.json` 的内置模板，并支持逐行自定义需求。
- 全文分析时把当前模板编译为 prompt fragment，传入 `process_citing_paper`，让单篇论文分析也能优先找首次评价、详细对比、理论基础、方法来源等证据。
- 单篇论文结构化 finding 复用 `scholar_evidence.py` 的标签、关键词高亮、强度评分和可汇报强证据过滤逻辑。
- 新增单篇论文亮点评价卡片，并导出 `highlight_cards.csv` / `highlight_cards.md`。
- 页面新增“分析模板”和“亮点评价卡片”模块，列表筛选里的“强表述命中”升级为“强证据”。

当前策略：
- 普通 related work 组引用仍保留在结构化判断明细里，但不会进入亮点评价卡片。
- 单篇论文如果缺少目标论文作者信息，自引状态会保持未知；一旦元数据提供目标作者或配置排除作者，就会参与强证据判断。

## 2026-05-30：过滤弱背景提及，避免误入强引用证据

分支：`codex/organize-analysis-venue-work`

背景：
- 全文分析会保留一些弱提及，例如 related work 中的组引用或背景综述。
- 这些弱提及对排查“是否被引用”有用，但不应默认出现在“强引用证据”列表里。
- 典型误例是 `grouped_literature_mention`、`background`、`low` 强度、低分数的组引用，被页面显示成强引用证据。

本次处理：
- 新增统一判断函数 `is_reportable_strong_evidence`，把强引用证据的展示口径集中到 `scholar_evidence.py`。
- 新分析入池时过滤 `grouped_literature_mention`、`weak_body_mention`、低分数、低强度和纯背景综述项。
- 页面、报告、亮点评价卡片和统计摘要统一使用可汇报强证据集合；旧 session 中已有弱项也不会默认显示。
- 保留早期 session 的兼容逻辑：没有新评分字段但有 method、baseline、positive、Fellow、长引用等强信号的旧证据仍可显示。

当前策略：
- 弱背景提及仍保留在全文分析结果文件中，方便诊断模型为何看到该引用。
- “强引用证据”只展示可支撑汇报的中高强度证据；普通 related work 组引用应留在分析详情，不进入强证据列表。

## 2026-05-30：用 NASA CM 对照补强 IEEE Fellow 和部分 venue registry

分支：`codex/organize-analysis-venue-work`

背景：
- Jingyi Ning 的 NASA CitationMaster 导出中，荣誉引用命中比本项目更全。
- 对照后发现主要不是分析逻辑问题，而是本地 registry 覆盖不足：
  - 本地 IEEE Fellow 只有约 2600 条，缺少 Jun Luo、Tao Gu、Xin Wang、Z Chen 等近期 Fellow。
  - 本地暂不支持 Academia Europaea 标签，导致 Daqing Zhang 的 AE 命中无法归类。
  - 本人论文 venue registry 缺少 INFOCOM、ICDCS、SECON、TOSN、WoWMoM、ICCCN 等网络/移动计算常见 venue。

本次处理：
- 新增 `data/reference/source_lists/ieee_fellows_academic_awards.json`，从 `xiaohk/academic-awards` 的 IEEE Fellows JSON 生成约 7490 条本地 source-backed seed。
- 刷新 `person_tag_registry.json`，IEEE Fellow 条目扩展到约 7994 条。
- 新增 `academia_europaea_member` tag type，并加入 Daqing Zhang 的 Academia Europaea 官方页面 seed。
- 补充网络/移动计算 venue aliases：
  - INFOCOM：CCF A
  - ICDCS / SECON / TOSN：CCF B
  - WoWMoM / ICCCN：CCF C
- 增加回归测试，锁定近期 IEEE Fellow seed、AE tag 支持和新增 venue 匹配。

对照结果：
- Jingyi Ning 的 NASA CM 荣誉引用 CSV 中 21 条记录，补强后本地 registry 可按同类标签匹配 21/21。
- 本人论文 venue 对照中，NASA CM 标为 CCF 的 INFOCOM / ICDCS / SECON / TOSN / WoWMoM / ICCCN 已能被本地 registry 命中。

当前策略：
- NASA CM 页面也提示 “Results may contain name collisions”，所以不能把所有 name-only 命中都当作最终事实。
- 本项目仍保留风险标记和人工/证据复核入口；registry 补全解决“查不到”，不等于解决“同名一定正确”。

## 2026-05-27：适配 98k 本地模型上下文，恢复全文分析默认输入预算

分支：`codex/organize-analysis-venue-work`

背景：
- 服务器端本地模型已用 `-c 98304` 启动，能够承载更长的全文分析请求。
- 如果只在服务器上手改代码，后续 `git pull` 容易产生冲突或被覆盖。

本次处理：
- 将 `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS` 的代码默认值恢复到 90000。
- 保留上一轮新增的截断提示、HTTP 400 response body 读取和 `context_length_exceeded` 页面提示。
- 更新回归测试，锁定当前默认预算为 90000，并继续验证超预算时会加入截断提示。

当前策略：
- 98k 上下文模型可直接使用代码默认值。
- 如果换回 32k 上下文模型，需要在 `.env.local` 里显式设置 `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS=45000` 或更低。

## 2026-05-27：识别全文分析请求上下文溢出

分支：`codex/organize-analysis-venue-work`

背景：
- 批量分析长 PDF 时，本地 OpenAI-compatible 服务返回 400。
- 服务端日志显示 `request (43127 tokens) exceeds the available context size (32768 tokens)`，根因是全文直读 prompt 超过模型上下文，而不是 PDF 上传或全文提取失败。

本次处理：
- 支持通过 `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS` 控制全文直读输入预算，给 system prompt、模板片段和模型输出留出上下文余量。
- 全文直读 prompt 被截断时，会明确加入“全文文本已按字符预算截断”的系统提示，便于后续排查。
- `classify_request_exception` 会读取 HTTPError 的 response body，识别 llama.cpp / local server 返回的 context exceeded 细节。
- 页面失败建议对 `context_length_exceeded` 给出具体处理方式：调低 `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`，或用更大上下文启动本地模型服务。
- 增加回归测试，锁定默认全文预算、context exceeded 分类和页面动作建议。

当前策略：
- 如果使用 32k 上下文本地模型，应显式调低 `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`。
- 如果本地模型以 64k / 128k 上下文启动，可以使用较高输入预算，但需要同步评估显存、速度和模型长上下文质量。

## 2026-05-24：修正出版社页面链接误指向 Scopus API

分支：`codex/organize-analysis-venue-work`

背景：
- 高价值引用队列的“打开出版社页面”有时会打开 Elsevier / Scopus API XML。
- 这类 URL 来自 Scopus 元数据里的机器接口，不是给浏览器阅读的论文落地页。

本次处理：
- 页面生成 publisher URL 时识别 `api.elsevier.com/content/`、OpenAlex API、Crossref API 等机器接口。
- 如果有 DOI，优先打开 `https://doi.org/<doi>`，让浏览器跳到真正出版社页面。
- 如果没有 DOI 但有 Scopus ID，则回退到 Scopus 可浏览记录页。
- 增加回归测试，锁定 Scopus API URL 不再直接显示给用户点击。

当前策略：
- 自动下载仍可使用 `source_url` 做候选 PDF 抽取。
- “打开出版社页面”只负责给用户可阅读、可登录、可手动下载的页面。

## 2026-05-24：把汇报需求落到亮点评价工作流

分支：`codex/organize-analysis-venue-work`

背景：
- 会议反馈强调系统要从“统计引用数量”转向“找出可汇报的高质量第三方引用评价”。
- 汇报材料需要原文证据、细分类标签、可复制总结句，并且要能排除自引、本组作者和长期合作者。
- 论文全文分析前，用户还需要用模板表达“找首次评价 / 大量比较 / 理论基础 / 方法来源”等具体需求。

本次处理：
- 新增内置分析模板 `data/reference/scholar_evidence_templates.json` 和模板编译模块 `skills/scholar_impact_analyzer/evidence_templates.py`。
- 学者会话默认保存 `analysis_templates` 和 `exclusion_profile`，页面新增：
  - 分析模板配置
  - 排除作者 / 本组作者配置
  - 审稿意见 / 外部评价导入
- 高价值引用队列新增第三方口径：
  - 当前学者本人
  - 被引目标论文作者
  - 用户维护的额外排除作者
  - 用户维护的额外排除机构
- 强引用标签扩展为更贴近 PPT 的类型：
  - SOTA / 最先进
  - 代表性工作
  - 详细对比
  - 方法拓展
  - 持续跟踪引用
  - 审稿意见亮评
- 新增“亮点评价卡片”：
  - 自动筛出非自引且强度足够的证据
  - 汇总标签、强度分、原文高亮、汇报句和持续引用线索
  - 支持导出 `highlight_cards.csv` 和 `highlight_cards.md`
- 全文分析 prompt 会接收当前模板片段，让模型优先寻找用户指定的证据类型。
- 新增/更新回归测试，覆盖模板编译、第三方排除、亮点评价导出、审稿意见导入和 prompt 传递。

当前策略：
- 自引、本组合作者和排除机构不会从队列中硬删除，而是降权并标记，方便解释和回查。
- 亮点评价卡片只收录当前判定为第三方引用、且强度分达到阈值的证据。
- 审稿意见导入只作为补充证据进入强引用证据池，不混入 citation edge。

后续建议：
1. 如果后续继续补充 PPT 模板，可以优先扩展 `scholar_evidence_templates.json`，不要把规则写死在页面里。
2. 如果需要更精确的“本组作者”识别，下一步应把排除列表保存成可复用的 profile，而不是只存在单个 session。
3. 若要自动生成 PPT 文案，可基于 `highlight_cards.md` 继续做二次摘要。

## 2026-05-23：机构登录下载辅助流程

分支：`codex/organize-analysis-venue-work`

背景：
- IEEE Xplore、ACM DL 等出版社页面常返回登录/订阅页，系统不能也不应保存学校账号并自动登录。
- 之前自动下载失败后只显示通用失败原因，用户需要自己判断是不是机构权限问题。

本次处理：
- PDF 下载失败分类新增 `requires_institution_login`，识别 IEEE/ACM/Springer/Elsevier 等常见受限页面、`denied`、`access denied`、`institutional sign in` 等信号。
- 高价值引用队列新增出版社入口链接，优先使用 `source_url`，否则使用 DOI 页面。
- 队列准备状态对机构登录失败显示“需要机构登录下载 PDF”，方便用户打开出版社页、手动登录下载，再刷新本地 PDF 索引自动命中。
- `pdf_download_report.csv` 增加 `publisher_url` 字段，方便批量整理需要人工登录处理的论文。

当前策略：
- 不自动保存账号、密码或浏览器 cookie。
- 不批量模拟机构登录下载付费 PDF。
- 系统只负责识别“需要机构登录”、提供入口、下载后本地匹配和绑定。

## 2026-05-23：修复高价值队列自引误标排查结果

分支：`codex/organize-analysis-venue-work`

背景：
- 服务器已更新到“把当前学者加入自引判断”的版本后，部分高价值队列项仍显示 `self_citation:non_self`。
- 典型例子是同一篇引用论文命中多篇目标论文时，页面展示的是合并后的队列项。

本次处理：
- 自引判断会先拆分 `Jingyi Ning; Lei Xie` 这类被保存成单个字符串的作者列表，避免作者元数据格式不统一导致误判。
- 自引姓名签名支持英文姓名缩写倒排，例如 `Jingyi Ning` 可以匹配引用作者里的 `Ning J.`。
- 自引姓名签名会忽略 DBLP 风格的四位数字后缀，例如 `Lei Xie 0004`。
- 队列合并多条引用边时，只要任意一条边判为自引，合并后的队列项保守显示为自引。
- 增加 `scripts/debug_scholar_self_citation.py`，用于对单个高价值队列项输出：
  - 页面已存的自引状态
  - 当前代码重新计算的自引状态
  - 当前学者名、引用作者、目标论文作者、命中的边数量
- 增加回归测试覆盖：
  - 分号分隔作者字符串的自引识别
  - `Ning J.` 这类姓加首字母缩写的自引识别
  - 同一引用论文合并后自引状态优先保留

排查建议：
- 如果页面仍显示异常，优先查看对应 session 的 `data/scholar_sessions/<session_id>/session.json` 中该队列项的 `citing_authors`、`source_publication_authors`、`self_citation_status` 和 `self_citation_overlap_authors`，确认问题是在作者元数据缺失、重建未生效，还是页面缓存。

## 2026-05-23：Scopus 缩写作者补全为全称

分支：`codex/organize-analysis-venue-work`

背景：
- Scopus cited-by 列表常只返回 `dc:creator`，作者名可能是 `Ning J.` 这类缩写。
- 这种缩写既影响页面可读性，也会增加自引判断和作者标签匹配的复杂度。

本次处理：
- 在引用列表清洗阶段，如果 Scopus 结果只有明显缩写作者且引用论文有 DOI，自动用 OpenAlex DOI 详情补全作者全称。
- 补全成功后，`authors` 和 `author_details` 都使用全称作者，后续高价值队列、人物候选和自引判断直接受益。
- 增加 `scripts/enrich_scholar_citing_authors.py`，用于修补已有 scholar session 的 `citation_edges`，修补后自动重建派生统计和高价值队列。

使用方式：

```bash
python3 scripts/enrich_scholar_citing_authors.py <scholar_session_id> --dry-run
python3 scripts/enrich_scholar_citing_authors.py <scholar_session_id>
```

注意事项：
- 只在“作者列表明显不完整/缩写且有 DOI”时补全，避免对完整作者列表额外发请求。
- OpenAlex 补全失败时保留原始 Scopus 作者，不中断引用展开。

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
- 汇报需求强调系统核心不应只是引用数量统计，而是找出“别人如何评价我的工作”的第三方证据。
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
- 证据标签是可扩展集合，后续新增模板时优先改 `scholar_evidence.py` 和 prompt，不要把规则继续散落到页面里。
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
