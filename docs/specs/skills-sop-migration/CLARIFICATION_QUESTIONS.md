# CLARIFICATION_QUESTIONS.md

## 1. Clarification Basis

本文件依据以下材料消解实现范围，不重复向用户询问可由代码和既有口径判断的问题：

- `REQUIREMENT_SPEC.md`；
- `CODEBASE_RECON.md`；
- 两份用户指定的 Skills/对话模式项目阐述文档；
- 当前 `Finance-agent-Skills` 生产主链；
- 只读历史 `Finance` 仓库中的 Skills v2、Web Search、资产和测试。

用户要求“完整开发流程”“迁移完善”“功能与面试回答完整对应”，因此默认选择完整能力闭环，而不是只修补当前薄 Registry。涉及不可逆外部动作的事项仍不擅自执行。

## 2. Resolved Decisions

### 2.1 Repository and Git Boundary

- **Decision:** 唯一实现仓库为 `D:/FinanceProject/Finance-agent-Skills`；`D:/FinanceProject/Finance` 只读。
- **Decision:** 保留 `main`，不删除任何分支；继续在当前新分支工作。
- **Decision:** 未获得 commit/push/PR 授权，本轮只修改工作树并验证。
- **Known governance deviation:** 当前分支 `feature/skills-sop-migration` 不符合仓库 `feat/<issue>-slug` 约定，且没有用户提供的 Issue 编号。为避免伪造 Issue 或擅自操作远端，先保留现名并在交付时报告。

### 2.2 Delivery Scope

- **Decision:** 本次后端核心闭环覆盖发现、注册、schema gate、版本/hash、请求级快照、LKG 刷新语义、Retriever、显式选择、置信分层、澄清/回退、分阶段 Loader、reference lexical search、route-specific rewrite、Skill-guided planner、统一 Validator/Executor、required evidence、Controller/degrade、Skill-aware synthesis、Trace 和离线评测。
- **Decision:** 5 个 Skill 均升级为 `SKILL.md + skill_spec.yaml + references + tests/cases`，spec 为机器执行真源。
- **Decision:** 不建立第二套 executor；历史 `skill_runner_v2.py`、`skill_executor_node.py` 只迁移可验证行为。
- **Decision:** 不修改记忆权威边界；长期记忆不能扩大 Skill 或工具权限。

### 2.3 Skill Confirmation and Public Protocol

- **Decision:** 为对应“显式选择优先 + 中置信确认”，本次纳入结构化确认闭环，而不只返回无法恢复的文字。
- **Contract:** 请求可携带 `explicit_skill`；中置信匹配返回机器可消费的 `skill_confirm` 候选和原因；客户端确认后以当前认证用户和会话重新提交 `explicit_skill`，服务端重新校验实体、输入合同、Skill version/hash 和权限快照。当前全链只读，不额外引入确认 token 持久化。
- **Frontend:** 以最小增量接入确认卡和确认/取消恢复；不顺带开发 plan/step/verification 等其他卡片。
- **Compatibility:** 旧客户端不传新字段时保持现有自动路由；WS 现有事件继续有效。

### 2.4 Retriever and LLM Rerank

- **Decision:** 实现“规则召回 + spec metadata shortlist + 可插拔 rerank”三段式。
- **Offline default:** 使用确定性 reranker，保证默认测试不访问模型。
- **Online behavior:** 可选模型 rerank 复用现有 model-provider 边界、版本化 Prompt、超时和安全 fallback；关闭或失败时回到确定性评分，不阻塞主链。
- **Thresholds:** 高置信自动进入；中置信确认；低置信回退通用链。具体阈值和 top1/top2 margin 在方案与 PLAN 中冻结并由数据集校准，不散落到多处配置。
- **Multi-task:** rewrite 识别多个独立任务时必须澄清或拆分，不允许单个 Skill 强吞；首版可选择“明确提示拆分”而不并行执行多个 Skill。

### 2.5 Registry, Lifecycle, Refresh, and Rollback

- **Decision:** 文件系统是持久真相源，Registry 是进程内运行时派生状态。
- **Lifecycle:** 实现 `draft/disabled/shadow/active/deprecated/rolled_back` 的可表达状态和合法迁移；自动候选池只接收满足启用条件的状态。
- **Scope boundary:** 当前个人项目实现版本化、原子 active snapshot、请求固定版本、刷新失败保留 last-known-good 和显式回滚语义；不实现按用户比例灰度、自动流量回滚或发布看板。
- **Startup/refresh:** 首次启动没有合法 active snapshot 时 fail closed；已有 LKG 时刷新失败保留旧快照并记录结构化失败事件。
- **No database migration:** 生命周期暂不持久化到数据库，避免无证据扩张持久化合同。

### 2.6 Schema Gate and Loader Contract

