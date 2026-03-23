# 金融分析智能体系统开发指南

## 📚 项目概述

本指南将带你从零开始开发一个基于LangGraph的多智能体金融分析系统。这是一个实战项目，适合Python基础较弱的本科生学习如何进行工程化开发。

### 系统架构
```
用户查询 → 信息提取 → 并行分析（4个智能体） → 结果汇总 → 生成报告
                ↓              ↓                 ↓          ↓
            股票代码      基本面/技术/估值/新闻      总结      Markdown
```

### 技术栈
- **LangGraph**: 工作流编排框架
- **LangChain**: AI应用开发框架
- **MCP协议**: 工具集成协议
- **OpenAI API**: 大语言模型接口
- **异步编程**: async/await

---

## 🎯 开发前准备（第1-2天）

### 1. 环境准备

#### 1.1 安装Python环境
```bash
# 确保Python版本 >= 3.10
python --version

# 创建虚拟环境
python -m venv finance_agent_env

# 激活虚拟环境
# Windows:
finance_agent_env\Scripts\activate
# Linux/Mac:
source finance_agent_env/bin/activate
```

#### 1.2 安装依赖包
```bash
# 创建requirements.txt文件
pip install langgraph==0.6.6
pip install langchain-openai
pip install langchain-mcp-adapters
pip install python-dotenv
pip install pandas
pip install transformers
pip install torch
pip install peft
```

#### 1.3 准备API密钥
- 注册OpenAI兼容的API服务（如DeepSeek、通义千问等）
- 获取API Key和Base URL
- 准备MCP服务器（A股数据服务器）

### 2. 项目结构规划

```
Finance/Financial-MCP-Agent/
├── src/
│   ├── __init__.py
│   ├── main.py                    # 主入口
│   ├── agents/                    # 智能体模块
│   │   ├── __init__.py
│   │   ├── fundamental_agent.py   # 基本面分析
│   │   ├── technical_agent.py     # 技术分析
│   │   ├── value_agent.py         # 估值分析
│   │   ├── news_agent.py          # 新闻分析
│   │   └── summary_agent.py       # 总结智能体
│   ├── tools/                     # 工具模块
│   │   ├── __init__.py
│   │   ├── mcp_config.py         # MCP配置
│   │   └── mcp_client.py         # MCP客户端
│   └── utils/                     # 工具模块
│       ├── __init__.py
│       ├── state_definition.py    # 状态定义
│       ├── logging_config.py      # 日志配置
│       └── execution_logger.py    # 执行日志
├── logs/                          # 日志目录
├── reports/                       # 报告目录
├── .env                          # 环境变量
└── requirements.txt              # 依赖列表
```

### 3. 学习准备

#### 3.1 必备知识点
- Python基础：类、函数、异步编程（async/await）
- 类型注解：TypedDict、Annotated
- LangChain基础：消息类型、提示词模板
- LangGraph基础：StateGraph、节点、边

#### 3.2 推荐学习顺序
1. Python异步编程（async/await）
2. LangChain消息系统（BaseMessage、HumanMessage、AIMessage）
3. LangGraph状态管理（StateGraph、AgentState）
4. ReAct框架原理（Reasoning + Acting）

---

## 🏗️ 开发流程（第3-15天）

### 阶段1：基础设施搭建（第3-4天）

#### 步骤1.1：创建环境配置文件

**文件**：`.env`
**目的**：管理敏感信息和配置参数

```bash
# 创建.env文件
OPENAI_COMPATIBLE_API_KEY=your_api_key_here
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com/v1
OPENAI_COMPATIBLE_MODEL=deepseek-chat
USE_LOCAL_MODEL=api
```

**注意事项**：
- 不要将`.env`文件提交到Git仓库
- 创建`.env.example`作为模板
- 确保API Key有效

#### 步骤1.2：创建日志配置模块

**文件**：`src/utils/logging_config.py`
**目的**：统一的日志管理系统

**开发顺序**：
```python
# 1. 导入基础模块
import logging
import os
from datetime import datetime

# 2. 定义图标常量（用于美化输出）
SUCCESS_ICON = "✅"
ERROR_ICON = "❌"
WAIT_ICON = "⏳"
INFO_ICON = "ℹ️"

# 3. 创建setup_logger函数
def setup_logger(name, level=logging.INFO):
    """创建并配置日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 配置控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    
    # 添加处理器
    logger.addHandler(console_handler)
    
    return logger
```

**测试代码**：
```python
if __name__ == "__main__":
    logger = setup_logger(__name__)
    logger.info(f"{SUCCESS_ICON} 日志系统测试成功")
    logger.error(f"{ERROR_ICON} 这是一个错误测试")
```

#### 步骤1.3：创建状态定义模块

