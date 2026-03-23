# 智星云 + Linux WSL + uv 部署指南（基础功能）

本指南面向**完全零基础**用户，在**智星云云主机**上使用 **Linux WSL** 和 **uv** 完成部署，**只使用 Qwen API**（不使用 FinR1、不使用新闻情感/风险小模型），最终实现：**输入一只股票，得到一份最新交易分析报告**。

---

## 一、环境与约定

### 1.1 适用环境

- **系统**：Linux（WSL 或智星云 Linux 实例）
- **终端**：bash（在 WSL 或 Linux 中打开终端）
- **包管理**：uv（创建虚拟环境、安装依赖）
- **项目路径**：后文用 **`{项目根目录}`** 表示，请替换为你的实际路径，例如：
  - `/root/Finance`
  - `/home/你的用户名/Finance`

### 1.2 需要你事先准备的信息

| 项目 | 说明 |
|------|------|
| **项目根目录** | Finance 项目在机器上的绝对路径，如 `/root/Finance`。 |
| **Python** | 建议 3.10 或 3.11，终端执行 `python3 --version` 确认。 |
| **Qwen API** | 阿里云 DashScope 兼容 API：API Key、Base URL、模型名（如 `qwen3.5-flash`）。 |
| **网络** | 能访问阿里云 API 与 PyPI（慢时可改用国内镜像）。 |

### 1.3 Qwen（阿里云 DashScope）示例配置

- **Base URL**：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- **模型名**：如 `qwen3.5-flash`、`qwen-plus`、`qwen-turbo` 等（以控制台为准）
- **API Key**：在阿里云 DashScope 控制台创建，填入 `.env` 中的 `OPENAI_COMPATIBLE_API_KEY`（**不要提交到 Git**）

---

## 二、部署步骤总览

1. 安装 uv（Linux/WSL）
2. 进入项目根目录并创建虚拟环境（uv）
3. 安装项目依赖
4. 配置 API（.env，Qwen）
5. 配置 MCP 服务器路径（mcp_config.py）
6. 部署前核查（清单）
7. 测试 MCP 服务（可选）
8. 运行 Agent 并生成一只股票的报告
9. 校验与常见问题

以下命令均在 **bash** 中执行，请将 **`{项目根目录}`** 替换为你的实际路径（如 `/root/Finance`）。

---

## 三、逐步操作说明

### 步骤 1：安装 uv（Linux / WSL）

若已安装 uv（`uv --version` 能输出版本号）可跳过。任选下面一种方式即可。

**方式 A：用 curl 安装（需先有 curl）**

```bash
# 若没有 curl，先安装：sudo apt update && sudo apt install -y curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**方式 B：用 wget 安装（curl 不可用时）**

```bash
wget -qO- https://astral.sh/uv/install.sh | sh
```

**方式 C：用 pip 安装（系统已有 Python 和 pip 时）**

```bash
pip install uv
# 或使用 --user 仅当前用户：pip install --user uv
```

**方式 D：用 pipx 安装（推荐与系统 Python 隔离）**

```bash
pipx install uv
```

安装完成后，若终端里输入 `uv` 提示找不到命令，把 uv 所在目录加入 PATH：

```bash
# uv 通常安装在 ~/.local/bin
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

再验证：

```bash
uv --version
```

能看到版本号即表示成功。

---

### 步骤 2：进入项目根目录并创建虚拟环境

```bash
# 进入项目根目录（请把 {项目根目录} 换成你的实际路径，例如 /root/Finance）
cd {项目根目录}
```

使用 uv 创建虚拟环境（目录名为 `.venv`）：

```bash
uv venv .venv
```

激活虚拟环境：

```bash
source .venv/bin/activate
```

激活成功后，命令行前会出现 `(.venv)`。

---

### 步骤 3：安装项目依赖

在**已激活** `.venv`、且当前在**项目根目录**的前提下执行：

```bash
# 安装根目录依赖（主程序与 Agent 所需）
uv pip install -r requirements.txt
```

若 PyPI 较慢，可使用国内镜像：

