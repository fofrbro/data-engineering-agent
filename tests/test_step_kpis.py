import pandas as pd

from src.audit_analysis import calculate_step_kpis


def test_step_kpis():
    steps = pd.DataFrame(
        {
            "step_name": ["validate_csv", "validate_csv", "quarantine_csv", "inspect_csv"],
            "status": ["SUCCESS", "FAILED", "QUARANTINED", "SUCCESS"],
            "duration_seconds": [0.5, 1.5, 0.2, None],
        }
    )

    kpis = calculate_step_kpis(steps)
    by_step = {row["step_name"]: row for row in kpis["by_step"]}

    assert kpis["total_steps"] == 4
    assert kpis["failed_steps"] == 1
    assert kpis["step_success_rate"] == 0.75
    assert kpis["average_step_duration_seconds"] == 0.7333333333333334
    assert by_step["validate_csv"]["success_rate"] == 0.5
    # Une mise en quarantaine est une action réussie.
    assert by_step["quarantine_csv"]["success_rate"] == 1.0
    # Aucune durée connue : inconnue plutôt que 0.
    assert by_step["inspect_csv"]["average_duration_seconds"] is None


def test_step_kpis_for_legacy_steps_without_duration():
    steps = pd.DataFrame({"step_name": ["a"], "status": ["SUCCESS"]})

    assert calculate_step_kpis(steps)["average_step_duration_seconds"] is None


def test_step_kpis_empty():
    empty = pd.DataFrame(columns=["step_name", "status", "duration_seconds"])

    assert calculate_step_kpis(empty) == {
        "total_steps": 0,
        "failed_steps": 0,
        "step_success_rate": 0.0,
        "average_step_duration_seconds": None,
        "by_step": [],
    }