**文件**：`src/utils/state_definition.py`
**目的**：定义LangGraph工作流的状态结构

**开发顺序**：
```python
# 1. 导入必要的类型定义
from typing import TypedDict, Sequence, Dict, Any, Annotated
from langchain_core.messages import BaseMessage
import operator

# 2. 定义字典合并函数
def merge_dicts(d1: Dict[str, Any], d2: Dict[str, Any]) -> Dict[str, Any]:
    """合并两个字典，d2的值会覆盖d1"""
    return {**d1, **d2}

# 3. 定义AgentState类
class AgentState(TypedDict):
    """LangGraph工作流的状态定义"""
    # 消息列表：使用operator.add进行合并（追加）
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 业务数据：使用merge_dicts进行合并（覆盖）
    data: Annotated[Dict[str, Any], merge_dicts]
    
    # 元数据：使用merge_dicts进行合并（覆盖）
    metadata: Annotated[Dict[str, Any], merge_dicts]
```

**理解要点**：
- `Annotated`的第二个参数定义了状态合并规则
- `operator.add`表示追加（适合消息列表）
- `merge_dicts`表示覆盖合并（适合数据字典）

#### 步骤1.4：创建执行日志模块

**文件**：`src/utils/execution_logger.py`
**目的**：记录每次执行的详细日志

**开发顺序**：
```python
# 1. 导入基础模块
import os
import json
from datetime import datetime
from typing import Dict, Any

# 2. 定义ExecutionLogger类
class ExecutionLogger:
    """执行日志记录器"""
    
    def __init__(self, execution_dir: str):
        self.execution_dir = execution_dir
        self.logs = []
    
    def log_agent_start(self, agent_name: str, input_data: Dict[str, Any]):
        """记录智能体开始执行"""
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "event": "start",
            "data": input_data
        })
    
    def log_agent_complete(self, agent_name: str, output_data: Dict[str, Any], 
                          execution_time: float, success: bool, error: str = None):
        """记录智能体执行完成"""
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "event": "complete",
            "execution_time": execution_time,
            "success": success,
            "error": error,
            "output_data": output_data
        })

# 3. 创建全局实例管理函数
_execution_logger_instance = None

def initialize_execution_logger():
    """初始化执行日志记录器"""
    global _execution_logger_instance
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    execution_dir = f"logs/{timestamp}"
    os.makedirs(execution_dir, exist_ok=True)
    _execution_logger_instance = ExecutionLogger(execution_dir)
    return _execution_logger_instance

def get_execution_logger():
    """获取执行日志记录器实例"""
    return _execution_logger_instance
```

---

### 阶段2：MCP工具集成（第5-6天）

#### 步骤2.1：创建MCP配置文件

**文件**：`src/tools/mcp_config.py`
**目的**：配置MCP服务器连接信息

**开发顺序**：
```python
# 1. 定义服务器配置字典
SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",  # 启动命令
        "args": [
            "run",
            "--directory",
            r"D:\your\path\to\a-share-mcp-is-just-i-need",  # 修改为实际路径
            "python",
            "mcp_server.py"
        ],
        "transport": "stdio",  # 通信协议
    }
}
```

**配置说明**：
- 修改`--directory`为你的MCP服务器实际路径
- 确保MCP服务器项目已正确安装依赖
- 测试服务器能否正常启动

#### 步骤2.2：创建MCP客户端

**文件**：`src/tools/mcp_client.py`
**目的**：连接MCP服务器并获取工具

**开发顺序**：
```python
# 1. 导入必要模块
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.tools.mcp_config import SERVER_CONFIGS
import asyncio

logger = setup_logger(__name__)

# 2. 定义全局变量（用于缓存）
_mcp_client_instance = None
_mcp_tools = None

# 3. 实现get_mcp_tools函数
async def get_mcp_tools():
    """获取MCP工具列表"""
    global _mcp_client_instance, _mcp_tools
    
    # 步骤1：检查缓存
    if _mcp_tools is not None:
        logger.info(f"{SUCCESS_ICON} 返回缓存的MCP工具")
        return _mcp_tools
    
    # 步骤2：初始化客户端
    try:
        logger.info(f"{WAIT_ICON} 初始化MCP客户端...")
        _mcp_client_instance = MultiServerMCPClient(SERVER_CONFIGS)
        
        # 步骤3：获取工具列表
        logger.info(f"{WAIT_ICON} 获取工具列表...")
        loaded_tools = await _mcp_client_instance.get_tools()
        
        # 步骤4：验证和缓存
        if not loaded_tools:
            logger.error(f"{ERROR_ICON} 未加载到任何工具")
            _mcp_tools = []
            return []
        
        _mcp_tools = loaded_tools
        logger.info(f"{SUCCESS_ICON} 成功加载 {len(_mcp_tools)} 个工具")
        
        return _mcp_tools
        
    except Exception as e:
        logger.error(f"{ERROR_ICON} MCP客户端初始化失败: {e}")
        _mcp_tools = []
        return []

# 4. 创建测试函数
async def _main_test_mcp_client():
    """测试MCP客户端"""
    tools = await get_mcp_tools()
    if tools:
        print(f"成功加载 {len(tools)} 个工具:")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")
    else:
        print("工具加载失败")

if __name__ == '__main__':
    asyncio.run(_main_test_mcp_client())
```

