# Skill 结合开发计划

> **审核修订（2026-03）**：已对照本仓库 `requirements.txt` / `backend/requirements.txt`、`MemoryService` 实际方法、`backend/config.py` 的 feature flag 模式，以及 **finance-incremental-dev**（增量、契约、可观测、失败降级）与 **agent-memory-systems**（检索质量优先、元数据过滤、上下文 token 预算、避免「只存不评检索」）做了对齐。文中原有参考链接保留；**与仓库不一致处已在下文标出并修正**。

## 目标范围（与原诉求一致）

在**现有 STM/LTM 体系**之上，将**选股 skill、基本面分析 skill**与 **`tushare-data`（Tushare 工具包）**接入**对话模式**：对话 agent **不再仅依赖「直连 Qwen 生成」**作为唯一路径，而是在 `enable_chat_skills=true` 时经 **Skill Registry → Router → Executor** 自主路由，**优先调用 Tushare 侧封装的能力**获取可核对、可更新的行情/财务数据，再由 LLM 整理回答（形态上类似 OpenClaw 的 skill 运行时，但**记忆系统仍走本仓库自研 Mem0/STM/LTM**，不在本计划内新增「记忆管理 skill」）。**记忆管理 skill 的开发暂缓**，从本计划中移除；现有 **`load_stm` / `memory_context` / `maybe_update_ltm_from_chat`** 等链路保留并与之适配。报告模式继续沿用当前 MCP + LangGraph 多分析师工作流，**不改为 skill runtime**。对话侧趋向 **skill-first**（可发现、可路由、可执行）。计划保留**权威参考入口**；存储侧继续 **PostgreSQL（+pgvector）+ Mem0**，且**默认不破坏报告模式**。([LangChain 文档][1])

## 最终判断

我建议你采用的不是“整体重构成 Deep Agents”，而是：

**保留现有报告模式与现有 LTM/STM 架构不动，在对话模式上新增一层 `Skill Registry + Skill Router + Skill Executor + Skill Subgraph/Tool Bundle`。**

这是最适合你项目现状的路线。原因是 LangChain 官方自己已经把角色分得很清楚：
**LangGraph** 适合“workflow + agents 的组合系统”，**LangChain v1** 的 `create_agent` 和 middleware 适合高层 agent loop，**Deep Agents** 更适合更自治、更长时程、内置 planning/filesystem/subagents 的 agent harness。你现在的 Finance 项目本质上是一个“工作流 + agent + MCP + 记忆”的组合系统，所以最优策略不是迁框架，而是**吸收 Deep Agents/OpenClaw 的 skill 设计模式，落在现有 LangGraph 系统里**。上游文档中 **LangChain v1 `create_agent` + middleware** 的建议适用于**升级后的**栈；**当前仓库仍为 LangGraph 0.6.x**，首期实现应以 `StateGraph` 与现有节点模式为主，升级后再对齐官方 v1 范式。([LangChain Blog][2])

---

## 一、你这个项目里，skill 应该怎么定义

你的对话 agent 里，skill 不应该只是“换个名字的 prompt 模板”，而应该是：

**一个可发现、可按需加载、可配置、可执行的能力包。**

这一点，最值得借鉴的有三组公开实践：

第一组是 **Deep Agents Skills 官方文档**。它明确采用 **progressive disclosure**：agent 启动时只知道每个 skill 的 `name` 和 `description`，真正命中 skill 后才加载完整的 `SKILL.md` 和附属资源。([GitHub][3])

第二组是 **OpenClaw Skills**。它把 skill 做成 `SKILL.md` 目录包，并且有清晰的加载优先级：bundled skills、`~/.openclaw/skills`、`<workspace>/skills`，同名时工作区最高优先级；同时默认 watch skill 文件夹，`SKILL.md` 变化后自动刷新快照。它还只把紧凑的 skill 列表注入 system prompt，而不是预加载所有 skill 内容。([OpenClaw][4])

第三组是 **Agent Skills 规范 + anthropics/skills 仓库**。规范明确了 skill 目录结构：至少一个 `SKILL.md`，可选 `scripts/`、`references/`、`assets/`；还支持 `compatibility`、`metadata`、`allowed-tools` 等字段。`anthropics/skills` 则是一个真正的、在生产 AI 产品里被使用过的 skill 仓库，适合你参考怎样写 skill 包。([Agent Skills][5])

所以，对你项目来说，skill 的正确组织方式应该是：

```text
Financial-MCP-Agent/src/skills/
  tushare-data/            # 与 Tushare 官方 Skills 包对齐（见第四节）；对话侧行情/财务数据主入口
    SKILL.md
    references/...
  fundamental-analysis/
    SKILL.md
    references/...
  stock-selection/
    SKILL.md
    references/...
```

这一步本身不改变你的报告模式，也不碰现有 MCP，只是为对话 agent 引入一个“技能层”。

---

## 二、每个关键模块应该参考什么仓库/文档

