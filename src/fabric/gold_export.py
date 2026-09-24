"""
Export et chargement des tables Gold vers le Lakehouse.

1. export_gold_for_fabric() : après une exécution vérifiée (SUCCESS),
   copie les fichiers Gold et un manifeste dans
   <export_root>/gold/<dataset>/, à déposer dans Files/gold/<dataset>/.
2. load_gold_from_manifest() : remplace chaque table Gold par sa
   dernière version vérifiée et trace le chargement dans gold_loads.
   Un run déjà chargé n'est pas rechargé.

Même logique que fabric/notebooks/load_gold_tables.py.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.fabric.incremental_load import LocalLakehouse
from src.workflow.agent_workflow import AgentPlan
from src.workflow.plan_executor import ExecutionResult


MANIFEST = "manifest.json"
GOLD_LOADS = "gold_loads"
GOLD_LOAD_COLUMNS = ["run_id", "dataset", "table_name", "rows", "loaded_at"]


class GoldExportError(ValueError):
    """Export impossible : exécution non vérifiée ou incomplète."""


def export_gold_for_fabric(
    plan: AgentPlan,
    result: ExecutionResult,
    export_root: str | Path = "data/fabric_export",
) -> Path:
    """Prépare les fichiers Gold d'une exécution réussie ; retourne le dossier."""

    if result.final_status != "SUCCESS":
        raise GoldExportError(
            f"Seule une exécution SUCCESS est exportée (statut : {result.final_status})."
        )

    folder = Path(export_root) / "gold" / plan.dataset
    folder.mkdir(parents=True, exist_ok=True)
    tables = []

    for table in plan.recommendation.gold:
        source = result.outputs.get(table.name)

        if not source or not Path(source).exists():
            raise GoldExportError(f"Fichier Gold absent : {table.name}")

        target = folder / f"{table.name}.parquet"
        shutil.copy2(source, target)
        tables.append(
            {
                "table_name": table.name,
                "file": target.name,
                "rows": len(pd.read_parquet(target)),
            }
        )

    manifest = {
        "dataset": plan.dataset,
        "run_id": result.run_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
    }
    (folder / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    return folder


def load_gold_from_manifest(lakehouse: LocalLakehouse, folder: str | Path) -> dict:
    """
    Charge les tables décrites par le manifeste.

    Retourne {"status": "LOADED" | "SKIPPED", ...}.
    """

    folder = Path(folder)
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))

    if lakehouse.table_exists(GOLD_LOADS):
        loads = lakehouse.read_table(GOLD_LOADS)
        already = (
            (loads["run_id"] == manifest["run_id"])
            & (loads["dataset"] == manifest["dataset"])
        ).any()

        if already:
            return {"status": "SKIPPED", "run_id": manifest["run_id"], "tables": []}

    loaded_at = datetime.now(timezone.utc)
    log = []

    for table in manifest["tables"]:
        data = pd.read_parquet(folder / table["file"])

        if len(data) != table["rows"]:
            raise GoldExportError(
                f"{table['table_name']} : {len(data)} ligne(s), "
                f"manifeste {table['rows']}."
            )

        lakehouse.overwrite(table["table_name"], data)
        log.append(
            {
                "run_id": manifest["run_id"],
                "dataset": manifest["dataset"],
                "table_name": table["table_name"],
                "rows": table["rows"],
                "loaded_at": loaded_at,
            }
        )

    lakehouse.append(GOLD_LOADS, pd.DataFrame(log, columns=GOLD_LOAD_COLUMNS))

    return {
        "status": "LOADED",
        "run_id": manifest["run_id"],
        "tables": [entry["table_name"] for entry in log],
    }
