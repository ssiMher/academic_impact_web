# 学术影响力分析项目交接说明

## 1. 先给接手人看什么

推荐按下面顺序阅读：

1. 本文档  
   先建立对当前系统状态、真实运行路径和排障入口的整体认识。
2. [学术影响力分析项目接口手册v2.md](/home/withe/.openclaw/学术影响力分析项目接口手册v2.md)  
   看完整接口、脚本职责、当前推荐调用链路。
3. [OPENCLAW_FEISHU_ARCHITECTURE.md](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/OPENCLAW_FEISHU_ARCHITECTURE.md)  
   看飞书接入的目标架构，以及为什么要走“结构化动作优先”。
4. [FEISHU_CHANNEL_SETUP.md](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/FEISHU_CHANNEL_SETUP.md)  
   看飞书渠道配置、权限、当前已打通部分和待确认部分。
5. [FEISHU_CARD_SCHEMA.md](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/FEISHU_CARD_SCHEMA.md)  
   看飞书文本/卡片展示层应该消费什么中间态。

如果接手人要继续改代码，还需要看：

- [impact_cli.py](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/impact_cli.py)
- [openclaw_bridge.py](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/openclaw_bridge.py)
- [intent_router.py](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/intent_router.py)
- [index.js](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/openclaw_plugin/index.js)
- [AGENTS.md](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/AGENTS.md)

## 2. 当前系统到底怎么跑

当前推荐链路已经调整为“agent + skill 为主，插件/卡片为辅”：

1. 用户自然语言进入 OpenClaw/飞书
2. 默认直接 `dispatching to agent`
3. agent 命中 `academic_impact_analyzer` skill
4. skill 调 `intent_router.py` / `openclaw_bridge.py` / `impact_cli.py`
5. 先返回简单文本或 markdown 摘要
6. 用户再继续下达 `refresh/download/analyze`
7. 最后再生成摘要或细节回答

目标颗粒度是：

1. 先列索引/状态
2. 再下载或刷新
3. 再分析指定论文
4. 最后给摘要

不推荐一上来就直接输出整篇“学术影响力长报告”，也不再推荐把飞书普通文本主链路强依赖在插件自然语言拦截上。

## 3. 当前真实状态

已经基本可用：

- `discover/status/refresh-probe/download/analyze` 核心链路
- `session.json` 持久化会话
- `card-state` 和 `feishu-card` 输出
- `openclaw paperimpact ...` CLI 路径
- `llama.cpp` 本地 27B 分析服务
- 飞书渠道接入和真实私聊消息收发
- `agent + skill` 自然语言主链路
- 工作区级 `AGENTS.md` + 项目级 `AGENTS.md` 约束链路
- `你能做什么 / 帮助` 会优先走项目级能力说明，不再优先回成通用 shell / coding 助手简介
- `paper_count` 现在表示“当前展示候选数”，真实总引用数应优先看 `target.citationCount` / `header.total_citation_count`，不要再把默认候选上限误说成论文总引用数
- 全文分析结果写 JSON 前会先清洗 surrogate 字符，避免 `UnicodeEncodeError: surrogates not allowed` 让整轮分析中断
- `完整引用段落 / 深度分析 / 全面分析` 会优先检查全文证据是否就绪，未就绪时应明确提示补 PDF / 补全文分析，而不是拿 citation context 硬答
- 用户说“等待下载完成 / 等分析完成”时，应只做有限轮询和状态汇报，不要中途自己去检查 PDF、读源码、装 `pdftotext` 之类的工具

仍需注意：

- 飞书当前建议 `streaming = true`，更适合长一点的分析结果。
- 飞书当前建议 `resolveSenderNames = false`，可以减少联系人权限噪声。
- 如果想让飞书真正流式显示，飞书应用还要开通并发布 `cardkit:card:write` / `cardkit:card:read`，因为当前 OpenClaw Feishu 流式实现走的是 Card Kit。
- 飞书卡片按钮和真正的卡片交互还没有完全取代文本回退路径。
- 飞书普通中文消息出现 `dispatching to agent` 现在是预期行为，不再视为默认故障。
- 某些飞书日志里的 `99991672` 是联系人权限噪声，不是当前主链路失败的根因。

