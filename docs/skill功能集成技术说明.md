# Skill 功能集成技术说明

> 面向对象：第一次接触本项目、不了解 Skill / Tushare / 记忆系统的新同学  
> 目标：讲清楚当前这套 Skill 是怎么接入对话 Agent 的、每个关键文件负责什么、一次真实提问是怎么跑起来的、怎么排查问题

---

## 1. 这份文档讲什么

这份文档专门讲本项目里“**对话模式 + Skill + Tushare + 用户画像/记忆**”这一整条链路。

现在的设计不是：

- 用户提问
- LLM 凭记忆直接回答

而是：

- 用户提问
- 系统先判断要不要走 Skill
- 如果要，就先拿真实数据
- 再把“用户画像 + 长短期记忆 + Tushare 数据”一起交给 LLM 生成最终回答

一句话理解：

> 现在的 Agent 遇到金融数据类问题，会优先查证据，再回答；遇到普通聊天问题，才直接走普通 LLM。

---

## 2. 先理解几个最重要的概念

### 2.1 什么是 Skill

这里的 Skill 可以理解成“能力入口”。

当前真实会进入运行时的 Skill 只有两个：

- `fallback`
- `tushare-data`

它们的含义很简单：

- `fallback`：普通聊天，不查 Tushare
- `tushare-data`：进入金融数据能力链路

### 2.2 什么是 analysis_mode

`analysis_mode` 不是 Skill，而是“这次要用这套能力做什么事”。

当前主要模式有：

- `general_chat`
- `single_stock_data`
- `single_stock_fundamental`
- `sector_market`
- `stock_selection`

所以现在的设计是：

- `selected_skill` 解决“走哪套能力”
- `analysis_mode` 解决“拿这套能力做什么”

这样比以前把所有业务模式都伪装成 skill 清楚很多。

### 2.3 什么是官方 Tushare Skill

官方 Tushare Skill 的 vendor 内容放在：

- [SKILL.md](/root/Finance/vendor/tushare-skills/tushare/SKILL.md)
- [_meta.json](/root/Finance/vendor/tushare-skills/tushare/_meta.json)
- [references](/root/Finance/vendor/tushare-skills/tushare/references)

这里要特别注意：

> 本项目没有接 OpenClaw runtime。  
> 我们接入的是官方 Skill 的“定义、文档、知识和 references”，执行引擎还是本项目自己写的。

也就是说：

- 官方 Skill 负责“能力定义”
- 本项目负责“路由、规划、调工具、证据校验、回答生成”

### 2.4 什么是 Tool

Tool 就是真正去调用 Tushare 的函数。

比如：

- 查股票行情
- 查财务指标
- 查基金列表
- 查板块快照
- 查指数行情

Skill 负责决定“要不要用 Tushare”，Tool 负责决定“具体调哪个接口”。

### 2.5 什么是 Planner

Planner 是“工具计划器”。

它不直接回答问题，而是先判断：

- 当前问题是什么模式
- 哪些工具应该调
- 哪些工具是必须的
- 哪些工具是补充的

举个例子：

用户问：

```text
请你根据我的用户画像，分析比亚迪今天值不值得买入
```

Planner 会倾向生成这样的计划：

- `get_market_bars`
- `get_fina_indicator`
- `get_income`
- `get_balance_sheet`
- `get_cashflow`
- `get_stock_basic_info`

因为这个问题既要市场证据，也要财务证据。

---

## 3. 当前整体架构

### 3.1 总流程

```text
前端问题
  ->
backend/routers/chat.py
  ->
backend/services/chat_service.py
  ->
读取 STM / LTM / 用户画像 / recent messages
  ->
route_chat_skill()
  ->
selected_skill + analysis_mode
  ->
execute_skill()
  ->
planner 生成工具计划
  ->
两条执行路径二选一
  - deterministic：高频结构化问题，直接并发取数
  - agentic：复杂问题，交给 agent 自主调工具
  ->
skill_evidence 做证据校验
  ->
LLM 基于 记忆 + 画像 + 工具结果 生成最终回答
  ->
保存 assistant 消息
  ->
触发画像更新 / LTM 入队 / STM 压缩
```

