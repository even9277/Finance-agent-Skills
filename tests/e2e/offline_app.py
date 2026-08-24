"""离线 Compose 验收专用 FastAPI 应用装配。"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.main import app
from backend.services import chat_service

__all__ = ["app"]


async def offline_chat_single_turn(
    *,
    db: AsyncSession,
    user_id: str,
    user_message: str,
    session_id: str | None = None,
) -> tuple[str, str, None, None]:
    """返回确定性聊天结果，阻止离线验收访问模型或生产服务。

    Args:
        db: 由真实 FastAPI 依赖注入创建的隔离测试数据库会话。
        user_id: 离线测试用户标识。
        user_message: 通过前端 Nginx 代理传入的固定测试问题。
        session_id: 可选会话标识；为空时返回固定离线会话。

    Returns:
        与生产聊天服务相同的四元组响应契约。
    """
    del db, user_id, user_message
    return "fake-provider: answer", session_id or "offline-session", None, None


# 该装配只由离线测试镜像导入，生产仍使用 backend.main:app。
chat_service.chat_single_turn = offline_chat_single_turn
