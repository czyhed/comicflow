from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    provider: str
    model: str
    config_version: str
    sample_count: int
    metrics: dict[str, float]
    external_cost: float
    failure_rate: float
    license_confirmed: bool

    def require_real_mode(self) -> None:
        required = {"quality", "latency_ms", "concurrency", "cost"}
        if (
            self.provider == "mock"
            or self.sample_count < 2
            or not required.issubset(self.metrics)
            or self.failure_rate > 0.1
            or not self.license_confirmed
        ):
            raise RuntimeError("PROVIDER_EVALUATION_REQUIRED")


def evaluate_mock_provider() -> EvaluationReport:
    return EvaluationReport(
        provider="mock",
        model="mock-v1",
        config_version="local",
        sample_count=2,
        metrics={
            "quality": 1.0,
            "latency_ms": 0.0,
            "concurrency": 1.0,
            "cost": 0.0,
        },
        external_cost=0,
        failure_rate=0,
        license_confirmed=True,
    )