### 3.2 现在采用的是“混合式执行”

这是本轮改造里最关键的变化。

当前不是所有 Skill 问题都交给 agent 自己慢慢想，而是分两类：

#### 1. 确定性快路径 `deterministic`

适用于：

- `single_stock_data`
- `single_stock_fundamental`
- `sector_market`
- `stock_selection` 中的基金 / ETF 推荐

这条路径会：

- planner 先生成可执行工具计划
- 系统直接并发调用工具
- 再把已经拿到的工具结果交给 synthesis 模型组织最终回答

特点：

- 更快
- 更稳定
- 更像工业链路

#### 2. Agent 路径 `agentic`

适用于：

- 模糊问题
- planner 覆盖不稳定的问题
- 明显需要更自由多步推理的问题

这条路径会：

- 把 skill prompt、上下文和工具集交给 agent
- 由 agent 自主决定调不调工具、调哪些工具

特点：

- 灵活
- 但延迟和行为波动更大

---

## 4. 关键文件都在哪

### 4.1 对话总调度层

#### [chat_service.py](/root/Finance/backend/services/chat_service.py)

这是整个对话模式的总入口。

它负责：

- 保存用户消息
- 读取画像和记忆
- 组装 skill 路由上下文
- 调 `route_chat_skill()`
- 调 `execute_skill()`
- 处理画像 action
- 保存 assistant 消息
- 触发 LTM / STM 后处理

这次改造里，`chat_service.py` 主要新增了这些能力：

- `_load_memory_context_for_chat()`
  把用户画像和语义记忆读出来

- `_build_skill_route_context()`
  把 `running_summary + 最近几轮对话` 拼成路由上下文，解决“是，请查询”这种跟进语句只看当前一句的问题

- `_run_skill_chat_if_enabled()`
  对话模式的 skill 主入口

- `_prepare_reply_for_user()`
  统一处理回复里的画像动作

### 4.2 Skill 元数据层

#### [skill_registry.py](/root/Finance/Financial-MCP-Agent/src/skills/skill_registry.py)

负责：

- 扫描官方 vendor skill
- 读取 `SKILL.md`、`_meta.json`、`references`
- 对外提供：
  - `list_skills()`
  - `get_skill()`
  - `find_references()`
  - `matchable_descriptions()`

可以把它理解成“技能目录管理器”。

### 4.3 Skill 路由层

#### [skill_router_node.py](/root/Finance/Financial-MCP-Agent/src/agents/skill_router_node.py)

负责判断：

- 要不要进 Skill
- 进哪个真实 Skill
- 属于什么 `analysis_mode`
- 是否需要实时数据
- 是否属于专业分析

它的输出是一个结构化结果：

```json
{
  "selected_skill": "fallback|tushare-data",
  "analysis_mode": "general_chat|single_stock_data|single_stock_fundamental|sector_market|stock_selection",
  "needs_realtime_data": true,
  "needs_professional_analysis": false,
  "confidence": 0.92,
  "why": "..."
}
```

### 4.4 Skill 执行层

#### [skill_executor_node.py](/root/Finance/Financial-MCP-Agent/src/agents/skill_executor_node.py)

这是整个 Skill 运行时的核心执行器。

它负责：

- 根据 route 结果决定执行路径
- 调 planner
- 选择 deterministic / agentic
- 调用工具
- 校验证据
- 交给 synthesis 模型生成最终回答

这一层本轮最重要的变化有 4 个：

1. **真正把 `memory_context` 正文传给 Skill**
以前这里只传“长度=xxx”，现在是把截断后的正文真正送进 prompt。

2. **加入模型分层**

- router：`CHAT_ROUTER_MODEL`
- resolver：`CHAT_RESOLVER_MODEL`
- synthesis：`CHAT_SKILL_SYNTHESIS_MODEL`，留空时回退主模型

