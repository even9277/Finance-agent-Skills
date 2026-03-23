# 面向 Finance 项目的 STM+LTM 记忆模块集成深度调研报告

## 未知与假设

本报告基于你最新补充的约束做方案收敛，并明确以下仍然存在的未知与工程假设（**不向你追问**，仅作为后续落地时需要验证/决策的点）：

- 假设你愿意在 `Financial-MCP-Agent` 中把当前“一问一答生成报告”的调用方式，扩展为“多轮对话循环 + 同一 `thread_id` 的 LangGraph 持久化”。（LangGraph 的线程/检查点机制可支撑此模式。）citeturn6view1turn24view0  
- 假设你未来在 Vue 前端阶段会新增一个**本地 HTTP API**（例如 FastAPI）承载会话与记忆管理；早期 CLI 仍可直接调用同一套 Python SDK/模块。  
- 假设你对“长期记忆”优先采用“结构化画像 + 可检索记忆条目（向量/混合检索）”的混合策略；并通过版本化与可追溯 evidence 解决“压缩不丢信息”的审计诉求。  
- 假设你允许：PostgreSQL（含 pgvector）或独立向量库（Chroma/Milvus/Weaviate 等）作为存储后端；并允许定时清理/TTL（默认 7 天）以满足保留策略。citeturn3search4turn17search0turn24view0  
- 假设你“仅 A 股 + 简单板块标签”的需求，初期无需引入复杂行业本体/知识图谱；知识图谱方案（Graphiti/Zep）仅作为可选增强路线，而非默认。citeturn20view0turn22view0  
- 假设你使用云 API LLM 推理（摘要、信息抽取、偏好更新均可用），embedding 可选云 API 或本地开源模型；两者都可满足 Chinese 场景。citeturn4search2turn4search7turn24view1  

## 执行摘要

你这套 Finance 项目（以 `Financial-MCP-Agent` 为对话入口、通过 MCP 调用 A 股数据/新闻工具、最后由汇总 Agent 产出 Markdown 报告）要加入 **短期记忆（STM）+ 长期记忆（LTM）**，最关键的不是“选一个 memory 库就完事”，而是设计一个能同时满足：

- **成本/时延可控**：多轮对话不会因上下文无限增长而越来越慢、越来越贵。citeturn24view2turn2search1  
- **“压缩但不丢信息”的可审计性**：任何被写入 LTM 的偏好/关注标的，都能追溯到原始对话与工具输出证据，且支持用户编辑/删除/导出。citeturn20view0turn22view0turn12search13  
- **与 LangGraph/MCP 架构兼容**：早期 CLI 单用户本地运行，后期 Vue 前端可通过 HTTP/MCP 统一访问记忆层。citeturn6view0turn23search1turn23search3  

基于近三年论文与开源实践，本报告给出 2–4 个最匹配你约束的开源候选，并给出三条可落地路线（轻量内嵌 / MCP 记忆服务 / 混合架构），同时补齐：数据模型、对外 API 契约、评测验收（尤其是“压缩不丢信息”）、安全与保留策略、以及每条路线的工期与风险。

结论上，**最推荐的默认路线**是：

- 以 **LangGraph 原生持久化 + Store（LTM）** 为核心，把 STM 与 LTM 都先“放在你现有的 LangGraph 生态里”，并在汇总 Agent 前后加两个节点：**“检索注入（read）”** 与 **“记忆更新（write）”**。citeturn24view0turn24view1turn24view2  
- LTM 管理层优先考虑 **LangMem**（MIT）来做“结构化抽取/合并/更新”的通用管线，并直接落到 LangGraph Store（可启用语义检索）。citeturn21view0turn18search1turn24view1  
- 在“尽量不丢信息”的要求下，STM 压缩采用“双轨”：**原始对话+工具输出（7 天 TTL）** + **可递增更新的运行摘要**（running summary），必要时再叠加 **LLMLingua/LongLLMLingua 的 prompt 压缩** 来进一步降低 token。citeturn24view2turn2search0turn2search1  

当你后续要做 Vue 前端、或希望让其他 agent/skill 也读写记忆时，再把 LTM 抽为独立服务：优先基于 **LangGraph memory-template**（MIT）或自研 MCP Memory Service；若你未来需要“状态变化可追溯 + 更强时序推理/知识更新”，再评估 **Graphiti（Apache-2.0）**。citeturn19view0turn22view0turn20view0  

**面向 Finance 项目的 STM+LTM 记忆模块集成深度调研报告（Mem0 单技术路线最终版）**

