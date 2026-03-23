# Langfuse 集成指南

## 1. 部署Langfuse（二选一）

### 方案A：使用Langfuse Cloud（推荐快速开始）
1. 访问 https://cloud.langfuse.com/
2. 注册账号（免费额度：50k observations/月）
3. 创建新项目，获取：
   - Public Key
   - Secret Key
   - Host URL

### 方案B：自托管部署（Docker）
```bash
# docker-compose.yml
version: '3.8'
services:
  langfuse:
    image: langfuse/langfuse:latest
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@postgres:5432/langfuse
      - NEXTAUTH_URL=http://localhost:3000
      - NEXTAUTH_SECRET=your-secret-key
    depends_on:
      - postgres
  
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=langfuse
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

启动：`docker-compose up -d`

## 2. 安装依赖

```bash
pip install langfuse
```

## 3. 配置环境变量

在 `.env` 文件中添加：

```bash
# Langfuse配置
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_HOST="https://cloud.langfuse.com"  # 或自托管地址
```

## 4. 集成代码（需修改现有代码）

### 4.1 创建Langfuse包装器

创建文件：`src/utils/langfuse_tracer.py`

```python
"""Langfuse追踪器 - 与现有日志系统集成"""
import os
from typing import Dict, Any, Optional
from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context
from dotenv import load_dotenv

load_dotenv()

class LangfuseTracer:
    """Langfuse追踪器封装"""
    
    def __init__(self):
        self.client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
        self.trace = None
        
    def start_trace(self, name: str, input_data: Dict[str, Any], 
                   user_id: Optional[str] = None, metadata: Optional[Dict] = None):
        """开始追踪"""
        self.trace = self.client.trace(
            name=name,
            input=input_data,
            user_id=user_id,
            metadata=metadata or {}
        )
        return self.trace
    
    def log_agent_execution(self, agent_name: str, input_data: Dict, 
                           output_data: Dict, execution_time: float):
        """记录Agent执行"""
        if not self.trace:
            return
        
        span = self.trace.span(
            name=agent_name,
            input=input_data,
            output=output_data,
            metadata={
                "execution_time": execution_time,
                "agent_type": "analysis_agent"
            }
        )
        return span
    
    def log_llm_generation(self, model: str, messages: list, 
                          response: str, token_usage: Optional[Dict] = None):
        """记录LLM生成"""
        if not self.trace:
            return
        
        generation = self.trace.generation(
            name="llm_call",
            model=model,
            input=messages,
            output=response,
            usage={
                "input": token_usage.get("prompt_tokens", 0) if token_usage else 0,
                "output": token_usage.get("completion_tokens", 0) if token_usage else 0,
                "total": token_usage.get("total_tokens", 0) if token_usage else 0
            }
        )
        return generation
    
    def log_tool_usage(self, tool_name: str, tool_input: Dict, 
                      tool_output: Any, execution_time: float):
        """记录工具调用"""
        if not self.trace:
            return
        
        span = self.trace.span(
            name=f"tool_{tool_name}",
            input=tool_input,
            output={"result": str(tool_output)[:1000]},
            metadata={
                "tool_name": tool_name,
                "execution_time": execution_time
            }
        )
        return span
    
    def end_trace(self, output_data: Dict, success: bool = True):
        """结束追踪"""
        if self.trace:
            self.trace.update(
                output=output_data,
                metadata={"success": success}
            )
        
        # 确保数据上传
        self.client.flush()

# 全局实例
_langfuse_tracer: Optional[LangfuseTracer] = None

def get_langfuse_tracer() -> LangfuseTracer:
    """获取Langfuse追踪器"""
    global _langfuse_tracer
    if _langfuse_tracer is None:
        _langfuse_tracer = LangfuseTracer()
    return _langfuse_tracer
```

### 4.2 修改Agent代码（以fundamental_agent.py为例）

```python
# 在文件顶部导入
from src.utils.langfuse_tracer import get_langfuse_tracer

