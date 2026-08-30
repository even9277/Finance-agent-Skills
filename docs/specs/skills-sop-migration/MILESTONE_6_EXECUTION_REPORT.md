# Milestone 6 Execution Report

## 1. Milestone Identity

- Milestone: 6 — Unified Web News Weak-evidence Tool
- Branch: `feature/skills-sop-migration`
- Completed: 2026-08-30
- Execution policy: exactly one frozen milestone；未 commit、push、PR 或执行真实外部搜索。
- Previous report: `MILESTONE_5_EXECUTION_REPORT.md`

## 2. Frozen Contract

`market-move-explain` 的 `search_web_news` 必须默认关闭、只读、可降级，并继续经过 `ToolGovernanceCatalog → Permission → Planner → PlanValidator → ControlledExecutor → EvidenceVerifier → ControlledSynthesizer`。网页内容不得回流 Planner、不得成为控制指令、不得单独形成确认性归因。允许改动 typed settings、Provider/factory、对话合同/治理/计划/证据/Prompt、测试与 Web eval；禁止新增依赖、真实 key、第二执行环、公开 API/UI、数据库、鉴权或部署改动。

## 3. Implementation Outcome

### 3.1 Typed configuration and default-off boundary

`backend.config.Settings` 新增：

- `enable_web_news=false`
- `tavily_api_key=""`
- timeout、max results、freshness、summary length
- minute rate limit、daily quota
- include/exclude domain lists with normalization and overlap rejection

`.env.example` 只包含空 key 和安全示例。flag 关闭或 key 缺失时 Provider 在 HTTP 前返回稳定永久错误；不会创建网络请求，也不会把 key 写入 observation、异常正文或模型上下文。

### 3.2 One governed execution path

- 新证据维度：`EvidenceDimension.WEB_NEWS`。
- 新治理政策：`search_web_news`，`api_family=web-search-read`，`side_effect=READ`，输入仅为 `query/max_results/freshness_days`。
- 工具目录升级为 `controlled-read-tools-v2`。
- `ReadOnlyToolProvider` 只在唯一 ToolPort 内把 `search_web_news` 分发给 Web adapter，其余调用交给 Tushare；`ControlledExecutor` 未复制、未旁路。
- 只有 `market-move-explain` 的 spec 声明该工具，因此其他四类 Skill 权限与计划没有扩大。

### 3.3 Query and transport isolation