这版报告只保留 **Mem0**，不再讨论其他记忆框架。原因很明确：你当前项目的主干已经是 **Python + LangGraph + MCP + 多 Agent 汇总**，而 Mem0 同时具备开源 OSS SDK、自托管 REST API、LangGraph 集成示例、可按 `user_id / agent_id / run_id` 做隔离、支持 `add / search / update / delete / delete_all` 的完整记忆操作、并允许你定制“抽什么事实、何时更新旧记忆”的 prompt，这正好覆盖你要做的“短期压缩上下文 + 长期投资画像 + 用户可编辑更新”三件事。Mem0 主仓库目前约 **50.1k stars**，仓库内能看到 `examples`、`evaluation`、`server`、`openmemory`、`tests` 等完整工程目录，且 README 明确提供了 **Self-Hosted (Open Source)** 使用方式；官方文档也单独给出了 **LangGraph integration**、**OSS REST API server**、**AsyncMemory** 和 **custom fact extraction / update prompt** 这些能力。([GitHub][1])

---

**一、最终结论：你的项目应如何使用 Mem0**

对你这套 `Financial-MCP-Agent + a-share-mcp-is-just-i-need` 来说，最合理的做法不是把 Mem0 当成“完整对话系统”，而是把它定位成一个**长期记忆层（LTM service / LTM library）**，专门负责两件事：
第一，**从多轮对话中抽取用户长期稳定或半稳定的投资偏好**，例如风险偏好、持有周期、偏好的市场范围（A 股/ETF/QDII）、关注板块、自选股；
第二，**在每次生成新报告前做召回**，把相关历史偏好和用户曾经明确说过的约束注入给 `summary_agent`，让最终报告更个性化。Mem0 文档本身就是这么设计的：`add` 用来把对话转成记忆，`search` 用来按自然语言查询召回，`update/delete/delete_all` 用来做纠错、删除和用户数据治理。([Mem0][2])

所以，这里的架构定位应该是：
**STM 仍由你现有 LangGraph state 管理，LTM 交给 Mem0。**
不要试图让 Mem0 替代 LangGraph thread state，也不要直接把所有原始消息都塞进 Mem0 作为“短期记忆”。Mem0 更适合做**抽取后的长期记忆层**，而短期记忆应该继续由 `messages + running_summary + recent window` 这套机制在当前图里控制。Mem0 官方的 LangGraph 集成示例其实也是这个模式：LangGraph 管对话流程，Mem0 管跨轮记忆保留与检索。([Mem0][3])

---

**二、为什么 Mem0 适配你的项目**

你的项目有几个非常具体的约束：
你要保留现在的 LangGraph 工作流；你希望先从 `summary_agent` 开始用记忆；你后面还要支持前端可编辑、可删除、可导出；你还有“用户偏好会变”的场景。Mem0 的现有能力正好能对上这些点。

首先，Mem0 已经有 **LangGraph 集成示例**。官方示例明确展示了：在 LangGraph 的 `State` 里保存 `mem0_user_id`，在节点执行时先 `search` 召回历史记忆，再把这些记忆写进 system prompt，最后把本轮 user/assistant 交互用 `add` 写回 Mem0。这个模式和你的 `summary_agent` 非常相似，只不过你的系统不是单个 chatbot，而是四个 analyst 并行分析后再汇总。也就是说，你不需要大改四个 analyst，只需要在汇总前后加读写 Mem0 的步骤即可。([Mem0][3])

其次，Mem0 有完整的 **OSS 自托管** 路线，而不是只能走平台 API。主仓库 README 明确给了 `pip install mem0ai` 的开源安装方式；OSS 配置文档则说明你可以自己配置 LLM、vector store、embedder、reranker，而且可以直接 `Memory.from_config(config)` 以自托管模式运行。对你这种金融投研场景，这一点非常重要，因为它意味着你可以把记忆库落在你自己的 Postgres/pgvector 或其他向量库里，而不是一上来就把用户投资偏好交给外部托管平台。([GitHub][1])

再次，Mem0 提供了 **REST API server**。这对你后续要从 CLI 走向 Vue 前端非常关键。官方文档写得很清楚：Mem0 OSS 的 REST server 是 FastAPI 驱动的，提供 create / retrieve / search / update / delete / reset 等 HTTP 接口，可以按 `user_id / agent_id / run_id` 组织记忆；默认开发时可用 Docker Compose 跑在本地，OpenAPI 文档在 `/docs`，但如果暴露到内网外，需要你自己补认证和 HTTPS。这个能力让你可以先在 Python 内部直接调用 SDK，后面再无缝抽成一层本地 HTTP 记忆服务。([Mem0][4])