```bash
uv pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**设置 PYTHONPATH（重要）**  
主程序需要把项目根目录加入 Python 路径。**每次新开终端并激活虚拟环境后都要执行一次**：

```bash
export PYTHONPATH="${PWD}"
```

（若一直只在当前终端操作，执行一次即可。）

**说明**：MCP 服务（a-share）由主程序通过 `uv run --directory ...` 在子进程中启动，会按 a-share 目录下的 `pyproject.toml` 自动安装其依赖，无需在本步骤单独安装 a-share 的包。

---

### 步骤 4：配置 API（Qwen）

进入 Agent 目录并复制示例配置：

```bash
cd {项目根目录}/Financial-MCP-Agent
cp .env.example .env
```

编辑 `.env` 文件（可用 `nano .env` 或 `vim .env` 或 VS Code）：

```env
OPENAI_COMPATIBLE_API_KEY=你的Qwen_API_Key
OPENAI_COMPATIBLE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_COMPATIBLE_MODEL=qwen3.5-flash
USE_LOCAL_MODEL=api
```

- 将 `你的Qwen_API_Key` 替换为你在阿里云 DashScope 控制台创建的 API Key。
- 若使用其他模型，将 `OPENAI_COMPATIBLE_MODEL` 改为对应模型名（如 `qwen-plus`）。
- `USE_LOCAL_MODEL=api` 表示全部使用 API，不使用 FinR1，保持即可。

保存后返回项目根目录：

```bash
cd {项目根目录}
```

---

### 步骤 5：配置 MCP 服务器路径（关键）

主程序通过 MCP 调用 **a-share-mcp-is-just-i-need** 提供的 A 股数据工具，必须配置 a-share 的**绝对路径**。

编辑文件：

```bash
# 将 {项目根目录} 换成你的实际路径
nano {项目根目录}/Financial-MCP-Agent/src/tools/mcp_config.py
```

找到 `--directory` 所在行，将其值改为你机器上 **a-share-mcp-is-just-i-need** 的**绝对路径**，例如：

- 若项目在 `/root/Finance`，则填写：`/root/Finance/a-share-mcp-is-just-i-need`
- 若项目在 `/home/你的用户名/Finance`，则填写：`/home/你的用户名/Finance/a-share-mcp-is-just-i-need`

修改后该段应类似（注意 Python 中路径用引号，无需 `r` 前缀也可）：

```python
SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            "/root/Finance/a-share-mcp-is-just-i-need",  # 改为你的实际绝对路径
            "python",
            "mcp_server.py"
        ],
        "transport": "stdio",
    }
}
```

保存退出后，MCP 配置即完成。

---

### 步骤 6：部署前核查（清单）

在运行主程序前，建议逐项确认以下内容，避免因缺文件或路径错误导致失败。

**6.1 目录与文件是否存在**

在项目根目录执行：

```bash
cd {项目根目录}

# 以下命令用于检查关键文件是否存在，无报错即表示存在
test -f requirements.txt && echo "OK: requirements.txt"
test -f Financial-MCP-Agent/.env.example && echo "OK: .env.example"
test -f Financial-MCP-Agent/.env && echo "OK: .env (已创建)"
test -f Financial-MCP-Agent/src/main.py && echo "OK: main.py"
test -f Financial-MCP-Agent/src/tools/mcp_config.py && echo "OK: mcp_config.py"
test -f a-share-mcp-is-just-i-need/pyproject.toml && echo "OK: a-share pyproject.toml"
test -f a-share-mcp-is-just-i-need/mcp_server.py && echo "OK: mcp_server.py"
test -d a-share-mcp-is-just-i-need/src && echo "OK: a-share src"
```

若某项未输出 `OK`，请检查路径或是否已复制 `.env.example` 为 `.env`。

**6.2 环境与命令**

```bash
# 确认虚拟环境已激活（命令行前应有 (.venv)）
which python
# 应指向项目根目录下的 .venv 内的 python

# 确认 uv 可用
uv --version

# 确认 PYTHONPATH 已设置（应输出项目根目录）
echo $PYTHONPATH
```

**6.3 .env 内容**

确认 `Financial-MCP-Agent/.env` 中已填写：

- `OPENAI_COMPATIBLE_API_KEY`（非空）
- `OPENAI_COMPATIBLE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `OPENAI_COMPATIBLE_MODEL=qwen3.5-flash`（或你使用的模型名）
- `USE_LOCAL_MODEL=api`

**6.4 mcp_config.py 路径**

确认 `Financial-MCP-Agent/src/tools/mcp_config.py` 中 `--directory` 的值为 **a-share-mcp-is-just-i-need** 的**绝对路径**，且该目录下存在 `mcp_server.py` 和 `pyproject.toml`。

全部通过后，再进行步骤 7、8。

---

### 步骤 7：测试 MCP 服务（可选但推荐）

在项目根目录、已激活 `.venv` 的前提下：

```bash
cd {项目根目录}/a-share-mcp-is-just-i-need
uv run python test_baostock.py
```

若无报错、能看到 Baostock 相关成功信息，说明 MCP 所需的数据环境正常。然后返回根目录：

```bash
cd {项目根目录}
```

（若因网络导致 Baostock 偶发超时，可重试；不影响后续生成报告。）

---

### 步骤 8：运行 Agent 并生成一只股票的报告

