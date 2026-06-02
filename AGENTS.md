# Finance AGENTS.md

本文件是 `/root/Finance` 工作区的项目级 AI 编码规则。它面向 Codex、Cursor、Claude Code 等 coding agent，用来约束后续开发行为，降低低级错误、无关重构和与现有项目不兼容的改动。

如果子目录以后新增更具体的 `AGENTS.md`，以更靠近被修改文件的规则为准；用户在当前对话中的明确要求优先级最高。

## 项目定位

Finance 是一个智能投研助手项目，主链路包括：

- 后端：`backend/`，FastAPI、Pydantic、数据库模型、路由、服务编排、鉴权与中间件。
- 前端：`frontend/`，Vue3、TypeScript、Vite、Pinia/composables、聊天和报告页面。
- Agent 运行时：`Financial-MCP-Agent/src/`，LangGraph/LangChain、多 Agent 报告、对话路由、Skills、工具调用、Memory、Trace、LLM 客户端。
- 数据与部署：`migrations/`、`docker/`、`scripts/`、`tests/`。
- 项目文档：`docs/`，其中 `docs/项目描述.md` 是目标行为和项目叙事的最高优先级文档。

本项目的开发目标不是“只要能跑”，而是保证功能可理解、可测试、可观测、可降级、可回滚，并且与已有代码契约保持兼容。

## 目录边界

默认可修改的主项目区域：

- `backend/`
- `frontend/src/`
- `Financial-MCP-Agent/src/`
- `docs/`
- `tests/`
- `migrations/`
- `docker/`
- `scripts/`

默认只读参考区域，除非用户明确要求修改：

- `Reference/`
- `FinRL_DeepSeek/`
- `a-share-mcp-is-just-i-need/`
- `vendor/`

条件性开发区域：

- `news_model_training/` 仅在任务明确涉及新闻情感/风险小模型训练、数据处理或评测时修改。

默认禁止手工修改的生成物、缓存和运行产物：

- `frontend/dist/`
- `logs/`
- `Financial-MCP-Agent/logs/`
- `Financial-MCP-Agent/reports/`
- `__pycache__/`
- `.pytest_cache/`
- `node_modules/`
- `.venv/`、`.venv_lg1_test/`

如果任务需要触碰只读或禁止区域，必须先说明原因、风险和替代方案。

## 信息源优先级

1. 用户当前消息中的明确要求。
2. 本文件和更近目录的 `AGENTS.md`。
3. `docs/项目描述.md`。
4. 已批准的开发计划：`docs/开发计划/<模块名>-优化开发计划.md`。
5. 当前代码、测试和运行配置。
6. 其他项目文档。使用前必须检查是否与 `docs/项目描述.md` 对齐。
7. `Reference/` 下的优秀 Agent 仓库和外部最佳实践。只能用于提炼思路，不能不加适配地照搬。

规划和实现时，必须把外部经验翻译成本仓库的具体规则、目录和命名。

## 开发前必做

开始任何代码修改前，先完成以下检查：

- 运行或阅读 `git status --short`，识别已有脏文件，不要覆盖用户改动。
- 阅读相关模块代码，不要凭文件名猜实现。
- 搜索已有实现，优先复用现有模式，常用命令示例：`rg "关键字"`、`rg --files`。
- 明确本次任务类型：bug 修复、功能新增、重构、性能优化、文档治理、部署配置、测试补强。
- 明确影响面：前端、API schema、后端 service、DB、Agent runtime、tools、memory、trace、tests、docs、env。
- 涉及 Finance 项目能力边界时，先核对 `docs/项目描述.md`。

需求不清楚时，先澄清再改代码。不要用大范围探索式改动替代需求澄清。

## 计划规则

复杂任务先写计划，再执行。计划至少包含：

