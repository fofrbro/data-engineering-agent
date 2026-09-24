import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.audit_analysis import calculate_pipeline_kpis


VIEW_SQL = Path("fabric/sql/pipeline_observability.sql").read_text(encoding="utf-8")
NOTEBOOK = Path("fabric/notebooks/incremental_load_audit_tables.py").read_text(
    encoding="utf-8"
)

REQUIRED_KPIS = {
    "total_runs",
    "assess_only_runs",
    "ingest_runs",
    "quarantine_runs",
    "reject_runs",
    "successful_runs",
    "success_rate",
    "quarantine_rate",
    "reject_rate",
    "average_duration_seconds",
}


def run_view(runs: pd.DataFrame) -> dict:
    """Exécute la requête de la vue dans SQLite sur pipeline_runs."""

    select = VIEW_SQL.split(" AS\n", 1)[1]

    with sqlite3.connect(":memory:") as connection:
        runs.to_sql("pipeline_runs", connection, index=False)
        cursor = connection.execute(select)
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, cursor.fetchone()))


RUNS = pd.DataFrame(
    [
        ("r1", "INGEST", "ASSESS_ONLY", "SUCCESS", 1.0),
        ("r2", "INGEST", "INGEST", "SUCCESS", 3.0),
        ("r3", "QUARANTINE", "INGEST", "QUARANTINED", 2.0),
        ("r4", "REJECT", "ASSESS_ONLY", "REJECTED", 4.0),
        ("r5", None, "INGEST", "FAILED", 5.0),
    ],
    columns=["run_id", "decision", "execution_mode", "final_status", "duration_seconds"],
)


def test_view_exposes_required_kpis():
    assert REQUIRED_KPIS | {"failed_runs"} == set(run_view(RUNS))


def test_view_matches_python_kpis():
    view = run_view(RUNS)
    python = calculate_pipeline_kpis(RUNS)

    assert set(view) == set(python)

    for name, value in python.items():
        assert view[name] == pytest.approx(value), name


def test_view_on_empty_table_matches_python():
    empty = RUNS.iloc[0:0]

    assert run_view(empty) == calculate_pipeline_kpis(empty)


def test_notebook_embeds_the_versioned_view_sql():
    assert VIEW_SQL.strip() in NOTEBOOK


STEP_VIEW_SQL = Path("fabric/sql/pipeline_step_observability.sql").read_text(
    encoding="utf-8"
)

STEPS = pd.DataFrame(
    [
        ("r1", 1, "validate_csv", "SUCCESS", 0.5),
        ("r2", 1, "validate_csv", "FAILED", 1.5),
        ("r1", 2, "quarantine_csv", "QUARANTINED", 0.2),
        ("r3", 1, "inspect_csv", "SUCCESS", None),
    ],
    columns=["run_id", "step_order", "step_name", "status", "duration_seconds"],
)


def run_step_view(steps: pd.DataFrame) -> list[dict]:
    select = STEP_VIEW_SQL.split(" AS\n", 1)[1] + " ORDER BY step_name"

    with sqlite3.connect(":memory:") as connection:
        steps.to_sql("pipeline_steps", connection, index=False)
        cursor = connection.execute(select)
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def test_step_view_matches_python_step_kpis():
    from src.audit_analysis import calculate_step_kpis

    view = run_step_view(STEPS)
    python = calculate_step_kpis(STEPS)["by_step"]

    assert [row["step_name"] for row in view] == [
        row["step_name"] for row in python
    ]

    for view_row, python_row in zip(view, python):
        assert view_row["executions"] == python_row["executions"]
        assert view_row["failed_executions"] == python_row["failed_executions"]
        assert view_row["success_rate"] == pytest.approx(python_row["success_rate"])
        assert view_row["average_duration_seconds"] == (
            pytest.approx(python_row["average_duration_seconds"])
            if python_row["average_duration_seconds"] is not None
            else None
        )


def test_notebook_embeds_the_versioned_step_view_sql():
    assert STEP_VIEW_SQL.strip() in NOTEBOOK
