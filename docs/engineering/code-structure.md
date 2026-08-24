# 代码结构与命名规范

## 1. 命名

- Python 包/模块：`snake_case`；类：`PascalCase`；函数/变量：`snake_case`；常量：`UPPER_SNAKE_CASE`。
- Agent 节点用业务阶段命名，如 `entity_resolution_node`、`route_node`；不要使用 `misc_node`、`helper2`。
- 测试文件使用 `test_<module>.py`，测试函数描述行为，如 `test_invalid_tool_params_are_rejected_before_execution`。
- 分支使用 `type/<issue>-<slug>`；提交使用 Conventional Commits。
- Prompt 文件包含稳定领域和版本，例如 `route_v1.md`；动态数据不写进文件名。

## 2. Python 分层

```text
src/finance_agent/
  contracts/       # 状态、事件、错误和公共协议
  workflows/       # 编排、终止、重试和阶段转换
  domain/          # 稳定业务规则
  entity_resolution/
  routing/
  rewriting/
  planning/
  execution/
  verification/
  synthesis/
  tools/           # 工具 Schema、注册和治理
  prompts/         # 版本化模板和 registry
  providers/       # Port 和外部能力接口
  memory/
  observability/
```

实际路径在模块迁移的 PLAN 中冻结；未迁移模块不为追求目录好看而空建兼容文件。

## 3. 文件职责

- Router 不写业务分支。
- Service/workflow 不直接拼接 HTTP 响应细节。
- Domain 不 import 具体 SDK、FastAPI 或数据库 Session。
- Provider 不决定业务路由，不吞异常。
- Prompt 不散落在 Router、Service 和工具实现中。
- Trace、日志和脱敏集中在 observability，不在每个节点自创字段。

## 4. 文档和注释

公开边界使用中文 Google-style docstring。注释说明业务意图、数据来源、失败语义、兼容约束和下游影响，不解释显而易见的赋值或循环。
