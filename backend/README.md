# Finance 智投助手 — 后端 (Phase 1)

## 依赖安装

```bash
# 在项目根目录或 backend 目录下安装
pip install -r backend/requirements.txt
```

## 启动方式

```bash
# 在 /root/Finance 根目录运行（推荐）
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动时会自动创建 SQLite 数据库文件 `backend/finance.db`。

## API 文档

启动后访问：
- Swagger UI：http://localhost:8000/api/docs
- OpenAPI JSON：http://localhost:8000/api/openapi.json

## 前置条件

1. **MCP 服务**：`a-share-mcp-is-just-i-need` 的 MCP 服务由 agent 内部通过 stdio 自动启动，需确保 `uv` 已安装。
2. **LLM API Key**：`Financial-MCP-Agent/.env` 中配置 `OPENAI_COMPATIBLE_API_KEY` 等变量。
3. **当前工作目录**：务必从 `/root/Finance`（项目根）启动，否则 sys.path 注入路径计算有误。

## 目录结构

```
backend/
├── main.py          # FastAPI 入口
├── config.py        # pydantic-settings 配置
├── requirements.txt
├── .env.example     # 环境变量示例
├── db/
│   ├── database.py  # SQLAlchemy 异步引擎
│   └── models.py    # ORM 模型
├── routers/         # 5 个路由模块
├── schemas/         # Pydantic 请求/响应模型
├── services/        # 业务逻辑层
└── middleware/      # 中间件（Phase 4 实现鉴权）
```