最后，Mem0 不是只会“追加记忆”，它明确支持 **更新和删除**。这正是你项目的关键需求：用户今天说“偏稳健”，下周可能改成“可以接受高波动”；用户今天关注“半导体”，过一阵子可能删除这个板块；这些都不能靠只追加来解决。Mem0 的更新文档支持 `update(memory_id, text, metadata)`，删除文档支持 `delete(memory_id)`、`batch_delete` 和 `delete_all(user_id=...)`，而且文档明确把这些操作和 compliance / user erasure / stale memory cleanup 绑定在一起。([Mem0][5])

---

**三、Mem0 在你项目里的正确职责划分**

这一步最重要，因为它决定你后面代码怎么改。

你现在有两类“记忆”需求，但它们不是一个层面：

第一类是**短期记忆 STM**。
它服务于“当前这次多轮对话”，目标是控制 token、保留最近上下文、不让用户刚说过的话丢掉。这一层应该继续放在 LangGraph 里，而不是放到 Mem0。你可以在 `AgentState` 里增加：
`running_summary`：对 thread 内已经发生的对话做递增摘要；
`recent_messages`：保留最近 N 轮原始消息；
`raw_event_refs`：指向近 7 天原始对话和工具输出。
这部分不要交给 Mem0，因为 Mem0 的价值在于“抽取后的长期可检索事实”，而不是管理 thread 内的 token 窗口。

第二类是**长期记忆 LTM**。
它服务于“跨会话、跨日期的用户个性化画像”。这部分才是 Mem0 的主战场。对你的项目，我建议只把以下内容写入 Mem0：
风险偏好，例如“稳健 / 平衡 / 激进”；
投资期限，例如“短线 / 波段 / 中长线”；
市场范围偏好，例如“只看 A 股”或“也接受黄金、QDII、美股基金”；
关注板块，例如“半导体 / AI / 红利 / 黄金”；
关注标的，例如“贵州茅台、宁德时代、沪深300ETF、012922”；
回答偏好，例如“更看重风险提示”“结论前要先给逻辑链”；
显式纠错，例如“不要再把我归类成保守型，我现在偏进取”。

这些内容正好适合 Mem0 的 `add` 抽取、`search` 召回、`update/delete` 治理。Mem0 文档也建议通过自定义 fact extraction prompt 来控制“只存你关心的事实”，并通过 custom update prompt 来决定新增、更新、删除或不变。([Mem0][6])

---

**四、推荐的最终架构：LangGraph 内管 STM，Mem0 管 LTM**

对你来说，最优路线不是“独立新系统”，而是以下这个分层：

`用户输入 → Financial-MCP-Agent/LangGraph → analyst 并行分析 → summary_agent 汇总`
在这个流程里插入两处 Mem0：

一处在 `summary_agent` **之前**：
增加一个 `memory_read` 步骤，根据当前用户问题和 `user_id` 去 Mem0 做 `search`，把检索到的长期记忆写进 `state["data"]["memory_context"]`。

一处在 `summary_agent` **之后**：
增加一个 `memory_write` 步骤，把本轮用户问题 + 最终回答 + 必要的结构化工具结论送给 Mem0 做 `add`。同时，在用户明确修正偏好时，提供 `update/delete` 通道。

这样做的好处是：
四个 analyst 基本不用改，最多只需要能看到 `memory_context`；
真正承担“个性化输出”的 summary 阶段能够消费长期记忆；
Mem0 的读写点都集中，便于调试、审计和后续服务化。Mem0 的 LangGraph 官方示例本质上就是“节点里先 search，再 add”的套路，只是你这里把这个逻辑收敛到 summary 层，会比在四个 analyst 上分散改造更稳。([Mem0][3])

---

**五、针对你当前目录结构的改造建议**

下面这部分直接按你给的目录来写，目标是让你下一步开发能照着动。

**1）`Financial-MCP-Agent/src/utils/state_definition.py`**
这里增加三个字段最合适：
`memory_user_id: str`
`memory_context: dict | None`
`running_summary: str | None`

`memory_user_id` 用来稳定标识同一个投资用户。你现在是单用户实例，早期可以固定成 `"default_investor"`；后面前端接入后，用登录用户 ID 即可。Mem0 文档明确建议在存取时用 `user_id` 做范围隔离，搜索文档也强调“always provide user_id”。([Mem0][7])

`memory_context` 用来承接从 Mem0 检索回来的结果，例如：

```json
{
  "risk_profile": ["用户当前风险偏好偏进取"],
  "horizon": ["倾向1-3个月波段"],
  "watchlist": ["贵州茅台", "沪深300ETF"],
  "sector_focus": ["半导体", "红利"],
  "response_preferences": ["先讲风险再讲机会"]
}
```

