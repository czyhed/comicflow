from __future__ import annotations

from collections import Counter


class MetricsRegistry:
    """Small process-local metrics seam; production can scrape or forward these counters."""

    _stable_counters = (
        "health_checks_total",
        "generation_success_total",
        "generation_retry_total",
        "moderation_blocked_total",
        "export_failure_total",
        "stage_duration_ms_total",
        "unit_export_cost_credits_total",
    )

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()

    def increment(self, name: str) -> None:
        self._counters[name] += 1

    def snapshot(self) -> dict[str, int]:
        return {name: self._counters.get(name, 0) for name in self._stable_counters}
