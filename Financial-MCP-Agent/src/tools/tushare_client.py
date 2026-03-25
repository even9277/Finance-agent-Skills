from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from cachetools import TTLCache
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.utils.logging_config import setup_logger

logger = setup_logger("tushare_client")


class TushareClientError(RuntimeError):
    """Raised when tushare client cannot fulfill a request."""


@dataclass(slots=True)
class _CachedResult:
    value: Any
    cached_at: float


class TushareClient:
    def __init__(
        self,
        *,
        token: str,
        ttl_seconds: int = 120,
        min_interval_seconds: float = 0.2,
        timeout_seconds: float = 20.0,
    ):
        self.token = token.strip()
        self.ttl_seconds = ttl_seconds
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._cache: TTLCache[str, _CachedResult] = TTLCache(maxsize=256, ttl=ttl_seconds)
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._pro = None

    async def stock_basic(self, **kwargs):
        return await self._call_api("stock_basic", **kwargs)

    async def daily(self, **kwargs):
        return await self._call_api("daily", **kwargs)

    async def fina_indicator(self, **kwargs):
        return await self._call_api("fina_indicator", **kwargs)

    async def income(self, **kwargs):
        return await self._call_api("income", **kwargs)

    async def balancesheet(self, **kwargs):
        return await self._call_api("balancesheet", **kwargs)

    async def cashflow(self, **kwargs):
        return await self._call_api("cashflow", **kwargs)

    async def fund_basic(self, **kwargs):
        return await self._call_api("fund_basic", **kwargs)

    async def fund_nav(self, **kwargs):
        return await self._call_api("fund_nav", **kwargs)

    async def fund_daily(self, **kwargs):
        return await self._call_api("fund_daily", **kwargs)

    async def fund_share(self, **kwargs):
        return await self._call_api("fund_share", **kwargs)

    async def etf_basic(self, **kwargs):
        return await self._call_api("etf_basic", **kwargs)

    async def index_classify(self, **kwargs):
        return await self._call_api("index_classify", **kwargs)

    async def sw_daily(self, **kwargs):
        return await self._call_api("sw_daily", **kwargs)

    async def index_member(self, **kwargs):
        return await self._call_api("index_member", **kwargs)

    async def pro_bar(self, **kwargs):
        cache_key = self._build_cache_key("pro_bar", kwargs)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached.value

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            retry=retry_if_exception_type(TushareClientError),
            reraise=True,
        ):
            with attempt:
                result = await asyncio.wait_for(
                    self._call_pro_bar_once(**kwargs),
                    timeout=self.timeout_seconds,
                )
                self._cache[cache_key] = _CachedResult(value=result, cached_at=time.time())
                return result

    async def _call_api(self, method_name: str, **kwargs):
        cache_key = self._build_cache_key(method_name, kwargs)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached.value

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            retry=retry_if_exception_type(TushareClientError),
            reraise=True,
        ):
            with attempt:
                result = await asyncio.wait_for(
                    self._call_api_once(method_name, **kwargs),
                    timeout=self.timeout_seconds,
                )
                self._cache[cache_key] = _CachedResult(value=result, cached_at=time.time())
                return result

    async def _call_api_once(self, method_name: str, **kwargs):
        pro = await self._get_pro_client()
        method = getattr(pro, method_name, None)
        if method is None:
            raise TushareClientError(f"Unsupported tushare method: {method_name}")

        async with self._lock:
            now = time.monotonic()
            wait_seconds = self.min_interval_seconds - (now - self._last_request_at)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

        try:
            return await asyncio.to_thread(method, **kwargs)
        except Exception as exc:
            logger.warning("[tushare_client] %s failed: %s", method_name, exc)
            raise TushareClientError(str(exc)) from exc

    async def _call_pro_bar_once(self, **kwargs):
        if not self.token:
            raise TushareClientError("Missing Tushare token")
        try:
            import tushare as ts
        except ImportError as exc:
            raise TushareClientError("tushare is not installed") from exc

        async with self._lock:
            now = time.monotonic()
            wait_seconds = self.min_interval_seconds - (now - self._last_request_at)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

        def _invoke():
            ts.set_token(self.token)
            return ts.pro_bar(**kwargs)

        try:
            return await asyncio.to_thread(_invoke)
        except Exception as exc:
            logger.warning("[tushare_client] pro_bar failed: %s", exc)
            raise TushareClientError(str(exc)) from exc

    async def _get_pro_client(self):
        if self._pro is not None:
            return self._pro
        if not self.token:
            raise TushareClientError("Missing Tushare token")
        try:
            import tushare as ts
        except ImportError as exc:
            raise TushareClientError("tushare is not installed") from exc

        def _init():
            ts.set_token(self.token)
            return ts.pro_api()

        try:
            self._pro = await asyncio.to_thread(_init)
            logger.info("[tushare_client] initialized pro client")
            return self._pro
        except Exception as exc:
            logger.error("[tushare_client] init failed: %s", exc, exc_info=True)
            raise TushareClientError("Failed to initialize Tushare client") from exc

    @staticmethod
    def _build_cache_key(method_name: str, kwargs: dict[str, Any]) -> str:
        parts = [method_name]
        for key in sorted(kwargs):
            parts.append(f"{key}={kwargs[key]}")
        return "|".join(parts)


_client_factory: Callable[[], TushareClient] | None = None
_client_singleton: TushareClient | None = None


def configure_tushare_client_factory(factory: Callable[[], TushareClient] | None) -> None:
    global _client_factory, _client_singleton
    _client_factory = factory
    _client_singleton = None


def get_tushare_client(token: str | None = None) -> TushareClient:
    global _client_singleton
    env_token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    effective_token = (token or env_token).strip()

    if _client_singleton is not None:
        if _client_singleton.token:
            return _client_singleton
        if effective_token:
            _client_singleton = TushareClient(token=effective_token)
            return _client_singleton
        return _client_singleton

    if _client_factory is not None:
        _client_singleton = _client_factory()
        return _client_singleton

    _client_singleton = TushareClient(token=effective_token)
    return _client_singleton