**测试步骤**：
```bash
# 运行测试
python -m src.tools.mcp_client

# 预期输出：显示所有可用工具的名称和描述
```

---

### 阶段3：智能体开发（第7-11天）

#### 智能体开发通用模板

每个智能体都遵循相同的开发模式，只是分析内容不同。

#### 步骤3.1：基本面分析智能体

**文件**：`src/agents/fundamental_agent.py`
**目的**：进行基本面分析（财务数据、盈利能力等）

**开发顺序**：

##### 第1步：导入和初始化
```python
# 1. 导入必要模块
import os
import json
import time
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

from src.utils.state_definition import AgentState
from src.tools.mcp_client import get_mcp_tools
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.utils.execution_logger import get_execution_logger

# 2. 加载环境变量
load_dotenv(override=True)
logger = setup_logger(__name__)
```

##### 第2步：定义主函数框架
```python
async def fundamental_agent(state: AgentState) -> AgentState:
    """基本面分析智能体"""
    
    # 1. 获取执行日志记录器
    execution_logger = get_execution_logger()
    agent_name = "fundamental_agent"
    
    # 2. 从状态中提取数据
    current_data = state.get("data", {})
    current_messages = state.get("messages", [])
    current_metadata = state.get("metadata", {})
    user_query = current_data.get("query")
    
    # 3. 记录开始执行
    execution_logger.log_agent_start(agent_name, {
        "user_query": user_query,
        "stock_code": current_data.get("stock_code"),
        "company_name": current_data.get("company_name")
    })
    
    # 4. 验证输入
    if not user_query:
        logger.error(f"{ERROR_ICON} 缺少用户查询")
        current_data["fundamental_analysis_error"] = "缺少用户查询"
        execution_logger.log_agent_complete(agent_name, current_data, 0, False, "缺少用户查询")
        return {"data": current_data, "messages": current_messages, "metadata": current_metadata}
    
    # 记录开始时间
    agent_start_time = time.time()
    
    try:
        # 5. 创建LLM实例
        # 6. 获取MCP工具
        # 7. 创建ReAct智能体
        # 8. 执行分析
        # 9. 提取结果
        # 10. 返回更新后的状态
        pass
        
    except Exception as e:
        logger.error(f"{ERROR_ICON} 执行失败: {e}")
        current_data["fundamental_analysis_error"] = str(e)
        execution_logger.log_agent_complete(agent_name, current_data, 
                                          time.time() - agent_start_time, False, str(e))
        return {"data": current_data, "messages": current_messages, "metadata": current_metadata}
```

##### 第3步：实现LLM和工具获取
```python
# 在try块中实现

# 步骤5：创建LLM实例
api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")

if not all([api_key, base_url, model_name]):
    logger.error(f"{ERROR_ICON} 缺少环境变量")
    current_data["fundamental_analysis_error"] = "缺少环境变量"
    execution_logger.log_agent_complete(agent_name, current_data, 
                                      time.time() - agent_start_time, False, "缺少环境变量")
    return {"data": current_data, "messages": current_messages, "metadata": current_metadata}

logger.info(f"{WAIT_ICON} 创建ChatOpenAI实例: {model_name}")
llm = ChatOpenAI(
    model=model_name,
    api_key=api_key,
    base_url=base_url,
    temperature=0.3,  # 较低温度确保一致性
    max_tokens=6000   # 足够的token用于详细分析
)

# 步骤6：获取MCP工具
logger.info(f"{WAIT_ICON} 获取MCP工具...")
mcp_tools = await get_mcp_tools()

if not mcp_tools:
    logger.error(f"{ERROR_ICON} 没有可用的MCP工具")
    current_data["fundamental_analysis_error"] = "没有可用的MCP工具"
    execution_logger.log_agent_complete(agent_name, current_data, 
                                      time.time() - agent_start_time, False, "没有可用的MCP工具")
    return {"data": current_data, "messages": current_messages, "metadata": current_metadata}

logger.info(f"{SUCCESS_ICON} 成功加载 {len(mcp_tools)} 个工具")
```

