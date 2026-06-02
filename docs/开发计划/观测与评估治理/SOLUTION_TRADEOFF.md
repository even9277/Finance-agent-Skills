# SOLUTION_TRADEOFF.md

## 1. Tradeoff Context

本次 tradeoff 聚焦你已确认的范围：在**不改业务主逻辑**前提下，补齐对话链路的观测与评测收敛能力（可读报告、阶段一致字段、线上 bad case 回流、趋势评测），并明确与“硬门禁、Redis、STM/LTM 扩展、prompt 全量迁移”的边界。

---

## 2. Inputs Reviewed

- REQUIREMENT_SPEC.md: 使用等价输入 `docs/开发计划/观测与评估治理/观测与评估现状-缺口矩阵.md`
- CODEBASE_RECON.md: 未发现同名文档；本次通过现有代码与既有分析补齐等价 Recon（`skill_trace.py`、`langfuse_exporter.py`、`tests/evals/runner.py`）
- CLARIFICATION_QUESTIONS.md: 未发现同名文档；使用缺口矩阵中的已确认决策（A/D/A/A）作为等价澄清结果
- User decisions:
  - 每轮报告先落后端文件
  - 优先级“全都要”但分阶段
  - Langfuse 为辅助可视化，本地 trace 为主
  - 评测先趋势观察，不阻断 PR
- External sources:
  - Langfuse 官方文档（Tracing、Scores、Datasets、Masking）
  - LangSmith 官方文档（Observability、Evaluation）
  - OpenTelemetry 官方文档（Signals、Context propagation）
  - OpenAI 官方文档（Agent Evals、Evals API、Agents SDK tracing/guardrails）
  - GitHub Actions 官方文档（Protected checks、required checks 行为）
  - 开源仓库证据（OpenClaw、Hermes Agent、cc-haha、Langfuse repo、promptfoo）

---

## 3. User Decisions and Defaults

### 3.1 Confirmed Decisions

1. 观测体系先完善“可读+可追踪”，不先做性能和内存扩展。
2. 本地 JSONL/结构化 trace 是主审计链路，Langfuse 仅辅助观测。
3. 评测治理先做趋势观察和回归对比，不做阻断 PR 的硬闸门。
4. 本轮不接 Redis、不扩 STM/LTM、不做 prompt 全量迁移。

### 3.2 Conservative Defaults Used

- **Defaulted**：在缺少独立 `CODEBASE_RECON.md`、`CLARIFICATION_QUESTIONS.md` 的情况下，使用缺口矩阵和当前代码事实作为等价输入。
- **Defaulted**：门禁策略采用“软门禁（告警/报告）优先，硬门禁延期”。

### 3.3 Blocking Decisions

- 当前无未决 P0 阻塞项。  
- 结论：**Not Blocked**，可进入 Plan Freezing。

---

## 4. Core Decision Point

在你当前项目阶段，应选择“仅补观测点（A）”“结构化治理（B）”还是“重构成统一观测评测平台（C）”，以最低风险获得可持续诊断与回归能力。

---

## 5. Reference Sources and Repository Evidence

### 5.1 Official Docs

#### Source: Langfuse Data Model / Tracing

**Link:** https://langfuse.com/docs/observability/data-model  
**What was inspected:** Trace/Observation/Session 分层、上下文字段传播  
**Relevant practice:** 单轮请求统一 Trace，步骤统一 Observation，跨轮统一 Session  
**Reusable part:** Directly reusable  
**Fit for this task:** 与你现有 `trace_id + span + event` 完全同构，适合收敛字段口径

#### Source: Langfuse Scores / Datasets / Experiments

**Link:** https://langfuse.com/docs/evaluation/scores/overview  
**What was inspected:** score 类型、dataset run、实验模型  
**Relevant practice:** 评分挂载到 trace/observation/session，支持离线实验与比较  
**Reusable part:** Partially reusable  
**Fit for this task:** 适合做“辅助可视化+回归比较”，但不应替代本地主审计链

#### Source: Langfuse Masking

**Link:** https://langfuse.com/docs/observability/features/masking  
**What was inspected:** 发送前脱敏策略  
**Relevant practice:** 上传前 PII 屏蔽、字段白名单  
**Reusable part:** Directly reusable  
**Fit for this task:** 与当前 exporter 的隐私保护方向一致，可正式制度化

#### Source: LangSmith Observability + Evaluation

**Link:** https://docs.langchain.com/langsmith/evaluation  
**What was inspected:** offline/online eval 流程、回归比较  
**Relevant practice:** 先 dataset 回归，再线上观测；基线对比驱动迭代  
**Reusable part:** Conceptual only  
**Fit for this task:** 设计思想可直接借鉴，但不建议新增平台依赖

