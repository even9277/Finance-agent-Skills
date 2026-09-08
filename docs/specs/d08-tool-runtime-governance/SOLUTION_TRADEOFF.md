# D08 方案权衡

## 决策点

在不重写受控对话主链的前提下，把现有请求内 Executor 扩展为可跨请求、可选跨实例的工具运行时治理。

## 方案

| 方案 | 内容 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- | --- |
| A 最小修补 | Executor 内增加 family Semaphore 和 sleep | 改动小 | 每请求新建，不能跨请求/实例熔断 | 不选 |
| B 结构化治理 | 领域 Port + 进程级本地 Runtime + 可选 Redis 熔断状态 | 符合现有分层，可测试、可降级、无新依赖 | 需要生命周期、配置和集成测试 | 选择 |
| C 通用网关 | 独立限流服务、队列、统一 Provider 网关 | 长期扩展强 | 超出个人项目和本轮范围 | 延后 |

## 冻结方向

- `ControlledExecutor` 在每次真实调用前请求治理 Runtime admission，顺序为熔断检查→family 并发/间隔→调用超时→错误分类→记录结果→有界退避重试。
- Runtime 通过领域 Protocol 注入；测试使用确定性 Fake，本地实现承担 Semaphore/单调时钟，Redis 仅共享熔断状态。
- ToolPolicy 增加稳定的 family 调度元数据；默认目录拆分接口族。
- Redis 不可用时记录低敏降级并继续使用本地状态；不静默取消治理。
- 不新增依赖，不改公共 Chat API、数据库、Prompt、Skills、Memory 或报告代码。

## 外部实践

- Azure Throttling Pattern：多实例本地计数会低估总请求量；共享状态要权衡延迟，并向上游表达 Retry-After。
- Azure Circuit Breaker/Transient Fault：有限重试与熔断职责不同，重试必须有总预算。
- 本项目 D06 Redis runtime：typed 配置、短超时、低敏健康、fail-open 生命周期可部分复用。

## 风险控制

- 使用可注入 Clock/Sleeper 与确定性 jitter source，避免脆弱 sleep 测试。
- HalfOpen 只允许单探测；状态更新必须原子化。
- Executor 保留总时间预算，治理等待和退避均计入总预算。
- 公开错误只使用稳定枚举；日志不保存参数、Token 或 Provider 正文。
