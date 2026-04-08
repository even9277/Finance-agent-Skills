"""
Legacy Langfuse 兼容封装。

注意：
1. 当前主 trace 入口已经迁移到 `src.tools.skill_trace`
2. 新代码不应再直接把它作为主 tracing 接口
3. 这里保留仅用于兼容历史调用与初始化 Langfuse runtime
"""
import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

from src.tools.skill_trace import initialize_trace_runtime

load_dotenv()

# 判断是否启用Langfuse
LANGFUSE_ENABLED = os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")

if LANGFUSE_ENABLED:
    try:
        from langfuse import Langfuse
        from langfuse.decorators import observe, langfuse_context
    except ImportError:
        print("Warning: Langfuse not installed. Run: pip install langfuse")
        LANGFUSE_ENABLED = False


class LangfuseTracer:
    """Langfuse追踪器封装"""
    
    def __init__(self):
        initialize_trace_runtime()
        if not LANGFUSE_ENABLED:
            self.client = None
            self.trace = None
            return
            
        self.client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            base_url=os.getenv("LANGFUSE_BASE_URL") or None,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
        self.trace_id = None
        self.trace = None
        
    def start_trace(self, name: str, input_data: Dict[str, Any], 
                   user_id: Optional[str] = None, metadata: Optional[Dict] = None):
        """开始追踪一次完整的执行"""
        if not LANGFUSE_ENABLED:
            return None

        self.trace_id = self.client.create_trace_id()
        self.trace = self.client.start_observation(
            trace_context={"trace_id": self.trace_id},
            name=name,
            as_type="span",
            input=input_data,
            metadata={
                "user_id": user_id,
                **(metadata or {}),
                "tags": ["stock_analysis", "production"],
            },
        )
        return self.trace
    
    def log_agent_execution(self, agent_name: str, input_data: Dict, 
                           output_data: Dict, execution_time: float, 
                           success: bool = True, error: Optional[str] = None):
        """记录Agent执行"""
        if not LANGFUSE_ENABLED or not self.trace:
            return None
        
        span = self.trace.start_observation(
            name=agent_name,
            as_type="agent",
            input=input_data,
            output=output_data if success else {"error": error},
            metadata={
                "execution_time_seconds": execution_time,
                "agent_type": "analysis_agent",
                "success": success
            },
            level="ERROR" if not success else "DEFAULT"
        )
        return span
    
    def log_llm_generation(self, model: str, messages: list, 
                          response: str, execution_time: float = 0,
                          token_usage: Optional[Dict] = None):
        """记录LLM生成"""
        if not LANGFUSE_ENABLED or not self.trace:
            return None
        
        # 格式化输入消息
        formatted_messages = []
        for msg in messages:
            if hasattr(msg, 'content'):
                formatted_messages.append({
                    "role": getattr(msg, 'type', 'user'),
                    "content": msg.content
                })
            elif isinstance(msg, dict):
                formatted_messages.append(msg)
        
        generation = self.trace.start_observation(
            name="llm_generation",
            as_type="generation",
            model=model,
            input=formatted_messages,
            output=response,
            usage_details={
                "input": token_usage.get("prompt_tokens", 0) if token_usage else 0,
                "output": token_usage.get("completion_tokens", 0) if token_usage else 0,
                "total": token_usage.get("total_tokens", 0) if token_usage else 0,
            },
            metadata={
                "execution_time_seconds": execution_time
            }
        )
        return generation
    
    def log_tool_usage(self, tool_name: str, tool_input: Dict, 
                      tool_output: Any, execution_time: float,
                      success: bool = True, error: Optional[str] = None):
        """记录工具调用"""
        if not LANGFUSE_ENABLED or not self.trace:
            return None
        
        # 截断过长的输出
        output_str = str(tool_output)
        if len(output_str) > 2000:
            output_str = output_str[:2000] + "... (truncated)"
        
        span = self.trace.start_observation(
            name=f"tool_{tool_name}",
            as_type="tool",
            input=tool_input,
            output={"result": output_str} if success else {"error": error},
            metadata={
                "tool_name": tool_name,
                "execution_time_seconds": execution_time,
                "success": success
            },
            level="ERROR" if not success else "DEFAULT"
        )
        return span
    
    def add_score(self, name: str, value: float, comment: Optional[str] = None):
        """添加评分（用于质量评估）"""
        if not LANGFUSE_ENABLED or not self.trace:
            return None

        self.trace.score(
            name=name,
            value=value,
            comment=comment
        )
    
    def end_trace(self, output_data: Dict, success: bool = True):
        """结束追踪"""
        if not LANGFUSE_ENABLED:
            return
            
        if self.trace:
            self.trace.update(
                output=output_data,
                metadata={"success": success},
                level="ERROR" if not success else "DEFAULT"
            )
            self.trace.end()
        
        # 确保数据上传
        if self.client:
            self.client.flush()


# 全局实例
_langfuse_tracer: Optional[LangfuseTracer] = None


def get_langfuse_tracer() -> LangfuseTracer:
    """获取Langfuse追踪器（单例模式）"""
    global _langfuse_tracer
    if _langfuse_tracer is None:
        _langfuse_tracer = LangfuseTracer()
    return _langfuse_tracer


def initialize_langfuse_tracer() -> LangfuseTracer:
    """初始化新的Langfuse追踪器实例"""
    global _langfuse_tracer
    _langfuse_tracer = LangfuseTracer()
    return _langfuse_tracer
