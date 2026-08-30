# Milestone 7 Execution Report

## 1. Milestone Identity

- Milestone: 7 — Public Explicit-skill and Skill-confirm UI Closure
- Branch: `feature/skills-sop-migration`
- Completed: 2026-08-30
- Execution policy: exactly one frozen milestone；未 commit、push、PR，未进入 Milestone 8。
- Previous report: `MILESTONE_6_EXECUTION_REPORT.md`

## 2. Frozen Contract

正式 REST/WS 请求新增可选 `explicit_skill`；中置信路由新增可选 `skill_confirm` 控制帧和前端确认卡。确认必须在同一 session 以原问题和显式 Skill 重提，不能重复插入用户消息；取消只清理本地状态，不发请求、不调工具。显式选择不能绕过 Registry 或 Skill input contract。旧请求字段、普通 REST 响应形状、WS 文本澄清与既有帧顺序必须兼容。禁止修改鉴权、数据库、部署、生产依赖或引入新的 UI/状态框架。

## 3. Implementation Outcome

### 3.1 Public REST/WS contract

- `ChatMessageRequest` 新增 optional `explicit_skill`，边界统一 trim/lowercase，并限制为 1–64 位 slug；空白值仍按未选择处理。
- `ChatMessageResponse` 新增 exclude-if-null 的 `skill_confirmation`，候选只暴露 `skill_name/confidence/version/reason` 与 Registry snapshot hash，不暴露 Skill 正文、工具权限或内部状态。
- REST 和 WS 都通过同一个 `ChatCommand.explicit_skill` 进入 `ControlledChatUseCase`。
- WS 使用同一个 Pydantic 请求模型校验；中置信时帧序为 `session_id → skill_confirm → 旧文本澄清 → done`。普通请求仍保持原帧序。

### 3.2 Server-side safety closure

- `ChatOutcome` 增量携带领域 `SkillConfirmation`，Presenter 负责映射公开载荷。
- 不存在/不可用的显式 Skill 在 Workflow 路由后、权限与计划前返回 `NEEDS_CLARIFICATION + INVALID_REQUEST`，工具调用和模型调用均为 0；不再静默回退普通模型。
- 合法显式 Skill 只覆盖自动选择；Rewrite 仍使用同一 Registry snapshot 的 input contract。`fund-compare` 只有一个主体时仍在 Planner 前澄清，工具调用为 0。
- 自动中置信仍以文本澄清兜底，同时返回 typed confirmation；确认前不进入 Permission、Planner、Executor 或 Model。

### 3.3 Frontend confirmation closure

- API client、WS payload/control-frame union、Pinia store 与 `useChat` 均使用 typed confirmation contract。
- 新 `SkillConfirmationCard.vue` 展示候选、置信度、版本和原因；只提供候选确认与取消，没有增加其他控制卡。
- 确认复用 pending 中保存的原问题与 session，通过 HTTP 携带 `explicit_skill` 重提，并设置 `appendUserMessage=false`，因此不会重复显示用户消息。
- 取消仅执行 `clearSkillConfirmation()`；新消息、会话切换、消息重载和 store reset 都会清理过期确认。
- 确认卡在发送/流式处理中禁用，避免同一 pending 被重复提交。

## 4. Concrete Protocol and Behavior Calls

### REST explicit selection

```json
{
  "user_id": "user-confirm",
  "message": "比较两只黄金基金",
  "session_id": "session-confirm",
  "explicit_skill": "fund-compare"
}
```

Router 实测构造的 `ChatCommand` 保留同一 session 和 `explicit_skill=fund-compare`。需要确认时，REST 增量返回：

```json
{
  "skill_confirmation": {
    "reason": "需要用户确认专业分析任务",
    "registry_snapshot_hash": "<sha256>",
    "candidates": [
      {"skill_name": "fund-compare", "confidence": 0.72, "version": "1.1.0", "reason": "基金比较语义相近"}
    ]
  }
}
```

### WebSocket confirmation

测试客户端实际收到：

1. `{"type":"session_id","session_id":"session-confirm"}`
2. `{"type":"skill_confirm","session_id":"session-confirm","confirmation":{...}}`
3. 原文本澄清消息
4. `{"type":"done","session_id":"session-confirm"}`

确认后的 WS 请求也实测把原 session 与显式 Skill 传给应用用例。旧 WS 请求不含 `explicit_skill` 时仍维持 `session_id → text → context_update → done`。

### Confirm/cancel and invalid-input smoke

