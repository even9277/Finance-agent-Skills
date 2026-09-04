# D04 受控交互 UI 澄清结论

## 1. Clarification Context

- Source requirement: `D04_CONTROLLED_INTERACTION_UI_REQUIREMENT_SPEC.md`
- Code evidence: `D04_CONTROLLED_INTERACTION_UI_CODEBASE_RECON.md`
- Tracking issue: GitHub Issue #48
- User direction: 自主继续完成 Spec、实现、真实 API E2E、Review、PR 和合并；不要求在每个非破坏性默认决策前暂停。

本文件将 Requirement Spec 的开放问题冻结为可进入方案权衡的产品合同。若后续代码证据要求修改数据库、Redis、认证、Prompt、Skill/Tool 权限、金融决策规则或新增生产依赖，必须停止并重新确认；否则按以下默认值推进。

## 2. Frozen Decisions

| ID | Question | Frozen decision | Reason / evidence |
| --- | --- | --- | --- |
| D04-Q01 | 用户可见事件最小集合 | 新增 `trace_summary`、`plan_preview`、`step_status`、`tool_status`、`verification_summary`；继续保留 D03 与 Skill/Memory/Context 帧 | 对齐面试文档 Claim；五类事件都能映射到现有权威阶段 |
| D04-Q02 | 协议版本 | 继续使用 `chat-stream-v2`，新增帧为同一信封下的类型化 union 成员 | D03 已为可扩展控制帧建立 request/session/sequence；无破坏性字段冲突 |
| D04-Q03 | 计划何时公开 | 只在 `PlanValidator` 返回 `ValidatedToolPlan` 后发送，且必须先于该计划的 step/tool RUNNING | 防止展示不可执行草稿，符合当前 Validator-only execution 边界 |
| D04-Q04 | 计划版本 | 首个已校验计划 `revision=1`；每次通过校验的补证计划 revision 递增；同一 request 内稳定 | 支持真实 bounded replan，避免用数组位置覆盖状态 |
| D04-Q05 | 计划步骤内容 | `step_id/title/purpose/required/status/depends_on/subject_summary`；不公开原始 arguments、idempotency key、permission hash | 足够解释执行目的，同时避免泄露内部契约 |
| D04-Q06 | 步骤状态 | 公共枚举冻结为 `PLANNED/RUNNING/SUCCEEDED/FAILED/SKIPPED/REPLANNED/CANCELLED` | 覆盖 UI 生命周期；与只表示结果的领域 `StepStatus` 分离 |
| D04-Q07 | 工具状态 | 独立 `tool_status`；枚举为 `STARTED/SUCCEEDED/FAILED/SKIPPED/CANCELLED` | 工具调用与业务步骤不是同一生命周期，避免把细节塞入 step payload |
| D04-Q08 | 工具显示内容 | `tool_call_id/step_id/display_name/status/attempt/elapsed_ms/parameter_summary/result_summary/error_code`；summary 为受控短文本 | 支持运行解释和失败定位，不暴露完整参数/结果 |
| D04-Q09 | 工具名称 | 后端维护稳定中文显示名映射；未知工具显示“受控数据工具”，不把任意内部函数名直接输出 | 用户可读且防内部实现泄露 |
| D04-Q10 | 参数摘要 | 只允许标的、时间范围、数据维度等明确白名单；每项为短文本，整体有长度上限 | 当前 `ToolArgument` 是通用结构，不能直接序列化到公网 |
| D04-Q11 | 结果摘要 | 只展示“已返回可校验证据 / 未返回可用数据 / 调用失败”等状态摘要和事实条数，不展示事实值 | 事实内容仍由最终受证据约束回答承担，过程卡片不旁路 Verifier |
| D04-Q12 | 证据摘要 | `SUFFICIENT/PARTIAL/INSUFFICIENT`、claim level、accepted/rejected count、covered/missing dimensions、用户可读限制说明 | 可由 `VerificationResult` 确定性投影，不依赖模型 Judge |
| D04-Q13 | Trace summary | 只展示低基数阶段、状态、耗时和固定中文说明；不透传 WorkflowEvent 任意 attributes | 满足过程可见性并保持内部 Trace 与公共 API 分离 |
| D04-Q14 | Replan 展示 | 新 revision 追加安全原因；旧已完成步骤保留；未执行且被替换步骤标记 `REPLANNED`；新增步骤使用新 ID | 与 `combined_plan` 和 bounded replan 对齐，不篡改历史 |
| D04-Q15 | 当前轮/历史归属 | Store 按 request ID 保存当前页面内的执行视图，页面默认展示当前或最近一轮；切换/加载会话清理不匹配状态；不跨刷新恢复 | 当前 Message 没有 request ID 持久化；跨刷新恢复属于 D06 |
| D04-Q16 | 并发与迟到事件 | reducer 必须校验 request/session/revision/stable ID；重复事件幂等，状态不得从终态回退，旧 request 不能覆盖当前面板 | 对齐 D03 严格关联和并发隔离 |
| D04-Q17 | 可见停止动作 | D04 包含“停止生成”；用户点击后关闭当前 WS、触发 D03 上游取消/事务回滚，本地状态立即进入 CANCELLED | D03 已有取消能力但没有产品入口，属于本轮明确体验 Gap |
| D04-Q18 | 取消后的步骤 | 正在运行的 step/tool 标记 CANCELLED；尚未运行标记 SKIPPED；已成功历史保持；不追加“连接错误”文本 | 用户主动取消不是技术故障，不能伪装失败或成功 |
| D04-Q19 | HTTP fallback | 保留当前同步文本回退；清理未完成控制态并显示“过程状态不可用”的非错误降级，不伪造计划/工具/证据 | HTTP 响应没有过程事件，D04 不复制执行链或增加第二协议 |
| D04-Q20 | 无工具/澄清路径 | 不显示空计划和空工具卡；可显示已完成的 route/clarification trace summary；Skill confirm 继续走既有卡片 | 避免为了演示制造虚假步骤 |
| D04-Q21 | 心跳 | D04 不新增 heartbeat | 当前代理 300 秒超时且无空闲超时事故证据；避免扩大协议范围 |
| D04-Q22 | 公开错误 | 只暴露稳定 error code 和固定/白名单用户消息；内部异常类型只进日志 | 延续 D03 安全错误边界 |
| D04-Q23 | UI 结构 | 一个 `ControlledExecutionPanel` 组合 Plan、Step/Tool、Evidence 和 lifecycle 子视图；默认摘要展开层级，不做原始 Debug 面板 | 降低信息过载；组件只渲染 typed props |
| D04-Q24 | Stop 位置 | streaming 时在输入区显示明显的“停止生成”按钮，同时执行面板显示“正在执行”状态 | 用户操作距离输入区最近；不将交互藏入详情卡 |
| D04-Q25 | Browser 自动化依赖 | 不新增 Playwright；使用 Vitest 组件测试 + 实际启动后的浏览器验收 | 当前仓库无 Playwright，D04 不为单一功能扩大依赖 |
| D04-Q26 | Live 用例数量 | 最多两例：正常真实模型 + 真实 Tushare 多步骤；第二例使用真实模型和确定性失败/受限工具或无工具路径 | 控制成本并覆盖成功与降级；禁止生产写 |
| D04-Q27 | Live 断言 | 断言 plan 在 execution 前、step/tool 状态闭合、verification 在 final end 前、正文/数据库一致、Trace 和公开摘要不泄密 | 真实调用必须证明控制链，不只证明 HTTP 200/有文本 |
| D04-Q28 | 文档更新 | 更新 README 中已过时的 WebSocket/D04 状态，并新增 D04 验收报告；不改面试原文 Claim | 主仓库事实说明必须与代码一致，面试文档属于外部需求来源 |

