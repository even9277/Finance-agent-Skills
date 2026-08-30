"""实现默认关闭、结果受限且不信任网页指令的 Tavily 新闻工具。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
import html
import json
import re
import socket
import threading
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from backend.config import Settings, settings as runtime_settings
from src.conversation.contracts import (
    EvidenceDimension,
    EvidenceFact,
    ToolCall,
    ToolObservation,
)
from src.conversation.errors import ToolPermanentError, ToolTimeoutError, ToolTransientError

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TRACKING_QUERY_NAMES = frozenset(
    {"fbclid", "gclid", "spm", "from", "source", "ref", "referrer"}
)
_INJECTION_TERMS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "call tool",
    "invoke tool",
    "reveal prompt",
    "忽略上文",
    "忽略之前",
    "系统提示词",
    "开发者消息",
    "调用工具",
    "泄露提示词",
)
_HTML_TAG = re.compile(r"<[^>]+>")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE = re.compile(r"\s+")
_PRIVATE_QUERY_PATTERNS = (
    re.compile(r"(?:持仓|成本价|金额|身份证|手机号|邮箱)[^，。；;]{0,24}"),
    re.compile(r"(?:api[_ -]?key|token|secret|password)[^，。；;\s]{0,32}", re.I),
)


@dataclass(frozen=True, slots=True)
class WebSearchHttpResponse:
    """HTTP 适配器返回的最小状态码与 JSON 信封。"""

    status_code: int
    payload: dict[str, Any]


class WebSearchTransport(Protocol):
    """隔离真实 HTTP 与离线测试的异步传输合同。"""

    async def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_sec: int,
    ) -> WebSearchHttpResponse:
        """发送 JSON POST 并返回已解析信封。"""
        ...


class UrllibWebSearchTransport:
    """使用 Python 标准库调用 Tavily，不引入新的生产依赖。"""

    async def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_sec: int,
    ) -> WebSearchHttpResponse:
        """在线程中执行有界 HTTP 请求并归一化网络异常。

        Args:
            url: 固定 Tavily Search Endpoint。
            headers: 包含只在传输层使用的授权头。
            payload: 经过 Provider 限制的搜索参数。
            timeout_sec: 单次请求超时秒数。

        Returns:
            状态码与 JSON 对象；不保留原始响应正文。

        Raises:
            ToolTimeoutError: 连接或读取超过显式超时。
            ToolTransientError: DNS、连接或不可识别的暂时网络故障。
        """

        def invoke() -> WebSearchHttpResponse:
            request = Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=timeout_sec) as response:  # noqa: S310
                    raw = response.read().decode("utf-8", errors="replace")
                    decoded = json.loads(raw or "{}")
                    body = decoded if isinstance(decoded, dict) else {}
                    return WebSearchHttpResponse(
                        status_code=int(response.status),
                        payload=body,
                    )
            except HTTPError as exc:
                # 不读取错误正文，避免第三方回显查询、密钥或不可控内容。
                return WebSearchHttpResponse(status_code=int(exc.code), payload={})
            except (TimeoutError, socket.timeout) as exc:
                raise ToolTimeoutError("web news request timed out") from exc
            except URLError as exc:
                if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                    raise ToolTimeoutError("web news request timed out") from exc
                raise ToolTransientError("web news network failure") from exc
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ToolTransientError("web news transport failure") from exc

        return await asyncio.to_thread(invoke)


class WebNewsQuotaGuard:
    """在进程内实施分钟速率和自然日总量的有界搜索配额。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._minute_timestamps: list[float] = []
        self._quota_day = date.today()
        self._daily_count = 0

    def reserve(self, *, rate_limit_per_min: int, daily_quota: int) -> None:
        """原子预留一次外部调用额度。

        Args:
            rate_limit_per_min: 滚动一分钟内允许的最大请求数。
            daily_quota: 当前进程自然日允许的最大请求数。

        Raises:
            ToolTransientError: 分钟速率或当日总量已耗尽。
        """
        now = time.monotonic()
        today = date.today()
        with self._lock:
            if today != self._quota_day:
                self._quota_day = today
                self._daily_count = 0
                self._minute_timestamps.clear()
            threshold = now - 60.0
            self._minute_timestamps = [
                timestamp for timestamp in self._minute_timestamps if timestamp >= threshold
            ]
            if len(self._minute_timestamps) >= rate_limit_per_min:
                raise ToolTransientError("web news minute quota is exhausted")
            if self._daily_count >= daily_quota:
                raise ToolTransientError("web news daily quota is exhausted")
            self._minute_timestamps.append(now)
            self._daily_count += 1