#### Source: OpenTelemetry Signals / Context Propagation

**Link:** https://opentelemetry.io/docs/concepts/signals/  
**What was inspected:** traces/logs/metrics 与上下文传播  
**Relevant practice:** 统一语义上下文，把日志和指标绑定 trace_id/span_id  
**Reusable part:** Directly reusable  
**Fit for this task:** 适合你当前“本地 trace 主链”做字段统一与跨阶段串联

#### Source: OpenAI Agent Evals / Evals API

**Link:** https://developers.openai.com/api/docs/guides/agent-evals  
**What was inspected:** workflow 级评估、trace grading、数据集评估  
**Relevant practice:** 先做 trace 级诊断，再做可复现 eval run  
**Reusable part:** Conceptual only  
**Fit for this task:** 适合你的评测闭环思路；不需要引入额外平台改造

#### Source: GitHub Protected Branch & Required Checks

**Link:** https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches  
**What was inspected:** required checks、pending/skip 语义  
**Relevant practice:** 评测可先作为 required 之外的软检查，再逐步升级  
**Reusable part:** Directly reusable  
**Fit for this task:** 与“先趋势观察，不阻断 PR”决策一致

### 5.2 Open-source Repositories

#### Source: OpenClaw

**Link:** https://github.com/openclaw/openclaw  
**What was inspected:** trace base、context/status report、routing policy  
**Relevant practice:** 报告分区输出（人类可读）+ 路由判定字段标准化  
**Reusable part:** Directly reusable  
**Fit for this task:** 可直接映射到 `turn_report` 结构和路由可解释字段

#### Source: Hermes Agent

**Link:** https://github.com/NousResearch/hermes-agent  
**What was inspected:** trajectory format、eval 脚本、provider fallback tests  
**Relevant practice:** 轨迹标准化 + eval runner + 回退链路可回归测试  
**Reusable part:** Partially reusable  
**Fit for this task:** 对“趋势评测闭环”帮助大，但其数据格式需本地化适配

#### Source: cc-haha

**Link:** https://github.com/NanmiCoder/cc-haha  
**What was inspected:** telemetry 分层 span、plugin telemetry 脱敏、router 入口治理  
**Relevant practice:** interaction/tool/llm/hook 分层与字段最小集  
**Reusable part:** Partially reusable  
**Fit for this task:** 适合抽取字段范式，不适合全量引入复杂 tracing 平台

#### Source: promptfoo

**Link:** https://github.com/promptfoo/promptfoo  
**What was inspected:** eval 产物与 CI 集成（json/html/junit）  
**Relevant practice:** 统一评测产物 + artifact 归档 + 趋势对比  
**Reusable part:** Conceptual only  
**Fit for this task:** 产物策略可复用；无需直接迁入其工具链

### 5.3 Local Project Patterns

| Local pattern | Evidence from codebase | How to reuse |
| --- | --- | --- |
| 本地 trace 主链 + exporter 扩展点 | `Financial-MCP-Agent/src/tools/skill_trace.py`（record envelope + exporter dispatch） | 继续以本地 JSONL 为主，统一 schema v1，不改主调用方式 |
| Langfuse 辅助导出且有隐私开关 | `Financial-MCP-Agent/src/tools/trace_exporters/langfuse_exporter.py`（白名单/敏感字段剔除） | 固化“白名单上传 + 隐私默认关闭完整 prompt/reply”规范 |
| 环节化评测骨架已存在 | `tests/evals/runner.py`（按 target 计算指标输出 metrics.json） | 在现有 runner 上补趋势汇总和 bad case 回流，不重写评测框架 |

---

## 6. Reusable Patterns

### 6.1 Directly Reusable Patterns

1. “Trace-Observation-Session”三层建模（Langfuse / OTel 对齐）
2. 每轮固定模板的人类可读报告（OpenClaw 风格）
3. 评测产物标准化与 artifact 归档（promptfoo 思路）
4. 软门禁先行、硬门禁后置（GitHub Actions 策略）

### 6.2 Partially Reusable Patterns

1. provider/tool routing 的配置化解释字段（Hermes）
2. interaction/tool/llm/hook 的细粒度 span 分层（cc-haha）
3. dataset/experiment 驱动回归（Langfuse/LangSmith）

### 6.3 Conceptual References Only

1. OpenAI agent evals 的“两阶段评测”方法（先 trace grading，后 dataset eval）
2. LangSmith 的 offline/online 评测治理节奏

### 6.4 Not Suitable for This Iteration