当前默认：

- router = `kimi-k2.5`
- resolver = `kimi-k2.5`
- synthesis = 当前主模型

3. **加入确定性快路径**

对高频结构化问题，不再只把工具计划写进 prompt，而是直接执行工具。

4. **trace 更完整**

现在会把这些信息带进 trace：

- `execution_path`
- `router_model`
- `resolver_model`
- `synthesis_model`
- `tool_batch_size`
- `evidence_ok`

### 4.5 规划层

#### [tushare_reference_planner.py](/root/Finance/Financial-MCP-Agent/src/agents/tushare_reference_planner.py)

负责根据：

- 用户问题
- `analysis_mode`
- 官方 references
- 当前可用能力开关

输出“建议调用哪些工具”的计划。

它本身不调工具，只做规划。

### 4.6 证据校验层

#### [skill_evidence.py](/root/Finance/Financial-MCP-Agent/src/agents/skill_evidence.py)

负责判断：

- 工具有没有真的成功返回
- 返回是不是空数据
- 标的是不是对的
- 当前问题所需的证据是不是够了

这是防止“模型装懂”的关键闸门。

现在的核心规则包括：

- `single_stock_fundamental`
  必须同时具备市场证据和财务证据

- `sector_market`
  必须具备板块 / 行业 / 指数类证据

- `stock_selection`
  基金推荐至少要求：
  - 候选池证据：`fund_basic`
  - 再加一类支撑证据：`fund_nav` / `fund_share` / `fund_daily`

### 4.7 Tushare SDK 封装层

#### [tushare_client.py](/root/Finance/Financial-MCP-Agent/src/tools/tushare_client.py)

这是最底层真正调 Tushare SDK 的地方。

负责：

- `ts.set_token()`
- `ts.pro_api()`
- 市场 / 财务 / 基金 / 板块 / 指数接口封装

### 4.8 Tool 层

#### [chat_tushare_tools.py](/root/Finance/Financial-MCP-Agent/src/tools/chat_tushare_tools.py)

这是给 agent / executor 直接调用的工具层。

负责：

- 暴露工具函数
- 参数规范化
- 股票代码标准化
- 基金 / ETF 自然语言解析
- 在工具调用开始和结束时记录 trace

现在的主要工具大致分为 5 类：

- 个股基础信息
- 行情数据
- 财务报表 / 财务指标
- 板块 / 行业 / 指数
- 基金 / ETF

### 4.9 Trace 层

#### [skill_trace.py](/root/Finance/Financial-MCP-Agent/src/tools/skill_trace.py)

负责输出 Skill 运行日志。

当前主要事件有：

- `chat.router.decision`
- `chat.skill.selected`
- `chat.tool.plan`
- `chat.model.stage`
- `chat.tool.start`
- `chat.tool.end`
- `chat.tool.error`
- `chat.reply.completed`

---

## 5. 模型分层是怎么工作的

这次为了降低延迟，我们把模型职责拆开了。

### 5.1 Router 模型

配置项：

- `CHAT_ROUTER_MODEL`

默认值：

- `kimi-k2.5`

职责：

- 只做“要不要走 Skill、属于什么 mode”的结构化判断

### 5.2 Resolver 模型

配置项：

- `CHAT_RESOLVER_MODEL`

默认值：

- `kimi-k2.5`

职责：

- 只做股票 / 基金标的解析

### 5.3 Synthesis 模型

配置项：

- `CHAT_SKILL_SYNTHESIS_MODEL`

默认行为：

- 为空时回退主模型 `OPENAI_COMPATIBLE_MODEL`

职责：

- 基于真实工具结果、用户画像、记忆上下文生成最终中文回答

这样拆分的好处是：

- 低复杂度步骤交给小模型
- 只有最后真正需要语言组织和综合分析时，才用主模型

---

## 6. 记忆、画像、STM/LTM 现在是怎么跟 Skill 打通的

