# Finance Agent 工程协作合同

本文件是仓库级开发规则。它面向项目维护者和编码 Agent，规定从需求到 merge 的最小完整链路。更具体的子目录规则可以补充本文件，但不得降低安全、测试和回滚要求。

## 1. 项目边界

- `Finance-agent-Skills` 是唯一主仓库，`main` 是唯一主线。
- `Finance` 是历史行为、失败案例、Prompt 和评测证据来源，不是运行时依赖，不得加入 `PYTHONPATH`、包依赖或生产镜像。
- 本项目采用模块化单体。后端 API、应用服务、Agent 主链、Provider 和基础设施有明确边界。
- 受控主链采用直接模块重构：先锁定契约，再在唯一目标目录替换实现；同一 PR 同步修改内部调用方并删除旧实现、旧导入、重复 Prompt 和过期开关。
- 禁止为新旧 Runtime 增加长期兼容 Adapter、转发模块、双写或永久双轨实现。

## 2. 何时使用完整 SOP

以下工作必须先建立 `docs/specs/<feature>/` 下的需求、代码勘察、方案权衡和冻结计划：跨模块重构、Agent 主链迁移、Provider/工具契约、Prompt 或评测数据变更、数据库/API/鉴权、安全、依赖、Docker/部署和生产行为变更。

低风险的单文件文档或明确缺陷可以走轻量路径，但仍必须检查 Git 状态、审查 diff、运行相关验证，并在 PR 中说明未运行的检查。

完整链路：

```text
Issue -> Requirement Spec -> Codebase Recon -> Clarification
      -> Solution Tradeoff -> Plan -> one milestone
      -> tests first -> implementation -> offline checks
      -> Compose offline E2E -> protected live E2E
      -> self-review -> independent review -> CI -> squash merge
      -> release observation -> rollback/retrospective
```

## 3. 分支、Issue 和 PR

- 一个可交付里程碑对应一个 Issue、一个短分支、一个 PR 和一个 Squash Commit。
- 分支名：`feat/<issue>-<slug>`、`fix/<issue>-<slug>`、`refactor/<issue>-<slug>`、`docs/<issue>-<slug>`、`chore/<issue>-<slug>`。
- 不在 `main` 直接开发、commit 或 force-push。PR 必须填写变更、非目标、测试、E2E、风险和回滚。
- 个人项目采用自审 + 独立 Agent Review + CI + 用户确认的 Review 闭环；不伪造第二位人工审批者。
- 默认使用 Squash Merge。合并后的一个提交必须能单独 `git revert`。
- 未经明确授权，不执行 commit、push、创建/合并 PR、分支保护、release 或部署。

## 4. 目录和依赖方向

目标方向：

```text
frontend -> backend/api -> backend/services/workflows
         -> finance_agent/contracts/workflows/domain
         -> finance_agent/providers (ports)
         -> infrastructure implementations
```

- Router/CLI 只负责协议适配、边界校验、认证上下文和响应映射。
- Application service/workflow 负责用例编排、事务边界、重试预算和状态转换。
- Agent/domain 模块负责业务决策、Typed State、工具治理和终止条件。
- Provider/infrastructure 负责模型、Tushare、MCP、数据库、记忆和 Langfuse 等外部系统。
- Provider 不得反向依赖 Router；路由不得直接拼 Prompt、执行工具或持有 Provider 私有字段。
- 新增 Python 包优先采用 `src/` 布局；新增边界必须有类型、中文 Google-style docstring 和测试。

## 5. Python、Agent 和接口规范

- 公共类、函数、路由、服务、Agent 节点和工具必须写中文 Google-style docstring，说明责任、参数、返回、失败和副作用。
- 跨模块接口、配置、工具 Schema、Agent State、持久化模型和外部输入必须显式类型化。
- 不用 `dict[str, Any]` 作为核心状态；使用 Pydantic/dataclass/TypedDict/Enum 等表达业务含义。
- Prompt、工具 Schema、公共 API、持久化字段和评测数据是版本化契约；变更必须写兼容性和验证方式。
- 只对瞬时错误进行有限次数、总时间预算内的重试；有副作用的工具必须具备幂等或明确禁止重试。
- 不把异常悄悄转换成空结果或成功布尔值；使用稳定 `error_code`、`status` 和可解释降级。
- 复杂初始化、外部调用、重试、脱敏、状态写入和终止条件前添加简短意图注释。