下面我按你点名的模块来给对应的参考入口，并说明为什么可迁移。

### 1）Skill Registry

你最应该参考的是 **OpenClaw Skills 加载机制 + Agent Skills 规范**。
OpenClaw 公开说明了 skill 的加载来源、优先级、watcher 和配置项；Agent Skills 规范定义了 `SKILL.md` 的 frontmatter 和目录结构。这两者加起来，就足够你在项目里实现一个自己的 `SkillRegistry`：扫描 skill 目录、解析 frontmatter、做名称冲突覆盖、支持启停和热刷新。([OpenClaw][4])

你在项目里建议新增：

* `Financial-MCP-Agent/src/services/skill_registry.py`
* `Financial-MCP-Agent/src/skills/`
* 可选：`<项目根>/skills/`（与仓库路径一致，例如本仓库为 `/root/Finance/skills/`）作为 **workspace override** 层，避免写死机器相关路径

**你该照搬的不是 OpenClaw 的 prompt 调用方式，而是它的“技能包管理方式”。**

### 2）Skill Router Node

这里最适合参考的是 **LangGraph Subgraphs 文档 + Deep Agents subagents 设计 + LangChain middleware**。
LangGraph 官方明确说，subgraph 适合多 agent 系统、复用一组节点、以及不同团队独立开发；Deep Agents 则把 subagent 作为一个清晰的能力边界，主 agent 通过 `task` 工具把工作委派给不同子代理；LangChain middleware 则适合在 agent loop 里做 prompt 变换、工具选择、guardrail 和 early termination。([LangChain 文档][6])

对你来说，`SkillRouterNode` 不要让模型“自由发挥地读 skill 再决定”，而应该：

* 先读取 `SkillRegistry` 中每个 skill 的摘要（name/description/execution_mode/allowed_tools）
* 再结合当前 `user_msg + running_summary + memory_context`
* 输出一个结构化选择结果：

  * `selected_skill`
  * `confidence`
  * `arguments`
  * `fallback_mode`

建议新增：

* `Financial-MCP-Agent/src/agents/skill_router_node.py`

### 3）Skill Executor Node

这里最应该参考的是 **LangChain MCP 文档 + `langchain-mcp-adapters` repo + Deep Agents middleware/subagents**。
LangChain 官方 MCP 文档展示了 `MultiServerMCPClient`、`client.get_tools()`、以及“在 LangGraph StateGraph 中使用 MCP tools”的完整做法；`langchain-mcp-adapters` README 里还有多 MCP server、LangGraph StateGraph、Agent Server 集成的现成例子。Deep Agents README 则展示了：主 agent 可以挂 middleware，也可以把子 agent 作为 `task` 工具来调。([LangChain 文档][7])

对你来说，`SkillExecutorNode` 应该做的是**显式分发**（本计划不含记忆管理 skill）：

* `tushare-data` → **Tushare 工具 bundle**（`pro_api` 封装 + 限流/缓存；见 Phase 1）
* `fundamental-analysis` → `subgraph`（Phase 2）
* `stock-selection` → `subgraph + tushare tools`（Phase 2）
* `fallback` → 普通聊天 agent（仍注入 `memory_context`，不绕过 `MemoryService`）

建议新增：

* `Financial-MCP-Agent/src/agents/skill_executor_node.py`

### 4）Subgraph / MCP tool / MemoryService 明确分层

这部分你已经有雏形，但还要彻底做清楚。

**Subgraph**：参考 LangGraph 官方 `use-subgraphs`。对你来说，`fundamental-analysis` 和 `stock-selection` 都很适合封成子图，因为它们都是多步流程、需要独立状态和输出 schema。([LangChain 文档][6])

**MCP tool**：参考 LangChain MCP 文档和 `langchain-mcp-adapters`。如果以后你希望某个 skill 被多个 agent 或多个服务共用，就把它暴露成 MCP tool；但第一期不一定要先走 MCP。([LangChain 文档][7])

**MemoryService**：继续保留你现在的 `MemoryService`，作为 **STM/LTM 与对话注入**的唯一权威入口；Router/Executor 在 `fallback` 与普通回复路径上仍通过既有 **`get_memory_context` 等**拉取上下文，**不引入**「记忆管理 skill」工作流（该方向暂缓）。Mem0 能力参考仍以官方为准。([docs.mem0.ai][8])

---

## 三、对话模式如何接入 skill，而不影响报告模式

你的要求里最关键的一条是：**报告模式维持原有 MCP 不变。**

我完全同意。
因此，推荐架构是：

### 报告模式

继续保持：

* 现有 `Financial-MCP-Agent` 多 agent 图
* 现有 `a-share-mcp-is-just-i-need`
* 现有 `memory_read_node / summary_agent / memory_write_node`

**不重构，不换 skill runtime。**

### 对话模式

单独新增一条 skill-first graph：