| Case | Observed result |
| --- | --- |
| 点击 `fund-compare` | 同一 session 重提原问题；API 第四参数为 `fund-compare`；用户消息仍只有 1 条 |
| 点击取消 | pending confirmation 清空；API 调用次数为 0 |
| `explicit_skill=unknown-finance-skill` | `NEEDS_CLARIFICATION / INVALID_REQUEST`；0 tool、0 model |
| `explicit_skill=fund-compare` 但只有一个基金主体 | `REWRITE_CLARIFICATION_REQUIRED`；0 tool |
| 旧 REST 请求 | 响应字段集合仍为 `reply/session_id/memory_profile/context_window` |

## 5. Changed Surface

- Backend public/application: `backend/schemas/chat.py`、`backend/routers/chat.py`、`backend/application/chat/contracts.py`、`backend/application/chat/use_case.py`
- Domain safety: `Financial-MCP-Agent/src/conversation/workflow.py`
- Frontend: `frontend/src/api/index.ts`、`frontend/src/stores/chatStore.ts`、`frontend/src/composables/useChat.ts`、`frontend/src/components/chat/SkillConfirmationCard.vue`、`frontend/src/views/ChatView.vue`
- Tests: REST/WS public contract、controlled chat E2E、API/store/composable/component Vitest

没有修改 auth、数据库、持久化模型、部署配置、依赖锁文件、Skill 资产或执行器。

## 6. Verification Evidence

| Command / check | Result |
| --- | --- |
| M7 backend focused REST/WS/workflow suite | `19 passed` |
| M7 frontend focused Vitest | `4 files / 7 tests passed` |
| backend + contract + E2E + conversation regression | `133 passed, 1 skipped, 2 deselected, 3 xfailed` |
| legacy/current Agent tests, non-live | `33 passed, 4 deselected` |
| frontend full Vitest | `5 files / 9 tests passed` |
| frontend `vue-tsc -b` | pass |
| frontend ESLint | pass |
| frontend production build | pass；仅既有 dynamic-import/chunk-size warnings |
| M7 changed-surface Ruff | `All checks passed` |
| M7 changed-surface Pyright | `0 errors, 0 warnings` |
| target matrix | `5 passed, 1 failed`；唯一失败是 Milestone 8 尚未注册 `skills_sop` runner |
| `git diff --check` | pass；仅 Windows LF→CRLF working-copy warnings |
| dependency diff | empty |
| historical `Finance` runtime import scan | empty |

仓库级既有 Ruff/Pyright 技术债未在 M7 越界修复；本里程碑改动面单独为全绿。未使用真实模型、行情、Tavily 或数据库，公开 Router/WS 使用 FastAPI TestClient 和离线应用输出完成协议验收。

## 7. Failures and Repairs

### Tests-first red phase

首轮 backend 新合同产生 5 个预期失败：公开 schema/response 尚无 `explicit_skill/skill_confirmation`、WS 未透传显式选择、非法显式 Skill 被旧实体澄清吞掉。实现公开模型、Presenter 和 Workflow fail-closed 分支后转为 19/19 通过。

### Frontend command-location error

第一次在仓库根目录执行 npm focused tests，因根目录没有 `package.json` 返回 `ENOENT`。该失败只反映命令工作目录错误；改为 `frontend/` 后进入真实测试。

### Vitest hoisted mock repair

首次前端真实运行时，三个文件/五个断言已通过，`useChat` suite 在 collection 阶段因 `vi.mock` 提升先于顶层 mock 初始化而失败。仅把两个测试 mock 改为 `vi.hoisted`，未修改生产逻辑；重跑后 4 文件/7 测试全绿。

## 8. Compatibility and Rollback

- 所有新增请求字段、响应字段和 WS 控制帧均为 optional；旧 REST/WS 客户端无需修改。
- 去掉前端确认卡仍保留服务端文本澄清和自动路由。
- 代码回滚可独立移除 `explicit_skill` public mapping、`skill_confirm` 帧和前端 pending state；不会影响记忆、消息持久化或五类 Skill 的自动选择/执行。

## 9. Remaining Work

- Milestone 8：route→synthesis 低基数 trace 与可复现 `skills_sop` runner/artifact；当前目标矩阵唯一红灯。
- Milestone 9：最终全量回归、端到端场景矩阵、窄修、文档和交付审计。
- 真实外部行情/模型/Web Search/Compose 验收仍需要显式凭证和环境授权；本里程碑公开协议与 UI 行为已完成默认离线验收。

## 10. Handoff

Milestone 7 complete. The next frozen step is Milestone 8 only: add low-cardinality route-to-synthesis observability and a reproducible `skills_sop` evaluation runner/artifact without changing the public confirmation contract or execution ownership.
