"""离线 E2E 使用的最小 Fake Provider，实现与真实依赖相同的调用意图。"""

from dataclasses import dataclass, field


@dataclass
class FakeModelProvider:
    """返回固定答案或可控异常的模型替身。"""

    reply: str = "fake-provider: answer"
    calls: list[str] = field(default_factory=list)

    async def complete(self, prompt: str) -> str:
        """记录一次模型调用并返回固定结果。"""
        self.calls.append(prompt)
        return self.reply


@dataclass
class FakeToolProvider:
    """返回固定只读金融数据的工具替身。"""

    calls: list[str] = field(default_factory=list)

    async def read_market_data(self, symbol: str) -> dict[str, str]:
        """模拟一个只读行情工具，不产生外部副作用。"""
        self.calls.append(symbol)
        return {"symbol": symbol, "close": "100.00", "as_of": "2026-01-01"}


@dataclass
class FakeMcpProvider:
    """模拟只读 MCP 资源查询。"""

    calls: list[str] = field(default_factory=list)

    async def read_resource(self, resource: str) -> str:
        """记录资源名并返回固定内容。"""
        self.calls.append(resource)
        return f"fake-resource:{resource}"