`running_summary` 则继续作为 LangGraph 内的 STM 压缩，不交给 Mem0。

**2）`Financial-MCP-Agent/src/main.py`**
这里要做两件事。
第一，把单次调用改成带固定 `thread_id` 的多轮模式；
第二，在 graph 执行前后插入两个记忆操作：

* 调 graph 前：调用 `mem0_service.search(...)` 取回历史记忆，写入初始 state。
* 调 graph 后：调用 `mem0_service.add(...)` 把本轮值得长期保留的事实写回。

Mem0 的 LangGraph 示例用的是 `config = {"configurable": {"thread_id": mem0_user_id}}`，同时 state 中携带 `mem0_user_id`；你这里完全可以沿用这套思路，只是把 `chatbot` 节点替换成你已有的多 agent 工作流。([Mem0][3])

**3）新增 `Financial-MCP-Agent/src/memory/` 目录**
建议你新增下面几个文件：

`mem0_client.py`
封装 Mem0 SDK 初始化。早期可直接用 OSS `Memory` 或 `AsyncMemory`；后期如果要服务化，再替换成对本地 REST API 的调用。OSS SDK 用 `Memory.from_config(config)` 即可；如果你准备接 FastAPI 或异步后端，官方也有 `AsyncMemory`。([Mem0][8])

`mem0_schema.py`
定义你自己的记忆类别和 metadata 约定。比如：
`category = risk_profile | horizon | market_scope | watchlist_stock | sector_focus | response_preference | correction`

`mem0_prompts.py`
放两类 prompt：
`custom_fact_extraction_prompt`：只抽你要的金融画像信息；
`custom_update_memory_prompt`：定义何时 ADD / UPDATE / DELETE / NONE。
Mem0 官方已经提供了这两个能力，并且明确建议你用它们来控制“抽什么”和“旧记忆如何更新”。对你这个项目，这一步尤其关键，因为你不想把“随口闲聊”也当成长久记忆。([Mem0][6])

`memory_service.py`
做你项目内部统一接口，供 graph 调用：
`retrieve_memory_context(user_id, query)`
`write_conversation_memory(user_id, user_msg, assistant_msg, metadata)`
`update_explicit_preference(...)`
`delete_memory(...)`
`delete_all_for_user(...)`

这样你后面从 SDK 切 REST server 时，业务层不需要重写。

**4）`Financial-MCP-Agent/src/agents/summary_agent.py`**
这是本轮最关键的改造点。你要让 summary agent 在生成最终 Markdown 报告时额外看 `memory_context`。
最简单的做法是：在系统提示词里增加一段“用户长期偏好上下文”，但要给它加硬约束：

* 仅把 `memory_context` 作为个性化参考，不覆盖实时财务/技术/新闻事实。
* 若历史偏好与本轮用户明确表述冲突，以本轮用户表述为准。
* 若历史偏好不存在，不要编造。

之所以要这样写，是因为 Mem0 search 返回的是“相关长期记忆”，它能增强个性化，但不应该凌驾于本轮实时分析结果之上。官方搜索文档也把它定位成语义召回 + filter，而不是绝对真理源。([Mem0][9])

---

**六、Mem0 的具体写法：你该存什么，不该存什么**

这一步比“怎么接 SDK”更重要，因为记忆质量决定了后面报告是否稳定。

**建议写入 Mem0 的内容**

一类是**用户稳定偏好**：
“偏稳健”“不接受大回撤”“更偏红利和央国企”“不碰 ST”“只看 A 股”
这类内容应该打上 `category = risk_profile / constraints / market_scope`

一类是**用户半稳定关注点**：
“最近关注半导体”“想重点跟踪黄金和美股 QDII”“持续看茅台和宁德时代”
这类内容打上 `category = sector_focus / watchlist_stock`

一类是**回答偏好**：
“希望结论简洁”“先给风险再给建议”“要有表格”
这类内容打上 `category = response_preference`

一类是**显式纠错与更新**：
“我现在不保守了”“把光伏从关注列表里删掉”“以后少看短线情绪票”
这类内容必须能触发 UPDATE 或 DELETE。Mem0 官方的 custom update memory prompt 就是专门解决这个问题的：它允许模型在比较“新事实”和“已有记忆”后返回 `ADD / UPDATE / DELETE / NONE`，而且 update 要保留原 memory ID。([Mem0][10])

**不建议写入 Mem0 的内容**

