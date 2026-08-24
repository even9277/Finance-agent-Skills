# CLARIFICATION_QUESTIONS.md

> 状态：已确认（2026-08-20）。
> 说明：项目所有者否决“新包 + 旧入口 Adapter”的迁移方式，要求直接重构主仓库对应模块；其余推荐项全部接受。本文件记录决策，不代表已经实施。

## 0. 最终决策记录

- **直接重构，不做兼容 Adapter**：在 `Finance-agent-Skills` 内建立唯一目标结构，逐模块替换、移动或重写当前实现；`Finance` 只提供行为、失败案例和测试证据。
- **不做整链大爆炸替换**：直接重构指“不维护两套实现和转接层”，不等于把所有模块塞进一个 PR。每个模块仍必须先锁契约、补测试，再原位替换；内部调用方与被调用方在同一个 PR 中同步更新。
- **回滚依靠版本与交付物**：模块合并后出现问题时使用 `git revert`、上一个已验证镜像或数据库无关的配置回退；不为了回滚长期保留旧实现。
- **Feature Flag 只控制独立新能力或切流时点**：不得用 Feature Flag 永久养两套同义模块；稳定后必须删除过期 Flag 与死代码。
- 下文决策 2～9 的推荐项全部确认。

## 1. 先说结论：这次要建设什么

这次不追求“看起来像大厂”的工具数量，而是建立四个可以被实际证明的闭环：

1. **研发闭环**：Issue → 规格 → 分支 → 小步实现 → Review → CI → Squash Merge → 可回滚提交。
2. **质量闭环**：格式/Lint/类型 → 单元 → 契约 → 集成 → 离线 Eval → 容器 E2E → Live E2E。
3. **运行闭环**：请求进入 → 稳定 ID 贯穿 → 结构化日志/Trace/Langfuse → 错误归因 → bad case 回流评测。
4. **迁移闭环**：旧入口保留 → 新受控 Runtime 走 Feature Flag → 单模块灰度 → 对比评测/E2E → 切流或回退。

可以把它理解成盖楼：本阶段先统一施工图、材料标准、验收表和消防通道；随后先搭一根能承重的主梁，再逐段安装实体解析、路由、Planner、Executor、Verifier 等模块。不能先把历史仓库整栋搬过来，再一边住一边拆。

## 2. 需要确认的决策

### 决策 1：目标代码结构采用哪种迁移方式？

**用户决定：采用直接模块重构，不建立旧入口 Adapter。**

| 选择 | 白话解释 | 优点 | 代价 |
| --- | --- | --- | --- |
| A. 继续原地拆大文件 | 在 `chat_service.py`、`skill_executor_node.py` 周围继续抽文件 | 第一步改动小 | 继续受 `src` 包名、`sys.path` 注入和历史边界约束，容易反复返工 |
| B. 新包 + 适配层 | 新代码进入有效 Python 包，例如 `Financial-MCP-Agent/src/finance_agent/`；旧入口只通过 Adapter 调新 Runtime | 边界清楚、可独立类型检查/测试；可小步切换 | 用户已否决：会形成不希望保留的双轨和转接层 |
| C. 一次性全仓重构 | 立即把 Backend、Agent、Memory、Tools 全部迁到新结构 | 最终目录最快变整齐 | 改动面过大，难 Review、难回滚，风险最高 |
| **D. 直接分模块重构（已选）** | 先冻结模块输入输出和回归测试，再在主仓库唯一目标位置替换实现；同一 PR 更新内部调用方并删除被替代代码 | 不养双轨；结构和行为逐步收敛；每个 PR 可单独 revert | 要求契约测试充分，模块边界和 PR 范围必须严格控制 |

已选 D 的具体原则：