```text
load_stm_and_profile
  -> load_memory_context        # 既有 MemoryService，非「记忆 skill」
  -> skill_router_node
  -> skill_executor_node
  -> final_response
  -> save_messages
  -> maybe_update_ltm_from_chat
```

也就是说，**skill-first 只发生在 chat mode**。
report mode 还是你已经跑通的稳定主图。
这样做的好处是：

* 风险小
* 不影响现有报告生成
* 能快速验证对话 skill 的收益
* 出问题时可以 feature flag 回退

这也符合 LangGraph 官方关于“生产里的 agentic system 往往是 workflows 和 agents 的组合”的判断。([LangChain Blog][9])

---

## 四、行情/基本面能力怎么接进 skill 体系（Tushare 与 Baostock）

你提到可参考 **Tushare 开源**组织工具面；**本仓库报告/多分析师链路**仍大量使用 **Baostock**（见根目录 `requirements.txt`），与报告侧一致。

**与本计划（对话 skill）的明确分工（已拍板）：**

1. **对话模式 skill 路径（Phase 1–2）**：以 **Tushare（`tushare` + `TUSHARE_TOKEN`）** 作为 **`tushare-data` / `fundamental-analysis` / `stock-selection`** 的数据能力源，**不**用 Baostock 作为对话侧 skill 的默认拉数通道；Router/Executor 仅对白名单 skill 开放 Tushare 工具 bundle，避免「直连模型猜行情」。
2. **报告模式**：保持现有 **Baostock + MCP + 多分析师图** 不变；若未来要统一数据源，再单独立项 **`MarketDataProvider` 抽象** 与双源治理，**不在本计划内**强行合并两套语义。

**第一期不要把数据源 skill 先做成独立 MCP server**，而是 **内部工具 bundle + 可选 subgraph**，这样接入成本最低，也不影响现有报告模式的 MCP 路线。

为什么这么选：

* 报告模式已有 MCP 与多分析师图
* chat mode 要的是“新增 skill”，不是“再造一套基础设施”
* 数据源对 chat mode 更像“能力源”，不必先服务化

最值得参考的三组开源实践是：

**1. 官方 `waditu/tushare`**
这是最权威的 Python 客户端入口，README 明确展示了 `ts.set_token()` 和 `ts.pro_api()` 的基本用法，也是你写内部 `tushare_client.py` 的最稳参考。仓库约 14.2k stars。([GitHub][10])

**2. `YUHAI0/smart-financial-mcp`**
这是 Python 路线的 Tushare MCP 实践，README 已经展示了工具分组、token 管理、基本信息、行情和分析类工具的组织方式，比较适合作为“chat skill 的工具面设计”参考。([GitHub][11])

**3. `guangxiangdebizi/FinanceMCP` / `FinanceMCP-DCTHS`**
这类仓库展示了另一种很值得借鉴的模式：
工具按 `src/tools/` 拆分，每个工具有统一接口，然后在 `src/index.ts` / `src/httpServer.ts` 做集中注册。你虽然不是要照搬 TS 技术栈，但这个“**工具分层 + 集中注册**”的设计很适合迁到你的 `chat_tushare_tools.py`。([GitHub][12])

### 我建议的 Tushare skill 接入方式

#### `fundamental-analysis` skill

封装 **Tushare** 内部工具（与对话 skill 主路径一致），建议至少有：

* `get_stock_basic_info`
* `get_daily_bars`
* `get_fina_indicator`
* `get_income`
* `get_balance_sheet`
* `get_cashflow`

这些工具不要先暴露给所有对话，而是只允许 `fundamental-analysis` 和 `stock-selection` skill 使用。
这正好可以利用 Agent Skills 规范里的 `allowed-tools` 概念。([Agent Skills][5])

#### `stock-selection` skill

第一期做法：

* 直接调用 **`tushare_client.py` + `chat_tushare_tools.py`（或等价命名）** 与既有 `MemoryService` 画像/记忆上下文
* 结合你的 `user_invest_profiles + Mem0 memory_context`
* 在 skill 子图里筛选并排序

第二期再考虑把 Tushare 能力抽成独立 MCP server，给别的 agent 共用。
LangChain 官方 MCP 文档已经支持你未来这样做。([LangChain 文档][7])

### 官方「Tushare Skills」（waditu）与在本项目中的落地方式

