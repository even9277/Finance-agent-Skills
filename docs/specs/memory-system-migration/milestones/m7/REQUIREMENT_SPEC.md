# REQUIREMENT_SPEC.md

## 1. Task Type

Primary type: New Feature

Secondary types: Backend API, Agent workflow change, Frontend workflow, Persistent-data safety, Test / Evaluation Improvement, Engineering Governance

Classification rationale: M7 adds a user-visible memory command capability across the controlled chat entrypoint, memory API, and frontend while preserving the already-delivered memory authority, cache, semantic-index, and controlled-finance boundaries.

## 2. Requirement Restatement

用户需要能够在正常中文对话中检查、增加、修改、删除或忘记自己的记忆，例如“我的风险偏好改成稳健型”“以后回答简短一点”“删除新能源偏好”“忘掉我的文本记忆”。系统需要先识别这是记忆操作，再在执行金融规划、工具调用和证据链之前完成安全的记忆命令处理。

记忆命令必须只作用于当前已认证用户，并明确反馈“已修改、待确认、已删除、未找到、已拒绝或部分完成”等结果及派生一致性状态。歧义或批量破坏性请求不能直接执行，必须生成绑定用户和会话的单次确认命令；确认必须防重放、防跨用户、防跨会话、防版本过期。现有普通金融问题、已有 REST/WebSocket 接口和 M6 的受控主链路不得被破坏。

## 3. Problem Source

问题来源是已冻结的记忆迁移计划、面试问题口径和用户对完整可演示链路的要求。M6 已提供权威记忆、Redis 可选缓存、pgvector/Mem0 派生索引和受控召回，但用户命令与前端控制尚未形成完整闭环。

## 4. Current Behavior

- M6 已将 PostgreSQL `memory_records` 作为权威源，并将 Redis、pgvector/Mem0 和 Provider references 作为可重建派生层。
- 受控对话可以消费经过治理的记忆，但尚未有经过验收的自然语言 inspect/update/delete/forget 命令分支。
- 计划中已有记忆 REST/API 和前端记忆入口，但 M7 的统一命令结果、确认状态、刷新和失败语义尚未完成验收。
- 现有普通金融请求需要继续走原有 Context、Entity Resolution、Route、Rewrite、Permission、Plan、Validate、Execute、Verify、Controller、Synthesis、Termination 顺序。
- 前端已有 lint、类型检查和生产构建门禁，但缺少 M7 所需的记忆命令组件测试和至少一条浏览器/API 用户旅程。
- 当前未提供真实用户操作的稳定复现日志；行为基线以 M6 合并后的代码、计划和离线 Compose 验收为准。

## 5. Expected Behavior

### 记忆命令识别和分支

1. 收到已认证用户消息后，系统先执行有类型的记忆命令预检。
2. 明确的 inspect/update/delete/forget 命令进入记忆命令分支，命令分支完成后直接返回，不得继续进入金融规划或工具执行。
3. 非记忆命令继续使用现有受控金融主链路，不能因为新增预检而改变工具权限、证据约束或终止条件。
4. 无法安全识别目标、范围或值时，系统返回澄清或待确认状态，不猜测并执行。

### 命令语义

- `inspect`: 返回当前用户可见的有效记忆摘要、类别、来源/状态和一致性状态，不泄露其他用户内容。
- `update`: 对经过验证的字段或文本偏好执行用户授权的新增/更新；高影响字段仍遵守 M5 的确认和治理规则。
- `delete`: 删除明确指定的单条或有限范围记忆，并使权威召回立即不可见，派生层异步或同步完成状态可观察。
- `forget`: 对宽范围或类别范围删除生成安全预览和 pending confirmation，不直接执行破坏性操作。
- `confirm/cancel`: 只处理当前用户、当前会话、未过期且版本匹配的 pending command；确认是一次性的、幂等的，取消后不能再次执行。

### API 和前端

- REST 和 WebSocket 使用同一个应用层命令结果合同，包含机器可读 `status`、`command_id`/安全引用、影响计数、派生一致性状态、可展示消息和错误码。
- 前端可以查看有效记忆、发起编辑/删除、展示待确认预览、确认或取消，并在成功后刷新本地状态和相关列表。
- 前端错误、网络超时、权限拒绝和部分派生失败必须有明确可恢复状态，不能把失败显示成成功。

## 6. Scope

### 6.1 In Scope