不要把所有原始用户问题都写成长期记忆。
不要把 analyst 的中间长推理、K 线解释、一次性的新闻噪声统统写进去。
不要把“今天这个问题里临时提到一个股票”立刻当成长期关注标的。

原因很简单：Mem0 虽然能做 semantic search，但如果你把长期记忆池污染成“全是临时上下文”，后面检索召回质量会下降。官方文档也建议用 custom fact extraction prompt 控制只抽“你真正关心的事实”，而不是把所有聊天都留下。([Mem0][6])

---

**七、最关键的定制点：把 Mem0 的抽取和更新 prompt 改成金融版**

这部分直接决定你项目成败。

**1）custom_fact_extraction_prompt**

你要把默认“通用用户偏好抽取”改成“金融投研画像抽取”。
这个 prompt 应该只允许抽以下事实：

* 风险偏好
* 投资期限
* 市场范围（A 股 / ETF / QDII / 黄金）
* 关注板块
* 关注股票 / 基金代码 / ETF
* 明确约束（不碰某类标的、仓位偏好、是否厌恶高波动）
* 回答偏好

并且要加入负例，明确以下内容不抽：

* 临时寒暄
* 单次行情判断
* analyst 的中间分析过程
* 没有被用户明确表达的偏好
* 无法结构化归类的泛泛讨论

Mem0 文档明确建议 fact extraction prompt 要包含允许的事实类型、few-shot 示例、空输出示例，并且严格返回 `{"facts": [...]}` 结构。([Mem0][6])

**2）custom_update_memory_prompt**

你项目里最适合用这一能力。
因为用户投资偏好天然会变，所以你必须定义清楚这四种行为：

* `ADD`：新关注了某个板块或股票
* `UPDATE`：原有偏好被新说法替换，例如“从稳健改成进取”
* `DELETE`：明确表示取消，例如“不要再把新能源记在我的关注列表里”
* `NONE`：与已有记忆一致，不做修改

Mem0 官方文档已经给了这套机制，而且强调这个 prompt 的作用就是“当新事实到来时，决定加、改、删还是不变”，并建议保留 `old_memory` 和原 ID，方便审计。对你的项目，我建议把这个 prompt 进一步金融化：
例如明确写上“最新明确表述优先于旧表述”“股票/板块删除必须在用户明确删除时触发”“不要因为一次临时问询就更新长期风险偏好”。([Mem0][10])

---

**八、存储后端怎么选：Mem0 配 Postgres/pgvector 最适合你**

你原报告里允许 Chroma、Milvus、Weaviate、Postgres 等后端。
如果现在已经收敛到 Mem0，我建议最务实的方案就是：

**Mem0 OSS + Postgres/pgvector**

理由有三点。

第一，Mem0 官方明确支持 `pgvector`，配置里只要把 `vector_store.provider` 设为 `"pgvector"` 即可；文档还给了 `user/password/host/port/connection_string` 等配置项，并说明需要在 Postgres 里先执行 `CREATE EXTENSION IF NOT EXISTS vector;`。([Mem0][11])

第二，你这个项目后面要做 Vue 前端、用户编辑/删除/导出，所以你最终一定还会有结构化业务表。用 Postgres 能让“业务数据”和“记忆向量层”更容易统一治理。

第三，你现在是单用户/本地优先，没必要一开始就引入更重的向量数据库。

如果后面你要把“记忆搜索精度”做得更高，再考虑给 Mem0 配 reranker。OSS 配置文档也明确说可以同时配置 LLM、vector store、embedder、reranker。([Mem0][8])

---

**九、SDK 直连还是 REST 服务：分两阶段最稳**

**第一阶段：先用 SDK 直连。**
在 `Financial-MCP-Agent` 里直接引入 `mem0ai`，用 `Memory.from_config(config)` 或 `AsyncMemory`。这样改动最小，最适合先把逻辑跑通。Mem0 的 `AsyncMemory` 明确适用于 FastAPI、background workers 和任何 asyncio 工作流，并且方法与同步 API 对齐。([Mem0][12])

**第二阶段：再抽成 REST 服务。**
当你接 Vue 前端时，把 Mem0 OSS 的 REST API server 单独部署出来。官方文档明确说这个 FastAPI server 暴露了所有 OSS memory operation，可以通过 HTTP 做 add/search/update/delete/reset，并且自带 OpenAPI `/docs` 页面。需要注意的是：官方也明确提醒，默认镜像不含认证，若暴露给更大网络，必须自己加 auth 和 HTTPS。([Mem0][4])

换句话说，路线应该是：