这是这轮修复的重点之一。

### 6.1 之前的问题

之前 Skill 分支虽然链路上“看起来有记忆”，但实际上：

- prompt 里没真正注入 `memory_context` 正文
- 画像 action 的处理顺序也不对

所以会出现：

- Skill 回答看起来没吃到记忆
- 回复里即使有画像动作，也可能没真正写回

### 6.2 现在的正确流程

现在的 Skill 分支会这样走：

1. 读取用户画像和语义记忆
2. 生成 `memory_context`
3. 读取 `running_summary`
4. 读取最近几轮消息，构造 route context
5. 路由完成后，把这些内容真正交给 `execute_skill()`
6. Skill 回复生成后：
   - 先执行 `_handle_profile_action_in_reply()`
   - 再执行 `_strip_profile_actions_from_reply()`
7. 保存 assistant 消息
8. 正常触发：
   - `maybe_update_ltm_from_chat`
   - `compress_if_needed`

这意味着：

> Skill 对话现在和普通对话一样，也会参与画像更新、LTM 入队和 STM 压缩。

---

## 7. 一条真实问题是怎么跑起来的

### 7.1 例子一：普通闲聊

用户输入：

```text
你是谁
```

流程：

1. router 判断这是普通聊天
2. `selected_skill = fallback`
3. 走普通 LLM
4. 保存消息
5. 继续 STM/LTM 后处理

### 7.2 例子二：贵州茅台最新财务指标

用户输入：

```text
帮我看一下贵州茅台最新财务指标
```

流程：

1. router 判断：
   - `selected_skill = tushare-data`
   - `analysis_mode = single_stock_fundamental`

2. resolver 尝试把“贵州茅台”解析成股票标的

3. planner 给出工具计划，通常包括：
   - `get_market_bars`
   - `get_fina_indicator`
   - `get_income`
   - `get_balance_sheet`
   - `get_cashflow`
   - `get_stock_basic_info`

4. 因为这是高频结构化问题，所以优先走 deterministic 路径

5. executor 直接并发取数

6. `skill_evidence` 检查：
   - 市场数据有没有
   - 财务数据有没有
   - 标的是不是对的

7. 证据通过后，把以下内容一起交给 synthesis 模型：
   - 用户问题
   - 用户画像摘要
   - `memory_context`
   - `running_summary`
   - 工具结果

8. 生成最终回答

### 7.3 例子三：比亚迪今天值不值得买

用户输入：

```text
请你根据我的用户画像和回答要求，专业分析下比亚迪的今天值不值得买入
```

这是最典型的“专业分析”链路。

系统会判断：

- 需要 Skill
- 需要实时数据
- 需要专业分析
- mode = `single_stock_fundamental`

这类问题比“只查财务指标”要求更高，因为回答“今天值不值得买”至少要有：

- 市场证据
- 财务证据

如果只拿到了财务数据，没有行情数据，就不会放行。

### 7.4 例子四：半导体板块今天行情

用户输入：

```text
分析半导体板块今天行情
```

系统会判断：

- `selected_skill = tushare-data`
- `analysis_mode = sector_market`

planner 会优先考虑：

- `get_sector_snapshot`
- `get_sector_constituents`

然后走板块证据校验。

### 7.5 例子五：黄金 ETF 基金推荐

用户输入：

```text
能推荐下黄金ETF的基金吗？
```

现在已经不是误用股票/板块工具了，而是基金链路：

1. router 判断为 `stock_selection`
2. planner 规划：
   - `get_fund_basic_info`
   - `get_fund_nav`
   - `get_fund_share`
   - `get_fund_market_bars`

3. deterministic 路径先拿候选基金
4. 再对 Top N 候选并发拉基金净值 / 份额 / 行情
5. evidence 要求：
   - 至少有 fund candidate
   - 再加一类支撑 fund 证据

### 7.6 例子六：跟进式消息“是，请查询”

用户输入：

```text
是，请查询
```

