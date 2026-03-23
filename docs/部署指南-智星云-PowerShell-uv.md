# 智星云 + PowerShell + uv 部署指南（基础功能）

> **若你使用 Linux 或 WSL**，请改用 **《部署指南-智星云-WSL-uv.md》**，其中为 bash 命令与 Linux 路径，并包含 Qwen（qwen3.5-flash）与部署前核查清单。

本指南面向**完全零基础**用户，在**智星云云主机**上使用 **PowerShell** 和 **uv** 完成部署，**只使用 Qwen API**（不使用 FinR1、不使用新闻情感/风险小模型），最终实现：**输入一只股票，得到一份最新交易分析报告**。

---

## 一、你的需求复述与约定

### 1.1 需求复述

- **环境**：智星云云主机，使用 **PowerShell** 终端，使用 **uv** 做安装与依赖管理。
- **要做的**：创建虚拟环境 → 完成 API 配置（使用 **Qwen 的 API_KEY**）→ 按步骤完成 **MCP 部署**。
- **范围**：
  - **不使用** FinR1 本地模型；
  - **不使用** 新闻情感/风险小模型（统一用 API 获取信息）；
  - **目标**：能跑通「获取一个股票的最新交易报告」（例如：输入「帮我看看茅台(600519)这只股票值得投资吗」，在 `Financial-MCP-Agent/reports` 下生成 Markdown 报告）。

### 1.2 需要你事先准备或确认的信息

| 项目 | 说明 | 你需要做的 |
|------|------|------------|
| **项目路径** | 智星云上 Finance 项目所在目录 | 确认实际路径，例如 `D:\Finance` 或 `C:\Users\你的用户名\Finance`，后文用 `{项目根目录}` 表示，每一步会提醒你替换。 |
| **Python 版本** | 建议 3.10 或 3.11 | 在 PowerShell 中执行 `python --version` 确认已安装；若未安装，请先在智星云实例中安装 Python。 |
| **Qwen API** | 通义千问（阿里云 DashScope）OpenAI 兼容 API | 在阿里云控制台开通 DashScope、创建 API-KEY；记下 **API Key**、**Base URL**、**模型名称**（如 qwen-plus）。 |
| **网络** | 智星云主机需能访问外网 | 能访问阿里云 API、PyPI（若 PyPI 慢可改用国内镜像）。 |

### 1.3 若以下与你的情况不符，请先做决策

- **智星云系统是 Windows 还是 Linux？**  
  本指南按 **Windows + PowerShell** 编写。若是 Linux，请改用 `bash`，并把所有路径、激活命令改为 Linux 写法（例如 `source .venv/bin/activate`）。
- **是否一定用 uv 创建/管理虚拟环境？**  
  是则严格按下面「用 uv 创建虚拟环境」执行；若你更习惯只用 `python -m venv`，也可以改用 `python -m venv .venv`，再在激活后 `pip install -r requirements.txt`，其余步骤不变。
- **Qwen 的 Base URL 和模型名**  
  使用**阿里云 DashScope 兼容模式**时一般为：  
  - Base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`  
  - 模型：`qwen-turbo` / `qwen-plus` / `qwen-max` 等（以你在控制台看到的为准）。

---

## 二、部署步骤总览

1. 安装 uv（PowerShell）
2. 进入项目根目录并创建虚拟环境（uv）
3. 安装项目依赖（根目录 + 确认 MCP 服务依赖）
4. 配置 API（.env，Qwen）
5. 配置 MCP 服务器路径（mcp_config.py）
6. 测试 MCP 服务（可选但推荐）
7. 运行 Agent 并生成一只股票的报告
8. 校验与常见问题

以下每一步都给出**可直接复制到 PowerShell 执行的命令**（需把 `{项目根目录}` 换成你的实际路径）。

---

## 三、逐步操作说明

### 步骤 1：安装 uv（PowerShell）

在 **PowerShell** 中执行（若已安装 uv 可跳过）：

```powershell
# 使用官方推荐方式安装 uv（需允许脚本执行）
irm https://astral.sh/uv/install.ps1 | iex
```

安装完成后**关闭并重新打开 PowerShell**，然后验证：

```powershell
uv --version
```

能看到版本号即表示安装成功。

---

### 步骤 2：进入项目根目录并创建虚拟环境

假设你的项目在 `D:\Finance`（请替换为你的实际路径）：

```powershell
# 进入项目根目录（请把 D:\Finance 改成你的实际路径）
cd D:\Finance
```

使用 uv 创建虚拟环境（环境目录名为 `.venv`）：

```powershell
uv venv .venv
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