* 现在：`summary_agent -> Python memory_service -> Mem0 SDK`
* 后面：`summary_agent / Vue -> internal HTTP -> Mem0 REST server`

这样你不会过早服务化，但也不会把未来扩展堵死。

---

**十、按你的项目改造的最小实施步骤**

下面这版可以直接当开发 checklist。

**步骤 1：在项目里引入 Mem0 OSS**
安装 `mem0ai`，并配置一个本地 Postgres/pgvector。Mem0 OSS 配置文档和 pgvector 文档都给了初始化入口。([Mem0][8])

**步骤 2：新增内部记忆服务层**
在 `Financial-MCP-Agent/src/memory/` 下封装 `MemoryService`，不要让 agent 直接调用第三方库。
接口只保留四类：
`search_for_summary(user_id, query)`
`add_conversation_memory(user_id, messages, metadata)`
`update_memory(memory_id, text, metadata)`
`delete_user_memories(user_id)`

这样后面切换调用方式最轻。

**步骤 3：先只改 `summary_agent`**
在 summary 生成前调用 `search_for_summary`，把结果拼成 `memory_context` 注入 prompt；
在 summary 生成后，把“用户输入 + 最终回答”写回 Mem0。
不要一开始就给四个 analyst 都接记忆，否则你很难判断效果问题出在召回、prompt 还是分析器自身。

**步骤 4：把抽取 prompt 金融化**
写一版 `custom_fact_extraction_prompt` 和 `custom_update_memory_prompt`，只围绕投资画像设计。
这一版 prompt 建议先只覆盖 6 类事实：
风险偏好、持有周期、市场范围、关注板块、关注标的、回答偏好。
范围不要一开始放太大。

**步骤 5：为用户主动编辑预留接口**
你后面一定会需要“把某个记忆改掉/删掉”。
Mem0 原生就支持 `update` 和 `delete/delete_all`，所以前期设计 UI 或 CLI 命令时，直接围绕这两个能力展开。([Mem0][5])

**步骤 6：将原始对话和工具输出继续保留在你自己的 raw 层**
不要把“原始审计素材保留 7 天”这件事也压到 Mem0 身上。
Mem0 负责长期记忆抽取与检索；原始对话、tool output、执行日志仍然保留在你自己的 `logs/` 或数据库 raw_event 表里。这样更适合做审计和 evidence 回放。

---

**十一、你下一步开发时最该注意的 4 个坑**

**第一个坑：不要直接照搬 Mem0 的 LangGraph 官方示例。**
官方示例用的是 `MemoryClient()`，并提示要使用 Mem0 Platform API key；这说明它是一个“演示集成思路”的例子，不是最适合你当前金融项目的生产落地方式。你应该借它的集成模式，但实际实现上优先选 OSS `Memory` / `AsyncMemory` 或自托管 REST server。([Mem0][3])

**第二个坑：不要让 Mem0 直接承担 STM。**
短期上下文压缩还是留在 LangGraph state；Mem0 只存抽取后的长期事实。

**第三个坑：fact extraction prompt 不要太宽。**
如果你不约束，Mem0 会把很多无用聊天都抽成“记忆”。官方文档已经专门提醒：prompt 太宽会导致无关事实进入长期记忆。([Mem0][6])

**第四个坑：服务化时要补鉴权。**
Mem0 的 OSS REST server 默认不带 auth，文档明确要求对外暴露前自行加认证和 HTTPS。([Mem0][4])

---

**十二、最终建议**

这份最终版只给你一个主线结论：

**你的 Finance 项目应采用“LangGraph 管 STM，Mem0 管 LTM”的单技术路线。**
第一阶段先把 Mem0 以内嵌 SDK 方式接到 `summary_agent` 上，只实现“读历史偏好 + 写长期画像”；
第二阶段再把 Mem0 抽成内部 REST 记忆服务，给 Vue 前端做编辑/删除/导出；
第三阶段才考虑启用 Mem0 的更高级能力，比如 graph memory 或更复杂的过滤/重排。Mem0 当前的仓库、OSS 配置、LangGraph 集成、REST server、AsyncMemory、自定义 fact extraction / update prompt、update/delete 能力，都足够支撑你这条路线，而且工程侵入性也可控。([GitHub][1])

下一步最有价值的动作，是把它继续下沉成**代码级实施清单**：我可以直接按你的项目目录，给你输出“要新建哪些文件、哪些函数签名、`summary_agent.py` 怎么改、`main.py` 怎么接 thread_id 和 memory_context、`mem0_prompts.py` 第一版怎么写”。