- 记忆命令的 typed contract、解析/预检、目标和范围验证、命令分支及应用层编排。
- 用户所有权校验、字段白名单、文本长度/类别/范围校验、敏感或高影响字段的确认门禁。
- pending command 的持久化状态、用户/会话绑定、指纹、期望版本、预览/影响计数、过期、确认、取消、幂等和重放拒绝。
- 与 M5 权威候选治理、M6 混合召回、Redis cache-aside、pgvector/Mem0 派生索引和 Provider reference 生命周期的衔接。
- 现有 chat REST/WebSocket presenter 的统一结果映射；保持已有字段兼容，新增字段必须是兼容扩展。
- 记忆 API 和前端记忆控制组件/交互。
- 中文版控提示词或结构化解析 schema 的版本化（如确有模型解析边界需要）。
- 单元、API/数据库集成、跨用户/跨会话负例、离线评测、前端组件测试和 Docker Compose 端到端旅程。
- GitHub Issue、短生命周期分支、PR、CI、代码审查、合并和 M7 里程碑报告。

### 6.2 Out of Scope

- 不替换 ControlledChatUseCase、现有受控工作流或 LangGraph 运行时。
- 不改变 Planner、Permission、Evidence 的职责，不允许记忆内容成为金融市场证据。
- 不把 Redis、Mem0、pgvector 变成权威源，不新增独立 Mem0 服务或第二任务系统。
- 不进行真实用户数据迁移、生产部署、多地域、高可用拓扑、合规认证或批量物理清理。
- 不在默认测试、PR CI 或离线 Compose 中调用付费模型、生产服务、真实 Tushare 或 Mem0 网络服务。
- 不在 M7 扩展报告模式记忆注入、用户记忆导出、宽泛 Langfuse 升级或 M8/M9 的完整故障评测。

### 6.3 Unknown Scope

- 现有前端记忆面板的最终视觉交互和是否需要新增路由：待代码勘察后确定，默认复用现有 Chat/Memory 入口。
- 自然语言解析是否使用确定性规则、结构化模型输出或二者组合：待代码勘察和方案权衡后确定，默认离线可确定性运行。
- 删除命令的默认最大影响条数和保留期：待方案冻结，默认采用小范围上限并要求宽范围确认。
- 是否需要将命令审计详情暴露给普通用户：待安全评审，默认只展示安全摘要和操作结果，不展示内部提示词或敏感 payload。

## 7. Constraints

### 7.1 Hard Constraints

- PostgreSQL 是唯一权威源；任何派生层失败不能伪造成功或反向覆盖权威记录。
- 所有命令必须绑定认证上下文和 `user_id`；任何跨用户读取、修改、删除、确认都必须失败关闭。
- pending confirmation 必须绑定 `user_id`、`session_id`、规范化范围、命令指纹、期望版本和过期时间，并且只能消费一次。
- 明确的记忆命令完成后不得继续金融工具链；普通金融请求必须保持现有行为和阶段顺序。
- M5 高影响字段确认门禁不可绕过；模型推断不能伪装成用户明确授权。
- 默认测试和 CI 不调用付费模型、生产服务、真实 Tushare 或 Mem0 网络；live 测试必须显式标记并隔离。
- 不提交真实 `.env`、凭据、授权头、用户记忆正文、原始查询、原始模型提示词或未脱敏 trace/artifact。
- API、数据库、配置、提示词和持久化状态变化必须可回滚；迁移不得通过不可审查的启动时任意 DDL 完成。
- 代码修改不得破坏 M0-M6 已有功能和测试；任何必要行为变化必须有回归测试和迁移说明。
- 必须使用 GitHub Issue/短分支/PR/CI/review/merge 闭环，不能直接向 `main` 写功能代码。

### 7.2 Soft Constraints

- 面向小白的 API、终端、日志、报告和文档应使用清晰中文，同时保留稳定机器字段和错误码。
- 优先复用现有 memory contracts、repository、runtime、trace、frontend API 和 Compose 模式，避免平行抽象。
- 尽量小步提交，每个里程碑可独立回滚；优先确定性离线实现，再为受保护 live provider 留出明确开关。
- 所有新增公开类、函数、路由、workflow node 和工具使用 Google-style docstring、类型注解和中文意图注释。

## 8. Stakeholders and Impact

- 终端用户：可以管理自己的记忆，并得到可理解、可恢复、可追踪的执行结果。
- 后端/API：新增命令预检、权限边界、事务和统一结果映射；必须保持现有聊天协议兼容。
- Agent/受控工作流：增加一个在金融主链路之前的安全分支；普通金融路径不变。
- PostgreSQL/Redis/pgvector/Mem0：继续分别承担权威、缓存和可重建派生职责；删除和更新需要一致性状态。
- 前端：新增记忆查看、修改、删除和确认交互，必须处理加载、空态、失败、部分完成和过期确认。
- 面试/项目文档：每个“自然语言记忆命令、确认治理、跨用户隔离、可观测性和 E2E”表述都要能映射到代码、测试和日志证据。
- 维护者/评审者：需要通过 PR diff、CI、迁移和回滚记录判断变更是否可审查、可发布、可恢复。

