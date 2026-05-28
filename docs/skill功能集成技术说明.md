# Skill 功能集成技术说明

> 面向对象：第一次接触本项目、不了解 Skill / Tushare / Trace / Langfuse 的新同学  
> 目标：用尽量直白的方式讲清楚当前 Skill 是怎么接入对话 Agent 的、现在已经做到哪一步、一次真实问题是怎么跑起来的、出了问题去哪里查

---

## 1. 这份文档讲什么

这份文档专门讲本项目里“**聊天对话 + 金融 Skill + Tushare 工具 + 记忆系统 + Trace 观测**”这一整条链路。

现在系统的工作方式已经不是：

- 用户提问
- 大模型直接凭上下文回答

而是更像一个“有分工的投研助手”：

- 用户提问
- 系统先判断这是不是某个金融场景
- 如果是，就先选择合适的 Skill
- Skill 再去调真实工具拿证据
- 最后由模型把“用户问题 + 记忆 + 画像 + 工具结果”组织成自然语言回答

一句话理解：

> 现在的 Agent 遇到金融问题，优先先查证据再回答；只有普通闲聊才直接走普通聊天路径。

---

## 2. 先理解几个最重要的概念

### 2.1 什么是 Skill

这里的 Skill 可以理解成“系统已经约定好的专业处理方式”。

当前运行时真正会进入的能力入口，分成两种“自动路由结果”加一种“用户显式选择”：

- `fallback`
- `tushare-data`
- `financial-sop`（仅当用户显式选择某个 SOP skill 时进入）

它们的含义可以先这样记：

- `fallback`：普通聊天，不查金融数据
- `tushare-data`：旧的通用金融数据链路，适合“先判断问题类型，再临时规划工具”的场景
- `financial-sop`：新的标准化业务 Skill 链路，适合“场景明确、操作步骤比较固定”的高频投研问题

所以现在不是“让路由器直接三选一”，而是：

- 路由器只在 `tushare-data` 和 `fallback` 二选一
- 用户如果从前端面板显式选了 SOP，则直接进入对应 `financial-sop`

三条入口都还存在，但 SOP 入口已经从“LLM 自主决定”切成“用户显式决定”。

### 2.2 什么是 `selected_skill`、`selected_skill_family`、`skill_name`

这三个字段最容易混。

可以这样理解：

- `selected_skill`：这次最终走哪条入口
- `selected_skill_family`：这次属于哪一类能力家族
- `skill_name`：如果走的是 `financial-sop`，具体命中的那个业务 Skill 是谁

比如：

```json
{
  "selected_skill": "financial-sop",
  "selected_skill_family": "financial-sop",
  "skill_name": "etf-screen"
}
```

它表示：

- 这次不是普通聊天
- 也不是旧的 `tushare-data`
- 而是进入了新的 SOP Skill 家族
- 且具体命中了 `etf-screen`

### 2.3 什么是 `analysis_mode`

`analysis_mode` 可以理解成“这次分析任务的类型标签”。

在旧的 `tushare-data` 链路里，它主要表示：

- `general_chat`
- `single_stock_data`
- `single_stock_fundamental`
- `sector_market`
- `stock_selection`

在新的 `financial-sop` 链路里，它通常就是 `skill_name` 的下划线版本，比如：

- `fund-compare` -> `fund_compare`
- `etf-screen` -> `etf_screen`
- `stock-first-pass` -> `stock_first_pass`

所以今天的系统已经不是“只靠 `analysis_mode` 识别全部业务”，而是：

- 老链路主要靠 `analysis_mode`
- 新链路主要靠 `skill_name`

### 2.4 什么是 Tool

Tool 就是真正查数据的函数。

比如：

- 查股票行情
- 查财务指标
- 查基金净值
- 查 ETF 份额
- 查板块快照
- 查板块成分股

Skill 决定“这类问题该怎么做”，Tool 决定“具体调哪个数据接口”。

### 2.5 什么是 Planner

Planner 是“工具计划器”。

