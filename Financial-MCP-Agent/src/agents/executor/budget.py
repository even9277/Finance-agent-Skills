from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass(slots=True)
class ExecutionBudget:
    per_tool_timeout_ms: int = 8000
    per_tool_retry_limit: int = 1
    max_steps: int = 8
    total_timeout_ms: int = 25000
    max_replans: int = 1
    max_concurrency: int = 6
    per_api_family_limit: int = 2
    min_interval_ms: int = 150


@dataclass(slots=True)
class RuntimeBudgetState:
    budget: ExecutionBudget
    started_perf: float = field(default_factory=time.perf_counter)
    replan_attempts: int = 0

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started_perf) * 1000)

    def remaining_ms(self) -> int:
        return max(0, int(self.budget.total_timeout_ms - self.elapsed_ms()))

    def can_replan(self) -> bool:
        return self.replan_attempts < self.budget.max_replans and self.remaining_ms() > 0


__all__ = ["ExecutionBudget", "RuntimeBudgetState"]