## 4. 关键服务与配置

### OpenClaw Gateway

- 启动命令：`openclaw gateway run --force`
- 常看日志：`/tmp/openclaw/openclaw-YYYY-MM-DD.log`
- 主要配置：`/home/withe/.openclaw/openclaw.json`
- 当前推荐角色分工是：`deepseek` 做主控对话模型；本地 `llamacpp` 只做论文全文分析模型，不作为飞书主控回复模型

### 本地全文分析模型

- 运行方式：`llama.cpp` OpenAI 兼容服务
- 当前地址：`http://114.212.82.168:8002/v1/chat/completions`
- 当前模型：`Qwen3.5-27B-Q4_K_M.gguf`
- 当前已验证可用启动参数：`-c 32768 -np 1 -b 1024 -ub 512 -fa on -ngl 999`
- 当前已验证的上下文预算：`32768 tokens`
- `openclaw.json` 里的 `models.providers.llamacpp.models[0].contextWindow` 也应与此保持一致，当前已同步为 `32768`
- 主要用于：全文引用语义判断，不负责飞书会话级编排
- 如果日志里出现 `request (...) exceeds the available context size (8192 tokens)`：
  这表示请求太长，不是模型没启动

## 5. 关键代码入口

### 核心执行层

- [impact_cli.py](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/impact_cli.py)  
  负责 `discover/status/refresh-probe/download/analyze/card-state/feishu-card`

### OpenClaw 适配层

- [openclaw_bridge.py](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/openclaw_bridge.py)  
  负责把插件命令/会话层动作桥接到核心脚本

- [intent_router.py](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/intent_router.py)  
  负责把自然语言映射成 `list_citations/quick_analyze_target/full_analyze_target/refresh_download_status/download_by_reference/analyze_papers`

- [openclaw_plugin/index.js](/home/withe/.openclaw/workspace/skills/academic_impact_analyzer/openclaw_plugin/index.js)  
  负责 CLI / slash command / 调试辅助入口；普通自然语言已不再默认由这里拦截

## 6. 很重要：当前有运行时补丁，但不再建议把它当主链路

当前系统不只是改了工作区代码，还改过本机已安装的 OpenClaw 运行时代码。接手人必须知道这一点，否则很容易出现“文档看着对，但线上行为对不上”的情况。

当前重点补丁位置：

- `/home/withe/.npm-global/lib/node_modules/openclaw/extensions/feishu/src/bot.ts`
- `/home/withe/.npm-global/lib/node_modules/openclaw/dist/plugin-sdk/http-registry-7Lsnrxx9.js`

这些补丁原本的目的主要是：

- 让飞书私聊普通文本在进入 agent 前，先尝试命中插件命令
- 让插件支持 `matchText`，从而识别“分析一下……学术影响力”“重置会话”这类中文自然语言命令
- 给 Feishu 入口补算 `commandAuthorized`，避免自然语言插件命令被误拦成 `This command requires authorization.`

但当前推荐策略已经改变：

- 飞书普通自然语言默认直接交给 agent
- agent 再调用 `academic_impact_analyzer` skill
- 插件保留给 CLI / slash command / 手工调试
- 不再把“先命中插件命令”作为线上主依赖

这样做的实际影响：

- 影响范围不只这个 skill，而是这台机器上当前安装的 OpenClaw 运行时
- 只要 Feishu channel 走到对应代码路径，行为都会受补丁影响
- 修改后通常需要重启 gateway / Feishu 通道进程，旧进程不会自动吃到新代码
- 这些改动不在项目 git 工作区里，`git status` 看不到，必须靠文档记录
- 一旦升级或重装 OpenClaw，这些补丁很可能被覆盖掉
- 如果新版 OpenClaw 改了导出接口，旧补丁可能直接报运行时错误

