# 开发 SOP

## 1. 为什么要分阶段

分阶段不是增加仪式，而是让每次变更都能回答四个问题：改了什么、如何证明、出了问题如何恢复、下一步谁负责。大范围 Agent 重构如果只依赖聊天记录，容易漏掉隐式调用、Prompt 和错误路径。

## 2. 从 0 到 merge

### 阶段 A：需求和证据

创建 Issue，写清用户可观察问题、目标、非目标、验收、风险和回滚。跨模块工作依次生成 Requirement Spec、Codebase Recon、Clarification、Solution Tradeoff 和 PLAN。

### 阶段 B：分支和基线

从最新 `origin/main` 建短分支；执行 `git status --short`、现有回归和相关 E2E。发现用户改动、主线分叉或无法解释的基线失败，先停止。

### 阶段 C：测试先行

写正常、边界和失败路径的 characterization/contract tests。对于 Agent，固定输入、期望路由/工具/证据/降级；对于 API，固定响应/流式事件 Schema。

### 阶段 D：单模块直接重构

只修改当前计划允许的模块。使用明确的 contracts、types 和 Provider Port；不要复制 Finance 整个目录，不要建立兼容 Adapter。内部调用方与正式实现同一 PR 修改，旧实现同一 PR 删除。

### 阶段 E：验证

先静态检查和单元，再契约、集成、离线 eval、前端构建、Compose 离线 E2E。功能验收必须构造虚拟请求跑完整链路；真实服务只在显式 Live E2E 使用。

### 阶段 F：Review 和 merge

自审 diff、安全、日志、兼容性、测试证据和回滚；独立 Agent Review 输出文件/行号/优先级；处理所有对话；CI 通过后 Squash Merge。一个 PR 形成一个可 revert 提交。

### 阶段 G：观察和复盘

记录版本、trace_id、成功/失败、耗时、费用和遗留风险。问题通过 revert/上一镜像恢复，随后补坏案例和根因记录。

## 4. 当前受控主链验收入口

开发者可直接运行 `CONTRIBUTING.md` 中的锁定命令。Compose E2E 会通过
Vue/Nginx 代理请求真实 FastAPI，并经过正式 `ControlledChatUseCase`、
`ControlledConversationWorkflow`、Repository、PostgreSQL 和生产 Trace Adapter；只在外部
Model、Tool Ports 使用确定性测试实现，验收后清理容器、网络和卷。

真实模型与只读 Tushare 只能通过显式 `live` marker 或受保护的
`workflow_dispatch` 运行，使用隔离数据库、关闭生产写并限制调用次数。M7 已在本地完成
一次真实模型 + 真实只读 Tushare 的公开 HTTP 验收；GitHub Environment secrets 和审批
仍需仓库管理员配置。默认 CI 永远不能读取这些凭证或产生费用。

## 5. 高风险停止条件

出现生产写、秘密泄露、鉴权绕过、数据库 Schema 变化、公共 API 破坏、跨越计划范围、无法解释的行为变化，或同一问题连续两次修复失败，立即停止并报告，不继续扩大 diff。

## 6. 个人项目的真实 Review

不伪造第二位人工审批者。证据顺序是：作者自审清单、独立 Agent Review、CI 结果、E2E/Live 记录、用户确认。真实协作者加入后，再启用 GitHub required reviewer 和 branch protection。
