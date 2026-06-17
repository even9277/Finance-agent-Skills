"""
Redis Key 统一生成器。

所有 Key 必须经过该类生成，避免业务层手拼字符串导致规则漂移。
"""

from __future__ import annotations


class KeyBuilder:
    NAMESPACE = "finagent"

    def __init__(self, env: str) -> None:
        env_clean = (env or "").strip()
        if not env_clean:
            raise ValueError("env 不能为空")
        self.env = env_clean

    def _join(self, *parts: str) -> str:
        clean_parts = []
        for part in parts:
            token = (part or "").strip()
            if not token:
                raise ValueError("key 组成部分不能为空")
            clean_parts.append(token)
        return ":".join((self.NAMESPACE, self.env, *clean_parts))

    def stm_state(self, user_id: str, session_id: str) -> str:
        return self._join("stm", "state", user_id, session_id)

    def stm_tail(self, user_id: str, session_id: str) -> str:
        return self._join("stm", "tail", user_id, session_id)

    def stm_summary(self, user_id: str, session_id: str) -> str:
        return self._join("stm", "summary", user_id, session_id)

    def report_idempotency(self, user_id: str, stock_code: str, query_hash: str) -> str:
        return self._join("report", "idempotency", user_id, stock_code, query_hash)

    def report_idempotency_by_user_query(self, user_id: str, query_hash: str) -> str:
        return self._join("report", "idempotency", user_id, query_hash)

    def report_status(self, task_id: str) -> str:
        return self._join("report", "status", task_id)

    def lock(self, name: str) -> str:
        return self._join("lock", name)

    def demo(self, item_id: str) -> str:
        return self._join("demo", "item", item_id)