Tushare 在官网提供了 **Tushare Skills** 安装说明：在 **OpenClaw** 生态中通过 **clawhub** 安装/升级 `tushare-data`，或通过 **离线 zip**（如官网提供的 `tushare-data.zip`）导入；在**大模型编程环境**中也可用 `npx skills add https://github.com/waditu-tushare/skills --skill tushare` 拉取技能包。数据源侧需 **`pip install tushare`**，并在 [Tushare Pro](https://tushare.pro/) 获取 **Token**，在 Python 中 `ts.set_token('...')` 或等价环境变量注入。([Tushare Skills 源仓库][21])

**与本 Finance 工程的关系（重要）**：

| 官方路径 | 在本仓库中的含义 |
|----------|------------------|
| OpenClaw / clawhub / WorkBuddy 里「装 skill」 | **运行时不在本仓库内**：生产对话走的是 **FastAPI `chat_service` + 自建 Skill Registry**，不依赖 OpenClaw 进程。 |
| `waditu-tushare/skills` 仓库里的 `SKILL.md` 与资源 | **应作为「领域说明 + 工具清单 + 最佳实践」的权威参考**，可 **git submodule、_vendor 拷贝或构建时同步**到 `Financial-MCP-Agent/src/skills/tushare-data/`（目录名可与官方包名对齐 `tushare-data`）。 |
| `pip install tushare` + Token | **必须在后端真实执行**：在 `backend/config.py` / `.env` 增加 `TUSHARE_TOKEN`（或你方命名），由 **`tushare_client.py`（待实现）** 在进程内 `set_token`，**禁止**写入日志或返回给前端。 |
| 官网提示「Rate limit exceeded」时离线 zip | 开发机可用手动 zip；**本服务**仍应对 Tushare 调用做 **重试/退避/缓存**，避免打满接口。 |

**对话模式「自主选择」该 skill 的推荐接线**：

1. **Registry**：注册 skill id **`tushare-data`**（或拆成 `fundamental-analysis` / `stock-selection` 子能力，但元数据中 `source: tushare` 指向同一工具包），`description` 中写明适用场景（实时行情、财务、宏观等），便于 Router 匹配。  
2. **Router**：在 `enable_chat_skills=true` 时，结合规则 + 可选小模型，将用户问题映射到 `tushare-data` 或 `fallback`（与第十一章「第二路 LLM」决策一致）。  
3. **Executor**：仅对白名单 skill 开放 **`tushare` 工具 bundle**（封装 `pro_api` 调用）；多步拉数时打 **步骤级日志与指标**（不含 token）。  
4. **与报告侧 Baostock 隔离**：对话 skill 走 Tushare；报告图走 Baostock；**禁止**在同一轮对话 skill 里混用两套代码而不做标的/字段映射（若未来要统一，另开契约评审）。

**建议新增目录（与第一节目录树对齐）**：

```text
Financial-MCP-Agent/src/skills/
  tushare-data/           # 可与 github.com/waditu-tushare/skills 同步内容
    SKILL.md
    references/...
  fundamental-analysis/
  stock-selection/
```

**环境变量（写入 `backend/.env.example`，勿提交真实 token）**：

* `TUSHARE_TOKEN=`（或 `TS_TOKEN=`，全项目统一一处即可）  
* 可选：`ENABLE_TUSHARE_SKILLS=true`（在 `enable_chat_skills` 之下再细分子开关，便于灰度）

**开发期可选操作（非生产必需）**：

* 在本地用官方文档中的 `npx skills add https://github.com/waditu-tushare/skills --skill tushare` **仅用于**把 skill 文件拉到工作区，再拷贝进 `src/skills/tushare-data/`；或直接从 [waditu-tushare/skills][21] clone/submodule。  
* 若团队使用 OpenClaw 做**产品演示**，可与本后端并行；**不要**把 OpenClaw 当作本仓库唯一运行时。

---

## 五、记忆管理 skill：本计划范围说明（暂缓，保留参考）

**本迭代不实现「memory-management」skill**（不从 Router/Executor 增加独立记忆管理 skill 路径）；画像与语义记忆的 **读/写** 仍走现有 **`MemoryService`**、`maybe_update_ltm_from_chat`、既有 API/队列，与 **finance-incremental-dev** 的契约与幂等要求一致。

下列材料仍对 **Phase 3 工程规则**与后续可选扩展有用，故保留链接，不要求本阶段落地为 skill：

* **OpenClaw**：`SKILL.md` 目录包、多层加载、摘要注入后再展开全文，可作为 Registry 组织方式的参照。([OpenClaw][4])
* **Mem0 + OpenClaw 集成**：Auto-Recall / 显式 memory tools 等思路，供将来若单独做「记忆 skill」时对照，**非本计划交付物**。([docs.mem0.ai][13])
* **Cursor Rules**：`.cursor/rules` 用于固化 skill 目录、Router 输出契约、`MemoryService` 调用约束等开发规范。([Cursor Documentation][14])

---

## 六、严格贴合本仓库的依赖基线（已核对）

> **重要**：下文以**当前仓库锁定的依赖**为准。原文中「LangChain 1.2.9 / LangGraph v1.1 + `create_agent` middleware」属于**上游新范式**，与本项目**尚未对齐**；若直接按该路径实现，会与现有代码 API 不一致，违背 finance-incremental-dev 的契约一致原则。

### LangChain / LangGraph（以仓库为准）

| 位置 | 当前约束 | 对 skill 计划的含义 |
|------|-----------|-------------------|
| 根目录 `requirements.txt` | `langgraph==0.6.6`、`langchain-core==0.3.74`、`langchain-openai==0.3.30`、`langchain-mcp-adapters==0.1.9` | **Phase 1–3 应基于 `StateGraph` / 现有节点风格编写**，与 `agent_service._get_workflow()` 一致；不要假设已存在 LC v1 的 `create_agent` middleware。 |
| `backend/requirements.txt` | `langgraph>=0.2.0`、`langchain-core>=0.3.0`（范围较宽） | 以实际运行环境 `pip freeze` 或根目录锁为准，避免「文档写 v1、环境跑 0.6」的漂移。 |

**工程建议（增量）：**

1. **默认路径**：在**不升级** major 的前提下实现 Skill Registry + Router + Executor + 子图（与现有多分析师图并存）。
2. **可选独立史诗**：单独立项「LangGraph/LangChain 大版本升级」，完成后再引入官方文档中的 v1 `create_agent` + middleware 模式；升级前必须在 CI/Staging 跑通报告模式 + 对话模式回归。([LangChain 文档][1])

### Mem0

* 启用 Phase 3 时按项目文档使用 **`mem0ai` 1.x** 线；具体钉版本以 `backend/requirements.txt` 取消注释后的约束或团队 lock 为准。
* 能力参考仍以 Mem0 官方为准（search/update/delete、metadata、async）。([GitHub][15])

### PostgreSQL + pgvector

* 与现有 LTM 双轨一致；chat skill **必须**经 `MemoryService` / 已有 `AsyncSession` 路径访问 DB，禁止并行造第二套画像写入通道。

### 数据源（与仓库现状）

* **报告侧**：已大量使用 **Baostock**（见根目录 `requirements.txt`），保持不动。
* **对话 skill 侧（本计划）**：已约定以 **Tushare**（`pip install tushare` + `TUSHARE_TOKEN`）作为 **`tushare-data` / 基本面 / 选股** 的数据源；与报告侧 **隔离**，避免同一 skill 路径混用 Baostock 与 Tushare 语义（见第四章）。

---

## 七、详细开发计划（三阶段，可直接导入 Cursor 拆任务）

下面按 **finance-incremental-dev**：**feature flag 默认关 = 旧行为不变**；先**可观测与契约**，再**行为**；失败**降级**（Tushare 异常 → 明确错误文案 + 可选 `fallback` 仅 LLM，不伪造行情）。三阶段边界如下。

| Phase | 目标 | 报告模式 |
|-------|------|----------|
| **Phase 1** | Skill 基础设施 + 对话图接入 Router/Executor + **Tushare 工具 bundle**（非 Baostock）+ 与 `MemoryService` 的 memory_context 注入衔接 | 不变 |
| **Phase 2** | `fundamental-analysis` / `stock-selection` 子图与 Executor 分发 | 不变 |
| **Phase 3** | `.cursor/rules`、日志、自检清单、依赖与 `.env.example` 文档化 | 不变 |

---

### Phase 1：Skill 功能集成基础设施（对话侧可路由到 Tushare，非直连 Qwen 唯一路径）

**目标**：`enable_chat_skills=true` 时，对话在 **已加载 STM/LTM 上下文** 的前提下，经 **Registry → Router → Executor** 自主路由；**行情/财务类意图**优先走 **`tushare-data`**（内部 `pro_api` 封装），由 **LLM 基于工具结果整理回答**；**关闭 flag 时**与现网一致（`load_stm → memory_context → LLM → save → maybe_update_ltm_from_chat`）。**不引入**记忆管理 skill。

#### 1.1 新增文件（建议路径）

| 文件 | 职责 |
|------|------|
| `Financial-MCP-Agent/src/services/skill_registry.py` | 扫描 `Financial-MCP-Agent/src/skills/` 与可选 `<项目根>/skills/`（后者覆盖前者），解析 `SKILL.md` frontmatter，暴露 `name/description/allowed_tools/execution_mode` 列表；开发模式可热刷新 |
| `Financial-MCP-Agent/src/agents/skill_router_node.py` | 输入：`user_msg`、`memory_context` 摘要、`running_summary`（与现有 chat 状态一致）；输出：结构化 `{ selected_skill, confidence, arguments, fallback_mode }` |
| `Financial-MCP-Agent/src/agents/skill_executor_node.py` | 按 `selected_skill` 分发：`tushare-data` → 调用 Tushare 工具 bundle；`fallback` → 仅 LLM（仍带 `memory_context`） |
| `Financial-MCP-Agent/src/tools/tushare_client.py`（或 `services/tushare_client.py`） | `ts.set_token` / `pro_api()` 单例，**token 仅环境变量**，超时/重试/限流钩子；**禁止**打日志 |
| `Financial-MCP-Agent/src/tools/chat_tushare_tools.py`（命名按仓库统一） | 对 `pro_api` 的薄封装：`get_stock_basic`、`daily`、`fina_indicator` 等 Phase 1 最小集，统一返回 `dict`/Pydantic，供 Executor 绑定 |
| `Financial-MCP-Agent/src/skills/tushare-data/SKILL.md` | 与 [waditu-tushare/skills][21] 对齐的说明与工具清单（可 submodule/vendor）；**仅作摘要与文档**，运行时以 Registry 为准 |
| 可选 `Financial-MCP-Agent/src/agents/chat_skill_graph.py` 或内联于 `chat_service` | 组装 `StateGraph`：`load_stm` → `load_memory_context` → `skill_router` → `skill_executor` → `final_response` → 交回 `chat_service` 写库 |

#### 1.2 修改文件（必改）

| 文件 | 修改要点 |
|------|----------|
| `backend/config.py` | 新增 `enable_chat_skills: bool = False`；可选 `enable_tushare_skills: bool = False`（嵌套在总开关下）；`tushare_token` 从环境读取，**不**写入默认值 |
| `backend/services/chat_service.py` | **`if not enable_chat_skills`**：保持现有分支不变；**`else`**：在拿到 `memory_context` / STM 后进入 **skill 图**，再写消息、再 `maybe_update_ltm_from_chat`；**流式**若已有独立路径，需同样分支或抽共享函数，避免重复 enqueue |
| `backend/.env.example` | 增加 `ENABLE_CHAT_SKILLS=`、`ENABLE_TUSHARE_SKILLS=`、`TUSHARE_TOKEN=`（占位，无真实密钥） |
| 根目录 `requirements.txt` 或 `backend/requirements.txt` | 新增 `tushare`（版本钉定前查 PyPI，注释兼容 Python 版本）；与 finance-incremental-dev 一致 |

#### 1.3 `skill_router_node` 输出结构（与 Phase 2 兼容）

```python
{
  "selected_skill": "tushare-data" | "stock-selection" | "fundamental-analysis" | "fallback",
  "confidence": 0.0-1.0,
  "arguments": {...},
  "why": "..."
}
```

**Phase 1 路由建议（先规则后模型）**：含「实时/行情/财务/财报/代码/基本面数据」等且需可核对数据 → **优先 `tushare-data`**（或拆到 Phase 2 的 `fundamental-analysis` 前可先映射到 `tushare-data` 通用拉数）；纯闲聊 → `fallback`。**不出现** `memory-management`。

#### 1.4 与长短期记忆衔接（无记忆 skill）

* Router/Executor **不得**绕过 `MemoryService`：在调用 `skill_executor` 前，state 中已包含 **`get_memory_context`**（或等价）结果，与现有 `chat_service` 一致。
* **`maybe_update_ltm_from_chat`** 仍在 **最终回复落库之后** 执行，与 Phase 1 前一致。

#### 1.5 finance-incremental-dev 自检（Phase 1 完成前）

* [ ] `enable_chat_skills=false` 时对话路径与现网一致  
* [ ] Tushare 失败时返回结构化错误 + 日志 `exc_info`，不静默吞掉  
* [ ] 密钥与 token 不出现在日志与响应体  

#### 参考入口

* `docs.langchain.com/oss/python/deepagents/skills`（skill 概念与 progressive disclosure）([GitHub][3])
* `docs.openclaw.ai/skills`（目录、优先级、watcher）([OpenClaw][4])
* `agentskills.io/specification`（frontmatter 规范）([Agent Skills][5])
* `github.com/anthropics/skills`（高质量 skill 包示例）([GitHub][16])

---

### Phase 2：基本面分析 skill + 选股 skill（子图 + Tushare，仍不经 Baostock）

**目标**：将 `fundamental-analysis`、`stock-selection` 从 Router 映射到 **独立子图**，Executor 显式分发；**数据仍只走 Tushare 工具层**（复用 Phase 1 的 `client`），**不**调用 Baostock。

#### 2.1 新增文件

| 文件 | 职责 |
|------|------|
| `Financial-MCP-Agent/src/agents/subgraphs/fundamental_analysis_subgraph.py` | 解析标的 → 调 `chat_tushare_tools` 拉财务/日线 → 结构化 JSON → 再 LLM 生成用户可读回答（输入带 `memory_context`） |
| `Financial-MCP-Agent/src/agents/subgraphs/stock_selection_subgraph.py` | 读 `user_invest_profiles` + `memory_context` → 约束 → Tushare 候选池与评分 → 输出列表与理由 |
| `Financial-MCP-Agent/src/skills/fundamental-analysis/SKILL.md` | 描述、边界、allowed_tools |
| `Financial-MCP-Agent/src/skills/stock-selection/SKILL.md` | 同上 |

#### 2.2 修改文件

| 文件 | 修改要点 |
|------|----------|
| `Financial-MCP-Agent/src/agents/skill_router_node.py` | 规则/模型：选股/筛选 → `stock-selection`；ROE/估值/财报/基本面 → `fundamental-analysis`；仅「要数据」→ `tushare-data` 或并入上两者（团队约定二选一，**文档内保持一致**） |
| `Financial-MCP-Agent/src/agents/skill_executor_node.py` | `match selected_skill` 增加子图调用；子图失败 → 降级或错误信息 |
| `Financial-MCP-Agent/src/services/skill_registry.py` | 注册新 skill 元数据 |

#### 2.3 输出与复用

* 子图输出 schema 见前文 Phase D/E 建议（`headline`/`key_metrics`/…），与前端契约若暂无对接，**仅后端日志 + 文本回复**亦可。

#### 参考入口

* LangGraph subgraphs：`docs.langchain.com/oss/python/langgraph/use-subgraphs`([LangChain 文档][6])
* 项目内 `fundamental_agent.py` / `value_agent.py` 等（**逻辑复用**而非报告全图）([LangChain 文档][6])
* Tushare：`waditu/tushare`([GitHub][10])、`smart-financial-mcp`([GitHub][11])

---

### Phase 3：工程治理与可交付（Cursor 与运维）

**目标**：规则固化、可观测、可回归，便于后续交割。

#### 3.1 新增 `.cursor/rules`（建议）

1. **`skill-architecture.mdc`**：skill 目录、`SKILL.md` frontmatter、`execution_mode` 枚举。  
2. **`memory-safety.mdc`**：画像/记忆写入仅经 `MemoryService` 与既有 API；与「无记忆 skill」一致。  
3. **`chat-skill-routing.mdc`**：新 skill 必须改 `skill_registry.py`、`skill_router_node.py`、`skill_executor_node.py`。  
4. **`tushare-tooling.mdc`**：chat 侧行情/财务 **仅 Tushare**；token、速率、错误码、返回 schema；**报告侧 Baostock 勿混写进 chat 工具**。

#### 3.2 文档与依赖

* `docs/` 中补充故障排查（Tushare 限流、flag 关闭回退）；`README` 或部署文档中增加 **Linux + venv/uv + Docker** 与 env 列表（finance-incremental-dev）。

#### 参考入口

* Cursor Rules：([Cursor Documentation][14])

---

## 八、这一版方案和 OpenClaw 的区别，要明确写进设计稿

你之前已经问过 OpenClaw，我这里直接帮你定性：

**OpenClaw 的优点是 skill 的“发现、安装、覆盖、热更新”很成熟；
但它的 skill 触发本质上仍是 prompt-mediated。**

而你这版 Finance 项目应该做的是：

* **借 OpenClaw 的 skill 包管理方式**
* **不照搬 OpenClaw 的 skill 调用方式**
* skill 触发由 `SkillRouterNode` 决定
* skill 执行由 `SkillExecutorNode` 决定
* 高风险动作必须通过 `MemoryService` / 工具层 / 子图执行

这样才适合金融投研场景。OpenClaw 官方 system prompt 文档和 skills 文档已经足够说明这一点。([OpenClaw][19])

---

## 九、推荐你直接采用的技术栈落点（与仓库一致）

* **LangGraph / LangChain**：以 **`langgraph==0.6.6` + `langchain-core==0.3.x`**（根目录 lock）为默认实现基线；文档中的 **v1 `create_agent`/middleware** 仅作未来升级参考。([LangChain 文档][1])
* **Mem0**：沿用 Phase 3 既定 `mem0ai` 线，不改 LTM 基础设施原则。([GitHub][15])
* **PostgreSQL + pgvector**：继续 Docker 部署，不新增第二套存储
* **MCP**：报告模式继续沿用现有 A 股 MCP；chat mode **Phase 1–2** 为内部 Tushare 工具化，再视情况把 skill 服务化为 MCP
* **行情/基本面数据源**：**报告侧** Baostock；**对话 skill 侧** Tushare（本计划已拍板），与报告侧隔离

---

## 十、推荐执行顺序（与三阶段对齐）

第一，完成 **Phase 1**：`SkillRegistry` + `SkillRouterNode` + `SkillExecutorNode` + **`tushare_client` / `chat_tushare_tools`** + `tushare-data/SKILL.md` + `backend` feature flag 与 **`chat_service` 分支**，确保 **关闭 flag 时行为与现网一致**。  
第二，完成 **Phase 2**：`fundamental_analysis_subgraph`、`stock_selection_subgraph` 与 Router/Executor 分发。  
第三，完成 **Phase 3**：`.cursor/rules`、日志与自检清单、文档与依赖说明。

**说明**：记忆管理 skill **不在**本路线内；长短期记忆通过既有 **`MemoryService`** 与 **`maybe_update_ltm_from_chat`** 衔接。

---

## 十一、审核结论：已修正项与需你决策项

### 11.1 已在本文中修正的冲突

| 原问题 | 处理 |
|--------|------|
| 依赖写成 LangChain v1 / LangGraph v1.1，与仓库 **0.6.6 / 0.3.x** 不符 | 第六章、第九章改为**以仓库 lock 为准**，升级单独立项 |
| 原 Phase C（memory-management）与「暂缓记忆 skill」矛盾 | **已移除**该阶段；记忆仍走 `MemoryService` 既有路径 |
| 路径 `Finance/skills` 易与真实仓库根混淆 | 统一为 **`<项目根>/skills/`** |
| 对话侧数据源在 Baostock / Tushare 间摇摆 | **对话 skill 固定 Tushare**；报告侧 Baostock 不变（第四章、第七章） |
| Phase 级次过多（A–F）不利于交割 | 收敛为 **Phase 1–3**，每阶段附 **新增/修改文件** 表 |

### 11.2 需你（产品/技术）决策

1. **对话 skill 已采用 Tushare**：需落实 [Tushare Pro](https://tushare.pro/) **Token** 与 **`TUSHARE_TOKEN` / `ENABLE_TUSHARE_SKILLS`** 运维策略；**不再**在「Baostock vs Tushare」上与报告侧混为一谈。
2. **Router 是否调用第二路 LLM**：**A)** 首期纯规则路由（低成本、可测）；**B)** 规则 + 小模型结构化输出（成本与延迟上升）；需在 `enable_chat_skills` 下可配置。
3. **Skill 运行时归属**：默认 **backend 编排 + 引用 `Financial-MCP-Agent` 模块**（与 `chat_service` / `agent_service` 一致）；若坚持全部放进 Agent 包内，需统一文档与 import 边界。

