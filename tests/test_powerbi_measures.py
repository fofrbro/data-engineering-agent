from pathlib import Path

import pandas as pd
import pytest

from src.audit_analysis import calculate_pipeline_kpis, calculate_step_kpis
from src.powerbi.measures import (
    OBSERVABILITY_BY_NAME,
    OBSERVABILITY_MEASURES,
    MeasureSpec,
    evaluate,
    render_measures_script,
    to_dax,
)


RUNS = pd.DataFrame(
    [
        ("r1", "INGEST", "ASSESS_ONLY", "SUCCESS", 1.0),
        ("r2", "INGEST", "INGEST", "SUCCESS", 3.0),
        ("r3", "QUARANTINE", "INGEST", "QUARANTINED", 2.0),
        ("r4", "REJECT", "ASSESS_ONLY", "REJECTED", None),
        ("r5", None, "INGEST", "FAILED", 5.0),
    ],
    columns=["run_id", "decision", "execution_mode", "final_status", "duration_seconds"],
)

STEPS = pd.DataFrame(
    [
        ("r1", "validate_csv", "SUCCESS", 0.5),
        ("r2", "validate_csv", "FAILED", 1.5),
        ("r3", "quarantine_csv", "QUARANTINED", 0.2),
        ("r5", "inspect_csv", None, None),
    ],
    columns=["run_id", "step_name", "status", "duration_seconds"],
)

TABLES = {"pipeline_runs": RUNS, "pipeline_steps": STEPS}

# Mesure Power BI -> KPI Python équivalent.
RUN_PARITY = {
    "Total Runs": "total_runs",
    "Successful Runs": "successful_runs",
    "Failed Runs": "failed_runs",
    "Assess Only Runs": "assess_only_runs",
    "Ingest Runs": "ingest_runs",
    "Quarantine Runs": "quarantine_runs",
    "Reject Runs": "reject_runs",
    "Success Rate": "success_rate",
    "Quarantine Rate": "quarantine_rate",
    "Reject Rate": "reject_rate",
    "Average Duration (s)": "average_duration_seconds",
}

STEP_PARITY = {
    "Step Executions": "total_steps",
    "Failed Steps": "failed_steps",
    "Step Success Rate": "step_success_rate",
    "Average Step Duration (s)": "average_step_duration_seconds",
}


def value(name, tables=TABLES):
    return evaluate(OBSERVABILITY_BY_NAME[name], tables, OBSERVABILITY_BY_NAME)


@pytest.mark.parametrize("measure, kpi", RUN_PARITY.items())
def test_run_measures_match_python_kpis(measure, kpi):
    assert value(measure) == pytest.approx(calculate_pipeline_kpis(RUNS)[kpi])


@pytest.mark.parametrize("measure, kpi", STEP_PARITY.items())
def test_step_measures_match_python_step_kpis(measure, kpi):
    assert value(measure) == pytest.approx(calculate_step_kpis(STEPS)[kpi])


def test_empty_tables():
    empty = {name: table.iloc[0:0] for name, table in TABLES.items()}

    assert value("Total Runs", empty) == 0
    assert value("Success Rate", empty) == 0
    # AVERAGE sur une table vide renvoie BLANK en DAX, 0.0 côté Python.
    assert value("Average Duration (s)", empty) is None


def test_dax_expressions():
    measures = OBSERVABILITY_BY_NAME

    assert to_dax(measures["Total Runs"], measures) == "COUNTROWS(pipeline_runs)"
    assert to_dax(measures["Quarantine Runs"], measures) == (
        'CALCULATE(COUNTROWS(pipeline_runs), pipeline_runs[decision] = "QUARANTINE")'
    )
    assert to_dax(measures["Success Rate"], measures) == (
        "DIVIDE([Successful Runs], [Total Runs], 0)"
    )
    assert to_dax(measures["Average Step Duration (s)"], measures) == (
        "AVERAGE(pipeline_steps[duration_seconds])"
    )


def test_required_kpis_are_all_defined():
    assert set(RUN_PARITY) | set(STEP_PARITY) <= {m.name for m in OBSERVABILITY_MEASURES}


def test_divide_with_unknown_measure_is_refused():
    broken = MeasureSpec("X", "divide", "t", "f", numerator="A", denominator="B")

    with pytest.raises(ValueError):
        to_dax(broken, {})


def test_versioned_script_is_up_to_date():
    versioned = Path("powerbi/observability_measures.dax").read_text(encoding="utf-8")

    assert versioned == render_measures_script()
