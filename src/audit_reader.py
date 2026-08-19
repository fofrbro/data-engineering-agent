from collections import Counter

from src.audit_store import read_audits


def list_audits(input_path=None) -> list[dict]:
    """
    Retourne tous les runs d'audit.
    """

    if input_path is None:
        return read_audits()

    return read_audits(input_path)


def find_by_run_id(
    run_id: str,
    input_path=None,
) -> dict | None:
    """
    Recherche un run précis par son run_id.
    """

    audits = list_audits(input_path)

    for audit in audits:
        if audit.get("run_id") == run_id:
            return audit

    return None


def filter_audits(
    *,
    decision: str | None = None,
    final_status: str | None = None,
    source_file: str | None = None,
    input_path=None,
) -> list[dict]:
    """
    Filtre les audits selon différents critères.
    """

    audits = list_audits(input_path)

    results = []

    for audit in audits:
        if (
            decision is not None
            and audit.get("decision") != decision
        ):
            continue

        if (
            final_status is not None
            and audit.get("final_status") != final_status
        ):
            continue

        if (
            source_file is not None
            and audit.get("source_file") != source_file
        ):
            continue

        results.append(audit)

    return results


def summarize_audits(
    input_path=None,
) -> dict:
    """
    Produit un résumé de l'historique des runs.
    """

    audits = list_audits(input_path)

    decisions = Counter(
        audit.get("decision")
        for audit in audits
        if audit.get("decision") is not None
    )

    statuses = Counter(
        audit.get("final_status")
        for audit in audits
        if audit.get("final_status") is not None
    )

    return {
        "total_runs": len(audits),
        "decisions": dict(decisions),
        "statuses": dict(statuses),
    }