- **Schema gate:** 校验 frontmatter、canonical name/alias 冲突、YAML、版本、route metadata、input contract、allowed tools 与治理目录 join、plan steps、required evidence、output/degrade、reference metadata、路径包含关系和 section map。
- **Permission rule:** Skill spec 和 reference 永远不能新增治理目录之外的工具或放宽证据边界。
- **Loader stages:** `rewrite` 只取输入/禁用边界；`planner` 取 workflow/steps/tools/evidence；`synthesis` 取 output/degrade 与已验收证据。
- **References:** 先按 `skill_id + stage` 硬过滤，再按标题、标签、任务词和 evidence type 做 lexical scoring；返回片段、token estimate 和 content hash。
- **Security:** reference 只放稳定方法论，不存实时行情、新闻正文、用户私有数据或凭证。

### 2.7 Web News

- **Decision:** 为对应 `market-move-explain` 口径，本次纳入 `search_web_news`，但它必须是统一治理工具，而非 Skill 私有脚本。
- **Provider:** 优先适配历史实现的标准库 HTTP/Tavily 能力，避免新生产依赖；真实调用默认关闭并需要显式配置 API key。若无 key，离线和普通运行以稳定的 disabled/degraded 结果处理。
- **Evidence:** `web_news` 是补充弱证据；市场异动解释必须先有 Tushare 市场事实。网页内容不回流 Planner，不触发新工具。
- **Safety:** query 仅含公开实体、事件词和时间窗；结果保留来源、发布时间、检索时间、去重和注入风险字段；不得把新闻标题写成确定因果。
- **Testing:** 默认 fake provider；live 测试单独 marker，缺凭证跳过。

### 2.8 Evaluation and Historical Metrics

- **Decision:** 迁移指标定义、gold schema、runner 和代表性数据，不伪造历史数据集。
- **Current evidence:** 历史仓库只有少量 smoke JSONL 和每 Skill cases，未发现支撑 75×3/225 次及冻结数字的完整原始数据与 artifact。
- **Reporting:** 本次只报告新 runner 的真实结果、数据集大小、版本和执行次数；文档中的 81.8%→93.8% 等继续标注为历史离线口径、当前不可独立复现。
- **Dataset target:** 先建立覆盖 5 Skill 的正例、反例、相邻混淆、缺槽位、证据/降级和输出越界的可扩展门禁集；是否达到 75 条由真实案例质量决定，不用复制文本凑数。

### 2.9 Configuration, Trace, and Compatibility

- **Decision:** 新运行参数进入 `backend.config.Settings` 和安全 `.env.example`，不在业务代码继续新增散落 `os.getenv()`。
- **Trace:** 每轮/每阶段记录低基数 `skill_name/version/spec_hash/registry_hash/route_source/confidence_band/references_loaded_hashes/degrade_reason`；敏感正文只存 hash 或受控 artifact。
- **Compatibility:** 旧 REST/WS 字段和 `tushare-data`/fallback/记忆路径保持可用；新增字段可选。
- **Failure:** Registry、rerank、reference、web news、trace 各有明确 fail-closed 或 safe-degrade 语义，不静默伪装成功。

## 3. Explicitly Deferred

- BM25 + embedding reference retrieval。
- 专用路由小模型和大规模模型训练。
- 企业级域名治理、完整搜索平台、生产 A/B。
- Script sandbox 和未有真实需求的 Skill 私有脚本。
- 按用户比例 shadow/灰度、自动流量回滚和发布管理 UI。
- Skills 生命周期数据库表和管理 API。
- 与本次确认闭环无关的 plan/step/verification 前端卡片。

## 4. Acceptance Interpretation

“与面试回答对应”按以下规则验收：

1. 代码真实存在并由当前生产入口可达；只存在历史仓库或文档不算实现。
2. 5 个 Skill 的资产合同与可执行工具、证据和降级闭合。
3. `financial-sop` 与 `tushare-data` 复用同一 Validator/Executor/Verifier/Controller/Synthesis 内核。
4. 显式选择、自动路由、确认、澄清、回退和多任务边界均有测试。
5. Web news 作为可选统一弱证据能力，不影响离线默认与无凭证启动。
6. Trace 能从一次回答定位到 Registry/Skill/spec/reference 版本。
7. 指标必须由仓库内数据和 runner 生成，历史口径与当前实测分开。

## 5. Remaining Authorization Gates

以下动作不属于实现默认授权，即使代码完成也不会自行执行：

- 创建远端 Issue、push、PR、merge、发布或删除分支；
- 使用真实 Tavily/Tushare/模型凭证运行 live 测试；
- 新增数据库迁移、生产第三方依赖或改变鉴权/部署安全边界。

当前没有阻塞方案设计的产品问题；上述决策可进入 Solution Tradeoff。
