# 金融项目一键上手指南（Autodl + Cursor + GPU）

本指南整合了安装.md的全部要求与指令，并补充了 Autodl 云端 GPU 环境创建、在本地 Cursor 通过 SSH 远程开发、将项目上传到远端、以及按步骤完成依赖安装、MCP 配置、模型下载/训练、测试与常见问题排查的一站式流程。面向初学者，逐步执行即可。

---

## 0. 目录结构约定

建议在远端统一使用以下路径（持久盘，关机不丢数据）：
- 项目根目录：`/root/autodl-tmp/Finance`
- 本地 FinR1 模型：`/root/autodl-tmp/Finance/FinR1`
- Qwen 模型与数据集：`/root/autodl-tmp/Finance/<...>`（按需）

---

## 1. 在 Autodl 创建 GPU 实例

1) 登录 Autodl 控制台 → 创建实例。
- GPU：建议 A100/4090（≥24GB 显存）
- 镜像：带 PyTorch/CUDA 的官方镜像（如 PyTorch 2.x + CUDA 11.8）
- 勾选开启 JupyterLab/SSH（平台默认已开）

2) 成本建议：不使用时“停止实例”以避免计费；数据放在 `/root/autodl-tmp` 持久目录。

---

## 2. 在 Cursor 中配置 SSH 远程开发

1) 本地（Windows PowerShell）生成 SSH 密钥：
```powershell
ssh-keygen -t ed25519 -C "your_email@example.com"
# 默认保存在 C:\Users\你的用户名\.ssh\
```
查看并复制公钥：
```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

2) 在 Autodl 控制台添加 SSH 公钥（或在实例 `~/.ssh/authorized_keys` 追加）。

3) 可选：创建 SSH 配置 `C:\Users\你的用户名\.ssh\config`：
```
Host autodl
    HostName <你的Autodl公网IP>
    User root
    Port 22
    IdentityFile C:\Users\你的用户名\.ssh\id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 120
```
测试：
```powershell
ssh autodl
# 或：ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@<IP>
```

4) 在 Cursor 中选择“Remote via SSH”→ 选择 `autodl` → 选择远端目录 `/root/autodl-tmp/Finance` 打开即可远程开发。

### 2.5（可选）使用 VS Code Remote-SSH 连接
如果你使用 VS Code 而非 Cursor，步骤类似：
- 安装扩展：Remote - SSH
- 按上述 2.1~2.3 完成本地密钥与 `~/.ssh/config` 配置
- VS Code 左下角点击绿色><图标 → Remote-SSH: Connect to Host… → 选择 `autodl`
- 首次连接选择 Linux，登录后 File → Open Folder… → 选择 `/root/autodl-tmp/Finance`
- 之后可直接在 VS Code 中编辑、终端运行、Git 提交

---

## 3. 将项目上传到 Autodl（三选一）

- 方法A：JupyterLab 网页上传（最简单）
  1. 本地把项目打包为 zip 或 tar.gz。
     - Zip（PowerShell）：
       ```powershell
       Compress-Archive -Force -Path D:\finance_agent\Finance -DestinationPath D:\Finance.zip
       ```
     - Tar.gz（更稳）：
       ```powershell
       tar -czf D:\Finance.tar.gz -C D:\finance_agent Finance
       ```
  2. 在 JupyterLab 左侧文件树进入 `/root/autodl-tmp/`，点击上传图标，选择压缩包并等待完成。
  3. 右侧终端解压：
     ```bash
     cd /root/autodl-tmp
     unzip Finance.zip -d /root/autodl-tmp/ || true
     # 或
     tar -xzf Finance.tar.gz
     ```
  4. 验证：
     ```bash
     ls -la /root/autodl-tmp/Finance
     ```

- 方法B：SCP 直传（需要可 SSH）
  ```powershell
  scp -r D:\finance_agent\Finance root@<IP>:/root/autodl-tmp/
  ```

- 方法C：Git 仓库克隆
  ```bash
  cd /root/autodl-tmp
  git clone <你的仓库地址> Finance
  ```

如遇“End-of-central-directory signature not found”说明 zip 损坏或未传完，请删除重传：
```bash
rm -f /root/autodl-tmp/Finance.zip /root/autodl-tmp/Finance.tar.gz
```

---

## 3.1 后续代码更新与同步（强烈推荐以下方式）

- 方式A：远端直接编辑（最简单）
  - 通过 Cursor/VS Code Remote-SSH 打开远端 `/root/autodl-tmp/Finance`
  - 直接改文件、在远端终端运行和调试；无需再次上传压缩包

- 方式B：使用 Git（团队协作/版本管理最佳）
  - 在本地提交并推送：
    ```bash
    git add -A
    git commit -m "feat: update code"
    git push origin <你的分支>
    ```
  - 远端拉取更新：
    ```bash
    cd /root/autodl-tmp/Finance
    git pull
    ```

- 方式C：单文件小改动用 scp
  ```powershell
  scp D:\finance_agent\Finance\path\to\file.py root@<IP>:/root/autodl-tmp/Finance/path/to/file.py
  ```

- 依赖变更（requirements.txt 改动后）
  ```bash
  source /root/autodl-tmp/Finance/finance_agent_env/bin/activate
  pip install -r /root/autodl-tmp/Finance/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
  ```

- 环境变量或配置变更
  - `.env` 变更后直接保存生效；若有后台常驻进程，需重启对应进程/服务

---

## 4. 严格按安装.md执行（本地/远端通用）

以下步骤完全对应 `Finance/安装.md` 的内容与指令。

### 4.1 安装依赖
```bash
cd /root/autodl-tmp/Finance
python -m venv finance_agent_env
source finance_agent_env/bin/activate
export PYTHONPATH=./                   # 把当前目录加入 Python 的包搜索路径
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