1. 全量替换为新观测平台或全链路重构（成本高、风险高）
2. 立即启用阻断 PR 的硬阈值门禁（与你当前决策冲突）
3. 为观测治理引入 Redis/STM/LTM 相关改造（超出范围）

---

## 7. Solution Options

### 7.1 Option A: Minimal Fix

**What changes:**  
仅补缺失埋点和少量字段，输出基础 `turn_report.md`。

**What does not change:**  
不收敛 schema，不补回流机制，不补趋势汇总策略。

**Benefits:**  
改动快、短期可见。

**Costs:**  
后续重复返工概率高。

**Risks:**  
字段继续漂移，跨阶段难对齐。

**Testing burden:**  
低。

**Rollback difficulty:**  
低。

**When to choose it:**  
仅当你需要 1-2 天内临时可视化，不追求持续治理。

### 7.2 Option B: Structured Improvement

**What changes:**  
统一事件 schema v1、固定每轮报告模板、打通 bad case 回流、输出趋势评测产物（软门禁）。

**What does not change:**  
不改业务决策逻辑、不重构 agent 框架、不启用硬门禁。

**Benefits:**  
投入适中，能稳定提升“可解释+可比较+可迭代”能力。

**Costs:**  
需要跨 trace 与 eval 两侧做一致性治理。

**Risks:**  
如果字段设计过重，可能拖慢链路；需要版本兼容策略。

**Testing burden:**  
中。

**Rollback difficulty:**  
低-中（主要是 schema/报告格式回退）。

**When to choose it:**  
当前最匹配你“先看清再优化”的阶段目标。

### 7.3 Option C: Long-term Architecture Direction

**What changes:**  
建设统一观测评测平台层（强耦合数据模型、集中实验服务、可视化平台优先）。

**What does not change:**  
短期不会立即提升问题定位速度。

**Benefits:**  
长期治理上限高。

**Costs:**  
改造成本高，周期长，迁移风险大。

**Risks:**  
范围膨胀，偏离当前主线目标。

**Testing burden:**  
高。

**Rollback difficulty:**  
高。

**When to choose it:**  
仅当后续多团队协作、强合规、强 SLA 场景明确时再启动。**Deferred**。

### 7.4 Option D: Observation-first Option

**What changes:**  
先只做字段审计、埋点补齐、报告模板，不碰评测口径和回流策略。

**What does not change:**  
评测闭环仍不完整。

**Benefits:**  
风险最低，最适合先排雷。

**Costs:**  
价值释放慢，无法支撑“改前改后对比”。

**Risks:**  
容易停留在“看日志但不能决策”的状态。

**Testing burden:**  
低。

**Rollback difficulty:**  
低。

**When to choose it:**  
证据不足或线上不稳定时可短暂采用，但不应长期停留。

---

## 8. Decision Matrix

| Dimension | Option A Minimal Fix | Option B Structured Improvement | Option C Long-term Architecture | Option D Observation-first |
| --- | --- | --- | --- | --- |
| Scope | 小 | 中 | 大 | 小 |
| Development Cost | 低 | 中 | 高 | 低 |
| Risk | 中 | 中 | 高 | 低 |
| Reusability | 低-中 | 高 | 高 | 中 |
| Fit to Current Requirement | 中 | **高** | 低 | 中 |
| Local Pattern Fit | 中 | **高** | 低 | 高 |
| External Pattern Fit | 低 | **高** | 中 | 中 |
| Test Burden | 低 | 中 | 高 | 低 |
| Rollback Difficulty | 低 | 低-中 | 高 | 低 |
| Long-term Maintainability | 低 | **中-高** | 高 | 中 |
| Recommendation | 备选 | **首选** | Deferred | 辅助策略 |

---

## 9. Recommended Solution

Selected option: **Option B（Structured Improvement）**，并采用 **Option D 的上线节奏（先观察后收敛）**。

Why selected:  
它是当前“收益/成本/风险”最平衡的路径：既不会像 A 那样短视，也不会像 C 那样过重；同时满足你已确认的“先趋势观察、不阻断 PR、Langfuse 为辅、本地 trace 为主”。

Why not the other options:
- A：不足以支撑中期迭代，后续会重复返工。
- C：当前阶段过度工程化，且与你本轮约束冲突。
- D：可作为节奏，不应作为最终方案本体。

Local patterns reused:
- `skill_trace.py` 的 record/exporter 架构
- `langfuse_exporter.py` 的隐私保护与辅助导出思路
- `tests/evals/runner.py` 的 target 化评测骨架

