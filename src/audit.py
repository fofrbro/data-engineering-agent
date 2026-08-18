from datetime import datetime, timezone
from uuid import uuid4


def create_run_id() -> str:
    """Génère un identifiant unique d'exécution."""
    return str(uuid4())


def create_audit_record(
    *,
    run_id: str,
    source_file: str,
    contract_path: str,
) -> dict:
    """
    Initialise un enregistrement d'audit.
    """

    return {
        "run_id": run_id,
        "source_file": source_file,
        "contract_path": contract_path,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "decision": None,
        "final_status": "RUNNING",
        "steps": [],
        "outputs": [],
        "error": None,
    }


def record_step(
    audit: dict,
    *,
    name: str,
    status: str,
    result: dict | None = None,
) -> None:
    """
    Ajoute le résultat d'une étape au journal d'audit.
    """

    step = {
        "name": name,
        "status": status,
    }

    if result is not None:
        step["result"] = result

    audit["steps"].append(step)


def record_output(
    audit: dict,
    *,
    path: str,
    layer: str,
) -> None:
    """
    Enregistre un fichier produit par le pipeline.
    """

    audit["outputs"].append(
        {
            "path": path,
            "layer": layer,
        }
    )


def finish_audit(
    audit: dict,
    *,
    status: str,
    decision: str | None = None,
    error: str | None = None,
) -> dict:
    """
    Termine l'enregistrement d'audit.
    """

    audit["finished_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    audit["final_status"] = status
    audit["decision"] = decision
    audit["error"] = error

    return audit