它不直接回答问题，而是先决定：

- 这个问题需要哪些工具
- 哪些工具是必须的
- 哪些工具只是补充
- 如果是 SOP Skill，要不要按 spec 固定步骤执行

例如用户问：

```text
宁德时代这份财报怎么看，值不值得继续跟踪？
```

系统通常会倾向先拿：

- 市场数据
- 财务指标
- 利润表
- 资产负债表
- 现金流量表

然后再生成解释。

---

## 3. 当前整体架构

### 3.1 总流程

```text
前端输入问题
  ->
backend/routers/chat.py
  ->
backend/services/chat_service.py
  ->
读取 STM / LTM / 用户画像 / 最近几轮消息
  ->
route_chat_skill()
  ->
若用户显式传 sop_skill_id，则直接进入对应 financial-sop
  ->
否则由 route_chat_skill() 只在 fallback / tushare-data 中二选一
  ->
execute_skill()
  ->
planner 生成工具计划
  ->
执行工具调用
  ->
skill_evidence 做证据校验
  ->
模型基于 记忆 + 画像 + 工具结果 生成最终回答
  ->
保存 assistant 消息
  ->
触发 LTM 入队 / STM 压缩 / trace 写入
```

### 3.2 现在是“二路自动路由 + 用户显式 SOP”

这是当前最关键的认知点。

#### 第一层：旧通用链路 `tushare-data`

适合这些问题：

- 查单只股票近期走势
- 查单只股票财务指标
- 查板块行情
- 做一类宽泛的金融数据检索

它的特点是：

- 更像一个“通用金融数据助手”
- 先根据 `analysis_mode` 做工具规划
- 再走确定性执行或 agent 执行

#### 第二层：用户显式选择的 SOP 链路 `financial-sop`

适合这些“问题模式比较稳定”的高频场景：

- 两只基金/ETF 对比
- ETF 推荐与筛选
- 单股首轮研判
- 板块热点简报
- 涨跌/异动原因解释

它的特点是：

- 每个 Skill 都有自己的 `SKILL.md + skill_spec.yaml`
- 工具白名单更严格
- 降级策略更明确
- 前端用 `sop_skill_id` 显式指定后，后端会直接构造 SOP 决策，跳过 LLM 对 SOP 的判断
- 更适合做工业化、可观测、可治理的业务场景

### 3.3 现在有哪些 Skill 已经落地

当前仓库里已经存在并能被发现的 `financial-sop` skills 有：

- `fund-compare`
- `stock-first-pass`
- `sector-hotspot-brief`
- `etf-screen`
- `market-move-explain`

对应目录在：

- [fund-compare](../Financial-MCP-Agent/src/skills/fund-compare)
- [stock-first-pass](../Financial-MCP-Agent/src/skills/stock-first-pass)
- [sector-hotspot-brief](../Financial-MCP-Agent/src/skills/sector-hotspot-brief)
- [etf-screen](../Financial-MCP-Agent/src/skills/etf-screen)
- [market-move-explain](../Financial-MCP-Agent/src/skills/market-move-explain)

如果用一句话概括当前进度：

> 旧的 `tushare-data` 已经能覆盖通用金融数据问答；新的 `financial-sop` 已经开始承接高频业务场景，并且已经落地了 5 个可发现的专业 Skill。

---

## 4. 关键文件都在哪

### 4.1 对话总调度层

#### [chat_service.py](../backend/services/chat_service.py)

这是整个聊天模式的总入口。

它负责：

- 保存用户消息
- 读取用户画像和长短期记忆
- 构造路由上下文
- 校验用户是否显式传入 `sop_skill_id`
- 若未显式选择 SOP，再调 `route_chat_skill()`
- 调 `execute_skill()`
- 保存 assistant 消息
- 触发 LTM 入队和 STM 压缩
- 记录 root trace 和最终指标

对小白来说，可以把它理解成“总导演”。

### 4.2 Skill 注册层

#### [skill_registry.py](../Financial-MCP-Agent/src/skills/skill_registry.py)