### 11.3 落地前自检（finance-incremental-dev 摘要）

* [ ] `enable_chat_skills=false` 时对话与现网一致  
* [ ] 画像/记忆写操作仅经 `MemoryService` + 既有队列  
* [ ] 新增环境变量写入 `backend/.env.example`，密钥不进库  
* [ ] Tushare 调用有超时/重试/日志（不含 token）；失败可降级或明确报错  

---

若需要 **第一版可落地的文件骨架**，可按第七章表格优先落地：

* `skill_registry.py`、`skill_router_node.py`、`skill_executor_node.py`
* `tushare_client.py`、`chat_tushare_tools.py`
* `tushare-data/SKILL.md`（可与 [waditu-tushare/skills][21] 对齐）
* Phase 2：`fundamental-analysis/SKILL.md`、`stock-selection/SKILL.md`、两子图
* Phase 3：`.cursor/rules` 下 `skill-architecture` / `memory-safety` / `chat-skill-routing` / `tushare-tooling`

[1]: https://docs.langchain.com/oss/python/releases "https://docs.langchain.com/oss/python/releases"
[2]: https://blog.langchain.com/doubling-down-on-deepagents/ "https://blog.langchain.com/doubling-down-on-deepagents/"
[3]: https://github.com/langchain-ai/deepagents "https://github.com/langchain-ai/deepagents"
[4]: https://docs.openclaw.ai/skills "https://docs.openclaw.ai/skills"
[5]: https://agentskills.io/specification "https://agentskills.io/specification"
[6]: https://docs.langchain.com/oss/python/langgraph/use-subgraphs "https://docs.langchain.com/oss/python/langgraph/use-subgraphs"
[7]: https://docs.langchain.com/oss/python/langchain/mcp "https://docs.langchain.com/oss/python/langchain/mcp"
[8]: https://docs.mem0.ai/open-source/features/overview "https://docs.mem0.ai/open-source/features/overview"
[9]: https://blog.langchain.com/how-to-think-about-agent-frameworks/ "https://blog.langchain.com/how-to-think-about-agent-frameworks/"
[10]: https://github.com/waditu/tushare "https://github.com/waditu/tushare"
[11]: https://github.com/YUHAI0/smart-financial-mcp "https://github.com/YUHAI0/smart-financial-mcp"
[12]: https://github.com/guangxiangdebizi/FinanceMCP "https://github.com/guangxiangdebizi/FinanceMCP"
[13]: https://docs.mem0.ai/integrations/openclaw "https://docs.mem0.ai/integrations/openclaw"
[14]: https://docs.cursor.com/en/context/rules "https://docs.cursor.com/en/context/rules"
[15]: https://github.com/mem0ai/mem0/releases "https://github.com/mem0ai/mem0/releases"
[16]: https://github.com/anthropics/skills "https://github.com/anthropics/skills"
[17]: https://docs.langchain.com/oss/python/langchain/middleware/overview "https://docs.langchain.com/oss/python/langchain/middleware/overview"
[18]: https://docs.mem0.ai/open-source/features/rest-api "https://docs.mem0.ai/open-source/features/rest-api"
[19]: https://docs.openclaw.ai/concepts/system-prompt "https://docs.openclaw.ai/concepts/system-prompt"
[20]: https://github.com/langchain-ai/langchain/releases "https://github.com/langchain-ai/langchain/releases"
[21]: https://github.com/waditu-tushare/skills "https://github.com/waditu-tushare/skills"
