"""Finance backend package bootstrap.

当前仓库仍采用非安装式 Agent 源码目录；在完成后续包治理前，只允许在此处集中
注册一次导入路径，禁止各业务模块继续散落 ``sys.path`` 修改。
"""

from pathlib import Path
import sys

_AGENT_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "Financial-MCP-Agent"
if str(_AGENT_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_PACKAGE_ROOT))
