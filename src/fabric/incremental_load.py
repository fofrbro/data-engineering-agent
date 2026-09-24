"""
Chargement incrémental des tables d'audit (pipeline_runs,
pipeline_steps).

Règles, identiques à celles du notebook Fabric
fabric/notebooks/incremental_load_audit_tables.py :

- pipeline_runs : seuls les run_id absents de la table sont
  ajoutés (anti-join), un run_id dupliqué dans la source n'est
  chargé qu'une fois ;
- pipeline_steps : une étape est identifiée par (run_id,
  step_order) ; seules les étapes absentes sont ajoutées, et
  uniquement si leur run existe dans la source. Ainsi un
  chargement interrompu entre les deux tables se rattrape au
  passage suivant ;
- les anciens runs ne sont jamais réécrits.

LocalLakehouse reproduit un Lakehouse avec des fichiers Parquet
pour exécuter et tester cette logique hors de Fabric.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.audit_parquet import (
    RUN_COLUMNS,
    STEP_COLUMNS,
    normalize_run_table,
    normalize_step_table,
)


RUN_KEY = ["run_id"]
STEP_KEY = ["run_id", "step_order"]


def _anti_join(
    source: pd.DataFrame,
    existing: pd.DataFrame,
    key: list[str],
) -> pd.DataFrame:
    if existing.empty:
        return source

    existing_keys = existing[key].drop_duplicates()
    merged = source.merge(
        existing_keys,
        on=key,
        how="left",
        indicator=True,
    )

    return merged[merged["_merge"] == "left_only"].drop(columns="_merge")


def select_new_runs(
    source_runs: pd.DataFrame,
    existing_runs: pd.DataFrame,
) -> pd.DataFrame:
    """Runs de la source absents de la table cible."""

    unique_source = source_runs.drop_duplicates(subset=RUN_KEY)

    return _anti_join(unique_source, existing_runs, RUN_KEY)


def select_new_steps(
    source_steps: pd.DataFrame,
    source_runs: pd.DataFrame,
    existing_steps: pd.DataFrame,
) -> pd.DataFrame:
    """
    Étapes de la source absentes de la table cible et
    rattachées à un run connu de la source.
    """

    attached = source_steps[
        source_steps["run_id"].isin(source_runs["run_id"])
    ].drop_duplicates(subset=STEP_KEY)

    return _anti_join(attached, existing_steps, STEP_KEY)


@dataclass
class IncrementalLoadResult:
    inserted_runs: int
    inserted_steps: int
    total_runs: int
    total_steps: int
    new_run_ids: list[str]

    def to_dict(self) -> dict:
        return {
            "inserted_runs": self.inserted_runs,
            "inserted_steps": self.inserted_steps,
            "total_runs": self.total_runs,
            "total_steps": self.total_steps,
            "new_run_ids": self.new_run_ids,
        }


class LocalLakehouse:
    """
    Lakehouse local : une table = un fichier Parquet.
    Seules les opérations nécessaires aux chargements sont fournies
    (lecture, ajout, remplacement).
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, table: str) -> Path:
        return self.root / "Tables" / f"{table}.parquet"

    def table_exists(self, table: str) -> bool:
        return self._path(table).exists()

    def read_table(self, table: str) -> pd.DataFrame:
        return pd.read_parquet(self._path(table))

    def overwrite(self, table: str, rows: pd.DataFrame) -> None:
        """Remplace entièrement la table."""

        path = self._path(table)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows.to_parquet(path, index=False)

    def append(
        self,
        table: str,
        rows: pd.DataFrame,
        normalize=None,
    ) -> None:
        """
        Ajoute des lignes. normalize reçoit la table complète : comme
        mergeSchema dans Delta, les colonnes nouvelles sont ajoutées et
        restent vides pour les lignes existantes.
        """

        path = self._path(table)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            rows = pd.concat(
                [pd.read_parquet(path), rows],
                ignore_index=True,
            )

        if normalize is not None:
            rows = normalize(rows)

        rows.to_parquet(path, index=False)


def _existing(lakehouse: LocalLakehouse, table: str, columns: list[str]) -> pd.DataFrame:
    if lakehouse.table_exists(table):
        return lakehouse.read_table(table)

    return pd.DataFrame(columns=columns)


def load_audit_incrementally(
    lakehouse: LocalLakehouse,
    source_runs: pd.DataFrame,
    source_steps: pd.DataFrame,
) -> IncrementalLoadResult:
    """
    Ajoute les nouveaux runs et étapes au Lakehouse.

    Les étapes sont écrites avant les runs : un run visible dans
    pipeline_runs a donc toujours ses étapes.
    """

    source_runs = normalize_run_table(source_runs)[RUN_COLUMNS]
    source_steps = normalize_step_table(source_steps)[STEP_COLUMNS]

    existing_runs = _existing(lakehouse, "pipeline_runs", RUN_COLUMNS)
    existing_steps = _existing(lakehouse, "pipeline_steps", STEP_COLUMNS)

    new_runs = select_new_runs(source_runs, existing_runs)
    new_steps = select_new_steps(source_steps, source_runs, existing_steps)

    if not new_steps.empty:
        lakehouse.append("pipeline_steps", new_steps, normalize_step_table)

    if not new_runs.empty:
        lakehouse.append("pipeline_runs", new_runs, normalize_run_table)

    return IncrementalLoadResult(
        inserted_runs=len(new_runs),
        inserted_steps=len(new_steps),
        total_runs=len(existing_runs) + len(new_runs),
        total_steps=len(existing_steps) + len(new_steps),
        new_run_ids=new_runs["run_id"].astype(str).tolist(),
    )
