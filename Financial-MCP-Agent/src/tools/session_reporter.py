"""
会话 Markdown 报告生成器

功能说明：
  每次对话完成后，将本轮对话的关键信息（用户提问、系统回答摘要、各阶段耗时）
  追加写入一份按会话 ID 命名的 Markdown 文件，方便人工复盘和问题排查。

文件路径规则：
  logs/session_reports/{session_id}.md

开关控制：
  ENABLE_SESSION_REPORT=false 时，所有写入操作静默跳过，不影响主流程。
  同时依赖 ENABLE_SKILL_TRACE，总开关关闭时也不生效。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logging_config import setup_logger

logger = setup_logger("session_reporter")

_REPORT_LOCK = threading.Lock()

# 阶段名称到中文标签的映射，便于报告可读
_STAGE_LABELS: dict[str, str] = {
    "route_stage1": "路由判断",
    "route_stage1_heuristic": "路由判断(规则)",
    "entity_resolve": "实体解析",
    "query_rewrite": "查询改写",
    "plan_generate": "计划生成",
    "tool_call": "工具执行",
    "evidence_verify": "证据核验",
    "synthesis": "回答合成",
    "replan": "重规划",
    "memory_read": "记忆读取",
    "memory_write": "记忆写入",
}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _report_enabled() -> bool:
    """只有总开关和会话报告开关同时开启才写报告"""
    return _bool_env("ENABLE_SKILL_TRACE", True) and _bool_env("ENABLE_SESSION_REPORT", True)


def _report_root() -> Path:
    """报告文件存放目录，可通过环境变量自定义"""
    configured = os.getenv("SESSION_REPORT_DIR", "").strip()
    if configured:
        return Path(configured)
    # 默认放在 Financial-MCP-Agent/logs/session_reports/
    return Path(__file__).resolve().parents[2] / "logs" / "session_reports"


def _report_path(session_id: str) -> Path:
    safe_id = str(session_id or "unknown").replace("/", "_").replace("..", "_")
    return _report_root() / f"{safe_id}.md"


def _now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _format_duration(ms: Any) -> str:
    """将毫秒数格式化为可读字符串"""
    try:
        val = float(ms)
    except (TypeError, ValueError):
        return "—"
    if val < 1000:
        return f"{val:.0f}ms"
    return f"{val / 1000:.2f}s"


def _truncate(text: str, max_chars: int = 200) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _build_file_header(session_id: str) -> str:
    """生成报告文件的第一行（仅在文件新建时写入）"""
    return (
        f"# 会话报告 · {session_id}\n\n"
        f"_首条消息时间：{_now_str()}_\n\n"
        "---\n\n"
    )


def _build_stage_table(span_records: list[dict[str, Any]]) -> tuple[str, float]:
    """
    从 span_records 列表中提取各阶段耗时，构建 Markdown 表格。
    返回 (表格字符串, 总耗时ms)
    """
    # 只取 span 类型记录，避免 event 类型混入
    spans = [r for r in (span_records or []) if r.get("name") and r.get("duration_ms") is not None]

    if not spans:
        return "_（无阶段耗时数据）_\n", 0.0

    rows: list[tuple[str, str, str]] = []
    total_ms = 0.0

    for span in spans:
        name = str(span.get("name") or "")
        label = _STAGE_LABELS.get(name, name)
        duration_ms = span.get("duration_ms") or 0
        status = str(span.get("status") or "ok")
        total_ms += float(duration_ms)

        # 结果列：根据 status 和 data 拼出易读描述
        data = span.get("data") or {}
        result_parts: list[str] = []
        if status == "error":
            result_parts.append("❌ 失败")
        else:
            result_parts.append("✓")

        # 附加有意义的 data 字段
        if name in ("route_stage1", "route_stage1_heuristic"):
            outcome = data.get("outcome") or data.get("method") or ""
            skill = data.get("skill_id") or ""
            if skill:
                result_parts.append(f"→ {skill}")
            elif outcome:
                result_parts.append(outcome)
        elif name == "entity_resolve":
            top = data.get("top_entity") or data.get("inherited_entity") or ""
            if top:
                result_parts.append(top)
        elif name == "plan_generate":
            planner = data.get("planner_type") or ""
            skill = data.get("skill_name") or ""
            if skill:
                result_parts.append(f"{planner}/{skill}")
            elif planner:
                result_parts.append(planner)
        elif name == "evidence_verify":
            total = data.get("total_steps") or 0
            result_parts.append(f"{total}步")
        elif name == "synthesis":
            mode = data.get("mode") or ""
            if mode:
                result_parts.append(mode)

        rows.append((label, _format_duration(duration_ms), " ".join(result_parts)))

    lines = [
        "| 阶段 | 耗时 | 结果 |",
        "|------|------|------|",
    ]
    for label, dur, res in rows:
        lines.append(f"| {label} | {dur} | {res} |")

    table = "\n".join(lines) + "\n"
    return table, total_ms


def _build_turn_section(
    turn_index: int,
    user_message: str,
    reply_summary: str,
    span_records: list[dict[str, Any]],
) -> str:
    """构建单轮对话的 Markdown 章节"""
    now = _now_str()
    stage_table, total_ms = _build_stage_table(span_records)

    lines = [
        f"## 第 {turn_index} 轮对话 · {now}",
        "",
        f"**用户提问：** {_truncate(user_message, 300)}",
        "",
        f"**系统回答：** {_truncate(reply_summary, 200)}",
        "",
        "**执行概览：**",
        "",
        stage_table,
        f"**总耗时：** {_format_duration(total_ms)}",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def append_turn_to_session_report(
    session_id: str,
    turn_index: int,
    user_message: str,
    reply_summary: str,
    span_records: list[dict[str, Any]] | None = None,
) -> None:
    """
    将一轮对话追加到会话 Markdown 报告文件中。

    参数说明：
      session_id   - 会话唯一标识，用作文件名
      turn_index   - 当前是会话的第几轮对话（从 1 开始）
      user_message - 用户发送的原始消息
      reply_summary - 系统回答的前200字摘要（由调用方截取或直接传全文）
      span_records  - 本轮产生的所有 trace span 记录列表（每个元素是 dict）

    副作用：
      - 在 logs/session_reports/{session_id}.md 追加内容
      - ENABLE_SESSION_REPORT=false 时静默跳过
      - 写入失败时记录 warning 日志，不抛出异常
    """
    if not _report_enabled():
        return

    try:
        path = _report_path(session_id)
        turn_text = _build_turn_section(
            turn_index=turn_index,
            user_message=user_message,
            reply_summary=reply_summary,
            span_records=span_records or [],
        )

        with _REPORT_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            is_new = not path.exists()
            with path.open("a", encoding="utf-8") as fp:
                if is_new:
                    fp.write(_build_file_header(session_id))
                fp.write(turn_text)

        logger.info(
            "session_reporter.turn_written %s",
            {"session_id": str(session_id)[:16], "turn_index": turn_index, "path": str(path)},
        )
    except Exception as exc:
        logger.warning(
            "session_reporter.write_failed %s",
            {"session_id": str(session_id)[:16], "error": str(exc)},
        )


__all__ = ["append_turn_to_session_report"]