async def fundamental_agent(state: AgentState) -> AgentState:
    """基本面分析智能体（集成Langfuse）"""
    
    execution_logger = get_execution_logger()
    langfuse_tracer = get_langfuse_tracer()  # 新增
    agent_name = "fundamental_agent"
    
    # ... 现有代码 ...
    
    agent_start_time = time.time()
    
    try:
        # 记录到Langfuse（新增）
        langfuse_tracer.log_agent_execution(
            agent_name=agent_name,
            input_data={
                "query": user_query,
                "stock_code": current_data.get("stock_code"),
                "company_name": current_data.get("company_name")
            },
            output_data={},  # 执行完成后更新
            execution_time=0
        )
        
        # ... 现有的LLM调用代码 ...
        
        response = await agent.ainvoke(input_data)
        
        execution_time = time.time() - agent_start_time
        
        # 提取结果
        final_output = extract_result(response)
        
        # 更新Langfuse记录（新增）
        langfuse_tracer.log_agent_execution(
            agent_name=agent_name,
            input_data={"query": user_query},
            output_data={"analysis": final_output[:500]},  # 截断以节省空间
            execution_time=execution_time
        )
        
        # ... 现有代码继续 ...
        
    except Exception as e:
        # 记录错误到Langfuse
        langfuse_tracer.end_trace(
            output_data={"error": str(e)},
            success=False
        )
        raise
```

### 4.3 修改主程序（main.py）

```python
from src.utils.langfuse_tracer import get_langfuse_tracer

async def main():
    execution_logger = initialize_execution_logger()
    langfuse_tracer = get_langfuse_tracer()  # 新增
    
    try:
        # ... 现有代码 ...
        
        # 开始Langfuse追踪（新增）
        langfuse_tracer.start_trace(
            name="stock_analysis_workflow",
            input_data={
                "query": user_query,
                "stock_code": stock_code,
                "company_name": company_name
            },
            metadata={
                "execution_id": execution_logger.execution_id,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        # 执行工作流
        final_state = await app.ainvoke(initial_state)
        
        # 结束Langfuse追踪（新增）
        langfuse_tracer.end_trace(
            output_data={
                "report_generated": "report_path" in final_state.get("data", {}),
                "report_path": final_state.get("data", {}).get("report_path")
            },
            success=True
        )
        
        # ... 现有代码继续 ...
        
    except Exception as e:
        langfuse_tracer.end_trace(
            output_data={"error": str(e)},
            success=False
        )
        raise
```

## 5. 使用装饰器模式（更简洁）

Langfuse支持装饰器，可以更简洁地集成：

```python
from langfuse.decorators import observe, langfuse_context

@observe()
async def fundamental_agent(state: AgentState) -> AgentState:
    """使用装饰器自动追踪"""
    # 添加自定义属性
    langfuse_context.update_current_trace(
        tags=["fundamental_analysis", "production"],
        metadata={"stock_code": state["data"].get("stock_code")}
    )
    
    # 原有业务逻辑
    # ...
    
    return result
```

## 6. 查看监控数据

访问 Langfuse Dashboard：
- **Traces**：完整执行链路（包含所有Agent和LLM调用）
- **Sessions**：用户会话分组
- **Users**：用户行为分析
- **Scores**：自定义评分（可用于A/B测试）
- **Datasets**：测试数据集管理
- **Cost**：详细的Token成本分析

## 7. 成本分析配置

Langfuse可以自动计算成本（需配置模型定价）：

```python
# 在Langfuse后台配置模型价格，或通过代码设置
langfuse_tracer.log_llm_generation(
    model="deepseek-chat",
    messages=input_messages,
    response=response_content,
    token_usage={
        "prompt_tokens": 1500,
        "completion_tokens": 800,
        "total_tokens": 2300
    }
)
# Langfuse会自动计算成本（如果配置了deepseek-chat的定价）
```

## 优势总结

✅ **开源免费**：可自托管，无供应商锁定
✅ **细粒度控制**：完整的Token和成本追踪
✅ **评估功能**：支持自定义评分和A/B测试
✅ **数据安全**：自托管方案数据完全受控
✅ **团队协作**：支持多项目和权限管理

## 劣势

⚠️ **集成复杂度**：需要修改现有代码（约50-100行）
⚠️ **依赖管理**：新增依赖包
⚠️ **运维成本**：自托管需要维护数据库和服务
