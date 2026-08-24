## 变更摘要

- 关联 Issue：#
- 本 PR 解决什么问题：
- 本 PR 明确不做什么：
- 是否涉及 Finance 历史代码：仅作为行为/失败/评测证据，不作为运行时依赖。

## 架构与接口

- 所属层：API / application / Agent domain / Provider / infrastructure / frontend / docs
- 影响的 API、WS/SSE、Agent State、Prompt、工具 Schema、数据库、配置：
- 是否保持公共协议和 Schema 兼容：是 / 否（若否，必须附独立批准的迁移方案）
- 是否直接替换唯一实现并删除旧实现：

## 验收与测试证据

| 层级 | 命令/方法 | 结果 |
| --- | --- | --- |
| Format/Lint/Type |  |  |
| Unit |  |  |
| Contract |  |  |
| Integration |  |  |
| Offline eval |  |  |
| Frontend |  |  |
| Compose offline E2E |  |  |
| Protected live E2E |  |  |

完整链路虚拟请求：

- 请求摘要：
- 预期后端/前端/数据库结果：
- trace_id / artifact：
- 失败路径：

## 可观测性与安全

- 日志/Trace 是否包含 `stage`、`trace_id`、`run_id`、`status`、`elapsed_ms`、`error_code`：
- 是否验证 key-based redaction：
- 是否调用真实模型/外部服务：否 / 是（服务、预算、只读/隔离写边界）
- 是否产生生产写入：必须为否

## Review 与交付

- [ ] 我已检查 `git diff`、`git diff --check` 和文件范围。
- [ ] 没有提交秘密、生成物、无关格式化或真实用户数据。
- [ ] 测试失败已按最窄范围修复；未运行项已说明原因和剩余风险。
- [ ] 已完成独立 Agent Review，并处理所有对话。
- [ ] 已写明回滚命令/上一已验证提交或镜像。
- [ ] 合并方式为 Squash Merge。

## 回滚方案与遗留风险

- 合并前回滚：
- 合并后回滚：
- 数据库/配置回滚：不涉及 / 说明
- 遗留风险与后续 Issue：