External practices reused:
- Langfuse/OTel 的事件分层与上下文传播口径
- OpenClaw 的人类可读报告结构
- Hermes/promptfoo 的评测产物与趋势对比方式
- GitHub Actions 的软门禁到硬门禁渐进策略

Remaining risks:
1. schema 设计过重影响性能
2. 历史 trace 与新字段兼容性不足
3. bad case 回流质量不稳定

What must be verified later:
1. 报告产物是否真正提升排障效率
2. 趋势指标是否稳定且可解释
3. Langfuse 与本地 trace 是否可一键互相定位

---

## 10. Unified Technical Direction

- 要做：围绕现有 `skill_trace -> 本地 JSONL -> eval runner` 主链，建立“统一字段 schema v1 + 每轮固定报告模板 + bad case 回流 + 趋势评测产物”的结构化治理。
- 不做：不改业务核心决策逻辑，不引入新平台重构，不启用硬门禁，不扩 Redis/STM/LTM/prompt 全量迁移。
- 主要模块：`Financial-MCP-Agent/src/tools/skill_trace.py`、`Financial-MCP-Agent/src/tools/trace_exporters/langfuse_exporter.py`、`tests/evals/runner.py`、`tests/evals/*`、评测 workflow 与治理文档目录。
- 复用模式：本地主审计 + Langfuse 辅助可视化；report-first（人读）+ trace-first（机读）双轨；软门禁优先。
- 后续验证：报告覆盖率、trace-eval 可关联率、route/rewrite/entity 趋势稳定性、bad case 回流效率。
- 风险控制：schema_version 兼容、轻量报告优先、字段白名单和脱敏策略先行。
- 延后事项：硬门禁、平台化重构、性能/内存专项优化。

---

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| 报告生成带来额外时延 | 先做轻量摘要版，详细版可异步或按需展开 |
| 新旧字段不兼容导致历史不可比 | 引入 `schema_version`，保留老版本读取兼容层 |
| Langfuse 上传造成隐私泄露风险 | 严格白名单 + 默认关闭完整 prompt/reply 上传 |
| bad case 回流样本噪声高 | 先人工半自动筛选，逐步形成标注规则 |
| 软门禁长期不升级导致质量失控 | 在趋势稳定后定义升级条件（非本阶段执行） |

---

## 12. Verification Direction

1. 覆盖性：各关键阶段是否均有统一字段且可串联同一 `trace_id`。  
2. 可读性：任意一轮是否能直接生成结构化 `turn_report` 并定位异常阶段。  
3. 可比较性：评测结果是否可稳定输出趋势并支持“改前 vs 改后”对比。  
4. 可追溯性：线上问题是否能回流为 eval 样本并在后续评测中复现。  
5. 可治理性：CI 中是否能稳定产出评测工件（即使不阻断 PR）。  

---

## 13. Deferred Work

1. 硬门禁（指标跌破即阻断 PR）  
2. 观测评测平台化重构（Option C）  
3. Redis 接入与性能专项优化  
4. STM/LTM 能力扩展  
5. prompt 体系全量迁移  

---

## 14. Handoff to Plan Freezing

下一步应使用 Plan Freezing Skill 产出 `PLAN.md`。

The plan should:
- follow selected option: **Option B（Structured Improvement）**
- allow modules/files:
  - `Financial-MCP-Agent/src/tools/skill_trace.py`
  - `Financial-MCP-Agent/src/tools/trace_exporters/langfuse_exporter.py`
  - `tests/evals/runner.py`
  - `tests/evals/*`
  - `.github/workflows/eval-smoke.yml`（或新增非阻断评测 workflow）
  - `docs/开发计划/观测与评估治理/*`
- forbid modules/files:
  - 业务主逻辑核心决策流（chat/report 主链路行为）
  - Redis / STM / LTM 相关功能模块
  - prompt 全量迁移范围
- include required tests:
  - 字段一致性与报告生成测试
  - route/rewrite/entity 趋势评测
  - trace 与 eval 关联性检查
- include required logs/metrics:
  - schema_version 覆盖率
  - turn_report 覆盖率
  - bad case 回流数量与命中率
  - route/rewrite/entity 核心趋势指标
- include rollback strategy:
  - 字段新增优先，不删旧字段
  - 新报告模板失败时可退回旧输出
  - 非阻断 workflow 可随时关闭
- preserve these constraints:
  - 本地审计主链不变
  - Langfuse 为辅助
  - 先观察不阻断 PR
  - 不做范围外能力开发
- keep these external references in mind:
  - Langfuse docs（data model/scores/masking）
  - OpenTelemetry signals/context propagation
  - OpenClaw/Hermes/cc-haha 的报告与评测模式
  - GitHub required checks 渐进治理策略
