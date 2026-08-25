# CLARIFICATION_QUESTIONS.md

## 1. Clarification Status

- Status: Resolved for solution tradeoff
- Scope: Milestone 7 only
- Decision authority: 用户已授权在不破坏既有功能、遵守企业级工程规范和完整验收的前提下由实现方选择安全默认值。

## 2. Resolved P0 Decisions

### Q1. 自然语言命令如何识别？

- Decision: M7 使用有版本的 deterministic Chinese command parser，覆盖明确的 inspect/update/delete/forget/confirm/cancel 句式和有限同义表达；不在默认路径调用 LLM。
- Reason: 记忆写删是有副作用操作，确定性 parser 更容易审查、离线测试和 fail-closed；模型解析可在后续 protected-live 评测中作为候选增强，但不能扩大默认写权限。
- Failure behavior: 未命中明确命令时继续普通金融链；命中命令词但目标/范围/值不完整时返回澄清/拒绝，不猜测执行。

### Q2. “忘掉我的文本记忆”作用范围是什么？

- Decision: 解释为当前已认证用户的全部 active 文本记忆，但只创建安全预览和 pending confirmation，不直接删除。
- Reason: 这是用户自然语言的通常含义，同时属于宽范围破坏性操作，必须把范围和计数冻结后再确认。
- Limit: 预览只返回类别和影响计数/受限片段，不返回其他用户或内部 payload；最终执行以冻结 ID+version 集合为上限，新增记录不被意外纳入。

### Q3. pending confirmation 如何持久化？

- Decision: 新增 PostgreSQL authority 表，以随机 command ID、authenticated user、session、command kind、normalized scope、target snapshot、fingerprint、expected versions、safe preview/count、status、expires_at 和 consumed_at 表达单次状态机。
- Reason: 内存/Redis token 不能在重启后恢复，也不能作为权限权威；数据库约束和行锁可证明 one-shot、幂等和跨用户/会话隔离。
- Default TTL: 10 分钟，沿用总计划中的 pending destructive confirmation 默认值。
- Supersede: 同一用户/会话出现新的冲突性破坏命令时，旧 pending command 变为 `CANCELLED/SUPERSEDED`。

### Q4. 命令处理是否保存用户消息和会话？

- Decision: 先通过现有 `prepare_turn` 建立/锁定会话并保存用户消息，再执行命令预检；命令结果作为 assistant message 与 pending/audit/authority/outbox 在同一调用方事务中提交。
- Reason: pending 必须绑定真实 session，命令也属于对话审计；同时用例必须在命令终态后跳过 retrieval 和 finance workflow。
- Compatibility: 普通请求继续原有 prepare/retrieval/workflow/save 流程。

### Q5. 高影响 profile 字段如何处理？

- Decision: 风险等级、收益目标、投资周期等高影响字段的自然语言修改不直接写 authority，统一创建 pending confirmation；回答偏好、关注板块等低影响显式命令可直接写入，仍记录审计和一致性状态。
- Reason: 保持 M5 “高影响字段 confirmation-only”不变量，不让 parser 绕过候选治理。

### Q6. 旧 memory API 写路径怎么处理？

- Decision: M7 将公开 profile/item CRUD 的写操作收口到同一 authoritative application use case/result contract；保留已有路径和兼容字段，不保留第二套直接 Mem0/legacy write authority。
- Reason: 同一行为必须只有一个权限、审计、Outbox、缓存失效和错误语义来源；旧读模型可逐步兼容，但写入不得双轨。
- Delete-all: 旧 `confirm=true` 不再直接执行宽范围删除；改为创建 pending command，并通过统一确认接口或聊天确认完成。

### Q7. REST 与 WebSocket 如何兼容？

- Decision: `ChatOutcome` 增加 optional `memory_command`；REST response 添加 optional object；WebSocket 添加 `memory_command` control frame，原 reply/session/context/done 帧保持可读。
- Reason: additive contract 不破坏旧客户端，并让前端能够刷新 memory store 和展示确认状态。

### Q8. 前端展示多少正文？

- Decision: 仅向当前用户展示最长 160 字符的受限片段；pending preview 默认类别+计数，单条明确操作可展示受限片段。
- Reason: 满足可检查性和确认可理解性，同时降低 UI、日志、截图中的隐私暴露。
- Logging rule: 前端 console、后端 log/trace 永不记录正文或命令原文。

### Q9. 前端测试工具怎么选？

- Decision: 使用 Vitest + Vue Test Utils 做组件/composable tests；使用 Playwright 做一条由 CI/Compose 控制的浏览器旅程。
- Reason: 与 Vue/Vite 技术栈收敛、社区成熟、可离线 mock；Playwright 能验证真实 Nginx/前端/后端交互。
- Delivery: 固定依赖版本并更新 `package-lock.json`；CI 新增 focused frontend test，浏览器 E2E 是否在 PR 默认门禁运行由方案阶段根据时间和镜像成本决定，但 M7 本地/Compose 验收必须运行。

## 3. Resolved P1 Defaults

- Parser version: `memory-command-parser-v1`。
- Contract/schema version: `memory-command-v1`。
- Pending TTL: 600 秒。
- 单次直接删除：仅允许一个明确 record ID/唯一解析目标。
- 宽范围最大预览：影响计数完整，正文片段最多 5 条且每条最多 160 字符。
- Confirm/cancel expressions: 仅在存在当前 session pending command 时解析“确认删除/确认/取消/不要删除”等明确句式；不接受模糊“好/行”。
- One-shot terminal states: `SUCCEEDED`, `CANCELLED`, `EXPIRED`, `REJECTED`, `SUPERSEDED`。
- Derived states: 复用 `CONSISTENT/PENDING/PARTIAL/DEGRADED`（以现有合同实际枚举为准）。
- Retention: pending command 的安全元数据按计划默认保留 180 天；物理清理/合规 SLA 不在 M7 宣称。

## 4. Explicit Non-Decisions

- 不在 M7 启用 LLM-based command parser。
- 不在 M7 运行真实 Mem0、真实 Tushare 或生产写入。
- 不在 M7 承诺生产级延迟、吞吐、SLA、合规保留或多副本指标。
- 不增加 Redis Streams/Kafka/Celery 或独立 Mem0 服务。
- 不把所有历史 memory route/service 一次性重构；只收口 M7 会触达的写路径并保留兼容读取。

## 5. Acceptance Clarifications

- 必须证明命令分支 `tool_call_count == 0` 且未进入 permission/plan/execute/evidence stages。
- 必须证明普通金融请求仍完整进入既有受控阶段。
- 必须证明 authority write/delete 与 audit/outbox/pending terminal transition 同事务；rollback 后无半写。
- 必须证明 cross-user/cross-session/replay/expired/stale-version confirmation 全部 fail-closed。
- 必须从浏览器或真实前端代理发起至少一条中文 update 和一条 forget+confirm 旅程。
- 默认验收使用 synthetic users 和 deterministic providers，所有测试数据在隔离数据库/卷中清理。

## 6. Handoff

All P0 product and safety decisions required for solution comparison are resolved. The next step should compare implementation options against current repository boundaries and current official/open-source practice, then produce `SOLUTION_TRADEOFF.md` without writing runtime code.