- Planner 只用权威实体名称/代码、事件词和有限时间标签构造最多 120 字的公开查询；不读取 recent messages、memory 或用户持仓约束。
- Provider 再做一次敏感词清理，防止持仓、联系方式、token/password 等字段因上游回归被外发。
- 真实 adapter 使用 Python 标准库向固定 `POST https://api.tavily.com/search` 发送 Bearer 请求；显式固定 `topic=news`、`search_depth=basic`、`include_answer=false`、`include_raw_content=false`、`include_images=false`、结果数和时间窗。
- 本地进程配额在 HTTP 前原子预留；429/5xx/网络故障为稳定 transient，4xx 为 stable permanent，错误响应正文不读取。
- 该请求形状参考 Tavily 官方 [Search endpoint](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[rate limits](https://docs.tavily.com/documentation/rate-limits) 和 [search best practices](https://docs.tavily.com/documentation/best-practices/best-practices-search)。

### 3.4 Weak-evidence normalization and safety

网页结果在进入 `EvidenceFact` 前执行：

- HTTP(S) URL 校验、tracking query 移除、域名 allow/deny；
- URL/title 去重、HTML/control character 清理、摘要截断、已知发布日期时效过滤；
- Prompt Injection 关键词扫描；疑似“ignore previous/system prompt/developer message/call tool/忽略上文/调用工具”等结果整体丢弃；
- 输出 title/url/domain/source type/published/retrieved/official/primary/matched entity/summary/confidence hint，不保存 raw content。

历史 `Finance` Web Search 仅作为只读参考，复用了最小查询、source policy、dedupe 和 injection scan 的语义；没有 runtime import、DDGS fallback、散落 env、缓存/异常原文或历史第二执行器依赖。

### 3.5 Verification and synthesis boundary

- `web_news` 是 Skill evidence contract 的 optional 维度；market facts 的 `must_have_any` 保持必需。
- Verifier 支持 `W1.title` 等命名字段质量检查，并显式要求至少存在一个非 Web 强证据才能给 `ANALYTICAL`。
- Prompt 升级为 `chat-synthesis-v4`：区分“已确认市场事实 / 搜索线索 / 可能驱动”，网页摘要永远是不可信弱证据，不能单独写成已确认原因。
- Web 关闭、缺 key、quota/HTTP 失败、空结果或 injection-only 时，失败 observation 由既有 Executor/Verifier 归一化；行情证据足够时仍可保守回答。

## 4. Concrete Workflow Calls

以下三条使用真实 Registry、Router、Rewrite、Planner、Validator、唯一 Executor、Verifier 和 Synthesis；HTTP 为可审计 fake transport，不访问网络：

| Case | Terminal | Skill | Tool calls | HTTP | Web accepted/rejected | Claim |
| --- | --- | --- | ---: | ---: | --- | --- |
| safe Web result | `SUCCEEDED` | `market-move-explain` | 6 | 1 | 1 / 0 | `ANALYTICAL` |
| default disabled | `SUCCEEDED` | `market-move-explain` | 6 | 0 | 0 / 1 | `ANALYTICAL` |
| injection-only result | `SUCCEEDED` | `market-move-explain` | 6 | 1 | 0 / 1 | `ANALYTICAL` |

三条均只调用模型一次；模型上下文只含 accepted evidence。后两条依赖市场强证据维持分析边界，没有把失败网页或注入正文交给模型。

## 5. Changed Surface

Milestone 6 直接改动：

- `backend/config.py`、`backend/.env.example`
- `backend/infrastructure/chat/web_search.py`
- `backend/infrastructure/chat/providers.py`、`backend/application/chat/factory.py`
- `Financial-MCP-Agent/src/conversation/{contracts,tool_governance,planning,verification}.py`
- `Financial-MCP-Agent/src/prompts/chat/{registry,synthesis_v4.md}`
- `backend/infrastructure/chat/testing.py`
- `tests/unit/conversation/{test_web_news_m6,test_skill_spec_execution_m5}.py`
- `tests/evals/web_search/test_web_search_eval.py`
- `tests/evals/synthesis/test_synthesis_eval.py`

`permissions/workflow/execution/synthesis` 的既有实现无需新执行分支；它们通过新治理政策、Provider 和 Prompt 合同自然消费本里程碑结果。

## 6. Verification Evidence

| Command / check | Result |
| --- | --- |
| M6 focused unit/E2E/live-marked suite | `8 passed, 1 deselected` |
| M6 + Web eval + M5 + controlled chat final focused | `33 passed, 1 deselected` |
| related Skills/contract/planner/executor/verifier/synthesis/mainline/E2E regression | `94 passed, 1 deselected` |
| `python -m pytest backend -q` | `11 passed`；56 个既有 `datetime.utcnow()` warnings |
| `python -m pytest Financial-MCP-Agent -q -m "not live"` | `33 passed, 4 deselected` |
| target matrix | `4 passed, 2 failed`；仅剩 M7 public explicit skill 与 M8 reproducible runner |
| changed-surface Ruff | `All checks passed` |
| changed-surface Pyright | `0 errors, 0 warnings` |
| `uv lock --check` | resolved 114 packages；lock unchanged |
| `git diff --check` | pass；仅 Windows LF→CRLF working-copy warnings |
| dependency diff | empty；未新增生产依赖 |
| historical runtime import scan | empty |
| credential scan | 仅 empty config 与明确 `test-/eval-only` fixtures |

真实 Tavily live test已标记 `live`，默认被 `pytest.ini` 排除；本里程碑没有真实凭证授权，因此按冻结合同不运行。

仓库级静态基线仍为 Ruff `65 errors`、Pyright `70 errors/6 warnings`，均不触及 M6 文件；未越界修复 legacy Agent/backend 技术债，不能把 changed-surface 全绿表述成全仓门禁全绿。

## 7. Failures and Repairs

### Test-first missing interfaces

首轮新测试 collection 因 `ReadOnlyToolProvider` 尚不存在而失败，证明测试先于实现。完成合同、治理、Provider 和装配后 focused suite 转绿。

### Static typing repair

首次仓库 Pyright 指出新 Transport Protocol 缺少显式省略体，以及测试 helper 的 Pydantic `_env_file` 动态参数无法由类型器识别。补充 Protocol `...` 和局部 `type: ignore[call-arg]` 后，M6 改动面 Pyright 为 0。

### Quota completeness audit

实现复核发现只处理供应商 429 不能证明冻结合同中的本地 quota 边界。第二次窄修增加 typed minute/day quota 和进程内线程安全 guard，并新增“第二次调用在 HTTP 前失败”测试；没有引入依赖或第二执行环。

## 8. Rollback

最快运行时回滚是保持 `ENABLE_WEB_NEWS=false`；此时市场异动计划仍会生成可审计 optional 步骤，但 Provider 零 HTTP，既有市场证据路径继续工作。代码级回滚可移除 Web policy/provider/factory 分发并恢复 Prompt v3，不影响其他四类 Skills、Tushare 工具、记忆权威、API 或数据库。

## 9. Remaining Work

- Milestone 7：公开 REST/WS `explicit_skill` 和确认 UI 闭环。
- Milestone 8：route→synthesis 低基数 trace 与可复现 `skills_sop` runner/artifact。
- Milestone 9：全量回归、窄修、文档与最终端到端交付审计。
- 真实 Tavily/真实行情/真实模型 live/Compose 验收需要后续显式凭证与环境授权；默认离线测试已完整覆盖请求形状、成功、关闭、限流、HTTP 失败、注入与降级。

## 10. Handoff

Milestone 6 complete. The next frozen step is Milestone 7 only: expose optional explicit Skill selection through the public REST/WS contract and complete confirm/cancel/old-client UI behavior without changing auth, persistence, or existing message compatibility.