## 9. Engineering Quality Requirements

### 9.1 Interface Documentation and Types

- 命令类型、目标 scope、状态、错误码、影响计数、确认 token/reference、派生一致性和 presenter response 使用显式类型或稳定枚举。
- API 输入在边界校验；应用层不接收未校验的任意 `dict[str, Any]` 作为核心状态。
- 持久化字段说明来源、隐私级别、版本、过期和下游消费者；公开接口文档说明副作用、失败语义和幂等行为。

### 9.2 Architecture and Module Ownership

- API/WS 只负责协议适配、认证上下文和响应映射；应用层负责命令编排和事务边界；domain/contracts 负责稳定规则；infrastructure 负责 SQL、缓存和 Provider；frontend 只负责交互状态。
- 记忆命令识别、普通金融 workflow、权限/证据校验和派生索引必须保持明确边界，不能在路由中混入数据库或模型调用。
- 同一命令结果合同应供 REST、WebSocket 和前端使用，避免三套状态机。

### 9.3 Configuration, Secrets, Constants, and Prompts

- 新增运行参数统一进入 typed Settings 和安全 `.env.example`；默认行为必须是离线安全的。
- 解析提示词、结构化 schema 和命令版本必须可追踪；真实 key/token 只能来自本机环境或 secret manager。
- 删除上限、确认 TTL、允许类别、文本长度、重试/超时等稳定规则优先作为有版本的代码常量或配置合同，不散落在路由中。

### 9.4 Terminal Output, Logging, Tracing, and Artifacts

- 重要阶段至少记录 `stage`、`run_id/trace_id`、`status`、`elapsed_ms`、`error_code` 和安全计数；记录命令类别可以，不能记录命令原文、记忆正文、用户 ID 或凭据。
- 命令识别、验证、预览、待确认创建、确认/取消、权威写入、派生刷新、过期/拒绝和普通金融分支都应可追踪。
- 用户/API 响应、简洁终端进度、结构化日志、详细 artifact 分层；长提示词和模型响应只允许进入经过脱敏的受控 artifact，默认不保留。

### 9.5 Validation, Errors, Retry, State, and Compatibility

- 无效类别、空值、越界、歧义、过期、重复确认、跨用户/跨会话和版本冲突必须返回稳定错误码并 fail-closed。
- 仅对瞬时 Provider/缓存失败做有上限的重试；权威事务失败不得伪造派生成功，派生失败应显示 `PENDING/PARTIAL/DEGRADED` 等状态。
- 确认执行必须有幂等键或等价保护；重放不能重复删除、重复写入或扩大影响范围。
- 记忆命令分支结束后必须有明确终止状态；普通金融请求继续原流程。

## 10. Success Criteria

### 10.1 Functional Criteria

- 对至少一组中文 inspect/update/delete/forget/confirm/cancel 示例，系统能返回正确的结构化状态和可理解中文结果。
- 明确单条更新/删除只影响当前用户的目标记录；跨用户、过期、无权限目标均被拒绝。
- 宽范围删除先返回安全预览和 pending confirmation；确认一次成功，重复确认、取消后确认、跨会话确认和版本过期确认均失败关闭。
- 权威更新/删除后，当前召回不会继续返回已失效记忆；派生刷新状态可观察且可重试。
- REST、WebSocket、聊天框和记忆面板对同一操作表现一致。

### 10.2 Compatibility Criteria

- M0-M6 根回归、现有受控聊天契约、memory authority/cache/semantic worker 测试继续通过。
- 普通金融问题仍按原阶段顺序执行，新增命令预检不改变工具 permission、evidence 或 Tushare 调用边界。
- 既有 API 请求/响应字段保持兼容；数据库升级/降级/重升级在隔离环境通过并保留历史数据。

### 10.3 Reliability Criteria

- 单用户同一命令重复提交不会产生重复有效写入或重复破坏性副作用。
- Redis、pgvector/Mem0 或派生 Worker 不可用时，权威命令结果仍正确，返回明确的降级/待同步状态。
- Worker/HTTP 超时、异常和进程重启后，pending command 和派生任务可恢复或进入可诊断死信，不丢失或越权执行。

### 10.4 Observability Criteria