它负责统一管理 Skill 元数据。

现在它做的不只是读取 vendor 内容，还包括：

- 扫描工作区里的 Skill
- 读取 `SKILL.md`
- 读取 `skill_spec.yaml`
- 返回 discoverable 的 `financial-sop` skills
- 提供 reference 检索

你可以把它理解成“技能目录 + 技能资产加载器”。

### 4.3 Skill 路由层

#### [skill_router_node.py](../Financial-MCP-Agent/src/agents/skill_router_node.py)

它负责判断：

- 是否需要实时金融数据
- 自动路由时走 `fallback` 还是 `tushare-data`
- 如果用户显式选了 SOP，对应的 `SkillRouteDecision(route="sop", skill_id=...)` 会由程序构造，而不是由这里的 LLM 输出

自动路由阶段现在只需要输出很小的二选一 JSON：

```json
{"route":"tushare"}
```

或：

```json
{"route":"fallback"}
```

对小白最重要的是记住：

- 自动路由器现在不再直接决定 SOP
- `sop_skill_id` 才是 SOP 入口的唯一显式触发方式
- 进入执行器前，系统仍会统一整理成兼容的 `route_trace`

### 4.4 Skill 执行层

#### [skill_executor_node.py](../Financial-MCP-Agent/src/agents/skill_executor_node.py)

这是整个 Skill 运行时最核心的执行器。

它负责：

- 根据路由结果决定执行路径
- 执行旧的 `tushare-data`
- 执行新的 `financial-sop`
- 调 planner
- 调工具
- 校验证据
- 构建 claims 和降级记录
- 交给 synthesis 模型组织最终回答

目前这里已经明确支持三个入口：

- `fallback`
- `tushare-data`
- `financial-sop`

### 4.5 规划层

#### [tushare_reference_planner.py](../Financial-MCP-Agent/src/agents/tushare_reference_planner.py)

这是旧通用链路 `tushare-data` 的 planner。

它负责根据：

- 用户问题
- `analysis_mode`
- 当前可用工具开关

输出“建议调用哪些工具”的计划。

它今天依然重要，但已经不是唯一 planner 了。

#### [skill_spec_planner.py](../Financial-MCP-Agent/src/agents/skill_spec_planner.py)

这是新 SOP 链路用的 planner。

它会根据：

- `skill_name`
- `skill_spec.yaml`
- 用户问题里解析出的实体

生成更固定、更可控的工具计划。

这也是 `financial-sop` 和旧 `tushare-data` 的最大区别之一：

- 旧链路更通用、更动态
- 新链路更标准化、更像 SOP

### 4.6 证据校验层

#### [skill_evidence.py](../Financial-MCP-Agent/src/agents/skill_evidence.py)

负责判断：

- 工具是否真的成功返回
- 返回是否为空
- 标的是不是对的
- 当前问题要求的证据是不是够了

这是防止“模型看起来回答得很像，但其实没证据”的关键闸门。

### 4.7 Tool 层

#### [chat_tushare_tools.py](../Financial-MCP-Agent/src/tools/chat_tushare_tools.py)

这是给 agent 和 executor 真正调用的工具层。

它负责：

- 暴露股票、基金、ETF、板块、指数等工具
- 参数规范化
- 股票代码 / 基金名称解析
- 工具调用 trace 记录
- 给证据链补充 `evidence_id`、耗时、来源等信息

### 4.8 Trace 与导出层

#### [skill_trace.py](../Financial-MCP-Agent/src/tools/skill_trace.py)

这是本地 trace 主入口。

它负责：

- 统一生成 `trace / span / event`
- 写入本地 JSONL
- 维护 trace 上下文
- 注册 exporter
- 按开关决定是否把数据导出到 Langfuse

#### [langfuse_exporter.py](../Financial-MCP-Agent/src/tools/trace_exporters/langfuse_exporter.py)

这是 Langfuse 适配层。

它负责把本地 trace 契约映射成 Langfuse 能展示的 trace / span / event 结构。