_PROCESS_QUOTA_GUARD = WebNewsQuotaGuard()


@dataclass(frozen=True, slots=True)
class _NormalizedNewsItem:
    """网页结果进入 EvidenceFact 前的安全中间结构。"""

    title: str
    url: str
    domain: str
    summary: str
    published_at: str
    retrieved_at: str
    source_type: str
    is_official: bool
    is_primary_source: bool
    confidence_hint: str


class TavilyWebNewsProvider:
    """执行唯一受治理的 Tavily 新闻搜索并返回弱证据事实。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: WebSearchTransport | None = None,
        quota_guard: WebNewsQuotaGuard | None = None,
    ) -> None:
        self._settings = settings or runtime_settings
        self._transport = transport or UrllibWebSearchTransport()
        self._quota_guard = quota_guard or _PROCESS_QUOTA_GUARD

    async def execute(self, call: ToolCall) -> ToolObservation:
        """执行默认关闭的只读搜索并剔除不可信网页指令。

        Args:
            call: Validator 已验收且只含公开最小查询的工具调用。

        Returns:
            由标题、链接、域名、短摘要和时间组成的扁平弱证据。

        Raises:
            ToolPermanentError: 功能关闭、密钥缺失、合同错误或客户端 HTTP 错误。
            ToolTransientError: 限流、服务端错误或暂时网络故障。
            ToolTimeoutError: 单次 HTTP 调用超时。
        """
        self._validate_call(call)
        if not self._settings.enable_web_news:
            raise ToolPermanentError("web news is disabled")
        api_key = self._settings.tavily_api_key.strip()
        if not api_key:
            raise ToolPermanentError("web news credential is missing")

        arguments = {item.name: item.value for item in call.arguments}
        query = _minimize_query(str(arguments.get("query") or ""))
        if not query:
            raise ToolPermanentError("web news query is blank")
        max_results = _bounded_integer(
            arguments.get("max_results"),
            default=self._settings.web_news_max_results,
            minimum=1,
            maximum=self._settings.web_news_max_results,
        )
        freshness_days = _bounded_integer(
            arguments.get("freshness_days"),
            default=self._settings.web_news_freshness_days,
            minimum=1,
            maximum=30,
        )
        payload: dict[str, object] = {
            "query": query,
            "topic": "news",
            "search_depth": "basic",
            "max_results": max_results,
            "time_range": _time_range(freshness_days),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "auto_parameters": False,
        }
        if self._settings.web_news_include_domains:
            payload["include_domains"] = list(self._settings.web_news_include_domains)
        if self._settings.web_news_exclude_domains:
            payload["exclude_domains"] = list(self._settings.web_news_exclude_domains)

        self._quota_guard.reserve(
            rate_limit_per_min=self._settings.web_news_rate_limit_per_min,
            daily_quota=self._settings.web_news_daily_quota,
        )
        response = await self._transport.post_json(
            url=_TAVILY_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            timeout_sec=self._settings.web_news_timeout_sec,
        )
        self._raise_for_status(response.status_code)
        items = self._normalize_results(
            response.payload.get("results"),
            max_results=max_results,
            freshness_days=freshness_days,
        )
        facts = tuple(
            fact
            for rank, item in enumerate(items, start=1)
            for fact in self._facts(rank, item, matched_entity=call.symbol)
        )
        return ToolObservation(
            step_id=call.step_id,
            tool_name=call.tool_name,
            symbol=call.symbol,
            evidence_dimension=call.evidence_dimension,
            facts=facts,
            source="tavily:search",
            observed_at=date.today(),
            attempts=1,
        )

    @staticmethod
    def _validate_call(call: ToolCall) -> None:
        if (
            call.tool_name != "search_web_news"
            or call.evidence_dimension is not EvidenceDimension.WEB_NEWS
        ):
            raise ToolPermanentError("web news call contract mismatch")

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code == 429 or status_code >= 500:
            raise ToolTransientError("web news provider is temporarily unavailable")
        if not 200 <= status_code < 300:
            raise ToolPermanentError("web news provider rejected the request")

    def _normalize_results(
        self,
        raw_results: object,
        *,
        max_results: int,
        freshness_days: int,
    ) -> tuple[_NormalizedNewsItem, ...]:
        """去重、域名过滤、截断摘要并丢弃疑似 Prompt Injection。"""
        if not isinstance(raw_results, list):
            return ()
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        today = date.today()
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        normalized: list[_NormalizedNewsItem] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            url = _canonical_url(str(raw.get("url") or ""))
            domain = _domain(url)
            if not url or not domain or not self._domain_allowed(domain):
                continue
            title = _clean_text(str(raw.get("title") or ""))
            summary = _clean_text(str(raw.get("content") or raw.get("snippet") or ""))
            published_at = _clean_text(
                str(raw.get("published_date") or raw.get("date") or "")
            )[:40]
            published_date = _parse_date(published_at)
            if (
                published_date is not None
                and not 0 <= (today - published_date).days <= freshness_days
            ):
                continue
            if not title or _injection_suspected(f"{title}\n{summary}"):
                continue
            title_key = _SPACE.sub("", title.casefold())
            if url in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(title_key)
            is_official = domain.endswith((".gov.cn", ".org.cn"))
            score = raw.get("score")
            confidence = "medium" if isinstance(score, (int, float)) and score >= 0.8 else "low"
            normalized.append(
                _NormalizedNewsItem(
                    title=title[:160],
                    url=url,
                    domain=domain,
                    summary=summary[: self._settings.web_news_max_summary_chars],
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    source_type="official" if is_official else "web_news",
                    is_official=is_official,
                    is_primary_source=is_official,
                    confidence_hint=confidence,
                )
            )
            if len(normalized) >= max_results:
                break
        return tuple(normalized)

    def _domain_allowed(self, domain: str) -> bool:
        excluded = self._settings.web_news_exclude_domains
        if any(_same_or_subdomain(domain, item) for item in excluded):
            return False
        included = self._settings.web_news_include_domains
        return not included or any(_same_or_subdomain(domain, item) for item in included)

    @staticmethod
    def _facts(
        rank: int,
        item: _NormalizedNewsItem,
        *,
        matched_entity: str,
    ) -> tuple[EvidenceFact, ...]:
        prefix = f"W{rank}"
        return (
            EvidenceFact(key=f"{prefix}.title", value=item.title),
            EvidenceFact(key=f"{prefix}.url", value=item.url),
            EvidenceFact(key=f"{prefix}.domain", value=item.domain),
            EvidenceFact(key=f"{prefix}.source_type", value=item.source_type),
            EvidenceFact(key=f"{prefix}.published_at", value=item.published_at or "unknown"),
            EvidenceFact(key=f"{prefix}.retrieved_at", value=item.retrieved_at),
            EvidenceFact(key=f"{prefix}.is_official", value=str(item.is_official).lower()),
            EvidenceFact(
                key=f"{prefix}.is_primary_source",
                value=str(item.is_primary_source).lower(),
            ),
            EvidenceFact(key=f"{prefix}.matched_entities", value=matched_entity or "query"),
            EvidenceFact(key=f"{prefix}.summary", value=item.summary or "no summary"),
            EvidenceFact(key=f"{prefix}.confidence_hint", value=item.confidence_hint),
        )


def _bounded_integer(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(value, maximum))


def _time_range(freshness_days: int) -> str:
    if freshness_days <= 1:
        return "day"
    if freshness_days <= 7:
        return "week"
    if freshness_days <= 30:
        return "month"
    return "year"


def _clean_text(value: str) -> str:
    without_html = _HTML_TAG.sub(" ", html.unescape(value))
    without_control = _CONTROL_CHARACTER.sub(" ", without_html)
    return _SPACE.sub(" ", without_control).strip()


def _minimize_query(value: str) -> str:
    minimized = _clean_text(value)
    for pattern in _PRIVATE_QUERY_PATTERNS:
        minimized = pattern.sub(" ", minimized)
    return _SPACE.sub(" ", minimized).strip()[:120]


def _injection_suspected(value: str) -> bool:
    normalized = value.casefold()
    return any(term in normalized for term in _INJECTION_TERMS)


def _canonical_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    query = urlencode(
        [
            (name, item)
            for name, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not name.lower().startswith("utm_")
            and name.lower() not in _TRACKING_QUERY_NAMES
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", query, ""))


def _domain(value: str) -> str:
    try:
        return (urlsplit(value).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _same_or_subdomain(domain: str, policy_domain: str) -> bool:
    return domain == policy_domain or domain.endswith(f".{policy_domain}")


def _parse_date(value: str) -> date | None:
    normalized = value.strip()[:10]
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


__all__ = [
    "TavilyWebNewsProvider",
    "UrllibWebSearchTransport",
    "WebNewsQuotaGuard",
    "WebSearchHttpResponse",
    "WebSearchTransport",
]
