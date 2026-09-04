# D05 报告 SSE 进度澄清结论

## 1. Clarification Context

- Source requirement: `D05_REPORT_SSE_PROGRESS_REQUIREMENT_SPEC.md`
- Code evidence: `D05_REPORT_SSE_PROGRESS_CODEBASE_RECON.md`
- Tracking issue: GitHub Issue #50
- User direction: 自主完成 D04、D05、D06 的 Spec、计划、实现、真实 API E2E、Review、PR 和合并，不要求每个可逆默认决定都停下来等待确认。

本文件把 D05 的产品与工程开放问题冻结为可进入方案权衡的合同。若实现需要数据库迁移、Redis 报告状态/幂等、跨实例 pub/sub、认证协议重构、报告 Prompt/金融逻辑变更或超过一条受保护真实报告调用，必须停止并重新确认；否则按以下默认值推进。

## 2. Frozen Decisions

| ID | Question | Frozen decision | Reason / evidence |
| --- | --- | --- | --- |
| D05-Q01 | SSE 是否替代轮询 | SSE 是新任务的首选 transport；只有连接建立、首帧、传输或协议失败才自动切为轮询；轮询 API 永久保留 | 用户目标和 Spec 明确要求主路径 + fallback |
| D05-Q02 | 降级是否重建任务 | 禁止。SSE 与 polling 始终使用首次 POST 返回的同一 `task_id/report_id`，fallback 不再 POST `/generate` | 防重复模型费用与副作用；D06 再治理重复提交 |
| D05-Q03 | 公开协议版本 | 新增单一 `report-progress-v1`，不复用 `chat-stream-v2`，也不维护旧报告 SSE 双协议 | 报告是长任务快照/阶段流，不是聊天正文流；当前 main 没有旧 SSE 公共合同 |
| D05-Q04 | SSE 事件集合 | `stream_ready`、`stage_update`、`task_terminal`；heartbeat 使用 SSE comment，不进入业务 reducer | 最小集合即可证明连接、真实阶段和唯一终态，避免 debug 事件膨胀 |
| D05-Q05 | 公共 envelope | 每个业务事件包含 `protocol_version/task_id/report_id/sequence/emitted_at/type`；sequence 在单连接内从 1 递增 | 满足关联、排序和任务隔离；D05 不宣称跨连接重放 |
| D05-Q06 | 公开阶段 | `PREPARING`、`FUNDAMENTAL_ANALYSIS`、`TECHNICAL_ANALYSIS`、`VALUATION_ANALYSIS`、`NEWS_ANALYSIS`、可选 `PERSONALIZATION`、`SYNTHESIZING`；终态不作为普通阶段 | 与真实报告节点和 UI 五个核心步骤对应；可选 STM/LTM 归并为一个稳定用户阶段 |
| D05-Q07 | 阶段状态 | `RUNNING/SUCCEEDED/FAILED/SKIPPED`；四个 analyst 可并行、完成顺序不固定；每个 stage 只能单调进入一个终态 | 不能把并行节点伪装成固定串行进度 |
| D05-Q08 | 总进度计算 | `pending=0`、任务启动/准备 `10→20`、四个 analyst 每完成一个总进度增加 15 到 80、可选个性化最多 85、综合开始/结束 `90→95`、持久化完成 `100`；任何写入不得降低已有 progress | 当前固定 identity 百分比会因并行完成乱序回退；改为完成计数才真实单调 |
| D05-Q09 | 权威事件源 | 阶段事件只能在 `run_report_task` 的真实准备动作或 LangGraph node start/end 转换点产生；不得从前端 timer、Agent 日志或最终结果事后动画生成 | 满足 Authoritative Progress，避免泄露日志/Prompt |
| D05-Q10 | transport 与 Application 边界 | 工作流通过 typed、协议无关 progress publisher 发布；SSE presenter 负责 sequence/wire/heartbeat；数据库 `Report` 仍是任务终态与 polling 权威 | 为 D06 替换 publisher/snapshot 留出端口，同时避免 HTTP 类型侵入 Agent |
| D05-Q11 | D05 基础设施 | 允许受限进程内 publisher 支撑当前单 worker 的低延迟实时事件，同时每次连接先读取数据库权威 snapshot，空闲时再校准任务状态；publisher 不是恢复真相源 | 当前 Docker 明确单 worker；完全依赖内存会与 Spec 冲突，完全 DB 高频观察又弱化实时节点事件 |
| D05-Q12 | D06 边界 | D05 不持久化 event history、不处理 `Last-Event-ID` replay、不做 Redis pub/sub/snapshot/idempotency；D06 用同一端口替换/增强 | 用户把 Redis 治理单列为 D06 P0 |
| D05-Q13 | 认证 transport | 浏览器用 `fetch` + `Authorization: Bearer` + `AbortController` 读取标准 SSE；禁止原生 EventSource query token | 现有认证是 header；历史 query token 会进入 URL/日志 |
| D05-Q14 | 所有权与不存在语义 | SSE 在返回 `StreamingResponse` 前验证；按 `task_id + auth.user_id` 同时查询，跨用户与不存在统一安全 404；未登录 401 | 不泄露他人任务存在性，且流开始后不再发送 HTTP auth 错误 |
| D05-Q15 | 状态 API 安全 | `/status` 保持路径和字段兼容，但与 SSE 共用安全 snapshot projector；公开固定 `error_code/error_message`，不再返回内部 `str(exc)` | D05-C05/C06 要求 SSE、fallback、direct polling 终态一致且安全 |
| D05-Q16 | 旧 `error_msg` 字段 | 为兼容保留 optional `error_msg`，但只填安全用户消息；新增 optional `error_code`，内部异常仅在脱敏日志中保留类型 | 兼容已有前端，同时消除原始异常泄漏 |
| D05-Q17 | 首次连接行为 | 成功鉴权后立即发送 `stream_ready` 和当前数据库 snapshot 对应的安全状态；若任务已终止，随后发送唯一 `task_terminal` 并关闭 | 历史任务/快速任务也能正确收口，不等待新内存事件 |
| D05-Q18 | 重连语义 | D05 前端不自动无限重连；首连或中途失败直接 fallback polling。手工重新进入页面只读取当前权威状态，不补发完整历史 | 完整断线恢复/事件 replay 属于 D06 |
| D05-Q19 | heartbeat | 服务端每 15 秒发送 `: heartbeat` comment，并在该周期校准数据库终态；Nginx 关闭 buffering 并保留 300 秒以上 read timeout | 避免代理空闲断线；comment 不污染业务 sequence |
| D05-Q20 | 客户端首帧预算 | HTTP 成功后 5 秒内未收到合法 `stream_ready` 视为 SSE 不可用，abort 后 fallback | stream_ready 不依赖模型，应快速到达；可稳定测试 buffering |
| D05-Q21 | polling 策略 | 立即 poll 一次，之后串行等待 2 秒；不使用 async `setInterval`。连续错误采用 2/4/8/15 秒有限退避，最多 5 次后停止并提示；页面/任务总观察预算 15 分钟 | 防重叠、静默无限循环与资源泄漏，同时覆盖常见 2–5 分钟报告 |
| D05-Q22 | transport UI | 明确展示 `正在连接实时进度`、`实时更新中`、`实时连接中断，已切换轮询`、`轮询确认中` 和终态；技术降级不把报告任务标成 failed | 用户能区分任务失败与 transport fallback |
| D05-Q23 | task reducer | 校验 task/report/sequence；同 stage 终态不回退，总 progress 取 max，任务终态锁定；旧 task 和迟到请求一律忽略 | 解决当前历史切换、异步 interval 和迟到响应覆盖问题 |
| D05-Q24 | 生命周期 | 同一 composable 最多一个 AbortController 和一个串行 polling loop；生成新任务、选择历史、组件卸载、beforeunload、退出登录和终态都执行同一个 cleanup | D05-C07 明确要求资源和任务隔离 |
| D05-Q25 | 报告失败 | `task_terminal(status=failed)` 是权威业务终态，不触发 polling fallback；只显示安全错误码/消息并关闭所有 transport | transport 失败与工作流失败必须区分 |
| D05-Q26 | Nginx | 为 `/api/report/events/` 增加专用 location：HTTP/1.1、`proxy_buffering off`、`proxy_cache off`、空 Connection header、读取超时和 chunked 透传；FastAPI 同时返回 no-cache/no-buffer headers | 当前通用 `/api` 无法证明逐事件 flush；旧分支仅提供配置线索 |
| D05-Q27 | 新依赖 | 不新增 Python 或 npm 生产依赖；SSE 使用 Starlette `StreamingResponse`、浏览器 fetch/TextDecoder | 当前栈已足够，降低 lockfile 和供应链成本 |
| D05-Q28 | 历史实现 | commit `8ef46f0` 和 `D:/FinanceProject/Finance` 的 SSE 代码标记为 rejected baseline；只复用专用 Nginx headers、heartbeat、subscribe cleanup 的概念 | 旧实现有 query token、untyped dict、跨 D05/D06、无严格 parser/完整 E2E 等缺陷 |
| D05-Q29 | Live 数量 | 只允许一条真实报告任务；使用真实模型与现有只读金融数据，隔离 SQLite/临时 artifact，总测试超时 12 分钟，不自动重试整份报告 | 满足真实运行证据并限制多 Agent 成本；重试可能重复付费 |
| D05-Q30 | Live 断言 | 断言真实 node stage、至少两个非终态业务阶段、单调 sequence/progress、唯一终态、DB/REST/SSE 正文 hash 一致、无凭证/Prompt/报告正文进入验收 artifact | 不断言模型措辞或实时行情数值，只证明工程合同 |

