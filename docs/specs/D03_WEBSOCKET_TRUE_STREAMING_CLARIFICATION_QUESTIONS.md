# CLARIFICATION_QUESTIONS.md

## 1. Purpose

本文件只冻结 D03 在进入方案权衡前必须确认的产品与工程决策。问题已根据 `D03_WEBSOCKET_TRUE_STREAMING_REQUIREMENT_SPEC.md` 和 `D03_WEBSOCKET_TRUE_STREAMING_CODEBASE_RECON.md` 收敛，不重复询问可以从代码确定的事实。

## 2. Recommended Decision Set

| ID | Decision | Recommended default | Reason |
| --- | --- | --- | --- |
| D03-Q01 | WebSocket 协议 | 前后端原子升级到单一结构化 v2 协议，不长期维护 raw-text/v2 双轨 | 当前只有一个正式前端；仓库规则禁止长期兼容 Adapter |
| D03-Q02 | 事件最小集合 | 只冻结 `stream_start`、`content_delta`、`stream_end`、`stream_error`，并保留已有业务控制事件 | 足以证明真实 streaming，又不提前实现 D04 控制面 |
| D03-Q03 | 事件关联 | 每个事件包含协议版本、request_id、session_id、sequence；内部 trace_id 不默认暴露给浏览器 | 满足重组、隔离和排障，同时减少内部标识暴露 |
| D03-Q04 | 完成事件 | `stream_end` 携带 terminal status、chunk_count 和正文 hash，不重复携带完整回答 | 避免双份大正文；可与客户端重组和数据库结果核对 |
| D03-Q05 | 业务 PARTIAL | Controller 产生的合法 `TerminalStatus.PARTIAL` 作为完整受控回答落库并正常结束 | 这是“证据有限但回答完整”，不是传输故障 |
| D03-Q06 | 传输中途失败 | 已展示 chunk 标记为 transport partial，但不作为完整助手消息落库；本轮事务按现有规则回滚 | 不新增数据库状态列，不把残缺回答写成权威结果 |
| D03-Q07 | 客户端断连 | 取消尚未完成的生成，停止发送并回滚未提交轮次；不自动重放 | 防止继续计费和重复工具副作用 |
| D03-Q08 | 停止按钮 | D03 只实现取消能力和断连传播，不新增可见按钮 | 控制按钮可在 D04 统一设计 |
| D03-Q09 | 非模型回答 | 澄清、Skill 确认、记忆命令等使用同一 v2 协议，但允许一个 `content_delta` 后结束 | 协议统一，但不冒充多 chunk 模型 streaming |
| D03-Q10 | 非 streaming Provider | 明确降级为单个 delta，并在 start/end 标记 degraded；禁止事后切片 | 保持可用且不伪造真实 streaming；默认演示 Provider 必须真流式 |
| D03-Q11 | 工具阶段保活 | 本轮不新增 heartbeat/步骤事件；沿用当前 loading UI 和 300 秒代理超时 | D04 才负责步骤状态；当前无证据要求额外保活 |
| D03-Q12 | Live E2E | 自动化 WS Live E2E + 前端 Vitest + 一次真实浏览器人工验收，不新增 Playwright | 最小充分且可调用真实 API，避免新增重型依赖 |

## 3. Clarification Questions

### D03-Q01：协议升级方式

- Question: 是否接受前后端在同一个 D03 里原子升级到结构化 WebSocket v2，并删除旧的“原始正文文本帧”合同？
- Why it matters: 当前测试和前端依赖 raw text；维护双协议会形成长期兼容分支。
- Recommended default: 接受原子升级。HTTP 接口保持不变；已有 `skill_confirm`、`memory_command` 和 `context_update` 作为 v2 typed event 保留。
- Consequence if rejected: 需要短期协议协商或兼容层，并增加双协议测试和删除期限。

### D03-Q02：事务和部分结果

- Question: 是否接受“业务 PARTIAL 正常落库；传输/Provider 中途失败的残缺 chunk 不落库，并回滚本轮”的区分？
- Why it matters: 当前数据库只保存完整助手文本，没有 transport partial 状态字段。
- Recommended default: 接受该区分，不新增数据库 Migration。
- Consequence if rejected: 若要求保存残缺正文，需要新增消息状态、恢复和前端历史展示合同，范围会扩大。

### D03-Q03：取消行为

- Question: 客户端断连或取消时，是否继续保持当前原子语义：用户消息、助手消息和本轮状态全部回滚？
- Why it matters: 当前用户消息在 `prepare_turn()` 中只 flush、不 commit；改变这一点会拆分事务。
- Recommended default: 本轮保持整体回滚；前端保留当前本地错误提示，刷新后该失败轮次不进入权威历史。
- Consequence if rejected: 若要求保留失败用户消息，需要新的失败轮次/重试状态合同。