## 3. Public Event Semantics

### 3.1 Common Envelope

所有新帧继续包含：

```text
protocol_version = chat-stream-v2
request_id
session_id
sequence
type
```

Router 继续拥有公开 `sequence`。领域 `WorkflowEvent.sequence` 只属于内部 Trace，不直接复制为公开 sequence。

### 3.2 Required Ordering Invariants

```text
stream_start
-> zero or more trace_summary
-> plan_preview(revision=N, validated=true)
-> step_status(RUNNING) / tool_status(STARTED)
-> tool_status(terminal) / step_status(terminal)
-> optional plan_preview(revision=N+1) and replan statuses
-> verification_summary
-> content_delta...
-> optional existing committed control frames
-> exactly one stream_end OR stream_error
```

- 并行工具的完成顺序可以不同，但每个 `tool_call_id` 和 `step_id` 的局部状态必须单调。
- 技术失败可以在任意未终止位置进入唯一 `stream_error`。
- 业务 `PARTIAL` 仍通过 `stream_end(status=PARTIAL)` 提交，不映射为技术错误。
- `skill_confirm` 等提前终止分支不要求 plan/step/tool/verification。

### 3.3 Status Monotonicity

- Step: `PLANNED -> RUNNING -> SUCCEEDED|FAILED|SKIPPED|CANCELLED`。
- 未运行步骤可从 `PLANNED -> REPLANNED|SKIPPED|CANCELLED`。
- Tool: `STARTED -> SUCCEEDED|FAILED|CANCELLED`；未实际调用的去重/依赖跳过可直接 `SKIPPED`。
- 已进入终态的相同 ID 不允许被迟到帧改写成 RUNNING 或另一个终态。
- 更高 plan revision 不删除低 revision 的已完成历史。