- 单次命令可通过 trace/run reference 关联预检、状态转换、权威写入、派生刷新和最终 presenter 结果。
- 日志/trace/fixture/报告扫描证明没有记忆正文、命令原文、用户 ID、凭据和原始模型 payload 泄露。
- 终端和 API 明确区分 `SUCCEEDED`、`PENDING`、`PARTIAL`、`FAILED`、`CANCELLED`、`EXPIRED`、`REJECTED`。

### 10.5 Testing Criteria

- 单元测试覆盖解析、schema 校验、范围归一化、错误码、确认状态机、指纹幂等和 token/TTL 边界。
- 数据库/API 集成测试覆盖事务回滚、所有权隔离、跨会话/跨版本确认、权威删除后过滤和派生任务状态。
- 前端组件测试覆盖加载、空态、编辑、删除预览、确认/取消、失败重试和过期状态。
- 离线 Docker Compose E2E 从真实 HTTP 前端代理发起中文记忆命令，再验证 PostgreSQL、Redis/派生索引、响应和普通金融请求不受影响。
- 默认测试不调用付费模型或生产服务；受保护 live 测试如后续需要，必须显式 marker、隔离用户和清理证据。
- GitHub CI 必须执行锁依赖、Ruff、Pyright、后端/Agent/离线评测、前端 lint/type/build、Compose config 和离线 Compose E2E。

## 11. Risks and Mitigations

- 风险：自然语言误识别导致误删。缓解：明确命令白名单、范围上限、预览、确认和 fail-closed。
- 风险：命令分支继续执行金融工具。缓解：在 workflow contract 中加入终止状态和负例测试，验证普通路径阶段顺序。
- 风险：Provider/缓存更新失败造成用户误以为已生效。缓解：权威状态与派生一致性分离，返回 `PENDING/PARTIAL` 并提供可观察任务状态。
- 风险：确认 token 被重放或跨用户使用。缓解：绑定用户/会话/指纹/版本/过期并使用一次性消费和数据库约束。
- 风险：前端与后端状态合同漂移。缓解：共享 schema/契约测试和一条真实浏览器/API E2E。
- 风险：修改既有 M6 代码引入回归。缓解：先新增命令边界和测试，禁止重写 M6 authority/retrieval；每个 PR 执行完整门禁。
- 风险：日志或测试夹具泄露私人记忆。缓解：字段级脱敏、合成用户、禁止正文 artifact、提交前 secret/generated scan。

## 12. Open Questions

For each question, include:

- Question: 记忆命令是否需要支持中英文混合和同义表达？
- Why it matters: 会影响解析规则、测试数据集和提示词版本；错误扩大识别范围会增加误操作风险。
- Suggested default: M7 先覆盖项目面试口径中的中文命令和少量明确同义句，其他语言放到后续评测。

- Question: “忘掉我的文本记忆”默认作用于全部文本记忆还是当前会话范围？
- Why it matters: 这是高影响删除范围，直接决定预览计数、确认 UX 和数据库锁范围。
- Suggested default: 默认解释为当前用户全部文本记忆，但必须先展示数量和范围并要求显式确认；无法确定时先澄清。

- Question: 前端是否需要展示完整记忆正文？
- Why it matters: 影响隐私、接口返回和脱敏策略。
- Suggested default: 默认展示经过分类和长度限制的用户自有摘要/正文片段；日志和 trace 永不展示原文。

- Question: M7 是否开启真实 Mem0 provider？
- Why it matters: 真实 provider 会引入外部网络、费用和数据治理风险，不能混入默认 CI。
- Suggested default: M7 只验证 deterministic/本地 pgvector 派生链路；真实 Mem0 仍由显式 protected-live milestone 管理。

## 13. Handoff to Next Step

Next step should use the Codebase Reconnaissance Skill. It should inspect the current codebase and verify which modules, files, data flows, tests, logs, and risk areas are relevant. It should not modify code.

## Decisions Needed Before Codebase Reconnaissance

- [x] 以 M7 为当前唯一执行里程碑，不提前进入 M8/M9。
- [x] 保持 PostgreSQL 权威、Redis/pgvector/Mem0 可重建派生和现有受控主链路边界。
- [x] 默认测试和 CI 使用 deterministic/offline provider，不调用付费或生产服务。
- [x] 记忆命令优先于金融规划；普通金融请求必须回归原链路。
- [ ] 确认“忘掉我的文本记忆”的默认范围；若无额外决定，采用全部文本记忆 + 预览 + 显式确认。
- [ ] 确认前端展示正文的最小隐私范围；若无额外决定，采用当前用户可见的受限摘要/片段。