- 目标
- 非目标
- 必须保持不变的行为
- 验收标准
- 变更面分析
- 实现策略选择：复用现有实现、本地小重构、新增模块、推迟处理
- 允许修改的文件
- 禁止修改的文件
- 执行动作
- 验收命令
- 停止条件

计划默认写到 `docs/开发计划/<模块名>-优化开发计划.md`。规划阶段默认只读分析，不修改业务代码，除非用户明确要求立即实现。

## 执行规则

- 默认小步开发。一次只解决一个明确目标。
- 优先最小必要改动，不做无关重构。
- 不删除或削弱现有用户可依赖路径。
- 新能力优先使用 feature flag、兼容层或降级路径，避免一次性替换旧链路。
- 涉及公共字段、Pydantic schema、TypeScript 类型、API 返回、DB 列、Agent state 字段时，必须检查全链路调用方。
- 修改行为时同步更新相关测试、文档或手动验收说明。
- 发现计划与现有代码或 `docs/项目描述.md` 冲突时，停止并说明冲突，不要自行扩范围。

禁止事项：

- 禁止为了通过测试删除测试、弱化断言或吞掉异常。
- 禁止硬编码密钥、token、数据库密码或真实生产配置。
- 禁止在未核对调用链的情况下重命名公共字段。
- 禁止在 router、Vue 组件或 Agent prompt 中堆复杂业务逻辑。
- 禁止把参考仓库代码直接复制进主项目而不解释适配理由。

## 后端规则

后端主目录是 `backend/`。保持分层清楚：

- `backend/routers/`：只负责 HTTP 入口、参数接收、依赖注入、响应转换。
- `backend/schemas/`：只定义请求/响应 Pydantic schema 和接口契约。
- `backend/services/`：负责业务流程编排。
- `backend/db/`：负责数据库连接、ORM 模型和迁移辅助。
- `backend/integrations/`：负责与 Agent runtime 等外部/内部子系统的适配。
- `backend/middleware/`：负责鉴权、请求上下文等横切逻辑。

后端开发要求：

- router 不直接写复杂业务，不直接散落数据库查询。
- service 不直接返回随意拼接的未校验结构，响应字段要与 schema 对齐。
- 改 schema 时同步检查前端 `frontend/src/api/`、store、composables 和相关组件。
- 异常要有明确错误信息和日志，不要 silent failure。
- 外部服务失败时优先降级，不让主链路直接崩溃。
- 日志必须可排查：关键异常使用 `logger.exception` 或 `exc_info=True` 保留异常链。

## 数据库规则

本项目以 PostgreSQL/pgvector 为目标数据库能力，兼容性逻辑需与现有 SQLite/本地开发路径谨慎区分。

数据库改动要求：

- 新增或变更字段时，必须同步检查 `backend/db/models.py`、迁移脚本、启动迁移逻辑和相关测试。
- 重要业务唯一性应尽量由数据库约束保证，不只依赖 Python 判断。
- 查询必须使用 ORM、参数绑定或已有安全封装，禁止拼接用户输入形成 SQL。
- 大表查询必须考虑 `limit`、分页、索引和排序字段。
- 缺列、缺表、连接失败要有明确日志或降级行为。
- 涉及 PostgreSQL 结构变更时，交付物应包含迁移文件或可执行 SQL，并说明是否需要人工执行。

## 前端规则

前端主目录是 `frontend/src/`。保持职责清楚：

- `frontend/src/api/`：统一封装接口请求、WebSocket URL、响应类型。
- `frontend/src/stores/`：管理跨组件状态。
- `frontend/src/composables/`：封装可复用业务逻辑和副作用。
- `frontend/src/components/`：组件只负责展示和局部交互。
- `frontend/src/views/`：页面级组合。

前端开发要求：

