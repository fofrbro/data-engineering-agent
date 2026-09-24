def audit_to_run_row(audit: dict) -> dict:
    """
    Transforme un audit complet en une ligne pipeline_runs.
    """

    return {
        "run_id": audit.get("run_id"),
        "source_file": audit.get("source_file"),
        "contract_path": audit.get("contract_path"),
        "decision": audit.get("decision"),
        "execution_mode": audit.get("execution_mode"),
        "final_status": audit.get("final_status"),
        "started_at": audit.get("started_at"),
        "finished_at": audit.get("finished_at"),
        "duration_seconds": audit.get(
            "duration_seconds"
        ),
        "error": audit.get("error"),
    }


def audit_to_step_rows(audit: dict) -> list[dict]:
    """
    Transforme les étapes d'un audit en lignes pipeline_steps.
    """

    run_id = audit.get("run_id")

    rows = []

    for position, step in enumerate(
        audit.get("steps", []),
        start=1,
    ):
        rows.append(
            {
                "run_id": run_id,
                "step_order": position,
                "step_name": step.get("name"),
                "status": step.get("status"),
                # Absents des audits antérieurs à l'horodatage des étapes.
                "started_at": step.get("started_at"),
                "finished_at": step.get("finished_at"),
                "duration_seconds": step.get("duration_seconds"),
                "error": step.get("error"),
            }
        )

    return rows


def audits_to_run_rows(
    audits: list[dict],
) -> list[dict]:
    """
    Transforme plusieurs audits en lignes pipeline_runs.
    """

    return [
        audit_to_run_row(audit)
        for audit in audits
    ]


def audits_to_step_rows(
    audits: list[dict],
) -> list[dict]:
    """
    Transforme plusieurs audits en lignes pipeline_steps.
    """

    rows = []

    for audit in audits:
        rows.extend(
            audit_to_step_rows(audit)
        )

    return rows