[1]: https://github.com/mem0ai/mem0 "GitHub - mem0ai/mem0: Universal memory layer for AI Agents · GitHub"
[2]: https://docs.mem0.ai/core-concepts/memory-operations/add?utm_source=chatgpt.com "Add Memory - Mem0"
[3]: https://docs.mem0.ai/integrations/langgraph "LangGraph - Mem0"
[4]: https://docs.mem0.ai/open-source/features/rest-api "REST API Server - Mem0"
[5]: https://docs.mem0.ai/api-reference/memory/update-memory?utm_source=chatgpt.com "Update Memory - Mem0"
[6]: https://docs.mem0.ai/open-source/features/custom-fact-extraction-prompt?utm_source=chatgpt.com "Custom Fact Extraction Prompt - Mem0"
[7]: https://docs.mem0.ai/core-concepts/memory-operations/search?utm_source=chatgpt.com "Search Memory - Mem0"
[8]: https://docs.mem0.ai/open-source/configuration "Configure the OSS Stack - Mem0"
[9]: https://docs.mem0.ai/v0x/core-concepts/memory-operations/search?utm_source=chatgpt.com "Search Memory - Mem0"
[10]: https://docs.mem0.ai/open-source/features/custom-update-memory-prompt?utm_source=chatgpt.com "Custom Update Memory Prompt - Mem0"
[11]: https://docs.mem0.ai/components/vectordbs/dbs/pgvector "Pgvector - Mem0"
[12]: https://docs.mem0.ai/open-source/features/async-memory "Async Memory - Mem0"

结论先放前面：**你的短期记忆最好选 LangGraph 原生 STM，而不是再引入第二套“短期记忆框架”**。原因很直接：你现在的主流程已经建立在 LangGraph `StateGraph` 上，而 LangGraph 官方把短期记忆定义为**线程级 state + checkpointer 持久化**，并且现成支持 3 种你最需要的控长策略：**trim、delete、summarize**。它的 Python 仓库大约 **23.3k stars**，最新 SDK release 是 **2026-01-13**，官方文档也明确把 short-term memory 作为当前主线能力来写。对你这种已经跑通多 Agent 工作流的项目，这条路改造最小、含金量最高。([GitHub][1])

我不建议把 **Mem0** 当成 STM。这个不是“Mem0 不强”，而是它的职责不对。Mem0 官方讨论里已经明确说过：它更像**长期记忆层**，至于“一个 session 里用户和助手说过什么”，要靠**消息列表或数据库**自己管；会话一长，还需要你自己做上下文管理。这个判断和你当前项目非常一致：Mem0 继续做 LTM 很合适，但 STM 该留在 LangGraph。([GitHub][2])

如果一定要给你一个“近一年内值得看的 STM shortlist”，我会只留两个名字：
**第一名：LangGraph 原生 STM**，因为它就是你当前栈；
**第二名：Letta**，但仅限于你愿意明显重构运行时。
Letta 仓库大约 **21.6k stars**，定位是 **stateful agents platform**，有 memory blocks、messages、tools 这些完整状态概念；但它更像“把整个 agent runtime 迁到 Letta 上”。而且 Letta 最新文档还写得很清楚：新的 **MemFS** 目前只在 **Letta Code + Letta API** 里支持，**不支持 Docker servers**；对你这种已经有 Python/LangGraph 服务流的项目，这个迁移成本太高，不适合作为短期记忆主线。([GitHub][3])

所以，真正适配你项目的选择其实已经很清楚：

**你的 STM 选型：LangGraph checkpointer + running summary + recent window。**
官方文档把短期记忆写得很直白：state 在每一步开始时读入，在 graph 调用或 step 完成后更新；长对话会遇到上下文窗口、成本和模型分心问题，所以需要 trim、delete 或 summarize。LangChain 这边还给了现成的 `SummarizationMiddleware`，可以按 token 数触发摘要，并保留最近若干条原始消息。([LangChain 文档][4])

基于你的项目，我建议 STM 具体这样落：

**第一层：thread 级持久化。**
每个用户或会话对应一个 `thread_id`，把 `messages`、`running_summary`、少量最近原始消息都存在 LangGraph state 里。LangGraph 官方的 functional API 也支持把“返回给调用方的值”和“保存到 checkpoint 的值”分开，这很适合你把报告输出和内部状态持久化拆开。([LangChain 文档][5])

**第二层：摘要而不是无限堆消息。**
你的项目不适合一直把 analyst 工具输出原样塞进上下文。更稳的做法是：保留最近 **8–12** 条消息原文，把更早的对话压成 `running_summary`；对工具输出只保留“最终结论摘要 + 关键数值 + 证据引用 ID”，不要把整段新闻、整页财务表解释继续带着跑。LangGraph 官方现在推荐的就是这种 summarize messages 路线，而不是无脑全量历史。([LangChain 文档][6])

