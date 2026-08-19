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