##### 第4步：创建ReAct智能体并执行分析
```python
# 步骤7：创建ReAct智能体
logger.info(f"{WAIT_ICON} 创建ReAct智能体...")
agent = create_react_agent(llm, mcp_tools)

# 步骤8：准备分析请求
stock_code = current_data.get('stock_code', 'Unknown')
company_name = current_data.get('company_name', 'Unknown')
current_time_info = current_data.get('current_time_info', '未知时间')

agent_input = f"""请分析{company_name}（股票代码：{stock_code}）的基本面情况。

当前时间：{current_time_info}

请进行以下基本面分析：
1. 获取公司基本信息和行业背景
2. 获取最新财务报表数据（资产负债表、利润表、现金流量表）
3. 分析盈利能力指标（毛利率、净利率、ROE等）
4. 分析成长能力指标（收入增长率、利润增长率等）
5. 分析运营效率指标（应收周转率、存货周转率等）
6. 分析偿债能力指标（资产负债率、流动比率等）
7. 查询历史分红情况
8. 提供基本面综合评估和投资价值分析

请使用可用的工具获取实际数据进行分析。"""

logger.info(f"分析请求: {agent_input}")

# 步骤9：调用ReAct智能体
logger.info(f"{WAIT_ICON} 调用ReAct智能体...")
start_time = time.time()

input_data = {
    "messages": [HumanMessage(content=agent_input)]
}

response = await agent.ainvoke(input_data)

execution_time = time.time() - start_time
logger.info(f"ReAct智能体执行完成，耗时 {execution_time:.2f} 秒")
```

##### 第5步：提取结果并更新状态
```python
# 步骤10：提取分析结果
final_output = "未生成分析结果。"

if "messages" in response and isinstance(response["messages"], list):
    messages = response["messages"]
    ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]
    
    if ai_messages:
        last_ai_message = ai_messages[-1]
        final_output = last_ai_message.content
        logger.info(f"{SUCCESS_ICON} 成功提取分析结果")
    else:
        logger.warning("响应中没有AI消息")

# 步骤11：更新状态
current_data["fundamental_analysis"] = final_output

# 步骤12：记录完成
execution_logger.log_agent_complete(
    agent_name, 
    current_data, 
    time.time() - agent_start_time, 
    True, 
    None
)

logger.info(f"{SUCCESS_ICON} 基本面分析完成")

# 步骤13：返回更新后的状态
return {
    "messages": current_messages,
    "data": current_data,
    "metadata": current_metadata
}
```

#### 步骤3.2：技术分析智能体

**文件**：`src/agents/technical_agent.py`
**开发方法**：复制`fundamental_agent.py`，修改以下内容：

```python
# 1. 修改函数名
async def technical_agent(state: AgentState) -> AgentState:

# 2. 修改agent_name
agent_name = "technical_agent"

# 3. 修改分析请求
agent_input = f"""请分析{company_name}（股票代码：{stock_code}）的技术面情况。

当前时间：{current_time_info}

请进行以下技术分析：
1. 获取最近的股价数据和交易量
2. 分析价格趋势（上升、下降、震荡）
3. 计算和分析技术指标（MA、MACD、RSI、KDJ等）
4. 分析支撑位和压力位
5. 分析成交量变化
6. 提供技术面综合评估和短期走势预判

请使用可用的工具获取实际数据进行分析。"""

# 4. 修改结果保存字段
current_data["technical_analysis"] = final_output
```

#### 步骤3.3：估值分析智能体

**文件**：`src/agents/value_agent.py`
**开发方法**：复制模板，修改为估值分析内容

```python
agent_input = f"""请分析{company_name}（股票代码：{stock_code}）的估值情况。

当前时间：{current_time_info}

请进行以下估值分析：
1. 获取当前股价和市值数据
2. 计算市盈率（PE）、市净率（PB）、市销率（PS）
3. 对比行业平均估值水平
4. 分析历史估值趋势
5. 使用DCF、DDM等方法进行内在价值评估
6. 提供估值综合评估（低估、合理、高估）

请使用可用的工具获取实际数据进行分析。"""

current_data["value_analysis"] = final_output
```

#### 步骤3.4：新闻分析智能体

**文件**：`src/agents/news_agent.py`
**开发方法**：复制模板，修改为新闻分析内容

```python
agent_input = f"""请分析{company_name}（股票代码：{stock_code}）的新闻情况。

当前时间：{current_time_info}

请进行以下新闻分析：
1. 获取最近的相关新闻
2. 分析新闻情感（正面、负面、中性）
3. 识别重大事件和风险因素
4. 评估新闻对股价的潜在影响
5. 提供新闻面综合评估

请使用可用的工具获取实际数据进行分析。"""

current_data["news_analysis"] = final_output
```

---

### 阶段4：总结智能体开发（第12天）