Windows PowerShell（若在本地）：
```powershell
python -m venv finance_agent_env
.\finance_agent_env\Scripts\Activate.ps1
$env:PYTHONPATH = "."
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 4.2 设置 API
项目支持两种模式：API 调用大模型 和 本地 FinR1 模型。
> 注意：目前只有 Summary Agent 可以使用本地 FinR1，其余4个 Agent 仍依赖 API 调用，所以无论哪种模式，都必须配置 API_KEY。

按安装.md：
```bash
cd Financial-MCP-Agent/                         # 进入本项目的目录
cp .env.example .env                            # 把示例配置文件复制为 .env
```
编辑 `.env`：
```
OPENAI_COMPATIBLE_API_KEY=your_api_key
OPENAI_COMPATIBLE_BASE_URL=your_base_url
OPENAI_COMPATIBLE_MODEL=your_model
USE_LOCAL_MODEL=api  # api 模式；如使用本地 FinR1 切为 local
```

### 4.3 配置 MCP 服务器路径
编辑 `Financial-MCP-Agent/src/tools/mcp_config.py`，将 `--directory` 指向你的 `a-share-mcp-is-just-i-need` 真实路径：
```python
SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            r"/root/autodl-tmp/Finance/a-share-mcp-is-just-i-need",  # 修改为你的实际路径
            "python",
            "mcp_server.py"
        ],
        "transport": "stdio",
    }
}
```

### 4.4 训练风险/情感模型（可选，GPU）
安装.md说明：默认使用 Qwen3-8B 与指定数据集训练两个模型：
- 风险分析：`test_qwen_risk.py`
- 情感分析：`test_qwen_sentiment.py`

数据集（安装.md）：
- 风险：`https://huggingface.co/datasets/benstaf/risk_nasdaq`
- 情感：`https://huggingface.co/datasets/benstaf/nasdaq_news_sentiment`

准备（可选）：
```bash
# 若需 GPU 版 torch（以 CUDA 11.8 为例）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install transformers accelerate bitsandbytes -i https://mirrors.aliyun.com/pypi/simple/
```

训练前请在 `train_qwen_risk.py`、`train_qwen_sentiment.py` 中修改：
- Qwen 模型路径（本地或远程）
- 训练数据集路径

若无 GPU 或不训练：可按安装.md在 `a-share-mcp-is-just-i-need/src/baostock_data_source.py` 注释风险与情感相关代码以跳过。

执行：
```bash
cd /root/autodl-tmp/Finance
python train_qwen_risk.py
python train_qwen_sentiment.py
```