- 不在组件里散落后端 URL、鉴权细节或重复请求逻辑。
- API 字段必须与后端 schema 对齐，注意 `snake_case` 与 `camelCase` 的映射。
- WebSocket、流式消息、乐观更新和错误回滚必须保持用户体验一致。
- 用户可见文案使用中文，避免工程术语直接暴露给普通用户。
- 修改 UI 时关注空状态、加载态、错误态、长文本、移动端布局和重复点击。
- 不手工修改 `frontend/dist/`，构建产物由构建命令生成。

## Agent 运行时规则

Agent 相关主目录是 `Financial-MCP-Agent/src/`。核心分层：

- `agents/`：路由、实体解析、planner、executor、verifier、synthesis、多 Agent 报告节点。
- `tools/`：Tushare/MCP/Web Search/trace 等工具封装。
- `skills/`、`skills_v2/`：金融 SOP Skills、skill spec、loader、schema gate、版本和快照。
- `memory/`：Mem0、长期记忆、短期记忆、画像和 LTM worker。
- `utils/`：日志、LLM 客户端、执行记录和通用工具。

Agent 开发要求：

- 工具调用必须有 schema、超时、错误结构和降级路径。
- 实时数据不足时必须说明数据限制，禁止编造行情、财务或新闻事实。
- 路由、实体解析、planner、executor、verifier、synthesis 的职责不要混在一个函数里。
- 新路由或新执行链路优先 flag-gated，并保留旧链路兼容。
- 关键链路必须写 trace：route、plan、tool_calls、latency、status、degradation_reason、final_answer。
- prompt 改动必须有输入/输出边界说明，不能只靠“更强提示词”解决结构问题。
- Skill 新增或修改时，同步考虑 `SKILL.md`、`skill_spec.yaml`、`references/`、`tests/cases.md` 和注册/加载逻辑。

## Reference 复用规则

`Reference/` 下的 `openclaw/`、`hermes-agent/`、`cc-haha/`、`traveling-agent/` 是参考仓库。

使用参考仓库时：

- 先说明参考的是哪个仓库、哪个模块、解决了什么问题。
- 提炼设计逻辑，不直接照搬不适配的目录结构。
- 必须映射回本项目现有命名、调用链和约束。
- 如果参考做法与 `docs/项目描述.md` 或当前代码冲突，以本项目为准。

## 端到端启动与验收流程

后续 Agent 修改代码后，应优先完成“能启动、能登录、能请求接口、能在前端发问题”的端到端验证。端到端验证是指从数据库、后端、前端到用户问题输入的完整链路验证，不只看单个函数测试。

### 路径 A：本地开发模式（推荐）

适合日常开发和调试。数据库可用 SQLite 默认路径，也可只用 Docker 启动 PostgreSQL。

1. 进入项目根目录：

   ```bash
   cd /root/Finance
   ```

2. 准备环境文件。真实密钥只能写本地 `.env`，不得提交：

   ```bash
   test -f Financial-MCP-Agent/.env || cp Financial-MCP-Agent/.env.example Financial-MCP-Agent/.env
   test -f backend/.env || cp backend/.env.example backend/.env
   ```

3. 如需 PostgreSQL/pgvector，先启动数据库和 pgAdmin：

   ```bash
   cd /root/Finance/docker
   docker compose up -d postgres pgadmin
   docker compose ps
   docker exec finance_postgres pg_isready -U finance -d finance_db
   cd /root/Finance
   ```

   如果只是快速验证默认 SQLite 路径，可以跳过此步。

4. 激活 Python 虚拟环境并确认关键依赖。优先使用项目已有 `.venv`；若环境缺依赖，再按 `backend/requirements.txt` 补齐：

   ```bash
   cd /root/Finance
   source .venv/bin/activate
   python -c "import pydantic; print('pydantic', pydantic.__version__)"
   python -c "import fastapi, sqlalchemy; print('backend deps ok')"
   ```

   如果 `.venv` 不可用，先说明环境问题，再选择：

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -r backend/requirements.txt
   ```

5. 启动后端服务。必须从 `/root/Finance` 根目录启动，避免 Agent 路径注入错误：

   ```bash
   cd /root/Finance
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

   期望看到类似日志：

   - `数据库初始化完成`
   - `trace runtime 初始化完成`
   - `预置登录账号已校准`
   - `应用启动完成`