- FastAPI Router 保持薄，公共 `/api/chat` 暂不变。
- Backend application service 负责会话、事务和用例编排。
- 允许把项目整理为可安装的 `finance_agent` Python 包，但迁入模块后直接修改仓库内部调用方，不保留旧模块转发文件。
- Model/Tushare/MCP/Langfuse/DB 使用明确的 Port/Provider 实现边界，不让 Provider 字段散落在业务节点；这里的 Port 是依赖反转接口，不是旧新 Runtime 兼容 Adapter。
- 每完成一个模块，旧实现、旧导入、旧 Prompt 和过期 Feature Flag 必须在同一里程碑或明确的紧邻清理里程碑中删除。

**确认结果：采用 D。**

### 决策 2：第一个实施里程碑做多大？

**推荐：只做“工程宪法与协作门禁”，不碰业务 Runtime。**

第一个 PR 建议只包含：

- 重写根 `AGENTS.md`，从轻量版升级为本项目统一工程合同。
- 新增 `CONTRIBUTING.md`，面向小白说明从 0 到 merge 的操作步骤。
- 新增 GitHub Feature/Bug Issue Form 与 PR Template。
- 新增架构与命名规范，明确新代码应该落到哪一层。
- 新增测试矩阵、日志/Trace/Langfuse 字段规范和 Definition of Done。
- 不引入运行时依赖，不移动业务文件，不改变 API/数据库。

这样做的意义：先让后续每一个基础设施 PR 都能按同一套规则被 Review；如果第一步同时改依赖、CI、目录和业务代码，反而没有稳定规则来审第一步本身。

**确认结果：接受；首个实施 PR 只做规则与模板。**

### 决策 3：PR 上到底跑哪些自动检查？

**推荐：分成 Required、Path-gated 和 Manual 三层。**

| 层 | 何时运行 | 包含什么 | 是否用真实服务 |
| --- | --- | --- | --- |
| Required 快速门禁 | 每个 PR | Ruff format-check/Lint、增量 Pyright、pytest unit/contract、离线 Eval smoke、前端 type-check/Lint/build | 否 |
| Path-gated 集成 | 改 Backend/DB/Docker/API 时 | PostgreSQL 服务集成、FastAPI REST/WS 契约、Docker build/health smoke | 否，模型/Tushare 用 fake adapter |
| Manual Live 验收 | 里程碑合并前或发版前显式触发 | 完整 Compose、真实登录、真实请求、真实模型/Tushare/MCP、前后端浏览器路径 | 是，受预算与环境保护 |

推荐目标：Required 约 10 分钟内；Compose/浏览器检查按路径触发，避免只改文档也拉完整环境。实际阈值以两周 CI 数据调整，不写死“必须 10 分钟”的虚假承诺。

**确认结果：接受；PR 默认离线，完整真实 E2E 必做但显式触发。**

### 决策 4：Live E2E 到底能做什么？

**推荐：允许真实读取，禁止生产写入。**

建议合同：

- 可以调用真实模型、Tushare、只读 MCP、Langfuse 测试环境。
- 使用单独测试账号、固定少量问题、单并发和单次预算上限。
- 不允许写生产画像、持仓、报告或外部业务系统；需要验证写入时使用隔离测试库/测试租户。
- 凭证只放 GitHub Environment Secret 或本地 `.env`，工作流必须 `workflow_dispatch`，不接受 PR 输入拼接为 shell 命令。
- 成功产物只保存脱敏摘要、trace_id、版本、耗时和断言；原始 Prompt/回复默认不上传。
- 失败后自动收集容器状态/脱敏日志并清理测试资源。

例子：可以真实问“查询贵州茅台最近一个交易日收盘价并说明数据日期”；不能用 E2E 自动修改真实用户持仓或向外部系统下单。

**确认结果：接受；真实读、隔离写，生产写永远禁止。**

### 决策 5：个人项目怎样做真实 Code Review？

**推荐：不伪造第二个人，采用四重证据。**

1. 作者自审清单：范围、错误处理、兼容性、密钥、日志、测试、回滚。
2. 独立 Agent Review：使用新的上下文审查 diff，输出带文件/行号/优先级的问题。
3. 所有 Review conversation 必须解决。
4. 项目所有者看懂 PR 摘要、测试证据和风险后决定 merge。