当前这台机器已经出现过一次版本兼容问题：

- OpenClaw `2026.3.13`
- Feishu 入口补丁在 `bot.ts` 里调用了 `matchPluginCommand`
- 但当前 `openclaw/plugin-sdk/compat` 已不再导出这个名字
- 结果飞书日志报错：`TypeError: (0 , _compat.matchPluginCommand) is not a function`

本机已执行过一次对应修复：

- 修复时间：`2026-03-20`
- 备份目录：`/home/withe/.openclaw/runtime_backups/openclaw-2026.3.13-feishu-fix/`
- 修复文件：`/home/withe/.npm-global/lib/node_modules/openclaw/dist/plugin-sdk/compat.js`
- 修复方式：把 `matchPluginCommand` / `executePluginCommand` 重新导出到 `compat.js`，并明确接到主运行时 registry（`../registry-DtTKJfN8.js`），而不是 plugin-sdk 独立 registry
- 修复目标：让 `extensions/feishu/src/bot.ts` 里的自然语言插件分发继续可用，而不需要改动业务 skill 代码

下次如果再遇到同类问题，建议先按这个顺序检查：

1. `compat.js` 是否仍导出 `matchPluginCommand`
2. `bot.ts` 是否仍从 `openclaw/plugin-sdk/compat` 导入该函数
3. OpenClaw 是否刚升级过，导致旧补丁与新导出表不一致
4. gateway / Feishu 进程是否已经重启并加载了新代码

这说明运行时补丁不是“改完就永远稳定”，而是必须跟 OpenClaw 已安装版本一起维护。

交接时要明确说明：

- 如果以后升级/重装 OpenClaw，这些补丁可能会丢失
- 升级后如果又要启用“插件自然语言拦截”实验路径，再检查这里
- 如果出现 `matchPluginCommand is not a function` 这类错误，优先怀疑“补丁仍在，但导出接口已经变了”
- 做运行时补丁前，最好先备份原文件或至少记录当前 OpenClaw 版本号、补丁文件路径、修改目的
- 回滚最简单的方式通常是恢复原文件，或重装当前版本 OpenClaw 后再按新版本接口重打补丁

## 7. 最小回归测试

### 命令行回归

```bash
openclaw paperimpact --help
openclaw paperimpact discover "DeepSeek-OCR 2: Visual Causal Flow"
openclaw paperimpact status <session_dir>
openclaw paperimpact card <session_dir>
```

### 飞书回归

推荐按这个顺序测：

1. `想知道有哪些论文引用了 DeepSeek-OCR 2: Visual Causal Flow`
2. `下载第2篇、第3篇`
3. `分析 DeepSeek-OCR 2: Visual Causal Flow 的学术影响力`
4. `全面分析 DeepSeek-OCR 2: Visual Causal Flow 的学术影响力`
5. `论文 Penguin-VL 是怎么引用 DeepSeek-OCR 2: Visual Causal Flow 的`

理想行为：

- 日志允许出现 `dispatching to agent`
- 不应该再出现 `This command requires authorization.`
- agent 应按 skill 调用本地 Python 工作流，而不是自由发挥长报告
- 先返回会话摘要/候选列表/状态，再按下载、刷新、分析逐步推进

## 8. 出问题先看哪里

### 现象 1：飞书回复 `This command requires authorization.`

优先检查：

- `openclaw.json` 里的 `channels.feishu.allowFrom`
- 插件是否又重新开启了自然语言拦截
- `openclaw_plugin/index.js` 里 `naturalLanguageIntercept` 是否被设回启用

### 现象 2：飞书消息直接 `dispatching to agent`

优先检查：

- 这在当前简化方案里是正常现象
- 重点要看 agent 后续有没有调用 skill，而不是看它是否先命中插件
- 只有当 agent 完全没走 skill、直接自由发挥时，才算真正异常

