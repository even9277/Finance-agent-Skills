"""根据本轮证据需求生成只读工具权限快照。"""

from __future__ import annotations

from .contracts import EvidenceDimension, RewriteResult, ToolPermissionSnapshot

_DIMENSION_TO_TOOL = {
    EvidenceDimension.BASIC_PROFILE: "stock_basic",
    EvidenceDimension.MARKET_SNAPSHOT: "pro_bar",
}


class DeterministicPermissionResolver:
    """把业务允许、已发现和可执行工具收敛为最小白名单。"""

    def resolve(self, rewrite: RewriteResult) -> ToolPermissionSnapshot:
        """创建 Planner 唯一可见的请求级工具快照。

        Args:
            rewrite: 已校验的证据需求。

        Returns:
            排序稳定、带版本与 hash 的权限快照。
        """
        tools = tuple(_DIMENSION_TO_TOOL[item] for item in rewrite.requested_dimensions)
        return ToolPermissionSnapshot.create(
            allowed_tools=tools,
            source="controlled-chat-m2",
            version="readonly-stock-tools-v1",
        )


def tool_for_dimension(dimension: EvidenceDimension) -> str:
    """返回 M2 证据维度唯一对应的只读工具名。"""
    return _DIMENSION_TO_TOOL[dimension]