GitHub 上不建议现在设置“必须 1 位其他人工 Approver”，因为单人仓库会永久无法自行合并；有真实协作者后再启用。Branch protection 仍应要求 PR、required checks、conversation resolution、linear history、禁止 force push/删除/绕过。

**确认结果：接受该 Review 口径。**

### 决策 6：GitHub 合并策略怎么统一？

**推荐：只保留 Squash Merge，合并后自动删分支。**

- 一个 Issue/里程碑对应一个 PR，PR 合并后在 `main` 上形成一个清晰、可 revert 的提交。
- 禁用 Merge Commit 和 Rebase Merge，避免三种历史风格混用。
- 功能分支：`feat/<issue>-<slug>`；修复：`fix/<issue>-<slug>`；治理：`chore/<issue>-<slug>`；文档：`docs/<issue>-<slug>`。
- 提交使用 Conventional Commits 风格，例如 `feat(chat): add typed route contract`，PR 标题同样可读。

修改 GitHub 设置是外部写操作；只会在用户明确授权后单独执行。

**确认结果：采用该策略；GitHub 保护规则仍需在实施时获得外部写操作授权。**

### 决策 7：Python 质量工具与依赖管理采用什么组合？

**推荐：Ruff + Pyright + pytest + uv，渐进收紧。**

- Ruff：统一 formatter、import 和常见 Lint，减少 Black/Flake8/isort 多工具重复配置。
- Pyright：与现有前端 TypeScript strict 思路一致；先对新包和边界接口 strict，历史大文件保持 basic/逐步消债，不能用全局 ignore 假装通过。
- pytest：开启 strict markers，明确 unit/contract/integration/eval/live/slow 分类。
- uv：把主 Python 项目变成可安装包并提交 lockfile；MCP 子项目作为独立包或 workspace member的可行性在方案阶段验证。
- 前端补 ESLint；Vue/TS strict、build 保留。

不建议第一天对所有历史代码全量自动格式化或 strict type-check；这会产生巨大无业务价值 diff。规则是“新代码零新增债务，旧代码按迁移触达范围消债”。

**确认结果：采用该工具组合和渐进收紧策略。**

### 决策 8：Langfuse 与 OpenTelemetry 怎么分工？

**推荐：项目内部先定义厂商无关 Trace 契约，Langfuse 只是一个 Adapter；暂不部署完整 OTel Collector。**

- 一次聊天轮次 = 一个 trace；一次会话 = session/group。
- route/rewrite/planner/executor/verifier/synthesis = 稳定低基数 span 名称。
- model call 记为 generation；tool call 记为 tool；动态 ID 放 attribute，不放 span name。
- 普通结构化日志必须带 trace_id/span_id，能从日志跳到 trace。
- 本地 trace 仍是可关闭外部平台时的审计证据；Langfuse 用公共 SDK 接口导出。
- 对 Token、Authorization、Cookie、user profile、原始 Prompt/response 做 key-based redaction；生产默认不采原文。
- 先统一语义与脱敏，再决定是否接 OTel Collector/metrics backend，避免为了“有 OTel”多维护一套空平台。

**确认结果：接受“标准语义 + Langfuse Exporter，Collector 后置”。**

### 决策 9：Redis、生产 CD、数据库迁移平台现在做不做？

**推荐：本轮全部后置，但在接口上留扩展点。**

- Redis：主仓库当前没有实现。只有当跨进程幂等、共享熔断、分布式任务状态成为真实需求时再引入；不能为了对齐描述先搭空壳。
- 生产 CD：没有明确云平台，当前做到“可复现镜像构建 + 离线容器 smoke + 手工 Live E2E + 版本化发布候选”；选定平台后再设计 deployment job。
- 数据库迁移：首批不改 Schema；后续单独引入正式迁移链，必须包含 upgrade/downgrade/备份验证。