6. 另开终端启动前端：

   ```bash
   cd /root/Finance/frontend
   npm install
   npm run dev -- --host 0.0.0.0
   ```

   前端默认端口是 `5173`，Vite 已将 `/api` 代理到 `http://localhost:8000`。

### 路径 B：全 Docker 模式

适合验证 Docker 构建、容器网络和生产构建形态。

```bash
cd /root/Finance/docker
docker compose up -d --build
docker compose ps
docker compose logs -f postgres backend frontend
```

健康检查：

```bash
curl -fsS http://localhost:8000/api/health
```

前端访问：

```text
http://localhost:5173
```

全 Docker 模式会使用 `docker/docker-compose.yml` 中的 `postgres`、`backend`、`frontend` 和 `pgadmin` 服务。不要手动修改 `frontend/dist/` 来修复 Docker 问题，应修源码或 Dockerfile/Compose 配置。

### 接口级冒烟测试

后端启动后，先做最小接口验收。

1. 健康检查：

   ```bash
   curl -fsS http://localhost:8000/api/health
   ```

2. 登录测试账号。启动时会幂等校准 `test1/test1` 和 `test2/test2`：

   ```bash
   LOGIN_JSON=$(curl -sS -X POST http://localhost:8000/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"test1","password":"test1"}')

   TOKEN=$(python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<< "$LOGIN_JSON")
   USER_ID=$(python -c 'import json,sys; print(json.load(sys.stdin)["user_id"])' <<< "$LOGIN_JSON")
   echo "$USER_ID"
   ```

3. 验证需要鉴权的接口：

   ```bash
   curl -fsS -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/auth/me"

   curl -fsS -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/chat/templates"

   curl -fsS -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/chat/sop-skills"
   ```

4. 同步对话接口冒烟。该请求会走后端对话主链路；如果 LLM/Tushare 凭证缺失，应检查是否有明确降级或错误信息：

   ```bash
   curl -sS -X POST http://localhost:8000/api/chat/message \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $TOKEN" \
     -d "{\"user_id\":\"$USER_ID\",\"message\":\"贵州茅台今天怎么样\"}"
   ```

5. 报告接口冒烟。报告是异步任务，先拿 `task_id`，再轮询状态：

   ```bash
   REPORT_JSON=$(curl -sS -X POST http://localhost:8000/api/report/generate \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $TOKEN" \
     -d "{\"user_id\":\"$USER_ID\",\"command\":\"帮我生成一份贵州茅台的简要投研报告\"}")

   TASK_ID=$(python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])' <<< "$REPORT_JSON")
   curl -sS -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/report/status/$TASK_ID"
   ```

### 前端端到端手动验收

前后端都启动后，用浏览器访问：

```text
http://localhost:5173
```

最低验收路径：

1. 使用 `test1/test1` 登录。
2. 进入对话模式。
3. 发送普通问题：`你好，介绍一下你能做什么`。
4. 发送实时金融问题：`贵州茅台今天怎么样`。
5. 发送 Skill 场景问题：`ETF 和 LOF 有什么区别`、`华安黄金 ETF 和博时黄金 ETF 哪个适合我`。
6. 检查是否出现会话、流式输出、route summary、plan preview、verification 或明确降级提示。
7. 进入报告模式，尝试生成一份简要报告，并检查任务进度、报告预览、历史记录。
8. 查看后端终端或日志，确认没有未处理异常、鉴权错误循环、WebSocket 断连循环或工具调用静默失败。

### 端到端验收失败时的处理规范

失败时不要直接大改。必须记录：

