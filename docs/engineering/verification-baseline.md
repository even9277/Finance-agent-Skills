# 基础设施验收基线

## 已完成

截至 2026-08-20，受控主链迁移前的工程基础设施已完成 M0-M5：

- 根 Python 依赖由 `pyproject.toml` 和 `uv.lock` 锁定。
- Ruff、Pyright、pytest markers、前端 ESLint 和离线 CI 已接入。
- 测试分为 unit、contract、integration、offline eval、Compose offline E2E 和 live。
- Compose E2E 使用临时 PostgreSQL、真实 FastAPI、生产构建的 Vue/Nginx 和确定性 Fake 聊天装配。
- Trace JSONL 在落盘前按 key 脱敏；可选 exporter 失败不阻断本地 Trace。
- 默认 CI 不读取模型、Tushare、MCP、Langfuse 或生产凭证。

## 当前已验证命令

| 层级 | 命令 | 最近结果 |
| --- | --- | --- |
| Python lock/lint/type | `uv lock --check`、Ruff、Pyright | 通过；Pyright 0 errors，9 个历史 warning |
| 分层测试 | `uv run --locked pytest tests/unit tests/contract tests/integration tests/e2e -q` | 9 passed，2 skipped |
| 全仓测试 | `uv run --locked pytest -q` | 60 passed，6 skipped，4 deselected |
| 前端 | `npm ci`、lint、type-check、build | 全部通过；保留既有 chunk warning |
| Compose | `docker compose -f docker/docker-compose.offline.yml ...` | 11 passed；internal network；资源清理完成 |

## 未执行与风险

- Live E2E 未执行：当前没有显式模型/外部服务凭证、隔离写租户、预算和 `LIVE_E2E_ENABLED` 开关。不能把离线 Fake 结果当作真实模型质量结果。
- PostgreSQL 启动日志暴露既有增量迁移事务误报：重复列异常后事务进入 aborted，但应用仍记录初始化成功。必须另开数据库迁移治理计划。
- Trace 当前按 key 脱敏，已覆盖本地 JSONL 和 exporter；`Bearer ...`、`sk-...` 等字符串模式脱敏作为后续增强。
- Pyright 历史 import warning、`datetime.utcnow()` 弃用 warning、TestClient 兼容 warning 和前端大 chunk warning 未在本基础设施计划中顺手清理。

## 下一步唯一入口

首个受控主链业务模块必须另建 `docs/specs/<module>/`，依次完成 Requirement Definition、Codebase Reconnaissance、Clarification、Solution Tradeoff、Plan Freezing，再执行一个独立 milestone。候选顺序为：typed state/主链骨架、实体解析与两阶段路由、route-specific rewrite、Tool Discovery/Planner/Validator、Executor/Evidence Envelope、Verifier/Controller、Synthesis/前端事件。

每个模块都必须以 Finance 历史代码和项目描述文档为证据来源，先写 characterization/contract test，再直接替换唯一目标实现；同步所有调用方并删除旧实现，不建立兼容 Adapter。