## 3. Public Protocol Semantics

### 3.1 Common Envelope

```text
protocol_version = report-progress-v1
task_id
report_id
sequence              # 当前 SSE 连接内严格递增
emitted_at             # UTC ISO-8601
type
```

`stream_ready` 额外包含当前任务 `status/progress` 和 transport=`sse`。它只表示连接与权限校验成功，不表示报告成功。

`stage_update` 包含：

```text
stage                  # 冻结枚举
stage_status           # RUNNING/SUCCEEDED/FAILED/SKIPPED
progress               # 0..99，单调
message                # 后端白名单短文案，最长 120 字符
elapsed_ms?            # 仅阶段耗时，不含原始载荷
error_code?            # 仅固定公开错误码
```

`task_terminal` 包含：

```text
status                 # completed/failed
progress               # completed=100；failed 保留最后单调值
report_id?             # completed 必填
error_code?
message
```

### 3.2 Required Ordering Invariants

```text
stream_ready(sequence=1)
-> zero or more stage_update
-> exactly one task_terminal
-> connection close
```

- 四个 analyst 的 `RUNNING/SUCCEEDED` 可以交错，不规定互相顺序。
- 对同一个 stage：`RUNNING -> SUCCEEDED|FAILED|SKIPPED`；终态后不得回退或改写成另一终态。
- `SYNTHESIZING RUNNING` 必须晚于四个 required analyst 的终态。
- `task_terminal(completed)` 必须晚于 `SYNTHESIZING SUCCEEDED` 和数据库正文提交。
- 技术连接失败不会产生伪造的 `task_terminal(failed)`；由前端切换 polling。
- heartbeat comment 不消耗 sequence，不进入 Store。