### 现象 3：回复格式退回长篇自由文本

优先检查：

- 是否没有先走 `card-state/status`
- 是否又回到了 agent 自由生成
- `intent_router.py` 是否正确抽取了 query 和动作
- 当前结构化结果里是否已经有 `reply_markdown`，但 agent 没有优先使用

### 现象 4：新论文请求被串到上一个论文任务里

优先检查：

- 当前飞书私聊 session 是否已经积累了很长的历史
- 用户这次是不是明确换了一个新论文标题，但 agent 还沿用了旧 session
- `AGENTS.md` / `SKILL.md` 里“新论文默认新建 session”的规则是否已生效

判断原则：

- `继续分析前三篇` 这类话，应该复用旧 session
- `分析一下 Training-Free Group Relative Policy Optimization 的引用情况` 这类话，应该视为新论文新任务
- 如果明显串题，先用 `/reset` 或“重置当前会话”清掉当前飞书 session 再测
- `重置当前会话 / 清空当前会话 / 重置会话` 现在应当始终能命中专用 reset 命令，不再依赖学术插件的自然语言拦截开关
- 飞书普通自然语言主链路现在应是 `agent 自主判断 + skill/tools 执行`；如果又被改回“先硬映射成 action 再执行”，串题和假完成的风险会重新升高
### 现象 5：`streaming = true` 但飞书还是整段输出

优先检查：

- `/tmp/openclaw/openclaw-YYYY-MM-DD.log` 里是否出现 `Create card request failed with HTTP 400`
- 飞书应用是否已开通 `cardkit:card:write` / `cardkit:card:read`
- 新权限加完后是否已经“创建版本 + 发布”

判断原则：

- 当前 OpenClaw Feishu 流式不是普通文本流，而是 Card Kit streaming card
- 所以只改 `openclaw.json` 里的 `streaming = true` 还不够，飞书应用权限也必须到位

### 现象 4：agent 说“本地 27B 没启动”，但模型日志明明在跑

优先检查：

- `8002` 服务日志里是否已经出现 `server is listening`
- 是否已经有 `POST /v1/chat/completions ... 200`
- 是否同时出现了 `request (...) exceeds the available context size (8192 tokens)`

判断原则：

- 如果有 `200`，说明服务是活的
- 如果有 `available context size`，真实问题是提示词过长，不是服务没启动
- 现在桥接层已经把这类错误改成“上下文超长”提示，不应再误报成“请先确认 27B 服务是否可达”

## 9. 交接时口头一定要补充的事

1. 现在最重要的是“稳定结构化流程”，不是继续堆更长的总结文案。
2. 飞书入口和 OpenClaw 网页入口不完全一样，网页里的 `new` 和飞书里的“重置会话”不是一套机制。
3. 如果要继续做卡片化，优先围绕 `card-state` 中间态推进，不要直接让飞书层消费整个 `session.json`。
4. 现在默认路线是 `Feishu -> agent -> skill -> Python 工具`，不要轻易再把主链路切回“插件自然语言拦截”。
5. `intent_router.py` 更适合 CLI / slash command / 本地调试；飞书普通自然语言不建议继续依赖它做主链路硬路由。
6. 如果后面要发版或升级 OpenClaw，先把运行时补丁做成正式插件化/扩展化能力，否则容易回归。
7. 当前推荐的“极简模式”是：插件只保留 reset 和调试命令，普通学术请求尽量直接交给 OpenClaw agent + skill，不要再额外叠一层入口编排。
8. 当前默认引用列表已从 10 提到 20；如果用户不特别指定数量，系统应优先返回 20 篇候选而不是 10 篇。
9. 现在已经有两个正式入口可用：
   - `capabilities`：输出当前助手支持的功能说明
   - `attach-pdf / attach_local_pdf`：把本地 PDF 绑定到某篇候选论文，后续按 `local_available` 继续分析
