# D08 里程碑执行报告

## 里程碑

- M5 Protected Live 与 Review
- 状态：In Progress（实现与本地验收完成，等待 PR/CI）
- 日期：2026-09-08

## 验证证据

| 范围 | 结果 |
| --- | --- |
| D08 真 Redis 双实例 + 不可达降级 | 2 passed |
| 对话 unit/contract/eval | 121 passed，1 deselected |
| 对话离线 E2E | 19 passed |
| 仓库默认非 Live 全量回归 | 449 passed，15 skipped，9 deselected，3 xfailed |
| Ruff | passed |
| Pyright（相关范围） | 0 errors；仅已有环境 import warnings |
| `git diff --check` | passed；仅 Git CRLF 提示 |

提交前并发修复后的最终回归：

| 范围 | 结果 |
| --- | --- |
| D08 本地治理 Unit | 8 passed |
| D08 真 Redis 双实例、迟到结果与不可达降级 | 3 passed |
| 对话 unit/contract/evals | 191 passed，1 skipped，1 deselected，3 xfailed |
| 对话离线 E2E | 21 passed，3 skipped，4 deselected |
| 仓库默认非 Live 全量回归 | 450 passed，16 skipped，9 deselected，3 xfailed |
| Ruff | passed |
| Pyright（相关范围） | 0 errors；20 个环境 import warnings |

## 真 Redis 场景

- 使用临时 `redis:7.4-alpine`，仅绑定 `127.0.0.1:6389`。
- 两个独立 Runtime 观察到共享 Open 状态，并且恢复窗口只放一个 HalfOpen 探测。
- Redis 不可达时本地治理继续工作且 health=DEGRADED。
- 测试容器已停止并由 `--rm` 清理。

## 修复

- 首轮全量回归唯一失败是 `/api/health` 精确合同缺少新组件。
- 更新低敏 `tool_runtime` 健康断言后，窄测试和全量回归均通过。
- Review 发现迟到成功结果可能提前关闭 Open/HalfOpen 熔断周期；本地和 Redis 状态机已改为忽略旧周期结果。
- Review 发现许可释放早于状态提交存在准入竞态；现改为先提交熔断结果，再释放 family 与请求级许可。
- Protected Live 参数化案例使用不同测试事件循环；测试隔离层已在每个案例前后重置进程 Runtime。

## Protected Live

- `d03-live-01`：真实 `glm-5.1` 流式模型 + 确定性只读工具，122 个内容分片，36.32 秒，`SUCCEEDED`。
- `d03-live-02`：真实 `glm-5.1` 流式模型 + 真实只读 Tushare，从 WebSocket Chat 入口通过，65.20 秒。
- 首次启动受系统 SOCKS 代理影响，在 Provider 构造前失败且未发生付费调用；清理当前测试进程代理变量后通过。
- 仅保存调用次数、时延、状态和内容哈希；未保存 Prompt、回答正文或凭证。

## 剩余

- 创建 PR、等待 CI、完成 PR Review，并记录合并证据。

建议提交信息：`feat(chat): add D08 tool runtime governance`