这个问题如果只看当前一句，完全不够。

所以现在 router 会结合：

- `running_summary`
- 最近几轮对话

构造 `conversation_context`。

如果上一轮已经在讨论“黄金 ETF 推荐”这类明确金融问题，那么“是，请查询”会继承上文继续走 Skill，而不是误回退到普通聊天。

---

## 8. 当前主要配置项

配置在：

- [backend/.env.example](/root/Finance/backend/.env.example)
- [config.py](/root/Finance/backend/config.py)

### 8.1 Skill 总开关

- `ENABLE_CHAT_SKILLS`
- `ENABLE_TUSHARE_SKILLS`
- `ENABLE_TUSHARE_PLANNER`

### 8.2 子能力开关

- `ENABLE_TUSHARE_MARKET_TOOLS`
- `ENABLE_TUSHARE_INDEX_TOOLS`
- `ENABLE_TUSHARE_SECTOR_TOOLS`
- `ENABLE_FUNDAMENTAL_ANALYSIS`
- `ENABLE_SECTOR_ANALYSIS`
- `ENABLE_STOCK_SELECTION`

### 8.3 新增的低延迟配置

- `ENABLE_DETERMINISTIC_SKILL_EXECUTION`
- `ENABLE_TOOL_PREFETCH_CONCURRENCY`
- `CHAT_ROUTER_MODEL`
- `CHAT_RESOLVER_MODEL`
- `CHAT_SKILL_SYNTHESIS_MODEL`

### 8.4 当前建议值

```env
ENABLE_CHAT_SKILLS=true
ENABLE_TUSHARE_SKILLS=true
ENABLE_TUSHARE_PLANNER=true

ENABLE_TUSHARE_MARKET_TOOLS=true
ENABLE_TUSHARE_INDEX_TOOLS=true
ENABLE_TUSHARE_SECTOR_TOOLS=true

ENABLE_FUNDAMENTAL_ANALYSIS=true
ENABLE_SECTOR_ANALYSIS=true
ENABLE_STOCK_SELECTION=true

ENABLE_DETERMINISTIC_SKILL_EXECUTION=true
ENABLE_TOOL_PREFETCH_CONCURRENCY=true

CHAT_ROUTER_MODEL=kimi-k2.5
CHAT_RESOLVER_MODEL=kimi-k2.5
CHAT_SKILL_SYNTHESIS_MODEL=
```

说明：

- `CHAT_SKILL_SYNTHESIS_MODEL` 留空时，会自动回退到主模型
- 本轮没有做新的缓存工程化配置

---

## 9. 日志写到哪里，能看到什么

日志继续写入现有目录，不新建新的日志根目录。

当前最关键的日志目录是：

- [logs](/root/Finance/Financial-MCP-Agent/logs)

对话 Skill 相关的关键日志包括：

- `chat.router.decision`
- `chat.skill.selected`
- `chat.tool.plan`
- `chat.model.stage`
- `chat.tool.start`
- `chat.tool.end`
- `chat.tool.error`
- `chat.reply.completed`
- `LTM-chat`
- `STM-chat`
- `LTM-stream`
- `STM-stream`

### 9.1 现在日志里新补充的关键字段

- `execution_path=deterministic|agentic`
- `router_model`
- `resolver_model`
- `synthesis_model`
- `tool_batch_size`
- `evidence_ok`

所以现在的日志不仅能看到“走没走 Skill”，还能看到：

- 是不是走了确定性快路径
- 路由和解析用的是哪个模型
- 一次规划了多少个工具
- 最终证据是否通过

---

## 10. 当前已经解决了哪些问题

### 已解决

1. Skill 分支真正吃到了 `memory_context` 正文，而不是只拿长度
2. Skill 分支的画像动作处理顺序已经修正
3. Skill 对话会正常参与：
   - 画像更新
   - LTM 入队
   - STM 压缩
