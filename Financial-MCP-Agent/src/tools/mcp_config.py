"""
MCP服务器配置模块 - 包含连接A股MCP服务器的配置信息
部署时请将 --directory 改为你机器上 a-share-mcp-is-just-i-need 的绝对路径（Linux/WSL 路径）。
"""

SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            "/root/Finance/a-share-mcp-is-just-i-need",  # 改为你的项目根目录/a-share-mcp-is-just-i-need 绝对路径
            "python",
            "mcp_server.py"
        ],
        "transport": "stdio",
    }
}