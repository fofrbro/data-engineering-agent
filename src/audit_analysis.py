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
            "execution_mode",
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
            "started_at",
            "finished_at",
            "duration_seconds",
            "error",
        ],
    )

    return pipeline_runs, pipeline_steps



def filter_structured_runs(
    pipeline_runs: pd.DataFrame,
) -> pd.DataFrame:
    """
    Retourne uniquement les runs produits avec le nouveau
    modèle d'audit disposant d'un execution_mode valide.
    """

    valid_modes = {
        "ASSESS_ONLY",
        "INGEST",
    }

    return pipeline_runs[
        pipeline_runs["execution_mode"].isin(valid_modes)
    ].copy()


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
            "assess_only_runs": 0,
            "ingest_runs": 0,
            "quarantine_runs": 0,
            "reject_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "success_rate": 0.0,
            "quarantine_rate": 0.0,
            "reject_rate": 0.0,
            "average_duration_seconds": 0.0,
        }

    assess_only_count = (
        pipeline_runs["execution_mode"]
        == "ASSESS_ONLY"
    ).sum()

    ingest_count = (
        pipeline_runs["execution_mode"]
        == "INGEST"
    ).sum()

    quarantine_count = (
        pipeline_runs["decision"]
        == "QUARANTINE"
    ).sum()

    reject_count = (
        pipeline_runs["decision"]
        == "REJECT"
    ).sum()

    success_count = (
        pipeline_runs["final_status"]
        == "SUCCESS"
    ).sum()

    failed_count = (
        pipeline_runs["final_status"]
        == "FAILED"
    ).sum()

    return {
        "total_runs": total_runs,
        "assess_only_runs": int(assess_only_count),
        "ingest_runs": int(ingest_count),
        "quarantine_runs": int(quarantine_count),
        "reject_runs": int(reject_count),
        "successful_runs": int(success_count),
        "failed_runs": int(failed_count),
        "success_rate": success_count / total_runs,
        "quarantine_rate": (
            quarantine_count / total_runs
        ),
        "reject_rate": (
            reject_count / total_runs
        ),
        "average_duration_seconds": (
            pipeline_runs["duration_seconds"]
            .mean()
        ),
    }


def _mean_or_none(values: pd.Series) -> float | None:
    """Moyenne des valeurs connues ; None si aucune n'est connue."""

    known = pd.to_numeric(values, errors="coerce").dropna()

    return float(known.mean()) if len(known) else None


def calculate_step_kpis(
    pipeline_steps: pd.DataFrame,
) -> dict:
    """
    KPI des étapes. Une étape réussie est une étape terminée
    sans erreur (statut différent de FAILED) : une mise en
    quarantaine ou un rejet sont des actions réussies.

    La durée moyenne ignore les étapes sans horodatage (audits
    antérieurs) et vaut None si aucune durée n'est connue.
    """

    if "duration_seconds" not in pipeline_steps.columns:
        pipeline_steps = pipeline_steps.assign(duration_seconds=None)

    total = len(pipeline_steps)

    if total == 0:
        return {
            "total_steps": 0,
            "failed_steps": 0,
            "step_success_rate": 0.0,
            "average_step_duration_seconds": None,
            "by_step": [],
        }

    failed = pipeline_steps["status"] == "FAILED"

    by_step = []

    for step_name, group in pipeline_steps.groupby("step_name", sort=True):
        group_failed = int((group["status"] == "FAILED").sum())

        by_step.append(
            {
                "step_name": step_name,
                "executions": len(group),
                "failed_executions": group_failed,
                "success_rate": (len(group) - group_failed) / len(group),
                "average_duration_seconds": _mean_or_none(
                    group["duration_seconds"]
                ),
            }
        )

    return {
        "total_steps": total,
        "failed_steps": int(failed.sum()),
        "step_success_rate": float((~failed).sum() / total),
        "average_step_duration_seconds": _mean_or_none(
            pipeline_steps["duration_seconds"]
        ),
        "by_step": by_step,
    }
