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

当前实现仍有大型服务文件和历史 `sys.path` 注入。它们是后续模块重构对象，不是新模块应继续复制的结构。

## 2. 目标依赖方向

```text
frontend
  -> backend/api                 协议适配、鉴权上下文、响应映射
  -> backend/services/workflows  用例编排、事务、重试和生命周期
  -> finance_agent/contracts      Typed State、错误码、公共协议
  -> finance_agent/domain         实体、路由、规划、执行、校验、总结规则
  -> finance_agent/providers      模型/Tushare/MCP/Memory/Langfuse Port
  -> infrastructure               具体 SDK、数据库和文件实现
```

Provider 和 infrastructure 不得依赖 Router；Router 不得拼接 Prompt、直接执行工具或持有 Provider 私有字段。小项目可以暂时合并 application/domain 文件夹，但依赖方向不能反转。

## 3. 受控主链目标模块

后续按独立 Issue/Plan 逐步建立以下边界：

1. `contracts`：请求、Typed State、错误码、事件和版本。
2. `workflows`：主链编排、阶段转移、终止和降级。
3. `entity_resolution`：金融实体标准化、歧义和候选。
4. `routing`：意图/路由阶段及 Skill 选择。
5. `rewriting`：查询改写、约束和回复偏好抽取。
6. `planning`：工具发现、计划、校验和执行前约束。
7. `execution`：工具调度、超时、幂等、证据包和副作用治理。
8. `verification`：证据充分性、结果校验、重规划边界。
9. `synthesis`：基于证据的最终回答和引用格式。
10. `tools`、`prompts`、`providers`、`memory`、`observability`：分别管理工具 Schema、版本化 Prompt、外部依赖、记忆和观测。

这些模块是目标边界，不代表本基础设施里程碑已经迁移业务代码。每次迁移必须从 Finance 提取证据后重新确认契约。

## 4. 直接重构规则

- 迁移前列出所有调用方、输入/输出、失败语义、Prompt、工具副作用和测试样例。
- 先增加 characterization/contract tests，再在唯一目标位置直接实现。
- 同一个 PR 更新所有内部 import/caller，并删除被替换文件、重复逻辑、过期 Flag 和旧 Prompt。
- 不创建旧入口转发文件，不用 Adapter 维持新旧同义实现。
- 公共 REST/WS、数据库 Schema、鉴权和用户数据默认保持不变。
- 模块跨边界需求出现时停止当前 PR，重新做 Spec/Tradeoff/Plan。
