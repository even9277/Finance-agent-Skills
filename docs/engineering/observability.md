# 日志、Trace 与 Langfuse 规范

## 1. 一套内部语义

- 一次聊天轮次对应一个 `trace_id`，多轮会话用 `session_id` 聚合。
- 每个重要阶段使用稳定名称：`route`、`entity_resolution`、`rewrite`、`plan`、`execute`、`verify`、`synthesis`。
- 模型调用是 `generation`；工具调用是 `tool`；handoff、retry、fallback 和 termination 用结构化字段表示。
- Langfuse 是 exporter，不是业务接口。Langfuse 关闭、网络失败或配额不足时，主链必须继续并保留本地审计。

## 2. 必需字段

日志和阶段事件至少包含：

```json
{
  "stage": "route",
  "trace_id": "stable-request-id",
  "run_id": "workflow-run-id",
  "status": "STARTED|SUCCEEDED|FAILED|SKIPPED|PARTIAL",
  "elapsed_ms": 42,
  "error_code": null
}
```

按模块增加 `route_result`、`selected_skill`、`selected_tool`、`params_valid`、`fallback_reason` 和安全的 provider/model 标识。动态 ID 放字段，不放 span 名。

## 3. 脱敏

必须按 key 脱敏：`authorization`、`cookie`、`token`、`api_key`、`password`、`secret`、`connection_string`、用户资料和金融账户敏感字段。脱敏发生在日志、Trace、异常、fixture、截图、CI artifact 和 Langfuse exporter 之前。

默认不记录完整 Prompt、原始模型响应和用户输入；只有必要的脱敏摘要才可进入受控 artifact。错误消息不能通过异常字符串绕过脱敏。

## 4. 终端和产物

终端只显示阶段摘要、成功/失败、耗时、trace_id 和 error_code。长诊断写入带版本和 trace_id 的脱敏 artifact。artifact 路径不可包含秘密或完整用户标识。

## 5. 验收

每个新增/修改模块必须测试：同一请求日志与 Trace 可关联；成功和失败状态完整；Langfuse 关闭不影响功能；敏感 key 不出现在日志、Trace、异常和报告；重试、fallback、终止都有可观察记录。