### 3.3 Snapshot and Fallback Semantics

- 新连接先从 `reports` 行构造安全 snapshot；进程内 publisher 只提供当前连接期间的低延迟事件。
- 若 publisher 事件丢失，heartbeat 校准或 polling fallback 最终以数据库 `status/progress/content` 收口。
- polling 不需要重建所有未收到的并行 stage 历史；它只更新任务级单调进度和终态，保留已经合法收到的 stage 状态。
- D05 不实现 durable cursor；不能在 README/面试材料宣称断线后完整重放。

## 4. Security and Redaction Contract

禁止进入 SSE data、状态 API、安全消息、前端 Store、日志摘要和验收 artifact：

- JWT、Authorization、Cookie、API key、数据库/Redis URL 及密码。
- 用户原始 command、完整画像、Memory 正文和身份信息。
- system/developer Prompt、Chain-of-Thought、模型响应对象、完整报告正文。
- 工具参数/原始结果、DataFrame、MCP payload、AgentState、内部 Trace attributes。
- Python exception 文本、stack trace、文件绝对路径和 Provider 私有响应。

允许进入公开事件的内容必须由显式 Pydantic Schema 和阶段/消息白名单构造；禁止对 AgentState、ORM 或 exception 直接 `model_dump()`/`str()` 后透传。

## 5. Frozen Test Scope

用户已要求测试在开发前确定，并避免无价值的重复用例。本轮只冻结下列最小充分集合：