4. 高频结构化问题已经支持 deterministic 快路径
5. router / resolver 已支持小模型分层，默认是 `kimi-k2.5`
6. 股票、基金、板块三类主要工具链已经打通
7. 跟进式消息能继承上文继续走 Skill

### 还可以继续优化，但本轮没有做

1. 更复杂的全自动接口发现
2. 更完整的选股评分体系
3. 更激进的缓存工程化
4. 更细粒度的权限能力探测

---

## 11. 如何排查问题

如果你发现“为什么没按预期调用 Skill”，按下面顺序看最稳。

### 第一步：看是否命中 Skill

查：

```text
chat.router.decision
```

重点看：

- `selected_skill`
- `analysis_mode`
- `router_model`

### 第二步：看走的是哪条执行路径

查：

```text
chat.skill.selected
chat.tool.plan
```

重点看：

- `execution_path`
- `planned_tools`
- `tool_batch_size`

### 第三步：看工具有没有真正调用

查：

```text
chat.tool.start
chat.tool.end
chat.tool.error
```

### 第四步：看证据有没有通过

查：

```text
chat.reply.completed
```

重点看：

- `used_tools`
- `successful_tools`
- `evidence_ok`

如果 `evidence_ok=false`，常见原因有：

- 工具没拿到数据
- 拿到的是空数据
- 标的不匹配
- 当前问题要求的是双证据，但只拿到了一类

### 第五步：看记忆和画像有没有真的参与

看：

- `LTM-chat`
- `LTM-stream`
- `STM-chat`
- `STM-stream`

如果是 Skill 分支，还可以结合：

- `memory_context`
- `running_summary`
- 最近多轮消息

一起排查是不是上下文没带进去。

---

## 12. 当前测试覆盖了什么

这轮新增或补强的测试包括：

- [test_skill_executor.py](/root/Finance/Financial-MCP-Agent/test_skill_executor.py)
  验证 skill prompt 确实包含真实 `memory_context`

- [test_skill_evidence.py](/root/Finance/Financial-MCP-Agent/test_skill_evidence.py)
  验证基金推荐和专业分析的 evidence 规则

- [test_chat_service_skill_processing.py](/root/Finance/backend/test_chat_service_skill_processing.py)
  验证 Skill 回复里的画像 action 处理顺序

原有相关测试仍在：

- [test_skill_router.py](/root/Finance/Financial-MCP-Agent/test_skill_router.py)
- [test_tushare_reference_planner.py](/root/Finance/Financial-MCP-Agent/test_tushare_reference_planner.py)
- [test_chat_tushare_tools.py](/root/Finance/Financial-MCP-Agent/test_chat_tushare_tools.py)

---

## 13. 新同学建议从哪开始读

如果你后面要继续开发这一块，建议顺序是：

1. 先看 [chat_service.py](/root/Finance/backend/services/chat_service.py)
2. 再看 [skill_router_node.py](/root/Finance/Financial-MCP-Agent/src/agents/skill_router_node.py)
3. 再看 [skill_executor_node.py](/root/Finance/Financial-MCP-Agent/src/agents/skill_executor_node.py)
4. 再看 [tushare_reference_planner.py](/root/Finance/Financial-MCP-Agent/src/agents/tushare_reference_planner.py)
5. 再看 [chat_tushare_tools.py](/root/Finance/Financial-MCP-Agent/src/tools/chat_tushare_tools.py)
6. 最后看 [skill_evidence.py](/root/Finance/Financial-MCP-Agent/src/agents/skill_evidence.py)

最重要的开发原则是：

> 先保证“路由清楚、日志可见、证据可靠”，再继续扩功能。

---

## 14. 一句话总结

如果要把整套设计讲给完全不懂的人听，可以用这句话：

> 现在的对话 Agent 在回答金融问题前，会先判断“要不要查真实数据”；如果要，就通过 `tushare-data` 这条 Skill 路径读取用户画像和长短期记忆，规划并调用 Tushare 工具，校验证据，再让 LLM 基于这些真实信息生成最终回答，而不是凭记忆直接猜。
