"""
MCP服务器配置模块。

优先从环境变量 `FINANCE_MCP_SERVER_DIR` 读取 MCP 子项目目录；
若未配置，则退回到仓库相对路径，兼容本地开发与 Docker 部署。
"""

from __future__ import annotations

import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MCP_SERVER_DIR = _PROJECT_ROOT / "a-share-mcp-is-just-i-need"
_MCP_SERVER_DIR = os.getenv("FINANCE_MCP_SERVER_DIR") or str(_DEFAULT_MCP_SERVER_DIR)


SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            _MCP_SERVER_DIR,
            "python",
            "mcp_server.py",
        ],
        "transport": "stdio",
    }
}