#### 步骤4.1：创建总结智能体

**文件**：`src/agents/summary_agent.py`
**目的**：整合所有分析结果，生成最终报告

**开发顺序**：

##### 第1步：导入和初始化
```python
import os
import time
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv

from src.utils.state_definition import AgentState
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.utils.execution_logger import get_execution_logger

load_dotenv(override=True)
logger = setup_logger(__name__)
```

##### 第2步：实现总结函数
```python
async def summary_agent(state: AgentState) -> AgentState:
    """总结智能体：整合所有分析结果"""
    
    execution_logger = get_execution_logger()
    agent_name = "summary_agent"
    
    # 1. 提取状态数据
    current_data = state.get("data", {})
    current_messages = state.get("messages", [])
    current_metadata = state.get("metadata", {})
    
    # 2. 记录开始
    execution_logger.log_agent_start(agent_name, {
        "stock_code": current_data.get("stock_code"),
        "company_name": current_data.get("company_name")
    })
    
    agent_start_time = time.time()
    
    try:
        # 3. 提取各个分析结果
        fundamental_analysis = current_data.get("fundamental_analysis", "无基本面分析")
        technical_analysis = current_data.get("technical_analysis", "无技术分析")
        value_analysis = current_data.get("value_analysis", "无估值分析")
        news_analysis = current_data.get("news_analysis", "无新闻分析")
        
        # 4. 构建总结提示词
        stock_code = current_data.get('stock_code', 'Unknown')
        company_name = current_data.get('company_name', 'Unknown')
        current_time_info = current_data.get('current_time_info', '未知时间')
        
        summary_prompt = f"""你是一位专业的金融分析师。请基于以下四个维度的分析结果，为{company_name}（{stock_code}）生成一份综合的投资分析报告。

## 分析时间
{current_time_info}

## 基本面分析
{fundamental_analysis}

## 技术分析
{technical_analysis}

## 估值分析
{value_analysis}

## 新闻分析
{news_analysis}

请生成一份结构化的Markdown格式报告，包含：
1. 执行摘要（投资建议：买入/持有/卖出）
2. 公司概况
3. 各维度分析要点总结
4. SWOT分析
5. 投资风险提示
6. 综合投资建议

报告要求：
- 使用Markdown格式
- 逻辑清晰、结构完整
- 突出关键信息和投资建议
- 客观公正，基于数据分析"""

        # 5. 创建LLM并生成总结
        api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")
        
        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.5,
            max_tokens=8000
        )
        
        logger.info(f"{WAIT_ICON} 生成综合报告...")
        
        response = await llm.ainvoke([HumanMessage(content=summary_prompt)])
        final_report = response.content
        
        # 6. 保存报告到文件
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        
        timestamp = current_data.get('current_date', 'unknown')
        safe_company_name = company_name.replace('/', '_').replace('\\', '_')
        report_filename = f"report_{safe_company_name}_{stock_code}_{timestamp}.md"
        report_path = os.path.join(report_dir, report_filename)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(final_report)
        
        logger.info(f"{SUCCESS_ICON} 报告已保存到: {report_path}")
        
        # 7. 更新状态
        current_data["final_report"] = final_report
        current_data["report_path"] = report_path
        
        # 8. 记录完成
        execution_logger.log_agent_complete(
            agent_name,
            current_data,
            time.time() - agent_start_time,
            True,
            None
        )
        
        return {
            "messages": current_messages,
            "data": current_data,
            "metadata": current_metadata
        }
        
    except Exception as e:
        logger.error(f"{ERROR_ICON} 总结失败: {e}")
        current_data["summary_error"] = str(e)
        execution_logger.log_agent_complete(
            agent_name,
            current_data,
            time.time() - agent_start_time,
            False,
            str(e)
        )
        return {
            "messages": current_messages,
            "data": current_data,
            "metadata": current_metadata
        }
```

---

### 阶段5：主程序开发（第13-14天）

#### 步骤5.1：创建主程序

**文件**：`src/main.py`
**目的**：整合所有模块，构建LangGraph工作流

**开发顺序**：

##### 第1步：导入所有模块
```python
import os
import sys
import asyncio
import argparse
import re
from datetime import datetime
from dotenv import load_dotenv

# 状态和日志
from src.utils.state_definition import AgentState
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.utils.execution_logger import initialize_execution_logger, finalize_execution_logger, get_execution_logger

# 智能体
from src.agents.fundamental_agent import fundamental_agent
from src.agents.technical_agent import technical_agent
from src.agents.value_agent import value_agent
from src.agents.news_agent import news_agent
from src.agents.summary_agent import summary_agent

# LangGraph
from langgraph.graph import StateGraph, END

# 加载环境变量
load_dotenv(override=True)
logger = setup_logger(__name__)
```

