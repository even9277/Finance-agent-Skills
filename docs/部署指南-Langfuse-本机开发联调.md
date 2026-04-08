# Langfuse 安装与部署指南（本机开发 / 新手版）

这份指南专门适配你当前这套 Finance 项目环境：

- 项目根目录：`/root/Finance`
- Python 虚拟环境：`/root/Finance/.venv`
- 后端配置文件：`/root/Finance/backend/.env`
- Agent 模型配置：`/root/Finance/Financial-MCP-Agent/.env`
- PostgreSQL：沿用仓库现有 `docker/docker-compose.yml`
- 后端启动方式：本机 `uvicorn backend.main:app --reload --port 8000`

这份文档和下面几份现有指南是配套关系，不是替代关系：

- [部署指南-PostgreSQL-Docker.md](/root/Finance/docs/部署指南-PostgreSQL-Docker.md)
- [从0到1恢复启动指令指南.md](/root/Finance/docs/从0到1恢复启动指令指南.md)
- [部署指南-智星云-WSL-uv.md](/root/Finance/docs/部署指南-智星云-WSL-uv.md)

## 1. 先理解这次要做什么

你现在的项目已经有本地 trace：

- 会把每轮对话的 `trace / span / event` 写到本地日志
- 会记录 skill 路由、工具调用、evidence、degrade、memory enqueue 等信息

Langfuse 这一步不是“替换本地 trace”，而是：

1. 保留本地 trace 作为最原始的审计记录
2. 再把同一份 trace 导出到 Langfuse
3. 让你能在网页上按 `session / skill / release / latency / error` 去看问题

所以正确顺序是：

1. 先确保本地 trace 正常
2. 再打开 `ENABLE_LANGFUSE`
3. 再去 Langfuse 页面验证链路

## 2. 先决条件

开始前请先确认下面几点：

```bash
cd /root/Finance
test -d .venv && echo "OK: .venv"
test -f backend/.env && echo "OK: backend/.env"
test -f Financial-MCP-Agent/.env && echo "OK: Financial-MCP-Agent/.env"
docker compose -f docker/docker-compose.yml ps
```

如果 PostgreSQL 还没启动，先按仓库现有方式拉起来：

```bash
cd /root/Finance
docker compose -f docker/docker-compose.yml up -d postgres
```

如果你还没完成基础后端部署，先看：

- [部署指南-PostgreSQL-Docker.md](/root/Finance/docs/部署指南-PostgreSQL-Docker.md)
- [从0到1恢复启动指令指南.md](/root/Finance/docs/从0到1恢复启动指令指南.md)

## 3. 安装 Langfuse Python SDK

本项目现在已经把 Langfuse 依赖写进 [requirements.txt](/root/Finance/backend/requirements.txt) 了，建议直接在现有 `.venv` 里安装，不要另开一套 Python 环境。

```bash
cd /root/Finance
source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

安装完成后，用下面命令确认：

```bash
cd /root/Finance
source .venv/bin/activate
python - <<'PY'
from langfuse import Langfuse
print("Langfuse SDK import OK")
print("Client class:", Langfuse.__name__)
PY
```

如果你看到 `Langfuse SDK import OK`，说明 SDK 安装完成。

## 4. 先同步 env，但先不要急着打开 Langfuse

我已经把 [backend/.env](/root/Finance/backend/.env) 和 [backend/.env.example](/root/Finance/backend/.env.example) 补上了 Langfuse 相关字段。

你现在先确认 `backend/.env` 至少有这一段：

```env
ENABLE_TRACE=true
ENABLE_EVIDENCE_LINEAGE=true
ENABLE_TRACE_ARTIFACT_REFS=false
ENABLE_TRACE_PROMPT_CAPTURE=false
ENABLE_TRACE_REPLY_CAPTURE=false
ENABLE_LANGFUSE=false

TRACE_ARTIFACT_DIR=/root/Finance/Financial-MCP-Agent/logs/chat_trace_artifacts

LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_PROJECT=finance-skill-chat
LANGFUSE_ENV=dev
LANGFUSE_RELEASE=local-dev
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_FLUSH_AT=20
LANGFUSE_FLUSH_INTERVAL_SEC=5
```

这里有两个非常重要的理解：

1. `ENABLE_LANGFUSE=false` 是第一阶段默认值  
   先验证本地 trace，再打开 Langfuse，排障更简单。

2. `LANGFUSE_BASE_URL` 和 `LANGFUSE_HOST` 现在都兼容  
   因为 Langfuse 新版文档更常写 `BASE_URL`，但你仓库历史上已经用了 `HOST`。

## 5. 先验证“只开本地 trace”没有问题

启动后端：

```bash
cd /root/Finance
source .venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

启动后你至少应看到类似输出：

- `数据库初始化完成`
- `trace runtime 初始化完成`

再开一个终端做健康检查：

```bash
curl -s http://127.0.0.1:8000/api/health
```

如果你平时用前端联调，再正常启动前端即可：

