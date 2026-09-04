# D04 受控交互与执行状态 UI 验收报告

## 1. 验收结论

- 功能结论：`D04-C01` 至 `D04-C08` 已通过离线自动化、真实浏览器和显式保护的真实 API 验收。
- 安全结论：公开帧只包含白名单摘要；未发现原始工具参数、证据事实、权限哈希、幂等键、Prompt、异常原文或凭证泄露。
- 兼容结论：D03 正文真流式、Skill 确认、记忆命令、上下文/压缩事件和事务回滚保持原合同。
- 发布结论：本机 Docker Desktop 的宿主机运行节点损坏，Compose 语法验证已通过；实际 Compose runtime 必须以 Issue #48 对应 PR 的 GitHub Actions 为最终发布门禁。

## 2. Claim 到证据矩阵

| Claim | 可观察行为 | 验收证据 | 结论 |
| --- | --- | --- | --- |
| D04-C01 | 已校验计划、真实步骤/工具状态和证据摘要先于最终正文 | domain/Application unit、public contract、WebSocket E2E、浏览器、protected Live | 通过 |
| D04-C02 | 并行/交错事件按稳定 ID 更新，重复终态不回退 | Pinia reducer 与协议顺序测试 | 通过 |
| D04-C03 | 工具失败与部分证据不显示为成功，错误信息脱敏 | executor/projection unit、PARTIAL E2E、真实 Tushare 降级 | 通过 |
| D04-C04 | 补证计划提升 revision 并保留旧成功历史 | workflow/WebSocket replan E2E、Store component 测试 | 通过 |
| D04-C05 | 无工具、静态或澄清分支不伪造执行卡；Skill 确认可继续 | clarification E2E、Skill 回归、浏览器确认卡 | 通过 |
| D04-C06 | 用户可停止当前流；未完成步骤/工具关闭且事务回滚 | backend disconnect、composable/store/input 测试、浏览器停止 | 通过 |
| D04-C07 | request/session/sequence 隔离，旧请求事件不能污染新状态 | Store/composable/Router contract | 通过 |
| D04-C08 | 既有 v2 控制帧和 D03 文本终态不回归 | WebSocket、frontend parser、全量离线回归 | 通过 |

## 3. 自动化与运行验收

| 门禁 | 结果 |
| --- | --- |
| D04 Python unit/contract/WebSocket E2E | `15 passed` |
| Root offline regression | `377 passed, 6 skipped, 7 deselected, 3 xfailed` |
| Backend / Agent non-live / eval smoke | `11 passed` / `33 passed, 4 deselected` / `29 passed` |
| Frontend focused / full Vitest | `18 passed` / `27 passed` |
| Frontend lint / type-check / production build | 通过 |
| D04 scoped Ruff / Pyright | 通过 |
| Protected Live baseline | `2 passed`；两条真实模型，其中一条真实只读 Tushare |
| Protected Live D04 real-model + real-Tushare | `1 passed, 1 deselected`；验证控制帧和安全 `PARTIAL` |
| Browser desktop / narrow / stop / Skill confirm | 通过；窄屏输入宽度 `248px`，无横向溢出 |
| Compose config | production/offline 均通过 |
| Compose runtime | 本机受 Docker Desktop 损坏阻塞；由 PR CI 执行最终门禁 |

详细命令、失败定位和宿主机限制见
[`D04_CONTROLLED_INTERACTION_UI_MILESTONE_4_EXECUTION_REPORT.md`](D04_CONTROLLED_INTERACTION_UI_MILESTONE_4_EXECUTION_REPORT.md)。

## 4. 自审结论

- 架构：Workflow/Executor 发布权威领域事件，Application 安全投影，Router 映射 Pydantic 帧，Pinia 归并状态，组件只负责渲染；依赖方向符合仓库合同。
- 正确性：计划仅在 Validator 成功后公开；工具 `STARTED` 紧贴真实 ToolPort 调用；所有公开事件与正文共享 D03 ack queue；客户端拒绝 request/session/sequence 不一致和终态回退。
- 并发与取消：步骤/工具按稳定 ID 独立闭合；用户停止关闭当前 Socket，本地状态立即转为 `CANCELLED`，服务端断连取消继续向事务边界传播。
- 安全：参数、结果、Evidence 与 Trace 均经过固定白名单；日志只保留关联 ID、低基数状态、计数、耗时和稳定错误码。
- 范围：未修改数据库、Redis、认证、Prompt、Skills 选择、工具权限、依赖或部署配置；未包含用户的 D01 文档。
- Review verdict：`APPROVE`，前提是 PR 的 Python、frontend、Docker packaging 与 Offline Compose E2E 全部通过。

## 5. 已知风险与后续边界

- WebSocket query token 可能出现在 Uvicorn 连接访问日志中；需要独立认证/日志安全任务，D04 不修改认证协议。
- 当前过程状态仅存在于页面内；刷新恢复、重放、重复提交保护和状态查询归 D06。
- npm 仍报告既有依赖 advisories；D04 未做可能破坏兼容性的依赖升级。
- 仓库全量非 CI 范围仍有历史 Ruff/Pyright 债务；D04 触达范围和仓库 CI 范围保持清洁。

## 6. 回滚

- 合并前：关闭 PR 并放弃 D04 分支。
- 合并后：针对 D04 的单个 squash commit 创建 revert PR；本次无数据库、配置或依赖回滚。