##### 第2步：定义主函数框架
```python
async def main():
    """主函数：金融分析智能体系统的核心执行逻辑"""
    
    # 1. 初始化执行日志系统
    execution_logger = initialize_execution_logger()
    logger.info(f"{SUCCESS_ICON} 执行日志系统已初始化")
    
    try:
        # 2. 定义LangGraph工作流
        # 3. 实现命令行界面
        # 4. 自然语言处理和股票信息提取
        # 5. 时间信息处理
        # 6. 准备初始状态数据
        # 7. 执行工作流
        # 8. 结果处理和报告生成
        pass
        
    except Exception as e:
        logger.error(f"{ERROR_ICON} 工作流执行失败: {e}")
        finalize_execution_logger(success=False, error=str(e))
```

##### 第3步：定义LangGraph工作流
```python
# 步骤2：定义LangGraph工作流

# 创建工作流图
workflow = StateGraph(AgentState)

# 添加起始节点
workflow.add_node("start_node", lambda state: state)

# 添加五个核心智能体节点
workflow.add_node("fundamental_analyst", fundamental_agent)
workflow.add_node("technical_analyst", technical_agent)
workflow.add_node("value_analyst", value_agent)
workflow.add_node("news_analyst", news_agent)
workflow.add_node("summarizer", summary_agent)

# 设置工作流入口点
workflow.set_entry_point("start_node")

# 添加并行执行边（4个分析智能体并行执行）
workflow.add_edge("start_node", "fundamental_analyst")
workflow.add_edge("start_node", "technical_analyst")
workflow.add_edge("start_node", "value_analyst")
workflow.add_edge("start_node", "news_analyst")

# 添加汇聚边（所有分析结果汇聚到总结智能体）
workflow.add_edge("fundamental_analyst", "summarizer")
workflow.add_edge("technical_analyst", "summarizer")
workflow.add_edge("value_analyst", "summarizer")
workflow.add_edge("news_analyst", "summarizer")

# 添加结束边
workflow.add_edge("summarizer", END)

# 编译工作流
app = workflow.compile()

logger.info(f"{SUCCESS_ICON} LangGraph工作流已构建")
```

##### 第4步：实现命令行界面
```python
# 步骤3：实现命令行界面

parser = argparse.ArgumentParser(description="金融分析智能体系统")
parser.add_argument(
    "--command",
    type=str,
    required=False,
    help="用户查询（例如：'分析茅台'）"
)
args = parser.parse_args()

if args.command:
    user_query = args.command
else:
    # 显示欢迎界面
    print("\n" + "="*80)
    print("🏦 金融分析智能体系统")
    print("Financial Analysis AI Agent System")
    print("="*80)
    print("\n本系统可以对A股公司进行全面分析，包括：")
    print("  • 基本面分析 - 财务状况、盈利能力")
    print("  • 技术面分析 - 价格趋势、技术指标")
    print("  • 估值分析 - 市盈率、市净率")
    print("  • 新闻分析 - 新闻情感、风险评估")
    print("\n示例查询：")
    print("  • 分析茅台")
    print("  • 帮我看看比亚迪这只股票怎么样")
    print("  • 600519 这个股票值得买吗？")
    print("\n" + "-"*80 + "\n")
    
    user_query = input("💬 请输入您的分析需求: ")
    
    while not user_query.strip():
        print(f"{ERROR_ICON} 输入不能为空，请重新输入！")
        user_query = input("请输入您的分析需求: ")
```

##### 第5步：提取股票信息
```python
# 步骤4：自然语言处理和股票信息提取

def extract_stock_info(query):
    """从查询中提取股票代码和公司名称"""
    stock_code = None
    company_name = None
    
    # 模式1: 公司名+括号内代码，如"分析茅台(600519)"
    pattern1 = r'分析\s*([^（(]+?)\s*[（(](\d{5,6})[)）]'
    match1 = re.search(pattern1, query)
    if match1:
        company_name = match1.group(1).strip()
        stock_code = match1.group(2)
        return company_name, stock_code
    
    # 模式2: 直接包含6位数字
    pattern2 = r'\b(\d{6})\b'
    match2 = re.search(pattern2, query)
    if match2:
        stock_code = match2.group(1)
    
    # 模式3: 提取公司名称
    pattern3 = r'分析\s*([^0-9（）()\s]+)'
    match3 = re.search(pattern3, query)
    if match3:
        company_name = match3.group(1).strip()
    
    return company_name, stock_code

company_name, stock_code = extract_stock_info(user_query)
logger.info(f"提取信息 - 公司: {company_name}, 代码: {stock_code}")
```

