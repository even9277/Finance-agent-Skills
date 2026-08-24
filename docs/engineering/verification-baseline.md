# 受控对话主链验收基线

## 已完成

截至 2026-08-24，受控对话主链 M0-M7 已完成并合并：

- 根 Python 依赖由 `pyproject.toml` 和 `uv.lock` 锁定。
- Ruff、Pyright、pytest markers、前端 ESLint 和离线 CI 已接入。
- 测试分为 unit、contract、integration、offline eval、Compose offline E2E 和 live。
- REST/WS 已共同切换到唯一 `ControlledChatUseCase`，旧 `chat_service.py` 已删除。
- Compose E2E 使用临时 PostgreSQL、真实 FastAPI、生产构建的 Vue/Nginx、真实受控
  Workflow 和生产 Trace Adapter，只 Fake 外部 Model/Tool Ports。
- Trace JSONL 在落盘前递归脱敏；一轮请求映射为一个 root，并按实际分支记录有序阶段
  Span。固定成功案例为 12 个阶段 Span；澄清会提前结束，重规划会增加重复阶段。可选
  exporter 失败不阻断本地 Trace。
- 默认 CI 不读取模型、Tushare、MCP、Langfuse 或生产凭证。
- Protected Live E2E 通过显式开关真实调用一次 LLM 和只读 Tushare，并使用临时数据库。

## 当前已验证命令

| 层级 | 命令 | 最近结果 |
| --- | --- | --- |
| Python lock/lint/type | `uv lock --check`、CI 维护范围 Ruff、Pyright | 通过；0 errors，0 warnings |
| 后端/Agent/eval | CI 对应锁定命令 | 后端 11 passed；Agent 33 passed、4 deselected；eval 11 passed |
| 全仓测试 | `uv run --locked pytest -q` | 126 passed，2 skipped，5 deselected |
| 前端 | `npm ci`、lint、type-check、build | 全部通过；保留既有 chunk warning |
| Compose | `docker compose -f docker/docker-compose.offline.yml ...` | 73 passed，1 skipped；资源清理完成 |
| Protected Live | `tests/e2e/test_live_controlled_chat_chain.py -m live` | 1 passed；真实 LLM + 只读 Tushare + 临时 SQLite |

## 未执行与风险

- GitHub protected Live workflow 已定义，但 Environment secrets 和审批规则仍需仓库管理员配置；
  本地一次 Live 成功只能证明固定纵向案例可运行，不能代表全场景模型质量。
- PostgreSQL 启动日志暴露既有增量迁移事务误报：重复列异常后事务进入 aborted，但应用仍记录初始化成功。必须另开数据库迁移治理计划。
- 真实 Langfuse 项目尚未调用；当前证据是本地 JSONL、脱敏和 exporter 故障隔离测试。
- 面试材料中的 70.2%→88.4%、93.8%、95%+、单轮 <10s 等历史数字尚未按新主链复测。
- 全仓历史目录仍有静态债务；CI 对 M0-M7 维护边界执行零问题门禁。`datetime.utcnow()`、
  TestClient 和前端大 chunk warning 仍是存量技术债。

## 后续增强入口

受控主链本体已经迁移完成。新增能力仍须另建 `docs/specs/<module>/`，依次完成
Requirement Definition、Codebase Reconnaissance、Clarification、Solution Tradeoff、Plan
Freezing，再执行独立 milestone。优先候选为：历史黄金集重建、版本化前端事件与确认卡、
网页新闻弱证据、模型化理解阶段、Redis 分布式韧性和真实 Langfuse 评测回流。

每个模块都必须以 Finance 历史代码和项目描述文档为证据来源，先写 characterization/contract test，再直接替换唯一目标实现；同步所有调用方并删除旧实现，不建立兼容 Adapter。
