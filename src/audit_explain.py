"""
Explication d'un run à partir de son audit.

Répond aux questions : quel fichier, quelle décision, pourquoi,
quel mode d'exécution, quelles étapes, quelle durée, quel résultat,
quels fichiers de sortie. Les audits anciens, incomplets, sont
expliqués avec les informations disponibles, sans rien inventer.
"""

from src.audit_reader import find_by_run_id


UNKNOWN = "non enregistré (audit antérieur)"

MODE_MEANINGS = {
    ("INGEST", "ASSESS_ONLY"): (
        "Le fichier est admissible à l'ingestion, mais cette "
        "exécution ne l'a pas ingéré."
    ),
    ("INGEST", "INGEST"): (
        "Le fichier est admissible et l'ingestion a réellement "
        "été demandée."
    ),
}


def _meaning(decision: str | None, execution_mode: str | None) -> str | None:
    if (decision, execution_mode) in MODE_MEANINGS:
        return MODE_MEANINGS[(decision, execution_mode)]

    if decision in ("QUARANTINE", "REJECT"):
        return "Le fichier n'a pas été ingéré, quel que soit le mode demandé."

    if decision is None and execution_mode:
        return "Aucune décision d'ingestion n'a été calculée pour ce run."

    return None


def explain_audit(audit: dict) -> dict:
    """Explication structurée d'un audit."""

    steps = [
        {
            "order": order,
            "name": step.get("name"),
            "status": step.get("status"),
            "duration_seconds": step.get("duration_seconds"),
            "error": step.get("error"),
        }
        for order, step in enumerate(audit.get("steps", []), start=1)
    ]

    failed_step = next(
        (step["name"] for step in steps if step["status"] == "FAILED"),
        None,
    )

    return {
        "run_id": audit.get("run_id"),
        "file": audit.get("source_file"),
        "contract": audit.get("contract_path") or None,
        "execution_mode": audit.get("execution_mode"),
        "decision": audit.get("decision"),
        "policy_rule": audit.get("policy_rule"),
        "reason": audit.get("decision_reason"),
        "meaning": _meaning(
            audit.get("decision"),
            audit.get("execution_mode"),
        ),
        "final_status": audit.get("final_status"),
        "started_at": audit.get("started_at"),
        "finished_at": audit.get("finished_at"),
        "duration_seconds": audit.get("duration_seconds"),
        "steps": steps,
        "failed_step": failed_step,
        "outputs": audit.get("outputs", []),
        "error": audit.get("error"),
    }


def explain_run(run_id: str, input_path=None) -> dict:
    """
    Explique un run enregistré.

    Lève KeyError si le run_id est inconnu.
    """

    audit = find_by_run_id(run_id, input_path)

    if audit is None:
        raise KeyError(f"Run introuvable : {run_id}")

    return explain_audit(audit)


def _seconds(value) -> str:
    return f"{value:.2f} s" if isinstance(value, (int, float)) else "inconnue"


def format_run_explanation(explanation: dict) -> str:
    """Explication lisible, en français."""

    decision = explanation["decision"] or "aucune"

    if explanation["policy_rule"]:
        decision += f" (règle {explanation['policy_rule']})"

    lines = [
        f"Run {explanation['run_id']}",
        f"Fichier : {explanation['file']}",
        f"Contrat : {explanation['contract'] or 'aucun'}",
        f"Mode d'exécution : {explanation['execution_mode'] or UNKNOWN}",
        f"Décision : {decision}",
        f"Pourquoi : {explanation['reason'] or UNKNOWN}",
    ]

    if explanation["meaning"]:
        lines.append(f"Signification : {explanation['meaning']}")

    lines += [
        f"Résultat : {explanation['final_status']}",
        f"Durée : {_seconds(explanation['duration_seconds'])}",
        "Étapes :",
    ]

    for step in explanation["steps"]:
        line = (
            f"  {step['order']}. {step['name']} - {step['status']}"
            f" ({_seconds(step['duration_seconds'])})"
        )

        if step["error"]:
            line += f" - erreur : {step['error']}"

        lines.append(line)

    if not explanation["steps"]:
        lines.append("  aucune")

    outputs = [
        f"{output.get('layer')} : {output.get('path')}"
        for output in explanation["outputs"]
    ]
    lines.append(f"Sorties : {', '.join(outputs) if outputs else 'aucune'}")

    if explanation["error"]:
        lines.append(f"Erreur : {explanation['error']}")

    if explanation["failed_step"]:
        lines.append(f"Étape en échec : {explanation['failed_step']}")

    return "\n".join(lines)