## 4. Security and Redaction Contract

禁止进入公开帧、前端 Store、测试 artifact 和普通日志的内容：

- API key、token、Authorization、Cookie、数据库连接串。
- 原始 system/developer prompt、Chain-of-Thought、模型私有响应对象。
- `ToolPlanStep.arguments` 完整结构、`idempotency_key`、权限/Registry 内部内容。
- 工具原始 payload、DataFrame、完整 Evidence facts、内部异常文本/堆栈。
- 完整用户画像、Memory item 正文和与当前展示无关的用户输入。

允许公开的内容必须由后端显式构造，不得用 `asdict()` / `model_dump()` 对领域对象整体透传。

## 5. Acceptance Mapping

| Requirement case | Required evidence |
| --- | --- |
| D04-C01 | Backend/WS/Frontend tests + real API E2E + browser |
| D04-C02 | Executor observer ordering + reducer duplicate/out-of-order tests |
| D04-C03 | Deterministic failing tool E2E + PARTIAL/verification/component tests |
| D04-C04 | Existing recoverable replan fixture + public protocol/store/UI tests |
| D04-C05 | Clarification/Skill confirm/static regression; zero fake control cards |
| D04-C06 | stop component/composable + backend disconnect rollback contract |
| D04-C07 | concurrent WS presenter + frontend stale request reducer tests |
| D04-C08 | full existing Skill/Memory/Context/Compression + D03 regression |

## 6. Decisions Not Reopened Without New Evidence

- 不建立第二套 Agent Runtime、WebSocket 协议或前端状态源。
- 不把 Trace Sink 当成公开 UI API。
- 不从最终 `ConversationResult` 事后回放伪造实时步骤。
- 不持久化 D04 卡片，不提前实现 D06。
- 不修改金融结论规则，不把工具成功等同于证据充分。
- 不新增前端 E2E 框架或生产依赖。
- 不把真实 API 测试加入默认离线 CI。

## 7. Handoff to Solution Tradeoff

方案阶段需要比较至少以下方向：

1. 扩展现有 Trace Sink 并从 Trace 生成公开事件。
2. 为 Workflow/Executor 增加独立 typed async progress observer，由 Application 转成公开流事件。
3. 只在最终 `ConversationResult` 生成完成后投影所有控制事件。

比较维度必须包括：权威时序、背压/取消、公共安全投影、与现有 Trace 的解耦、类型与测试成本、对 D03 事务语义的影响、是否会形成双轨状态源，以及后续 D06 恢复能力的演进空间。