**第三层：原始审计日志与 STM 分离。**
这一点很关键。社区里关于 LangGraph checkpoint 的讨论提到过：如果你会对 checkpoint 里的 messages 做 summary 或 delete，那它就不应该再充当前端“完整聊天记录”的唯一来源；完整历史最好单独存。对你来说，这正好对应你之前想保留 **7 天 raw_event** 的思路：
LangGraph STM 只管“当前对话够用的上下文”；
单独的 `raw_event`/日志表才管完整回放与审计。([GitHub][7])

按你的目录结构，我会这样插：

在 `state_definition.py` 里，把 STM 扩成这几个字段：
`messages`
`running_summary`
`recent_tool_digest`
`memory_context`（这个给 Mem0 LTM 注入）
`thread_meta`

在 `main.py` 里，固定每次 invoke 都带 `thread_id`。
在汇总前，加一个 `prepare_summary_context`：把 `running_summary + recent_messages + recent_tool_digest + mem0召回结果` 拼成 summary agent 的输入。
在汇总后，加一个 `maybe_summarize_state`：当 token 或轮次超阈值时更新 `running_summary`，并裁掉更早消息。
这样四个 analyst 几乎不用大改，STM 的复杂度主要集中在 summary 前后两个节点。这个做法和 LangGraph 官方“先 conversation、后 summarize_conversation”的模式是一致的。([GitHub][8])

如果你问“有没有经验贴层面的工程结论”，我会给你这三条：

第一，不要把 STM 和 LTM 混成一个库。Mem0 自己的讨论已经把这件事说透了：短期整段会话 history 要单独管理，Mem0 更适合长期可检索事实。([GitHub][2])

第二，别让摘要替代原始证据。LangGraph 的 message summary 是为了控 token，不是为了做不可逆归档；你项目里的 raw 对话、工具输出、报告生成日志应该继续单独保留。([GitHub][7])

第三，Letta 很强，但它更适合“从 Letta 出发造 stateful agent”，不适合“给现有 LangGraph 金融系统最小代价补一个 STM”。尤其 MemFS 目前不支持 Docker servers，这会让你后面的服务化路线更别扭。([Letta Docs][9])

所以最终建议就一句话：

**STM 选 LangGraph 原生；LTM 继续用 Mem0。**
也就是：
**LangGraph 管 thread 内状态、摘要和 recent window；Mem0 管跨会话投资画像与偏好。**
这套组合和你现有项目的耦合度最低，近一年里也都是活跃维护、社区热度高、文档清晰、代码完整的开源路线。([GitHub][1])

下一条我可以直接把这个 STM 方案落成你项目的**代码级改造版**：按你现在的目录，逐个写出 `state_definition.py`、`main.py`、`summary_agent.py` 该怎么改，以及 STM 触发摘要的阈值和 prompt 怎么设。

[1]: https://github.com/langchain-ai/langgraph?utm_source=chatgpt.com "GitHub - langchain-ai/langgraph: Build resilient language agents as graphs."
[2]: https://github.com/mem0ai/mem0/discussions/2818?utm_source=chatgpt.com "Does mem0 not preserve what the agent/ assistant said, is there a conditional filter for that? · mem0ai mem0 · Discussion #2818 · GitHub"
[3]: https://github.com/letta-ai/letta "GitHub - letta-ai/letta: Letta is the platform for building stateful agents: AI with advanced memory that can learn and self-improve over time. · GitHub"
[4]: https://docs.langchain.com/oss/python/langgraph/memory?utm_source=chatgpt.com "Memory overview - Docs by LangChain"
[5]: https://docs.langchain.com/oss/python/langgraph/functional-api?utm_source=chatgpt.com "Functional API overview - Docs by LangChain"
[6]: https://docs.langchain.com/oss/python/langchain/short-term-memory?utm_source=chatgpt.com "Short-term memory - Docs by LangChain"
[7]: https://github.com/langchain-ai/langchain/discussions/29574?utm_source=chatgpt.com "Managing Chat History with LangGraph and Postgres Checkpoints · langchain-ai langchain · Discussion #29574 · GitHub"
[8]: https://github.com/langchain-ai/langgraph/discussions/5664?utm_source=chatgpt.com "Memory Checkpointer vs Messages State · langchain-ai langgraph · Discussion #5664 · GitHub"
[9]: https://docs.letta.com/letta-code/memory/?utm_source=chatgpt.com "Memory | Letta Docs"
