# D08 对话工具运行时治理计划

## 1. 元数据

- Issue: #54
- Branch: `feat/54-tool-runtime-governance`
- Status: Implemented; delivery pending
- Repository: `D:/FinanceProject/Finance-agent-Skills`

## 2. 统一方向

选择“领域治理 Port + 进程级本地调度 + 可选 Redis 共享熔断”的结构化方案。只改对话运行时、配置、生命周期和测试；不修改面试材料、公共 Chat API、数据库、报告、Portfolio、Prompt、Skills 或 Memory 业务行为。

## 3. 允许范围

- `Financial-MCP-Agent/src/conversation/contracts.py`
- `Financial-MCP-Agent/src/conversation/ports.py`
- `Financial-MCP-Agent/src/conversation/execution.py`
- `Financial-MCP-Agent/src/conversation/tool_governance.py`
- `Financial-MCP-Agent/src/conversation/workflow.py`
- `backend/application/chat/factory.py`
- `backend/infrastructure/chat/tool_runtime.py`（新增）
- `backend/infrastructure/chat/tool_runtime_redis.py`（如确有必要新增）
- `backend/config.py`、`backend/main.py`、安全 `.env.example`
- D08 相关 `tests/unit`、`tests/integration`、`tests/e2e`
- 本目录实施治理文件。

## 4. 禁止变更

- 不修改 `D:/FinanceProject/Finance/金融Agent项目描述文档/`。
- 不触碰或暂存用户未跟踪的 D01 Spec。
- 不改数据库/API/Auth、前端、报告 Agent、D09 Resolver、D10 Portfolio。
- 不加依赖、长期双轨、原始 Provider 错误输出或真实凭证。

## 5. 工程合同

- 新公共类/函数使用中文 Google-style docstring 和显式类型。
- Runtime 必须进程级共享；领域模块不得导入 FastAPI、backend 或 redis-py。
- Redis 只共享熔断派生状态；故障时本地治理仍然有效。
- 稳定错误码：`TOOL_RATE_LIMITED`、`TOOL_CIRCUIT_OPEN`；现有错误兼容保留。
- 低敏观测字段：stage/status/trace_id/tool_name/api_family/attempt/wait_ms/circuit_state/error_code。
- Live 只读、显式开关、一次真实用户链路、无整轮重试。

## 6. 测试优先策略

1. characterization：现有全局并发、瞬时/永久错误不回归。
2. unit：family 并发、最小间隔、退避、Closed/Open/HalfOpen、Redis 降级。
3. integration：真 Redis 下两个 runtime 共享状态，Redis 重启/损坏安全恢复。
4. regression：conversation unit/contract/eval。
5. offline E2E：完整 Chat API 链路。
6. protected live E2E：真实模型 + 只读 Tushare/Web（以实际路由所需为准）。

## 7. Milestones

### M0 安全与基线
- 确认分支、用户文件、现有测试和外部凭证门禁；不改代码。

### M1 测试合同
- 添加 D08 失败测试和 Fake clock/runtime；锁定错误、状态和并发语义。

### M2 核心本地治理
- 增加领域合同、family 调度、最小间隔、退避和本地三态熔断。

### M3 Redis 与装配
- 增加可选共享熔断适配、typed Settings、生命周期、health 和本地降级。

### M4 验证与窄修复
- focused→regression→offline E2E→真 Redis integration。

### M5 Protected Live 与 Review
- 从真实 Chat 入口运行只读 live，审查 diff、日志、secret、回滚和 PR 证据。

## 8. 回滚

每个里程碑保持窄 diff；实施前可放弃分支，合并后通过单一 squash commit revert。无数据库和数据回滚。

## 9. Progress

- [x] M0 安全与基线（13 个 focused tests 通过；2 个 protected live cases 可收集）
- [x] M1 测试合同（5 个 D08 治理合同已落盘，并按预期因实现模块缺失而 RED）
- [x] M2 核心本地治理（接口族、最小间隔、有界退避和本地三态熔断已实现；18 个 focused tests 通过）
- [x] M3 Redis 与装配（Executor、Provider、共享 Redis、Settings、lifespan 与 health 已接入；22 个 focused tests 通过）
- [x] M4 验证与窄修复（真 Redis 2 passed；全量非 Live 449 passed；Ruff/Pyright/diff 通过）
- [ ] M5 Protected Live 与 Review（实现、Live 与本地 Review 已通过；等待 PR/CI 证据）

## 10. Decision Log

| 日期 | 决策 | 原因 |
| --- | --- | --- |
| 2026-09-08 | D08 仅接入受控对话 | 用户取消 D07、暂停 D10 |
| 2026-09-08 | 默认离线 + 强制 protected live | 用户要求模拟真实使用 |
| 2026-09-08 | 选择结构化治理方案 | 满足跨请求/实例且不重写主链 |
| 2026-09-08 | M0 基线通过 | 现有并发、重试与 Web News 合同可作为 D08 回归基线 |

## 11. Surprises & Discoveries

| 发现 | 影响 | 动作 |
| --- | --- | --- |
| `api_family` 已存在但未被 Executor 消费 | 可兼容扩展 | 复用权限快照而非建立第二注册表 |
| Workflow 每请求创建 Executor | 本地熔断不能放在 Executor 实例 | 从后端生命周期注入共享 Runtime |
| 现有错误类型无法表达 Retry-After 与 Circuit Open | Executor 无法稳定投影两种治理失败 | M2 增加显式领域异常和错误码 |
| Web News 已冻结 `web-search-read` 稳定族名 | 无需为分族目标改名并制造兼容回归 | 保留旧名，仅补充运行时政策 |
| 自定义测试 App 不运行主应用 lifespan | Protected Live 仍需执行本地治理 | `get_tool_runtime()` 未初始化时惰性创建进程级本地 Runtime |
| 健康接口精确 JSON 合同未包含 D08 组件 | 首轮全量回归 1 failed | 增加固定低敏 `tool_runtime` 健康合同后全量转绿 |
| 参数化 Live 案例为每例创建独立事件循环 | 进程级异步锁不能跨测试事件循环复用 | 每个隔离案例重置测试 Runtime；生产单事件循环语义不变 |
| 迟到成功可能覆盖已 Open/HalfOpen 状态 | 共享熔断器可能被旧周期结果提前关闭 | 本地与 Redis 均只允许当前 HalfOpen 探测完成恢复，并先写状态后释放许可 |

## 12. Outcomes & Retrospective

- D08 已接入唯一受控对话 Executor，没有保留第二执行路径。
- 本地接口族调度、最小启动间隔、有界退避和三态熔断均有确定性单测。
- Redis 共享状态使用原子 Lua、哈希工具键和 TTL；不可达时降级到本地治理。
- 两条 protected live 均从真实 WebSocket Chat 入口通过；未保存 Prompt、回答正文或凭证。
- 最终 PR、CI 和合并证据在 M5 交付完成后补录。