##### 第6步：准备初始状态
```python
# 步骤5：时间信息处理
current_datetime = datetime.now()
current_date_cn = current_datetime.strftime("%Y年%m月%d日")
current_date_en = current_datetime.strftime("%Y-%m-%d")
current_weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][current_datetime.weekday()]
current_time = current_datetime.strftime("%H:%M:%S")
current_time_info = f"{current_date_cn} ({current_date_en}) {current_weekday_cn} {current_time}"

# 步骤6：准备初始状态数据
initial_data = {
    "query": user_query,
    "current_date": current_date_en,
    "current_date_cn": current_date_cn,
    "current_time": current_time,
    "current_weekday_cn": current_weekday_cn,
    "current_time_info": current_time_info
}

if company_name:
    initial_data["company_name"] = company_name

if stock_code:
    # 添加交易所前缀
    if stock_code.startswith('6'):
        initial_data["stock_code"] = f"sh.{stock_code}"
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        initial_data["stock_code"] = f"sz.{stock_code}"
    else:
        initial_data["stock_code"] = stock_code

# 创建初始状态
initial_state = AgentState(
    messages=[],
    data=initial_data,
    metadata={}
)
```

##### 第7步：执行工作流并处理结果
```python
# 步骤7：执行工作流
print(f"\n{WAIT_ICON} 正在开始分析...")
if company_name:
    print(f"{WAIT_ICON} 分析公司: {company_name}")
if stock_code:
    print(f"{WAIT_ICON} 股票代码: {stock_code}")

print(f"\n{WAIT_ICON} 正在执行基本面分析...")
print(f"{WAIT_ICON} 正在执行技术面分析...")
print(f"{WAIT_ICON} 正在执行估值分析...")
print(f"{WAIT_ICON} 正在执行新闻分析...")
print(f"{WAIT_ICON} 这可能需要几分钟，请耐心等待...\n")

# 调用工作流
final_state = await app.ainvoke(initial_state)
print(f"{SUCCESS_ICON} 分析完成！")

# 步骤8：结果处理
if final_state and final_state.get("data") and "final_report" in final_state["data"]:
    print("\n--- 最终分析报告 ---\n")
    
    if "report_path" in final_state["data"]:
        print(f"\n{SUCCESS_ICON} 报告已保存到: {final_state['data']['report_path']}")
        
        execution_logger.log_final_report(
            final_state["data"]["final_report"],
            final_state["data"]["report_path"]
        )
else:
    print(f"\n{ERROR_ICON} 无法检索最终报告")

# 完成执行日志
finalize_execution_logger(success=True)
print(f"{SUCCESS_ICON} 执行日志已保存到: {execution_logger.execution_dir}")
```

##### 第8步：添加程序入口
```python
if __name__ == "__main__":
    asyncio.run(main())
```

---

### 阶段6：测试和优化（第15天）

#### 步骤6.1：单元测试

**测试MCP客户端**：
```bash
python -m src.tools.mcp_client
```

**测试单个智能体**：
```python
# 创建测试文件：test_agents.py
import asyncio
from src.agents.fundamental_agent import fundamental_agent
from src.utils.state_definition import AgentState

async def test_fundamental():
    state = AgentState(
        messages=[],
        data={
            "query": "分析茅台",
            "stock_code": "sh.600519",
            "company_name": "茅台",
            "current_time_info": "2024年1月1日"
        },
        metadata={}
    )
    
    result = await fundamental_agent(state)
    print(result["data"].get("fundamental_analysis"))

asyncio.run(test_fundamental())
```

#### 步骤6.2：集成测试

**测试完整工作流**：
```bash
# 测试命令行模式
python src/main.py --command "分析茅台"

# 测试交互模式
python src/main.py
# 然后输入：分析茅台
```

#### 步骤6.3：错误处理优化

**添加重试机制**：
```python
import tenacity

@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10)
)
async def call_llm_with_retry(llm, messages):
    """带重试的LLM调用"""
    return await llm.ainvoke(messages)
```

**添加超时控制**：
```python
import asyncio

try:
    response = await asyncio.wait_for(
        agent.ainvoke(input_data),
        timeout=300  # 5分钟超时
    )
except asyncio.TimeoutError:
    logger.error("执行超时")
```

---

## 📝 开发检查清单

### 第一周检查点
- [ ] 环境搭建完成
- [ ] 项目结构创建
- [ ] 日志系统工作正常
- [ ] 状态定义正确
- [ ] MCP工具连接成功

### 第二周检查点
- [ ] 4个分析智能体开发完成
- [ ] 总结智能体开发完成
- [ ] 主程序框架搭建完成
- [ ] LangGraph工作流运行正常
- [ ] 能生成分析报告

### 第三周检查点
- [ ] 所有单元测试通过
- [ ] 集成测试通过
- [ ] 错误处理完善
- [ ] 日志记录完整
- [ ] 文档完善