---

## 5. 当前有哪些 Skill 场景已经能测

面向新同学，可以先把现在的业务能力记成两类。

### 5.1 旧通用链路 `tushare-data`

现在仍然能覆盖：

- 单股行情问答
- 单股财务/基本面问答
- 板块市场概览
- 一般性的基金/选股类检索

这条链路更像“万能金融数据助手”。

### 5.2 新 SOP 链路 `financial-sop`

当前已落地的高频场景有：

#### `fund-compare`

适合：

- 比较两只基金/ETF/LOF
- 问“哪个更适合我”

示例：

```text
对比华安黄金ETF和博时黄金ETF，哪个更适合稳健投资者？
```

#### `stock-first-pass`

适合：

- 单股首轮研判
- 财报快读
- 值不值得继续跟踪

示例：

```text
宁德时代这份财报怎么看，值不值得继续跟踪？
```

#### `sector-hotspot-brief`

适合：

- 板块热度简报
- 板块龙头梳理
- 某个主题最近热不热

示例：

```text
近期半导体板块热度怎么样？还有哪些龙头值得关注？
```

#### `etf-screen`

适合：

- ETF 推荐
- ETF shortlist
- 主题型 ETF 筛选

它已经是通用 ETF Skill，不再只局限黄金。

示例：

```text
我想配置宽基ETF，帮我筛几个适合长期持有的。
```

#### `market-move-explain`

适合：

- 为什么涨
- 为什么跌
- 为什么异动

示例：

```text
比亚迪今天为什么跌？
```

---

## 6. 模型分层现在是怎么工作的

这套系统现在已经做了“按角色分模型”。

### 6.1 Router 模型

配置项：

- `CHAT_ROUTER_MODEL`

职责：

- 判断走哪条入口
- 在 `financial-sop` 里选哪个 `skill_name`

### 6.2 Resolver 模型

配置项：

- `CHAT_RESOLVER_MODEL`

职责：

- 做股票、基金、ETF 等实体解析

### 6.3 Synthesis 模型

配置项：

- `CHAT_SKILL_SYNTHESIS_MODEL`

默认行为：

- 留空时回退主模型 `OPENAI_COMPATIBLE_MODEL`

职责：

- 把“真实工具结果 + 用户画像 + 记忆上下文”组织成最终中文回答

这样拆分的好处是：

- 低复杂度步骤可以交给更轻的模型
- 只有最后真正要写回答时，才用更强的模型

---

## 7. 记忆、画像、STM/LTM 现在怎么和 Skill 打通

这是当前系统很重要的一点。

现在 Skill 分支已经不是一个“只查完数据就回答”的孤岛，而是和普通聊天共用一套记忆体系。

当前正确流程是：

1. 读取用户画像和语义记忆
2. 生成 `memory_context`
3. 读取 `running_summary`
4. 读取最近几轮消息，构造 `conversation_context`
5. 路由完成后，把这些上下文真正传给 `execute_skill()`
6. Skill 回复生成后，先处理画像动作，再清理展示文本
7. 保存 assistant 消息
8. 触发 LTM 入队和 STM 压缩

所以现在可以这样理解：

> Skill 对话和普通对话一样，也会参与画像更新、长记忆写入和短记忆压缩。

---

## 8. 一条真实问题是怎么跑起来的

下面用几个例子讲现在的真实链路。

### 8.1 例子一：普通闲聊

用户输入：

```text
你是谁
```

流程：

1. router 判断这是普通聊天
2. `selected_skill = fallback`
3. 走普通聊天回答
4. 保存消息
5. 继续 STM/LTM 后处理

### 8.2 例子二：贵州茅台最新财务指标

用户输入：

```text
帮我看一下贵州茅台最新财务指标
```

流程：

1. router 判断：
   - `selected_skill = tushare-data`
   - `analysis_mode = single_stock_fundamental`