## 6. 配置、秘密和 Prompt

- 真实 Token、Cookie、密码、连接串和生产设置只能来自环境变量或 Secret；提交安全 `.env.example`，不得提交真实 `.env`。
- 配置通过一个 typed Settings 入口加载并校验，业务代码不得到处调用 `os.getenv()`。
- 业务常量、枚举、协议版本和稳定规则留在代码中，不把所有常量塞进环境变量。
- 日志、Trace、fixture、截图、报告和 CI artifact 不得包含 Token、Authorization、Cookie、个人资料或完整敏感 Prompt/响应。

## 7. 日志、Trace 和终端输出

- 终端只输出阶段摘要；长 Prompt、响应、Verifier 诊断和报告写入安全、脱敏、可定位的 artifact。
- Python 使用 `logging.getLogger(__name__)` 和参数化消息，不使用散落的 `print` 作为运行日志。
- 重要阶段至少记录 `stage`、`run_id`/`trace_id`、`status`、`elapsed_ms`、`error_code`。
- 一次聊天轮次对应一个 Trace，一次会话用 `session_id` 聚合；模型调用标记为 generation，工具调用标记为 tool。
- Trace/span 名称使用稳定低基数名称；动态 ID 放属性，不放名称。
- 日志与 Trace 通过 `trace_id`/`span_id` 关联；所有敏感字段先做 key-based redaction。
- Langfuse 是可选 exporter，不得成为业务主链的硬依赖；关闭或失败时本地日志/Trace 仍可用。

## 8. 测试门禁

- 默认测试不调用付费模型、生产服务或真实写接口。`live` 必须显式 marker 和显式环境开关。
- 测试层级：unit、contract、integration、offline eval、Compose offline E2E、protected live E2E。
- 每个 Agent 功能验收必须启动完整链路，构造固定虚拟请求，并验证后端、数据库、前端事件和错误路径。
- Live E2E 允许真实读取；写入只能到隔离测试库/租户；生产写永远禁止。
- 测试先行：行为变更先加入 characterization/contract/regression case，再替换实现。
- Python 命令优先使用 `.venv/Scripts/python.exe`（Windows）或 `.venv/bin/python`（Unix）；默认执行 `python -m pytest` 会跳过 `live`。
- 测试失败时先看最窄日志，只修复具体失败；同一里程碑连续两次修复仍失败就停止并报告。

## 9. Git、交付和回滚

- 提交遵循 Conventional Commits，如 `refactor(router): split route contract`。
- 修改前运行 `git status --short`；不覆盖、清理或还原用户未提交改动。
- 修改后先看 `git diff --check` 和 diff，再从窄到宽运行检查。
- 普通模块重构禁止数据库 Schema 和破坏性 API 变更；需要时单独制定迁移和恢复计划。
- 合并前可放弃分支；合并后通过 revert PR；部署异常切回上一个已验证的不可变镜像或提交。
- Feature Flag 只用于独立能力启停或短期切流，稳定后删除 Flag 和死代码，不用于养两套同义 Runtime。

## 10. Definition of Done

- 需求、范围、风险、回滚和验收标准已记录在 Issue/Plan。
- 代码只位于正确分层；接口有类型、文档和错误语义。
- 相关 unit/contract/integration/eval 测试通过；完整链路 E2E 已执行并保存脱敏证据。
- 默认 CI 离线通过；Live E2E 的真实调用、费用、副作用和环境已明确记录。
- 日志/Trace 可按 `trace_id` 关联且没有秘密泄露。
- PR diff 无无关格式化、生成物、凭证或未解释的 skip。
- Review conversation 已处理，PR 说明了剩余风险和回滚方式。
- 合并后可以通过一个 revert 提交恢复上一已验证行为。