---

## 🚨 常见问题解决

### 问题1：MCP工具加载失败
**现象**：`get_mcp_tools()`返回空列表

**排查步骤**：
1. 检查`mcp_config.py`中的路径是否正确
2. 确认MCP服务器是否可以独立运行
3. 查看MCP服务器日志
4. 检查Python环境是否安装所需依赖

**解决方案**：
```bash
# 测试MCP服务器
cd /path/to/a-share-mcp-is-just-i-need
python mcp_server.py

# 检查依赖
pip install -r requirements.txt
```

### 问题2：API调用失败
**现象**：LLM调用返回错误

**排查步骤**：
1. 检查`.env`文件中的API Key是否正确
2. 确认Base URL是否可访问
3. 检查模型名称是否正确
4. 查看API配额是否用完

**解决方案**：
```python
# 测试API连接
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv

load_dotenv()
llm = ChatOpenAI(
    model=os.getenv("OPENAI_COMPATIBLE_MODEL"),
    api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY"),
    base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL")
)

response = llm.invoke("你好")
print(response.content)
```

### 问题3：异步执行问题
**现象**：`await`使用错误或事件循环问题

**解决方案**：
- 确保所有异步函数使用`async def`定义
- 调用异步函数必须使用`await`
- 主程序入口使用`asyncio.run(main())`

### 问题4：状态合并问题
**现象**：智能体间数据传递丢失

**排查步骤**：
1. 检查`AgentState`定义是否正确
2. 确认返回的状态结构符合要求
3. 查看`merge_dicts`函数是否正常工作

**解决方案**：
```python
# 确保返回正确的状态结构
return {
    "messages": state["messages"],  # 或追加新消息
    "data": {**current_data, "new_field": "value"},  # 合并数据
    "metadata": current_metadata
}
```

---

## 💡 开发建议

### 1. 渐进式开发
- 先实现基础功能，再添加高级特性
- 每完成一个模块就进行测试
- 不要一次性写太多代码

### 2. 日志优先
- 在关键位置添加日志
- 使用不同级别的日志（INFO、ERROR、WARNING）
- 日志要包含足够的上下文信息

### 3. 错误处理
- 每个可能出错的地方都要有try-except
- 错误信息要清晰明确
- 提供降级方案

### 4. 代码复用
- 相似的代码提取成函数
- 使用模板模式开发智能体
- 避免重复代码

### 5. 文档编写
- 每个函数都要有文档字符串
- 复杂逻辑要有注释
- 保持代码可读性

---

## 📚 学习资源

### 官方文档
- [LangGraph文档](https://langchain-ai.github.io/langgraph/)
- [LangChain文档](https://python.langchain.com/)
- [MCP协议文档](https://modelcontextprotocol.io/)

### 推荐教程
- Python异步编程教程
- LangGraph快速入门
- ReAct框架原理

### 调试技巧
- 使用`logger.info()`输出中间结果
- 使用断点调试工具（如VS Code）
- 查看执行日志分析问题

---

## 🎓 项目总结

通过完成这个项目，你将学到：

1. **工程化开发流程**：从需求分析到项目部署的完整流程
2. **异步编程**：Python的async/await使用
3. **AI应用开发**：LangGraph、LangChain的实战应用
4. **系统设计**：多智能体系统的架构设计
5. **工具集成**：MCP协议的使用
6. **错误处理**：生产级的错误处理和日志记录

### 下一步学习方向
- 学习更高级的LangGraph特性（条件边、子图等）
- 了解RAG（检索增强生成）技术
- 学习模型微调和优化
- 探索更多AI应用场景

---

## 📋 开发时间表

| 天数 | 任务 | 输出 |
|-----|------|------|
| 1-2 | 环境准备、项目结构 | 项目框架 |
| 3-4 | 基础设施（日志、状态、MCP） | 基础模块 |
| 5-6 | MCP工具集成 | 工具可用 |
| 7-9 | 前4个智能体开发 | 分析智能体 |
| 10-11 | 总结智能体开发 | 报告生成 |
| 12-13 | 主程序开发 | 完整系统 |
| 14-15 | 测试和优化 | 稳定版本 |

---

## ✅ 最终检查

在提交项目前，确保：

- [ ] 所有模块都有完整的错误处理
- [ ] 日志记录完整且有意义
- [ ] 代码有充分的注释
- [ ] 所有测试用例通过
- [ ] README.md文档完善
- [ ] .env.example文件已创建
- [ ] requirements.txt包含所有依赖
- [ ] 代码符合PEP 8规范

---

**祝你开发顺利！如有问题，查看日志，逐步调试，你一定能完成这个项目！** 🚀

