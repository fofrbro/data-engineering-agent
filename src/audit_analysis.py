import pandas as pd

from src.audit_reader import list_audits
from src.audit_tables import (
    audits_to_run_rows,
    audits_to_step_rows,
)


def load_audit_tables(input_path=None):
    """
    Charge l'historique d'audit sous forme de deux DataFrames.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]:
            pipeline_runs, pipeline_steps
    """

    audits = list_audits(input_path)

    run_rows = audits_to_run_rows(audits)
    step_rows = audits_to_step_rows(audits)

    pipeline_runs = pd.DataFrame(
        run_rows,
        columns=[
            "run_id",
            "source_file",
            "contract_path",
            "decision",
            "final_status",
            "started_at",
            "finished_at",
            "duration_seconds",
            "error",
        ],
    )

    pipeline_steps = pd.DataFrame(
        step_rows,
        columns=[
            "run_id",
            "step_order",
            "step_name",
            "status",
        ],
    )

    return pipeline_runs, pipeline_steps


def calculate_pipeline_kpis(
    pipeline_runs: pd.DataFrame,
) -> dict:
    """
    Calcule les principaux KPI d'observabilité.
    """

    total_runs = len(pipeline_runs)

    if total_runs == 0:
        return {
            "total_runs": 0,
            "success_rate": 0.0,
            "quarantine_rate": 0.0,
            "reject_rate": 0.0,
            "average_duration_seconds": 0.0,
        }

    success_count = (
        pipeline_runs["final_status"]
        == "SUCCESS"
    ).sum()

    quarantine_count = (
        pipeline_runs["decision"]
        == "QUARANTINE"
    ).sum()

    reject_count = (
        pipeline_runs["decision"]
        == "REJECT"
    ).sum()

    return {
        "total_runs": total_runs,
        "success_rate": success_count / total_runs,
        "quarantine_rate": quarantine_count / total_runs,
        "reject_rate": reject_count / total_runs,
        "average_duration_seconds": (
            pipeline_runs["duration_seconds"]
            .mean()
        ),
    }
