import pytest
from comicflow.providers.evaluation import EvaluationReport, evaluate_mock_provider


def test_mock_evaluation_report_is_reproducible_and_zero_cost() -> None:
    first = evaluate_mock_provider()
    second = evaluate_mock_provider()

    assert first == second
    assert first.provider == "mock"
    assert first.external_cost == 0
    assert first.sample_count == 2
    assert first.failure_rate == 0
    assert first.metrics["quality"] == 1.0


def test_incomplete_report_cannot_pass_real_mode_gate() -> None:
    report = EvaluationReport(
        provider="real",
        model="visual-v1",
        config_version="1",
        sample_count=2,
        metrics={"quality": 0.9},
        external_cost=1,
        failure_rate=0,
        license_confirmed=False,
    )

    with pytest.raises(RuntimeError, match="PROVIDER_EVALUATION_REQUIRED"):
        report.require_real_mode()