### D03-Q04：Provider 降级

- Question: 不支持原生 streaming 的 Provider 是否允许返回一个完整 delta，并明确标记 `degraded`？
- Why it matters: 强制所有 Provider 真流式可能影响可用性；事后切片又会违反 Spec。
- Recommended default: 允许明确降级；默认演示和 Live E2E Provider 必须支持真实 streaming。
- Consequence if rejected: WebSocket 对不支持 streaming 的 Provider 直接失败，用户只能改走 HTTP。

### D03-Q05：测试自动化程度

- Question: 是否接受“不新增 Playwright”的最小充分验收，还是要求新增真正自动化浏览器 Live E2E？
- Why it matters: 当前仓库没有浏览器自动化依赖；新增 Playwright 会增加 lockfile、浏览器镜像、CI 时间和维护成本。
- Recommended default: 不新增 Playwright。本轮使用：
  1. Fake Provider 的离线 WS Contract/E2E。
  2. 真实模型 + 真实 Tushare 的 protected WS Live E2E。
  3. Vitest 验证前端增量重组和状态机。
  4. 启动真实前后端后进行一次浏览器人工 Live 验收并保存脱敏结果摘要。
- Consequence if rejected: 方案阶段需要评估 Playwright 依赖、Docker/CI 浏览器环境和稳定性成本。

## 4. Frozen Test Scope If Defaults Are Approved

### 4.1 Unit / Contract

- 一个参数化 chunk 重组合同：顺序、Unicode/Markdown、空 chunk、终止唯一性。
- 一个失败/取消合同：首 chunk 前失败、部分输出后失败、客户端断连。
- 一个并发隔离合同：两个 session/request 不串流。
- 更新现有 Skill Confirmation 和 Memory Command WS 合同到 v2，不复制全部业务测试。

### 4.2 Offline E2E

- 从真实 FastAPI WebSocket 入口进入。
- 使用可控异步 Fake Model 与 Fake Tool。
- 验证 start → 多个 delta → end、数据库最终正文、Trace 摘要和 HTTP 兼容。
- 只增加一条成功主路径和一条部分失败/取消路径。

### 4.3 Frontend

- `parseWsFrame`/typed event 解析。
- Pinia 同一消息增量追加、完成、失败和清理。
- Composable 接收多 delta 并在 end 后只收口一次。
- 不测试完整模型措辞，不为每个 chunk 单独渲染快照。

### 4.4 Protected Live E2E

- `LIVE-01`：真实模型金融知识回答，至少两个非空 delta。
- `LIVE-02`：真实 Tushare + 真实模型回答，工具完成后至少两个非空 delta。
- 最多两条主路径；只有可识别瞬时网络错误允许额外一次重试。
- 记录脱敏 `request_id`、chunk_count、TTFT、total_ms、terminal_status 和 content hash。

### 4.5 Manual Browser Acceptance

- 启动真实前后端并登录测试账号。
- 提交一条固定金融问题。
- 观察同一条助手消息在完成前至少增长两次。
- 验证完成后刷新会话，数据库历史正文与页面最终正文一致。
- 验证断开页面或网络后不会继续产生可见 chunk；服务端记录取消/断连状态。

## 5. Explicitly Excluded Tests

- 不新增全仓覆盖率门槛。
- 不运行新闻训练、报告、Portfolio 等无关 Live 测试。
- 不把真实 API 测试放入默认 CI。
- 不断言完整模型措辞或固定实时行情数值。
- 不为每个 Provider 重复同一套完整 E2E；默认 Provider 通过 Live，其他 Provider 走合同测试或明确降级。
- 未确认前不新增 Playwright/Cypress/Selenium。

## 6. Decisions Required Before Solution Tradeoff

- [ ] 接受 v2 单协议原子升级，不长期维护 raw text 双轨。
- [ ] 接受业务 PARTIAL 正常落库，传输残缺结果不落库并回滚。
- [ ] 接受客户端断连时整轮回滚，不保存失败用户消息。
- [ ] 接受非 streaming Provider 以单 delta + degraded 明确降级。
- [ ] 接受 D03 不新增停止按钮和工具阶段 heartbeat。
- [ ] 接受“WS Live E2E + Vitest + 人工浏览器验收”，本轮不新增 Playwright。

## 7. Handoff

上述默认项获得用户确认后，下一步进入 Solution Tradeoff，比较至少以下方向：

1. Workflow/Application 主动推送增量的 typed callback/event sink。
2. Application 返回异步事件流，由 WS Presenter 消费，HTTP Presenter 聚合。
3. 是否需要单独的 streaming Use Case，同时遵守仓库“不得长期双轨 Runtime”的约束。

Solution Tradeoff 只比较方案，不修改代码；最终方案和测试命令在 Plan Freezing 阶段冻结。