这不是缩水：企业实践强调每个平台都对应明确的运行风险和 Owner；没有部署目标时写一个假的 `deploy.yml` 只会制造错误安全感。

**确认结果：同意 Redis、生产 CD 和数据库迁移平台后置。**

## 3. 建议的阶段路线草案

这是一张“先后顺序地图”，不是已冻结的执行计划。每个阶段仍会拆成一个独立 Issue/分支/PR。

```text
M0 规格与勘察（当前）
  -> M1 工程宪法与 GitHub 协作模板
  -> M2 可复现开发环境与静态质量门禁
  -> M3 测试分层、PostgreSQL 集成与离线 Docker E2E
  -> M4 日志/Trace/Langfuse 契约与脱敏
  -> M5 受控主链骨架（typed state + orchestrator port + feature flag）
  -> M6 实体解析与两阶段路由
  -> M7 route-specific rewrite 与 Prompt 治理
  -> M8 Tool Discovery + Planner + Validator
  -> M9 Executor + Evidence Envelope
  -> M10 Verifier + Controller + 有界 Replanner
  -> M11 Synthesis + 前端 plan/step/verification 事件
  -> M12 全链评测、Live E2E、切流与旧代码清理
```

### 每个里程碑都必须交付同样的六类证据

1. **行为证据**：用户能观察到什么变化。
2. **代码证据**：变更在哪一层，为什么属于这里。
3. **测试证据**：具体命令、通过数量、跳过项与原因。
4. **运行证据**：trace_id、关键阶段、耗时、错误或降级路径。
5. **风险证据**：兼容、数据、安全、费用和剩余未知项。
6. **回滚证据**：Feature Flag、revert 或旧镜像如何恢复。

## 4. 计划冻结前的默认决策清单

如果全部接受，后续方案将按以下口径冻结：

- [x] 直接分模块重构，不保留旧入口 Adapter 或长期双轨实现。
- [x] 第一个实施 PR 只做 AGENTS/CONTRIBUTING/架构规范/Issue 与 PR 模板。
- [x] PR 离线门禁 + 按路径容器集成 + 手工受保护 Live E2E。
- [x] Live E2E 真实读、隔离写、禁止生产写。
- [x] 独立 Agent Review + 自审 + CI + 用户确认，不伪造人工审批。
- [x] Squash-only、自动删分支、稳定后开启 main 保护。
- [x] Ruff + Pyright + pytest + uv，新增代码严格、历史代码渐进消债。
- [x] 厂商无关 Trace 语义 + Langfuse Exporter，OTel Collector 后置。
- [x] Redis、生产 CD、数据库迁移平台后置到真实需求明确。

## 5. 外部实践如何影响本项目

以下是用于方案阶段的外部证据方向：

- OpenAI Agents Python：根 `AGENTS.md` 写真实入口、目录所有权、固定验证顺序、PR 模板和小步提交；`PLANS.md` 要求每个里程碑可独立验证、说明恢复方式和明确接口。
- FastAPI 官方全栈模板：后端测试、Docker Compose smoke、Playwright 分工作流；真实 DB 集成与健康检查不是靠 README 口头保证。
- GitHub：Issue Form 让输入结构化；protected branch 可以强制 PR、required checks、conversation resolution、linear history 和禁止绕过。
- Google SRE：构建、测试、发布应可重复；小而自包含的发布更容易定位和回滚；没有真实部署目标时先把可复现 artifact 和回滚打牢。
- Langfuse：一次聊天轮次是一条 trace、会话是 session；模型/工具用正确 observation 类型，名称需稳定低基数。
- OpenTelemetry：日志通过 trace_id/span_id 与 Trace 关联，字段采用共享语义，避免每个模块自己发明命名。

最终 `SOLUTION_TRADEOFF.md` 会给出具体来源、适配理由和被拒绝方案，不会直接照抄任何仓库结构。
