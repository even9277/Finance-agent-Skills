# ============================================================================
# LangGraph状态定义模块 - 定义智能体工作流中的状态结构
# ============================================================================

# 导入必要的类型定义和工具
from typing import TypedDict, Sequence, Dict, Any, Annotated, Optional  # 类型注解工具
from typing import NotRequired  # Python 3.11+：TypedDict 可选字段
from langchain_core.messages import BaseMessage  # LangChain消息基类
import operator  # Python操作符模块，用于定义状态合并规则


def merge_dicts(d1: Dict[str, Any], d2: Dict[str, Any]) -> Dict[str, Any]:
    """
    字典合并函数 - 用于LangGraph状态管理中的data和metadata字段合并
    
    功能说明：
    - 当多个智能体节点更新状态时，LangGraph需要知道如何合并这些更新
    - 这个函数定义了合并规则：d2的值会覆盖d1中相同的键
    - 例如：d1={"a":1, "b":2}, d2={"b":3, "c":4} -> 结果={"a":1, "b":3, "c":4}
    
    参数：
        d1: 第一个字典（原有状态）
        d2: 第二个字典（新状态）
    
    返回：
        合并后的字典
    """
    return {**d1, **d2}  # 使用字典解包语法合并，d2优先


class AgentState(TypedDict):
    """
    AgentState - LangGraph工作流的状态定义类
    
    这是整个多智能体系统的核心状态结构，定义了在智能体之间传递的数据格式。
    每个智能体节点都会接收这个状态，处理后再返回更新后的状态。
    
    状态字段说明：
    """
    
    # messages字段：存储对话消息序列
    # - 类型：BaseMessage对象的序列（列表）
    # - 合并规则：operator.add - 新消息会追加到现有消息列表后面
    # - 用途：记录整个对话历史，包括用户查询、智能体回复、工具调用等
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # data字段：存储应用特定的数据
    # - 类型：任意键值对的字典
    # - 合并规则：merge_dicts - 新数据会覆盖或补充现有数据
    # - 用途：存储股票代码、公司名称、分析结果、时间信息等业务数据
    data: Annotated[Dict[str, Any], merge_dicts]
    
    # metadata字段：存储元数据信息
    # - 类型：任意键值对的字典
    # - 合并规则：merge_dicts - 新元数据会覆盖或补充现有元数据
    # - 用途：存储执行时间、错误信息、调试信息等系统级数据
    metadata: Annotated[Dict[str, Any], merge_dicts]
    
    # ── Phase 2 新增：STM（短期记忆）字段 ──────────────────────
    # 使用 NotRequired 使字段可选，现有代码无需传入这些字段，兼容性不受影响。

    # running_summary: 滑动窗口外的早期对话被压缩后存储于此
    # 触发条件：turn_count >= 10 或 token_estimate >= 6000
    running_summary: NotRequired[str]

    # recent_tool_digest: analyst 工具输出的精炼摘要
    # 只保留：最终结论 + 关键数值 + 证据 ID，不保留原始财务表/新闻段落
    recent_tool_digest: NotRequired[str]

    # thread_meta: 线程级元数据，记录轮次和 token 估算，供压缩触发判断
    # 结构：{turn_count: int, token_estimate: int, last_compress_at: str}
    thread_meta: NotRequired[Dict[str, Any]]

    # ── Phase 3 预留：LTM（长期记忆）字段 ──────────────────────
    # 以下字段 Phase 3 激活，Phase 2 保持为空默认值

    # memory_user_id: 用户标识，对应 Mem0 user_id
    memory_user_id: NotRequired[str]

    # memory_context: Mem0 召回的长期画像（Phase 3 注入点）
    memory_context: NotRequired[Dict[str, Any]]


def make_stm_defaults() -> Dict[str, Any]:
    """返回所有 STM/LTM 字段的默认值，供初始化状态时使用。"""
    return {
        "running_summary": "",
        "recent_tool_digest": "",
        "thread_meta": {"turn_count": 0, "token_estimate": 0, "last_compress_at": None},
        "memory_user_id": "",
        "memory_context": {},
    }
