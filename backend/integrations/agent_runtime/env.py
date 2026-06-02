from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_ENV_LOADED = False


def agent_root() -> Path:
    return Path(__file__).resolve().parents[3] / "Financial-MCP-Agent"


def ensure_agent_env_loaded() -> Path:
    global _ENV_LOADED
    root = agent_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    if not _ENV_LOADED:
        load_dotenv(str(root / ".env"), override=False)
        _ENV_LOADED = True
    return root