2. resolver 尝试把“贵州茅台”解析成股票标的
3. `tushare_reference_planner` 生成工具计划
4. executor 直接并发取数
5. `skill_evidence` 检查市场证据和财务证据
6. 证据通过后，synthesis 模型生成最终回答

### 8.3 例子三：单股首轮研判

用户输入：

```text
宁德时代这份财报怎么看，值不值得继续跟踪？
```

流程：

1. router 判断这是 `financial-sop`
2. `skill_name = stock-first-pass`
3. `skill_spec_planner` 按 spec 规划工具
4. executor 走确定性 SOP 执行
5. 证据通过后，生成“首轮研判”回答

这类回答通常会同时关注：

- 近期表现
- 财务情况
- 主要风险
- 是否值得继续跟踪

### 8.4 例子四：板块热点简报

用户输入：

```text
近期半导体板块热度怎么样？还有哪些龙头值得关注？
```

系统通常会判断：

- `selected_skill = financial-sop`
- `skill_name = sector-hotspot-brief`

然后会优先拿：

- 板块快照
- 板块成分股
- 必要时补充指数/行情数据

### 8.5 例子五：ETF 筛选

用户输入：

```text
我想配置宽基ETF，帮我筛几个适合长期持有的。
```

现在这类问题优先走：

- `selected_skill = financial-sop`
- `skill_name = etf-screen`

而不是再全部塞回旧的 `stock_selection`。

当前 `etf-screen` 的典型执行方式是：

1. 先发现候选 ETF
2. 再补基金净值、场内行情、份额规模等支撑数据
3. 再输出 shortlist 和差异说明

### 8.6 例子六：涨跌原因解释

用户输入：

```text
比亚迪今天为什么跌？
```

这类问题优先走：

- `selected_skill = financial-sop`
- `skill_name = market-move-explain`

系统重点不是做长篇投资建议，而是解释：

- 为什么跌
- 可能的驱动因素是什么
- 当前证据是否足够支撑这个解释

### 8.7 例子七：跟进式消息“是，请查询”

用户输入：

```text
是，请查询
```

如果只看这一句，信息是不够的。

所以 router 会结合：

- `running_summary`
- 最近几轮对话

一起构造 `effective_query`。

这意味着：

- 在老会话里继续追问时，系统会继承前文
- 但这也会让路由更受上下文影响

所以如果你的目标是“测试某个 Skill 是否命中正确”，**最好新建一个会话再测**。

---

## 9. 当前主要配置项

配置主要在：

- [backend/.env.example](../backend/.env.example)
- [backend/.env](../backend/.env)
- [config.py](../backend/config.py)

### 9.1 Skill 总开关

- `ENABLE_CHAT_SKILLS`
- `ENABLE_TUSHARE_SKILLS`
- `ENABLE_TUSHARE_PLANNER`

### 9.2 子能力开关

- `ENABLE_TUSHARE_MARKET_TOOLS`
- `ENABLE_TUSHARE_INDEX_TOOLS`
- `ENABLE_TUSHARE_SECTOR_TOOLS`
- `ENABLE_FUNDAMENTAL_ANALYSIS`
- `ENABLE_SECTOR_ANALYSIS`
- `ENABLE_STOCK_SELECTION`

### 9.3 执行与模型配置

- `ENABLE_DETERMINISTIC_SKILL_EXECUTION`
- `ENABLE_TOOL_PREFETCH_CONCURRENCY`
- `CHAT_ROUTER_MODEL`
- `CHAT_RESOLVER_MODEL`
- `CHAT_SKILL_SYNTHESIS_MODEL`

### 9.4 Trace 与 Langfuse 配置

