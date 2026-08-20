from pathlib import Path

import pandas as pd

from src.audit_analysis import load_audit_tables


DEFAULT_RUNS_PATH = Path("data/audit/pipeline_runs.parquet")
DEFAULT_STEPS_PATH = Path("data/audit/pipeline_steps.parquet")


def export_audit_to_parquet(
    input_path=None,
    runs_output_path: str | Path = DEFAULT_RUNS_PATH,
    steps_output_path: str | Path = DEFAULT_STEPS_PATH,
) -> tuple[Path, Path]:
    """
    Convertit l'historique JSONL en deux fichiers Parquet :
    pipeline_runs et pipeline_steps.
    """

    pipeline_runs, pipeline_steps = load_audit_tables(
        input_path
    )

    pipeline_runs = normalize_run_table(
        pipeline_runs
    )

    pipeline_steps = normalize_step_table(
        pipeline_steps
    )

    runs_path = Path(runs_output_path)
    steps_path = Path(steps_output_path)

    runs_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    steps_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    pipeline_runs.to_parquet(
        runs_path,
        index=False,
    )

    pipeline_steps.to_parquet(
        steps_path,
        index=False,
    )

    return runs_path, steps_path


def read_audit_parquet(
    runs_path: str | Path,
    steps_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Relit les deux tables Parquet.
    """

    pipeline_runs = pd.read_parquet(runs_path)
    pipeline_steps = pd.read_parquet(steps_path)

    return pipeline_runs, pipeline_steps



RUN_COLUMNS = [
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
]

STEP_COLUMNS = [
    "run_id",
    "step_order",
    "step_name",
    "status",
]


def normalize_run_table(
    pipeline_runs: pd.DataFrame,
) -> pd.DataFrame:
    """
    Normalise le schéma pipeline_runs pour un stockage analytique stable.
    """

    table = pipeline_runs.copy()

    for column in RUN_COLUMNS:
        if column not in table.columns:
            table[column] = None

    table = table[RUN_COLUMNS]

    table["run_id"] = table["run_id"].astype("string")
    table["source_file"] = table["source_file"].astype("string")
    table["contract_path"] = table["contract_path"].astype("string")
    table["decision"] = table["decision"].astype("string")
    table["execution_mode"] = table["execution_mode"].astype("string")
    table["final_status"] = table["final_status"].astype("string")
    table["started_at"] = table["started_at"].astype("string")
    table["finished_at"] = table["finished_at"].astype("string")
    table["duration_seconds"] = pd.to_numeric(
        table["duration_seconds"],
        errors="coerce",
    )
    table["error"] = table["error"].astype("string")

    return table


def normalize_step_table(
    pipeline_steps: pd.DataFrame,
) -> pd.DataFrame:
    """
    Normalise le schéma pipeline_steps.
    """

    table = pipeline_steps.copy()

    for column in STEP_COLUMNS:
        if column not in table.columns:
            table[column] = None

    table = table[STEP_COLUMNS]

    table["run_id"] = table["run_id"].astype("string")
    table["step_order"] = pd.to_numeric(
        table["step_order"],
        errors="coerce",
    ).astype("Int64")
    table["step_name"] = table["step_name"].astype("string")
    table["status"] = table["status"].astype("string")

    return table




def export_structured_audit_to_parquet(
    input_path=None,
    runs_output_path: str | Path = "data/audit/pipeline_runs_structured.parquet",
    steps_output_path: str | Path = "data/audit/pipeline_steps_structured.parquet",
) -> tuple[Path, Path]:
    """
    Exporte uniquement les audits structurés vers Parquet.

    Les anciens audits sans execution_mode sont exclus.
    """

    from src.audit_analysis import filter_structured_runs

    pipeline_runs, pipeline_steps = load_audit_tables(
        input_path
    )

    structured_runs = filter_structured_runs(
        pipeline_runs
    )

    structured_run_ids = set(
        structured_runs["run_id"]
    )

    structured_steps = pipeline_steps[
        pipeline_steps["run_id"].isin(
            structured_run_ids
        )
    ].copy()

    structured_runs = normalize_run_table(
        structured_runs
    )

    structured_steps = normalize_step_table(
        structured_steps
    )

    runs_path = Path(runs_output_path)
    steps_path = Path(steps_output_path)

    runs_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    steps_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    structured_runs.to_parquet(
        runs_path,
        index=False,
    )

    structured_steps.to_parquet(
        steps_path,
        index=False,
    )

    return runs_path, steps_path