### 4.5 测试 MCP 工具功能
```bash
cd /root/autodl-tmp/Finance/a-share-mcp-is-just-i-need
pip install baostock -i https://mirrors.aliyun.com/pypi/simple/
python test_baostock.py
```

### 4.6 测试 Agent 功能（安装.md 第6步）
```bash
cd /root/autodl-tmp/Finance/Financial-MCP-Agent
python src/main.py --command "帮我看看茅台(600519)这只股票值得投资吗"
```
生成的 Markdown 报告在 `Financial-MCP-Agent/reports`。

---

## 5. 使用本地 FinR1（仅 Summary Agent 支持）

安装.md指出：如需本地 FinR1，请设置 `USE_LOCAL_MODEL=local` 并自行下载 `https://huggingface.co/SUFE-AIFLM-Lab/Fin-R1`（约 7B）。

### 5.1 下载 FinR1（镜像更稳）
```bash
export HF_ENDPOINT=https://hf-mirror.com
cd /root/autodl-tmp/Finance
git lfs install
git clone https://hf-mirror.com/SUFE-AIFLM-Lab/Fin-R1 FinR1
```
若受限，可用缓存下载脚本（示例）：
```python
# /root/autodl-tmp/Finance/download_finr1.py
import os
from transformers import AutoTokenizer, AutoModelForCausalLM
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
name = "SUFE-AIFLM-Lab/Fin-R1"
cache = "/root/autodl-tmp/Finance/FinR1"
AutoTokenizer.from_pretrained(name, cache_dir=cache, trust_remote_code=True)
AutoModelForCausalLM.from_pretrained(name, cache_dir=cache, trust_remote_code=True)
print("FinR1 cached.")
```
运行：
```bash
python /root/autodl-tmp/Finance/download_finr1.py
```

### 5.2 切换为本地模式并设置路径
- `.env`：`USE_LOCAL_MODEL=local`
- `Financial-MCP-Agent/src/agents/summary_agent.py` 默认加载路径需要指向 `/root/autodl-tmp/Finance/FinR1`（若代码内有硬编码路径，请据实调整为你的路径）。

随后重复 4.6 的运行命令进行验证。

---

## 6. GPU 开启与监控

- 实例使用时启动，完毕后停止以节省费用。
- 运行中实时监控：
```bash
nvidia-smi
watch -n 1 nvidia-smi
```
- 显存不足建议：更大显存机型、降低 batch/sequence、或使用 8bit/4bit 量化（进阶）。

---

## 7. 常见问题排查

- 压缩包解压报错 `End-of-central-directory signature not found`
  - 说明 zip 损坏或未传完：删除后重新打包上传，或改用 `scp`/`git clone`。

- 无法下载 HuggingFace 模型
  - 设置镜像：`export HF_ENDPOINT=https://hf-mirror.com`
  - 检查磁盘空间（FinR1 建议 ≥15GB 剩余）。

- API 模式报错
  - `.env` 中 `OPENAI_COMPATIBLE_API_KEY`、`OPENAI_COMPATIBLE_BASE_URL`、`OPENAI_COMPATIBLE_MODEL` 三项必须齐全。

- MCP 工具路径错误
  - `src/tools/mcp_config.py` 的 `--directory` 路径需与实际一致。

---

## 8. 快速校验清单（你应当完成了）

- [ ] `/root/autodl-tmp/Finance` 已就位（文件完整）
- [ ] 创建并激活了虚拟环境，安装了依赖（阿里云镜像）
- [ ] `.env` 已复制并填写 API 配置，选择 `USE_LOCAL_MODEL=api` 或 `local`
- [ ] `mcp_config.py` 已正确指向 `a-share-mcp-is-just-i-need`
- [ ]（可选）FinR1 已下载到 `/root/autodl-tmp/Finance/FinR1` 且路径已配置
- [ ] `test_baostock.py` 通过
- [ ] `python src/main.py --command "帮我看看茅台(600519)这只股票值得投资吗"` 正常生成报告

完成！你已经可以在 Autodl 上用 GPU 跑完整流程，并在 Cursor 中远程开发与调试。
