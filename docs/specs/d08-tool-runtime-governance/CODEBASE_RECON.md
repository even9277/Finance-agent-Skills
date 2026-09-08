# D08 代码勘察

## 当前调用链

`POST /api/chat` → `build_chat_use_case()` → `ControlledConversationWorkflow` → permission/planner/validator → `ControlledExecutor` → `ReadOnlyToolProvider` → Tushare 或 Tavily。

## 已有能力

- `RunBudget`：总步骤、尝试次数、全局并发、单次和总超时。
- `ToolPolicy.api_family`：已进入权限快照，但除 Web/Tushare 两个粗粒度值外未被执行器消费。
- `ControlledExecutor`：DAG 分层、请求内 Semaphore、去重、`wait_for`、瞬时/永久错误分类。
- `WebNewsQuotaGuard`：仅进程内分钟/日配额，位于 Tavily Provider 内。
- Redis：已有 redis-py、typed Settings、短超时、生命周期和 fail-open 适配模式。
- Trace：领域事件使用稳定低基数字段，Provider 原始异常不会进入公开结果。

## 缺口

- 无 API family Semaphore、最小间隔或跨请求协调。
- 瞬时错误立即重试，无退避、jitter 或 Retry-After。
- 无工具级熔断和 Redis 共享健康。
- `ErrorCode` 无 `RATE_LIMITED`、`CIRCUIT_OPEN`。
- Workflow 每请求新建 Executor，因此共享运行时必须由后端生命周期装配并注入。
- `api_family` 当前把全部 Tushare 工具归为一个族，需要按行情、财务、基金、指数/板块拆分。

## 所有权建议

- `src/conversation`：稳定领域合同、治理 Port、执行顺序和错误投影。
- `backend/application/chat`：装配共享 Runtime，不持有 Redis 命令。
- `backend/infrastructure/chat`：本地调度器、Redis 状态适配、健康与生命周期。
- `backend/config.py`/`backend/main.py`：typed 配置、启动/关闭和安全 health。
- `tests/`：假时钟单元测试、真 Redis 集成、离线与 protected live E2E。

## 用户改动保护

`docs/specs/D01_STATIC_FALLBACK_REQUIREMENT_SPEC.md` 是未跟踪用户文件，与 D08 无关，禁止读取后改写、暂存或删除。