- `ENABLE_TRACE`
- `ENABLE_EVIDENCE_LINEAGE`
- `ENABLE_TRACE_ARTIFACT_REFS`
- `ENABLE_TRACE_PROMPT_CAPTURE`
- `ENABLE_TRACE_REPLY_CAPTURE`
- `ENABLE_LANGFUSE`
- `LANGFUSE_BASE_URL`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_PROJECT`
- `LANGFUSE_ENV`

对新同学来说，最重要的是先记住：

- Skill 功能开不开，看前几组 `ENABLE_*`
- Langfuse 上不上报，看 `ENABLE_LANGFUSE`

---

## 10. Trace 现在做到什么程度了

这部分是当前系统和“只靠日志打印”最大的区别。

### 10.1 本地 trace 已经不只是简单日志

现在本地 trace 已经有统一结构，核心在：

- `trace`
- `span`
- `event`

而且会写入本地 JSONL，便于后续审计和回放。

### 10.2 当前已经记录的关键信息

现在 trace 里已经不只记录“有没有调工具”，还会记录：

- 命中了哪个 `selected_skill_family`
- 具体是哪个 `skill_name`
- `analysis_mode`
- `execution_policy`
- 规划了哪些工具
- 哪些证据被接受、哪些被拒绝
- `claims`
- `degrade_history`
- `policy_violation`
- `memory_read`
- `memory_write_enqueue`
- `compaction_enqueue`

可以把它理解成：

> 不只是知道“系统答了什么”，还能知道“系统是怎么一步一步做出这个回答的”。

### 10.3 Langfuse 现在处于什么状态

当前已经有：

- 本地 trace 主契约
- Langfuse exporter
- 环境配置项
- 本机联调文档

也就是说：

- 本地 trace 已经是主记录源
- Langfuse 是额外的可视化观测面

更直白一点：

- 本地 JSONL 适合做精确审计
- Langfuse 适合看一条 trace 的完整链路、看聚合、看趋势

---

## 11. 日志和 Trace 写到哪里

当前最关键的目录是：

- [logs](../Financial-MCP-Agent/logs)

常见内容包括：

- `chat_traces.jsonl`
- `skill_trace.log`
- 其他工具/运行日志

### 11.1 常见的 trace 事件

当前比较常看的事件包括：

- `chat.router.decision`
- `chat.skill.selected`
- `chat.tool.plan`
- `chat.tool.start`
- `chat.tool.end`
- `chat.tool.error`
- `chat.claim_lineage`
- `chat.policy_violation`
- `chat.reply.completed`
- `chat.memory_write_enqueue`

### 11.2 现在日志里最值得看的字段

- `selected_skill_family`
- `skill_name`
- `analysis_mode`
- `execution_path`
- `planned_tools`
- `tool_batch_size`
- `route_confidence`
- `evidence_ok`
- `policy_violation_count`
- `claim_count`

这些字段已经足够帮助我们回答很多问题：

- 为什么没命中预期 Skill
- 为什么工具调了但答案还是保守
- 为什么系统开始降级
- 为什么这一轮没有写入记忆

---

## 12. 当前已经做到的能力和还没做完的地方

### 12.1 已经做到的

1. Skill 对话已经真正吃到了 `memory_context` 和 `running_summary`
2. Skill 对话会正常参与画像更新、LTM 入队、STM 压缩
3. 旧的 `tushare-data` 通用链路已经稳定可用
4. 新的 `financial-sop` 已经落地 5 个可发现 Skill
5. 高结构化问题已经优先走确定性执行
6. trace 已经覆盖 router、planner、tool、evidence、reply、memory 等阶段
7. Langfuse 已经具备接入和开发联调条件

### 12.2 还需要继续打磨的

1. 多轮追问场景下的路由边界还要继续优化
2. 个别板块解释类问题仍可能回落到旧的 `tushare-data`
3. Langfuse 页面展示还需要持续做字段和父子关系优化
4. 更多高频 Skill 还可以继续补充

---

## 13. 如何排查问题

如果你发现“为什么没按预期调用 Skill”“为什么回复不对劲”，按下面顺序看最稳。

### 第一步：先看命中了什么

优先查：

- `chat.router.decision`

重点看：

- `selected_skill`
- `selected_skill_family`
- `skill_name`
- `analysis_mode`
- `router_model`

### 第二步：看规划是不是合理

查：

- `chat.tool.plan`

重点看：

- `planner_type`
- `planned_tools`
- `tool_batch_size`

如果一开始规划错了，后面回答通常也会偏。

### 第三步：看工具有没有真正成功

查：

- `chat.tool.start`
- `chat.tool.end`
- `chat.tool.error`

重点看：

- 有没有超时
- 有没有空结果
- 标的是不是解析错了

### 第四步：看证据有没有通过

查：

- `chat.reply.completed`
- `chat.claim_lineage`

重点看：

- `evidence_ok`
- `claim_count`
- `accepted_evidences`
- `rejected_evidences`

如果 `evidence_ok=false`，常见原因有：

- 工具没拿到数据
- 拿到的是空数据
- 标的不匹配
- 当前问题要求多类证据，但只拿到了一类

### 第五步：看有没有发生降级

查：

- `degrade_history`
- `chat.policy_violation`

重点看：

- 为什么进入降级
- 是工具失败，还是证据不足
- 有没有工具越权或不在白名单里

### 第六步：看记忆有没有真正参与

查：

- `memory_read`
- `chat.memory_write_enqueue`
- `compaction_enqueue`

如果是多轮追问，还要特别看：

- `conversation_context`
- `effective_query`

因为有时候问题不是 Skill 本身不行，而是多轮上下文把这轮意图“带偏了”。

---

## 14. 当前测试覆盖了什么

当前和这条链路最相关的测试包括：

- [test_skill_router.py](../Financial-MCP-Agent/test_skill_router.py)
- [test_skill_executor.py](../Financial-MCP-Agent/test_skill_executor.py)
- [test_skill_evidence.py](../Financial-MCP-Agent/test_skill_evidence.py)
- [test_skill_trace.py](../Financial-MCP-Agent/test_skill_trace.py)
- [test_langfuse_exporter.py](../Financial-MCP-Agent/test_langfuse_exporter.py)
- [test_skill_registry.py](../Financial-MCP-Agent/test_skill_registry.py)
- [test_tushare_reference_planner.py](../Financial-MCP-Agent/test_tushare_reference_planner.py)
- [test_chat_tushare_tools.py](../Financial-MCP-Agent/test_chat_tushare_tools.py)
- [test_fund_compare_p1.py](../Financial-MCP-Agent/src/skills/fund-compare/tests/test_fund_compare_p1.py)

对新同学来说，可以这样理解这些测试：

- router 测试：看问题会不会命中正确 Skill
- executor 测试：看执行链路会不会跑偏
- evidence 测试：看有没有真的拿到足够证据
- trace / exporter 测试：看观测链路是不是完整

---

## 15. 新同学建议从哪开始读

如果你后面要继续开发这一块，建议顺序是：

1. 先看 [chat_service.py](../backend/services/chat_service.py)
2. 再看 [skill_router_node.py](../Financial-MCP-Agent/src/agents/skill_router_node.py)
3. 再看 [skill_executor_node.py](../Financial-MCP-Agent/src/agents/skill_executor_node.py)
4. 再看 [skill_registry.py](../Financial-MCP-Agent/src/skills/skill_registry.py)
5. 再看 [skill_spec_planner.py](../Financial-MCP-Agent/src/agents/skill_spec_planner.py)
6. 再看 [chat_tushare_tools.py](../Financial-MCP-Agent/src/tools/chat_tushare_tools.py)
7. 最后看 [skill_trace.py](../Financial-MCP-Agent/src/tools/skill_trace.py)

最重要的开发原则可以先记住一句话：

> 先保证“路由清楚、证据可靠、trace 可见”，再继续扩功能。

---

## 16. 一句话总结

如果要把整套设计讲给完全不懂的人听，可以用这句话：

> 现在的对话 Agent 遇到金融问题时，会先判断是走旧的通用数据链路，还是走新的标准化 SOP Skill；然后系统会结合用户画像和长短期记忆，去查真实市场数据、做证据校验、记录完整 trace，最后再由模型把这些真实信息整理成用户能看懂的回答，而不是直接凭模型猜。