若出现「无法加载，因为在此系统上禁止运行脚本」的报错，请先执行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

然后再执行一次激活命令。激活成功后，命令行前会出现 `(.venv)`。

---

### 步骤 3：安装项目依赖

**3.1 安装根目录依赖（Financial-MCP-Agent 和运行主程序所需）**

在**已激活** `.venv` 的前提下，仍在项目根目录 `D:\Finance` 下执行：

```powershell
# 确保在项目根目录且已激活 .venv
uv pip install -r requirements.txt
```

若 PyPI 较慢，可使用国内镜像：

```powershell
uv pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**3.2 设置 PYTHONPATH（重要）**

主程序需要把项目根目录加入 Python 路径，否则导入会报错。**每次新开 PowerShell 并激活虚拟环境后都要执行一次**：

```powershell
$env:PYTHONPATH = (Get-Location).Path
```

（若你一直只在当前终端里操作，执行一次即可。）

**3.3 MCP 服务（a-share）依赖**

MCP 服务由 `uv run --directory ...` 在子进程中启动，会使用 **a-share-mcp-is-just-i-need** 目录下的 `pyproject.toml` 自动安装其依赖（mcp、baostock、pandas 等），**无需你在本步骤手动再装 a-share 的包**。只要后面「MCP 路径」配对即可。

---

### 步骤 4：配置 API（Qwen）

**4.1 复制并编辑 .env**

进入 Agent 目录并复制示例配置：

```powershell
cd D:\Finance\Financial-MCP-Agent
Copy-Item .env.example .env
```

用记事本或 VS Code 打开 `Financial-MCP-Agent\.env`，按你的 Qwen API 信息修改为类似下面（**不要提交到 Git**）：

```env
OPENAI_COMPATIBLE_API_KEY=sk-你的Qwen_API_KEY
OPENAI_COMPATIBLE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_COMPATIBLE_MODEL=qwen-plus
USE_LOCAL_MODEL=api
```

说明：

- `OPENAI_COMPATIBLE_API_KEY`：在阿里云 DashScope 控制台创建的 API Key（通义千问）。
- `OPENAI_COMPATIBLE_BASE_URL`：如上为阿里云兼容模式地址；若你用其他兼容 Qwen 的服务，改成对应 Base URL。
- `OPENAI_COMPATIBLE_MODEL`：模型名，如 `qwen-turbo`、`qwen-plus`、`qwen-max` 等，以控制台为准。
- `USE_LOCAL_MODEL=api`：表示**全部使用 API**，不使用 FinR1，保持为 `api` 即可。

保存后返回项目根目录，方便后续命令统一从根目录执行：

```powershell
cd D:\Finance
```

---

### 步骤 5：配置 MCP 服务器路径（关键）

主程序会通过「MCP 客户端」调用 **a-share-mcp-is-just-i-need** 提供的 A 股数据工具（K 线、财报、新闻等）。必须让主程序知道 a-share 的**绝对路径**。

**5.1 用记事本或 VS Code 打开：**

```
D:\Finance\Financial-MCP-Agent\src\tools\mcp_config.py
```

（若你的项目不在 D:\Finance，请改成你的 `{项目根目录}\Financial-MCP-Agent\src\tools\mcp_config.py`。）

**5.2 修改 `--directory` 的路径**

找到类似下面这一段：

```python
SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            r"/root/code/Finance/a-share-mcp-is-just-i-need",  # 改这里
            "python",
            "mcp_server.py"
        ],
        "transport": "stdio",
    }
}
```

把 `r"/root/code/Finance/a-share-mcp-is-just-i-need"` 改成你机器上的**实际路径**，例如（注意使用 `r"..."` 或反斜杠转义）：

```python
r"D:\Finance\a-share-mcp-is-just-i-need"
```

保存后，MCP 部署配置即完成。主程序启动时会用 `uv run --directory 你填的路径 python mcp_server.py` 拉起 MCP 服务。

---

### 步骤 6：测试 MCP 服务（推荐）

在**项目根目录**、且**已激活 .venv 并设置过 PYTHONPATH** 的前提下，可先单独测一下 a-share 的 Baostock 是否正常（MCP 会用到 Baostock 取 A 股数据）：

```powershell
cd D:\Finance\a-share-mcp-is-just-i-need
uv run python test_baostock.py
```

若输出里没有报错、能看到 Baostock 相关成功信息，说明 MCP 所需的数据环境正常。再回到根目录：

```powershell
cd D:\Finance
```

（若智星云网络导致 Baostock 偶发超时，可多试一次；不影响后面「生成报告」的主流程。）

---

### 步骤 7：运行 Agent 并生成一只股票的报告

在**项目根目录**、**已激活 .venv**、且**已设置 PYTHONPATH** 的前提下执行：

```powershell
$env:PYTHONPATH = (Get-Location).Path
cd D:\Finance\Financial-MCP-Agent
python src/main.py --command "帮我看看茅台(600519)这只股票值得投资吗"
```

- 第一次运行时会拉取 a-share 的依赖（uv 在 `--directory` 下创建环境并安装），可能稍慢。
- 若一切正常，会依次执行：基本面、技术面、估值、新闻四个分析 Agent，最后汇总成报告。

报告会保存在：

```
D:\Finance\Financial-MCP-Agent\reports\
```

目录下会多出一个带时间戳的 Markdown 文件，即「该股票的最新交易分析报告」。

---

### 步骤 8：校验与常见问题

**8.1 快速校验清单**

- [ ] 已用 uv 创建并激活 `.venv`，且 `uv pip install -r requirements.txt` 无报错。
- [ ] 已设置 `PYTHONPATH` 为项目根目录（当前终端已执行过 `$env:PYTHONPATH = (Get-Location).Path`）。
- [ ] `Financial-MCP-Agent\.env` 中已填写 Qwen 的 API Key、Base URL、Model，且 `USE_LOCAL_MODEL=api`。
- [ ] `Financial-MCP-Agent\src\tools\mcp_config.py` 中 `--directory` 已改为你本机的 `a-share-mcp-is-just-i-need` 绝对路径。
- [ ] 已成功执行一次 `python src/main.py --command "帮我看看茅台(600519)这只股票值得投资吗"`，且 `reports` 下生成了报告。

**8.2 常见报错与处理**

| 现象 | 可能原因 | 处理办法 |
|------|----------|----------|
| 找不到模块（如 `src.xxx`、`langgraph`） | 未激活 .venv 或未设 PYTHONPATH | 重新激活 `.venv`，并在项目根执行 `$env:PYTHONPATH = (Get-Location).Path`，再从 `Financial-MCP-Agent` 下运行 `python src/main.py ...`。 |
| OPENAI_COMPATIBLE_API_KEY not found | .env 未生效或未复制 | 确认在 `Financial-MCP-Agent` 目录下有 `.env` 文件，且 Key/URL/Model 填写正确；主程序是从 `Financial-MCP-Agent` 启动的，会读该目录下的 .env。 |
| MCP 工具加载失败 / No tools loaded | MCP 路径错误或 uv 未找到 | 检查 `mcp_config.py` 里 `--directory` 是否为 `a-share-mcp-is-just-i-need` 的**绝对路径**；确认命令行中 `uv` 可用（`uv --version`）。 |
| 新闻分析里出现「模型未加载」 | 未部署新闻情感/风险小模型 | 符合预期：当前方案**不使用**本地小模型，新闻仍会返回标题/摘要/链接，仅风险与情感两栏显示为「模型未加载」或类似提示，不影响报告生成。 |

**8.3 不使用 FinR1、不使用新闻小模型的说明**

- **FinR1**：`.env` 中 `USE_LOCAL_MODEL=api` 表示汇总阶段也用 Qwen API，不会加载 FinR1。
- **新闻情感/风险小模型**：a-share 的新闻爬虫在「未配置或路径不存在」时会自动跳过加载风险/情感模型，仅返回爬到的新闻内容，风险/情感显示为「模型未加载」，**不影响**「获取一只股票的最新交易报告」这一基础功能。

---

## 四、MCP 部署说明（小结）

- **MCP 是什么**：Model Context Protocol，主程序通过它调用「a-share-mcp-is-just-i-need」里提供的工具（查 K 线、财报、指数、新闻等）。
- **部署要点**：
  1. 在 **Financial-MCP-Agent** 的 **mcp_config.py** 中，把 `--directory` 配成你机器上 **a-share-mcp-is-just-i-need** 的**绝对路径**。
  2. 主程序用 **uv** 在该目录下执行 `uv run ... python mcp_server.py`，uv 会根据 a-share 目录下的 **pyproject.toml** 自动准备依赖并启动 MCP 服务。
  3. 不需要单独再为 a-share 创建虚拟环境；也不需要配置 FinR1 或新闻风险/情感模型路径，即可完成「获取一个股票的最新交易报告」。

按上述步骤做完后，你应能在智星云上用 PowerShell + uv 稳定跑通：**输入一只股票 → 得到一份基于 Qwen API 与 A 股数据的最新交易报告**。若某一步报错，可把完整报错信息与执行到的步骤号发出来，便于进一步排查。
