# 架构与模块边界

## 1. 当前系统入口

```text
Vue Chat UI
  -> frontend API client
  -> FastAPI /api/chat REST/stream
  -> backend application service
  -> Agent workflow / Skill router / executor
  -> model and tool providers
  -> PostgreSQL and trace
  -> streaming events back to frontend
```

对话入口已经切换到 `ControlledChatUseCase -> ControlledConversationWorkflow`，旧
`backend/services/chat_service.py` 已删除。仓库仍有历史 `sys.path` 注入和报告模式代码，
但它们不是受控对话主链的新模块应继续复制的结构。

## 2. 当前受控对话依赖方向

```text
frontend
  -> backend/api                 协议适配、鉴权上下文、响应映射
  -> backend/application/chat           用例编排和事务所有权
  -> Financial-MCP-Agent/src/conversation
                                      Typed State、阶段规则和唯一 Workflow
  -> backend/infrastructure/chat        模型/Tushare/数据库/Trace Adapter
  -> PostgreSQL / JSONL / optional exporter
```

Provider 和 infrastructure 不得依赖 Router；Router 不得拼接 Prompt、直接执行工具或持有 Provider 私有字段。小项目可以暂时合并 application/domain 文件夹，但依赖方向不能反转。

## 3. 已落地的受控主链模块

M2-M7 已按独立 Issue/PR 建立以下边界：

1. `contracts`：请求、Typed State、错误码、事件和版本。
2. `workflows`：主链编排、阶段转移、终止和降级。
3. `entity_resolution`：金融实体标准化、歧义和候选。
4. `routing`：意图/路由阶段及 Skill 选择。
5. `rewriting`：查询改写、约束和回复偏好抽取。
6. `planning`：工具发现、计划、校验和执行前约束。
7. `execution`：有界 DAG 调度、超时、瞬时重试和单轮 action fingerprint 去重。
8. `verification`：证据充分性、结果校验、重规划边界。
9. `synthesis`：基于证据的最终回答和引用格式。
10. `tools`、`prompts`、`providers`、`memory`、`observability`：分别管理工具 Schema、版本化 Prompt、外部依赖、记忆基础设施和观测。当前受控主链仅消费最近消息与既有摘要/画像；LTM 检索、写回和分阶段画像注入仍是后续能力。

这些模块已经由唯一公开入口调用。当前实现状态、限制和面试口径映射以
`docs/specs/controlled-conversation-mainline/INTERVIEW_NARRATIVE_IMPLEMENTATION_MATRIX.md`
为准。Redis 共享熔断、前端确认/计划卡、网页新闻、Provider token streaming 和完整
Langfuse 评测回流仍是后续增强，不得写成当前已实现能力。

## 4. 直接重构规则

- 迁移前列出所有调用方、输入/输出、失败语义、Prompt、工具副作用和测试样例。
- 先增加 characterization/contract tests，再在唯一目标位置直接实现。
- 同一个 PR 更新所有内部 import/caller，并删除被替换文件、重复逻辑、过期 Flag 和旧 Prompt。
- 不创建旧入口转发文件，不用 Adapter 维持新旧同义实现。
- 公共 REST/WS、数据库 Schema、鉴权和用户数据默认保持不变。
- 模块跨边界需求出现时停止当前 PR，重新做 Spec/Tradeoff/Plan。