| ID | Layer | Single responsibility | Acceptance covered |
| --- | --- | --- | --- |
| D05-T01 | Unit | 参数化验证公开事件类型、白名单、sequence、stage 单调和 progress max；负例证明敏感字段无法进入 Schema | C02/C04/C05/C06 |
| D05-T02 | Unit/runner | 用可控真实 LangGraph fake nodes 产生并行 start/end，验证按完成计数单调、至少两个业务阶段、根图只执行一次、DB 唯一终态 | C01/C02/C05 |
| D05-T03 | Contract | 一个参数化 SSE route 测试覆盖 Bearer header、owner/not-found、headers、initial snapshot、heartbeat/terminal、disconnect cleanup | C01/C05/C06/C07 |
| D05-T04 | Frontend parser/reducer | 一个参数化 Vitest 覆盖合法帧、未知字段、task/sequence 错误、重复/迟到/终态回退 | C02/C04/C05/C07 |
| D05-T05 | Frontend composable | 一个场景表覆盖主 SSE、首帧超时、中途断开、malformed、fallback 同 task、无第二次 generate、历史切换和 unmount cleanup | C01/C03/C04/C07 |
| D05-T06 | Integration | 隔离数据库中真实 report runner + SSE presenter + polling projector，对成功/失败各一次验证三路径终态一致和安全错误 | C01/C05/C06 |
| D05-T07 | Offline Compose E2E | 真 Nginx、生产 Vue 构建、FastAPI、LangGraph、PostgreSQL；deterministic external nodes 完成 SSE 主路径，并用显式测试 header/fixture 强制 SSE 失败后同任务 polling | C01/C03/C08 |
| D05-T08 | Compatibility regression | 保留创建/status/history/detail/download/delete 与 D03/D04/Skills/Memory 默认回归；不逐字段复制已有测试 | C08 |
| D05-T09 | Protected Live | 一条真实模型 + 只读数据报告；记录低敏 stage/sequence/progress/elapsed/hash/调用计数，验证唯一任务和唯一终态 | C09 |

Explicitly excluded tests:

- 不新增 Playwright/Cypress/Selenium；浏览器体验用 Vitest 组件/composable + 启动真实前后端的人工检查补充。
- 不对每个 heartbeat、每个百分比或每个 Agent 文案写独立测试。
- 不固定模型措辞、行情数值、各并行 analyst 的完成顺序。
- 不在默认 CI 调用模型、MCP、Tushare 或生产服务。
- 不为 D05 测 Redis、多实例、Last-Event-ID、持久化 replay 或 duplicate submit；这些转入 D06。

## 6. Compatibility and Failure Matrix

| Situation | User-visible result | Server task effect | Transport action |
| --- | --- | --- | --- |
| SSE 正常 | 实时阶段 + 最终报告 | 原任务正常执行一次 | terminal 后关闭 |
| HTTP/SSE 建立失败 | 显示已切换轮询 | 不修改、不重建任务 | abort SSE，立即 poll 同 task |
| 首帧超时/非法 content-type | 显示已切换轮询 | 不修改任务 | abort，poll |
| 中途断开/malformed/sequence gap | 保留合法阶段，显示降级 | 不把任务置 failed | abort，poll |
| 报告工作流失败 | 显示安全失败码/文案 | DB authoritative failed | 收到 terminal 后关闭，不 fallback |
| polling 偶发错误 | 显示轮询重试 | 不修改任务 | 有界退避 |
| polling 连续 5 次失败/15 分钟超时 | 显示状态确认失败，可从历史恢复 | 不取消/重跑任务 | 停止所有 timer/request |
| 查看历史/离开页面/退出 | 展示所选页面 | 后台报告继续执行 | abort SSE，停止 poll；D05 不新增取消任务 |
| 已完成任务重新打开 | 展示历史正文 | 不执行 workflow | 直接 detail/status，不需要持续 SSE |

## 7. Decisions Not Reopened Without New Evidence

- 不把 JWT 放 URL，不改变登录/JWT 协议。
- 不从前端计时器、固定动画、Agent 日志或最终报告倒推出“实时阶段”。
- 不为正常 SSE 和 polling 建两套业务状态模型。
- 不引入新的生产依赖、数据库字段或消息队列。
- 不实现报告取消/暂停/恢复按钮，不让页面卸载取消服务端报告任务。
- 不把 report正文做 token streaming。
- 不整包 cherry-pick `8ef46f0` 或把历史 `Finance` 加入运行时。
- 不把 D06 的 Redis 幂等、状态快照、跨实例或 replay 提前塞进 D05。

## 8. Handoff to Solution Tradeoff

方案阶段至少比较以下方向：

1. 纯数据库观察型 SSE：服务端周期读取 `reports` 行并投影事件。
2. 纯进程内 typed publisher：工作流节点直接发布，SSE 订阅。
3. 混合方案：真实节点 typed publisher 提供低延迟阶段，数据库 initial snapshot/heartbeat 校准/轮询 fallback 提供权威收口，并为 D06 保留可替换端口。

比较维度必须包括：权威性、并行阶段真实性、跨请求/单 worker 边界、认证、sequence/终态、断连资源、Nginx flush、D06 演进、实现/测试成本、默认离线与 Protected Live 负担。推荐方向需满足本文件全部冻结决策，不能用“实现更简单”为理由缩小最终目标。