- 使用的是本地开发模式还是全 Docker 模式。
- 后端、前端、Docker 分别执行了什么命令。
- 第一个失败点是什么。
- 对应日志关键行是什么。
- 是环境/凭证问题、接口契约问题、前端状态问题、Agent 工具问题，还是数据库问题。
- 最小修复方案是什么。

常见判断：

- `401`：先检查是否登录、是否带 `Authorization: Bearer $TOKEN`。
- `422`：优先检查请求字段是否与 `backend/schemas/` 和 `frontend/src/api/index.ts` 一致。
- `500`：查看后端异常栈，先定位 router/service/DB/Agent/tool 哪一层。
- WebSocket 无输出：检查 `/api` 代理、鉴权、`/api/chat/stream` 日志和前端 `useChat.ts`。
- LLM/Tushare 失败：检查 `Financial-MCP-Agent/.env`、`backend/.env`、feature flag、trace artifact 和降级提示。

## 测试与验收

优先运行与改动相关的最小测试，不要无目的跑超大范围命令。

常用验证命令示例：

- 后端/Agent 单测：`pytest <相关测试文件> -q`
- eval smoke：`pytest tests/evals -m 'eval_smoke or not eval_smoke' -q`
- working state 相关脚本：`PYTHONPATH=/root/Finance .venv/bin/python backend/test_working_state_store.py`
- 前端构建或检查：在 `frontend/` 下使用项目已有 npm 脚本，先查看 `package.json` 再运行。
- 本地后端启动：`python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`
- 本地前端启动：`cd frontend && npm run dev -- --host 0.0.0.0`

如果测试无法运行，必须说明：

- 执行了什么命令
- 失败日志的关键错误
- 是代码问题还是环境问题
- 哪些验证已经完成
- 建议用户如何手动验收

## Debug 规则

遇到 bug 时先定位，不要直接改。

排查顺序：

1. 复现输入、期望结果、实际结果。
2. 查看最近 `git diff` 和相关日志。
3. 按层拆解：前端 UI/API、router、schema、service、DB、Agent route、planner、tool、memory、LLM、trace。
4. 提出 1-3 个可验证假设。
5. 做最小修复。
6. 补回归测试或手动复现步骤。
7. 看 diff，确认没有无关改动。

Agent/RAG 问题不要只改 prompt。必须检查：

- 当前时间和交易日是否注入。
- 股票/基金/行业实体是否解析正确。
- 是否选对 Skill 或工具。
- 工具参数和返回时间戳是否正确。
- trace 中是否记录降级、空结果或异常。
- 最终回答是否受证据约束。

## 安全规则

- `.env`、私钥、证书、生产 token 不得提交。
- 日志不得打印完整 token、手机号、身份证、银行卡号、API key。
- 所有外部输入必须经过 schema 校验或等价校验。
- 用户权限必须显式判断，不要只靠前端隐藏入口。
- 高风险操作，如删除数据、改鉴权、改迁移、改生产配置、批量重构，必须先说明风险并等待用户确认。

## 注释与文档

- 代码注释优先使用中文。
- 注释解释“为什么这样做”和“防什么问题”，不要机械复述代码。
- 复杂业务流程、降级策略、兼容层、迁移逻辑必须补充简洁注释。
- 用户可见文档和交付说明要照顾初学者，解释专业名词并给出具体例子。
- 复杂功能完成后，必要时补充 `docs/` 下的运行、排障或验收说明。

## 交付前自检

完成前必须自检：

- 是否对齐用户需求和 `docs/项目描述.md`。
- 是否只改了必要文件。
- 是否保护了现有行为和兼容路径。
- API schema、TS 类型、DB 字段、Agent state 是否全链路一致。
- 是否有错误处理、日志、trace 或降级。
- 是否运行了相关测试或给出无法运行的原因。
- 是否明确说明修改内容、验证结果、剩余风险。

最终回复应简洁说明：

- 修改了哪些文件。
- 核心改动是什么。
- 运行了哪些验证。
- 未验证项或风险是什么。
