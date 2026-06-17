"""
Redis 缓存层异常定义。
"""


class CacheUnavailableError(RuntimeError):
    """Redis 当前不可用（连接失败、超时或健康检查失败）。"""


class CacheVersionMismatchError(ValueError):
    """缓存版本不匹配（例如 payload_version 与调用方期望不一致）。"""