```bash
cd /root/Finance/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

然后在页面里登录测试账号：

- `test1 / test1`
- `test2 / test2`

在聊天里发一条高频 skill 问题，例如：

- `宁德时代这份财报怎么看，值不值得继续跟踪？`
- `推荐几个适合稳健投资者的黄金ETF`
- `半导体板块最近为什么这么热？`

接着检查本地 trace 是否有输出：

```bash
tail -n 20 /root/Finance/Financial-MCP-Agent/logs/skill_trace.log
tail -n 5 /root/Finance/Financial-MCP-Agent/logs/chat_traces.jsonl
```

如果这里已经能看到新的 trace 记录，说明第一步成功。

## 6. 选择 Langfuse 部署方式

### 方案 A：Langfuse Cloud

这是最适合新手的方式，也是我最推荐你先用来做 dev/staging 联调的方式。

你要做的事只有：

1. 打开 Langfuse Cloud 控制台
2. 创建一个项目
3. 拿到：
   - `Public Key`
   - `Secret Key`
   - `Base URL / Host`

然后填回 [backend/.env](/root/Finance/backend/.env)：

```env
ENABLE_LANGFUSE=true
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-你的公钥
LANGFUSE_SECRET_KEY=sk-lf-你的私钥
LANGFUSE_PROJECT=finance-skill-chat
LANGFUSE_ENV=dev
LANGFUSE_RELEASE=local-dev
LANGFUSE_SAMPLE_RATE=1.0
```

### 方案 B：Langfuse Self-Hosted

如果你只是先把项目功能跑通，不建议第一步就自托管 Langfuse。

原因很简单：

- 你当前项目已经有 PostgreSQL、前后端、MCP、Mem0 这些链路
- 自托管 Langfuse 会额外增加运维复杂度
- 新手最容易把“业务没跑通”和“监控平台没起好”混在一起

更稳妥的方式是：

1. 先用 Langfuse Cloud 联通项目
2. 确认 exporter、字段、面板都没问题
3. 再评估要不要迁到自托管

如果你后面确实要自托管，请优先看 Langfuse 官方自托管文档和官方仓库，不建议直接沿用仓库里那份较早期的示例文档：

- https://langfuse.com/docs
- https://python.reference.langfuse.com/langfuse

## 7. 打开 Langfuse 并重启后端

当你把 `ENABLE_LANGFUSE` 改成 `true` 后，一定要重启后端进程：

```bash
cd /root/Finance
source .venv/bin/activate
pkill -f "uvicorn backend.main:app" || true
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

重启后重点看后端日志：

- 正常情况：会看到 `trace runtime 初始化完成`
- 如果 Langfuse 没启用成功，通常会看到：
  - 缺少 key
  - SDK import 失败
  - exporter 初始化失败

## 8. 做第一次真实联调

最简单的联调方式就是继续用前端聊天：

1. 打开前端页面
2. 登录测试账号
3. 进入聊天
4. 连续问 2 到 3 个问题

推荐测试这 4 类：

1. `宁德时代这份财报怎么看，值不值得继续跟踪？`
2. `半导体板块最近为什么这么热？`
3. `推荐几个适合稳健投资者的黄金ETF`
4. `比亚迪今天为什么跌？`

然后去 Langfuse 页面检查：

1. 是否出现新的 trace
2. 是否能看到同一个 session 下的多轮记录
3. span 里是否有 router / executor / evidence / reply / memory 等阶段
4. metadata 里是否能看到 `skill_name`、`route_confidence`、`degrade_stage`

## 9. 最推荐的第一版配置

这是最适合本机开发和新手联调的第一版：

```env
ENABLE_TRACE=true
ENABLE_EVIDENCE_LINEAGE=true
ENABLE_TRACE_ARTIFACT_REFS=false
ENABLE_TRACE_PROMPT_CAPTURE=false
ENABLE_TRACE_REPLY_CAPTURE=false
ENABLE_LANGFUSE=true

LANGFUSE_ENV=dev
LANGFUSE_RELEASE=local-dev
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_FLUSH_AT=20
LANGFUSE_FLUSH_INTERVAL_SEC=5
```

不建议你一上来就打开下面两个：

- `ENABLE_TRACE_PROMPT_CAPTURE=true`
- `ENABLE_TRACE_REPLY_CAPTURE=true`

原因是：

- 更容易把敏感内容写入 trace
- 本地 artifact 数量会明显变多
- 你现在主要目标是先验证链路，不是先采全量内容

## 10. 最常见的排障方法

### 问题 1：我明明改了 `backend/.env`，但 Langfuse 还是没生效

先做这三件事：

1. 确认已经重启 `uvicorn`
2. 确认改的是 [backend/.env](/root/Finance/backend/.env)，不是只改了 `.env.example`
3. 确认 `ENABLE_LANGFUSE=true`

本项目现在已经在启动时把 `Financial-MCP-Agent/.env` 和 `backend/.env` 都注入到 `os.environ`，这样底层 trace/exporter 才能读取到真实值。

### 问题 2：后端能跑，但 Langfuse 页面没有 trace

按顺序检查：

1. 先看本地 trace 是否正常写入  
   `tail -n 5 /root/Finance/Financial-MCP-Agent/logs/chat_traces.jsonl`
2. 再看后端日志是否出现 `langfuse_init_failed` 或类似错误
3. 再检查 `LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL`

如果本地 trace 都没有，那先修本地链路，不要先怀疑 Langfuse。

### 问题 3：SDK 装了，但导出时报错

本项目现在按 Langfuse 4.x SDK 做了兼容。你如果手动装了更老版本，可能会出现 API 不一致。

最稳妥的命令是：

```bash
cd /root/Finance
source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

### 问题 4：想把 Langfuse 关掉，是否会影响主功能

不会。

只要把：

```env
ENABLE_LANGFUSE=false
```

然后重启后端，系统就会继续只保留本地 trace，不影响聊天、skill、memory 主链路。

## 11. 推荐的上线顺序

如果你是第一次做这件事，最建议按下面顺序走：

1. 只开本地 trace，确认聊天与 skill 正常
2. 安装 Langfuse SDK
3. 先用 Langfuse Cloud 接入 dev 环境
4. 用前端真实问答跑 5 到 10 条 trace
5. 在 Langfuse 页面确认筛选、搜索、trace 展示都正常
6. 再决定是否做 self-hosting / dashboard / 告警

## 12. 官方参考

- Langfuse Overview: https://langfuse.com/docs
- Langfuse Python SDK Reference: https://python.reference.langfuse.com/langfuse
