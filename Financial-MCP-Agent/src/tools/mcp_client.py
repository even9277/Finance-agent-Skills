# ============================================================================
# MCP客户端模块 - 负责连接MCP服务器并获取可用工具
# ============================================================================

# 导入必要的模块
from langchain_mcp_adapters.client import MultiServerMCPClient  # MCP多服务器客户端
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON  # 日志工具
from src.tools.mcp_config import SERVER_CONFIGS  # MCP服务器配置
import asyncio  # 异步操作支持，MCP工具获取是异步的
import json  # JSON数据处理

# 设置日志记录器
logger = setup_logger(__name__)

# 全局变量：用于缓存MCP客户端实例和工具列表
# 这样可以避免重复初始化和连接，提高性能
_mcp_client_instance = None  # MCP客户端实例缓存
_mcp_tools = None  # 工具列表缓存


def print_tool_details(tools):
    """
    打印工具的详细信息，用于调试和了解可用工具
    
    这个函数会遍历所有从MCP服务器获取的工具，并打印它们的详细信息，
    包括名称、描述、参数结构等，帮助开发者了解可用的功能。
    
    参数：
        tools: 从MCP服务器获取的工具列表
    """
    logger.info(f"{SUCCESS_ICON} 工具详细信息:")
    
    # 遍历每个工具，打印详细信息
    for i, tool in enumerate(tools, 1):
        logger.info(f"  {i}. 工具名称: {tool.name}")
        logger.info(f"     描述: {tool.description}")

        # 打印工具的输入参数结构（如果存在）
        # 这些属性包含了工具的参数定义，帮助理解如何调用工具
        for attr in ['input_schema', 'parameters', 'schema']:
            if hasattr(tool, attr):
                attr_value = getattr(tool, attr)
                if attr_value:
                    logger.info(f"     {attr}: {attr_value}")

        logger.info(f"     工具类型: {type(tool)}")
        # 如果需要查看工具的所有属性，可以取消注释下面这行
        # logger.info(f"     所有属性: {dir(tool)}")
        logger.info("     " + "-" * 50)


async def get_mcp_tools():
    """
    核心函数：获取MCP工具列表
    
    这个函数是整个MCP工具集成的核心，负责：
    1. 初始化MCP客户端连接
    2. 从A股MCP服务器获取可用工具
    3. 缓存工具列表以提高性能
    4. 处理连接和加载错误
    
    工作流程：
    1. 检查缓存 - 如果工具已加载，直接返回
    2. 初始化客户端 - 使用配置连接到MCP服务器
    3. 获取工具 - 从服务器获取可用工具列表
    4. 缓存结果 - 将工具列表缓存到全局变量
    5. 返回工具 - 返回LangChain兼容的工具列表

    返回:
        list: 从MCP服务器加载的LangChain兼容工具列表
              如果初始化或工具加载失败，则返回空列表
    """
    global _mcp_client_instance, _mcp_tools

    # 步骤1：检查缓存 - 如果工具已经加载过，直接返回缓存的结果
    if _mcp_tools is not None:
        logger.info(f"{SUCCESS_ICON} Returning cached MCP tools.")
        return _mcp_tools

    # 步骤2：初始化MCP客户端
    logger.info(f"{WAIT_ICON} Initializing MultiServerMCPClient with config: {SERVER_CONFIGS}")
    try:
        # 创建多服务器MCP客户端实例
        # 这个客户端可以同时连接多个MCP服务器
        _mcp_client_instance = MultiServerMCPClient(SERVER_CONFIGS)

        # 步骤3：从服务器获取工具列表
        logger.info(f"{WAIT_ICON} Fetching tools from MCP server 'a_share_mcp_v2'...")
        # get_tools()方法是异步的，需要使用await
        loaded_tools = await _mcp_client_instance.get_tools()

        # 步骤4：验证工具加载结果
        if not loaded_tools:
            logger.warning(f"{ERROR_ICON} No tools loaded from MCP server 'a_share_mcp_v2'. Check server logs and configuration.")
            _mcp_tools = []  # 缓存空列表，避免重复尝试
            return []

        # 步骤5：缓存成功加载的工具
        _mcp_tools = loaded_tools
        logger.info(f"{SUCCESS_ICON} Successfully loaded {len(_mcp_tools)} tools from 'a_share_mcp_v2'.")

        # 可选：打印工具名称列表（用于调试）
        # tool_names = [tool.name for tool in _mcp_tools]
        # logger.info(f"工具名称列表: {tool_names}")

        # 可选：打印详细的工具信息（用于调试）
        # print_tool_details(_mcp_tools)

        return _mcp_tools

    except Exception as e:
        # 错误处理：记录错误并返回空列表
        logger.error(f"{ERROR_ICON} Failed to initialize MCP client or load tools: {e}", exc_info=True)
        _mcp_tools = []  # 缓存空列表，避免重复尝试
        return []


async def close_mcp_client_sessions():
    """
    关闭MultiServerMCPClient管理的任何开放会话。
    如果必要，应在应用程序关闭时调用此函数。
    """
    global _mcp_client_instance
    if _mcp_client_instance:
        logger.info(f"{WAIT_ICON} Closing MCP client sessions...")
        try:
            logger.info(
                f"{SUCCESS_ICON} MCP client sessions (if any were persistently open) assumed closed or managed by library.")
            _mcp_client_instance = None   # 允许重新初始化
            global _mcp_tools
            _mcp_tools = None
        except Exception as e:
            logger.error(
                f"{ERROR_ICON} Error during MCP client session cleanup: {e}", exc_info=True)
    else:
        logger.info("MCP client was not initialized, no sessions to close.")


# 测试此模块的示例（可选，用于直接执行）
async def _main_test_mcp_client():
    logger.info("--- Testing MCP Client Tool Loading ---")
    tools = await get_mcp_tools()
    if tools:
        print(f"Successfully loaded {len(tools)} tools:")
        for tool in tools:
            print(
                f"- Name: {tool.name}")

        # 测试一个简单的工具调用（如果有合适的工具）
        if tools:
            logger.info("--- Testing Tool Call ---")
            # 尝试调用第一个工具（需要根据实际工具调整参数）
            first_tool = tools[0]
            logger.info(f"尝试调用工具: {first_tool.name}")

            # 这里需要根据实际的工具参数schema来构造测试参数
            # 暂时跳过实际调用，只是展示结构
            logger.info("工具调用测试跳过（需要实际参数）")
    else:
        print("Failed to load tools or no tools found.")

    # 测试关闭（如果适用）
    await close_mcp_client_sessions()
    logger.info("--- MCP Client Test Complete ---")

if __name__ == '__main__':
    # 这允许直接运行测试，例如：python -m src.tools.mcp_client
    # 确保您的环境已设置（例如，'uv'命令可用）。
    # E:\github\a_share_mcp的a_share_mcp服务器应该准备好运行。

    # 如果尚未配置，为测试运行设置基本日志记录
    if not logger.hasHandlers():
        import logging
        logging.basicConfig(level=logging.INFO)
        logger.info("Basic logging configured for test run.")

    asyncio.run(_main_test_mcp_client())