在**项目根目录**、**已激活 .venv**、且**已设置 PYTHONPATH** 的前提下执行：

```bash
export PYTHONPATH="${PWD}"
cd {项目根目录}/Financial-MCP-Agent
python src/main.py --command "帮我看看茅台(600519)这只股票值得投资吗"
```

- 首次运行时会通过 uv 在 a-share 目录下安装依赖，可能稍慢。
- 若正常，会依次执行基本面、技术面、估值、新闻分析，并生成汇总报告。

报告会保存在：

```
{项目根目录}/Financial-MCP-Agent/reports/
```

目录下会多出带时间戳的 Markdown 文件，即该股票的最新交易分析报告。

---

### 步骤 9：校验与常见问题

**9.1 快速校验清单**

- [ ] 已用 uv 创建并激活 `.venv`，且 `uv pip install -r requirements.txt` 无报错。
- [ ] 已执行 `export PYTHONPATH="${PWD}"`（当前终端有效）。
- [ ] `Financial-MCP-Agent/.env` 中已填写 Qwen API Key、Base URL、Model，且 `USE_LOCAL_MODEL=api`。
- [ ] `Financial-MCP-Agent/src/tools/mcp_config.py` 中 `--directory` 已改为 a-share 的**绝对路径**。
- [ ] 已成功执行一次 `python src/main.py --command "帮我看看茅台(600519)这只股票值得投资吗"`，且 `reports/` 下生成了报告。

**9.2 常见报错与处理**

| 现象 | 可能原因 | 处理办法 |
|------|----------|----------|
| 找不到模块（如 `src.xxx`、`langgraph`） | 未激活 .venv 或未设 PYTHONPATH | 重新执行 `source .venv/bin/activate` 和 `export PYTHONPATH="${PWD}"`，再从 `Financial-MCP-Agent` 下运行 `python src/main.py ...`。 |
| OPENAI_COMPATIBLE_API_KEY not found | .env 未生效或未复制 | 确认 `Financial-MCP-Agent/.env` 存在且 Key/URL/Model 正确；主程序从 `Financial-MCP-Agent` 启动，会读该目录下的 .env。 |
| MCP 工具加载失败 / No tools loaded | MCP 路径错误或 uv 未找到 | 检查 `mcp_config.py` 中 `--directory` 是否为 a-share 的**绝对路径**；确认终端中 `uv --version` 可用。 |
| 新闻分析里出现「模型未加载」 | 未部署新闻情感/风险小模型 | 符合预期：当前方案不使用本地小模型，新闻仍会返回标题/摘要/链接，不影响报告生成。 |

**9.3 不使用 FinR1、不使用新闻小模型的说明**

- **FinR1**：`.env` 中 `USE_LOCAL_MODEL=api` 表示汇总阶段也使用 Qwen API。
- **新闻情感/风险小模型**：a-share 在未配置或路径不存在时会自动跳过加载，仅返回新闻内容，风险/情感显示为「模型未加载」，不影响「获取一只股票的最新交易报告」。

---

## 四、MCP 部署说明（小结）

- **MCP**：主程序通过 Model Context Protocol 调用 a-share 提供的 A 股数据工具（K 线、财报、指数、新闻等）。
- **部署要点**：
  1. 在 **mcp_config.py** 中把 `--directory` 配成 **a-share-mcp-is-just-i-need** 的**绝对路径**（Linux 路径）。
  2. 主程序会用 **uv** 在该目录下执行 `uv run ... python mcp_server.py`，uv 会根据 a-share 的 **pyproject.toml** 自动安装依赖并启动 MCP 服务。
  3. 不需要单独为 a-share 创建虚拟环境，也不需要配置 FinR1 或新闻风险/情感模型路径。

按上述步骤并在**部署前核查**通过后，即可在智星云 Linux/WSL 上用 uv 稳定跑通：**输入一只股票 → 得到一份基于 Qwen API 与 A 股数据的最新交易报告**。若某一步报错，可把完整报错与执行到的步骤号发出来便于排查。

---

## 五、文档与代码同步说明

- 本部署指南已按 **Linux WSL + uv** 编写，并与当前仓库同步。
- **mcp_config.py** 默认路径为 `/root/Finance/a-share-mcp-is-just-i-need`，若项目不在 `/root/Finance`，请按步骤 5 修改为你的绝对路径。
- **.env.example** 已包含阿里云 DashScope 的 Base URL 与 `qwen3.5-flash` 示例，复制为 `.env` 后只需填入你的 API Key。
- 部署前核查（步骤 6）中的检查命令已在仓库中验证通过，关键文件与目录完整，可按清单逐项执行确保环境就绪。
