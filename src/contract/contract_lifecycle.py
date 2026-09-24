"""
Cycle de vie d'un Data Contract :

    PROPOSED ──approve──▶ VALIDATED
        └─────reject────▶ REJECTED

Un contrat proposé par l'agent n'est jamais considéré comme validé
sans décision explicite d'un relecteur. Un contrat sans statut a
été écrit à la main avant ce mécanisme : il est considéré VALIDATED.
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path


PROPOSED = "PROPOSED"
VALIDATED = "VALIDATED"
REJECTED = "REJECTED"

CONTRACT_STATUSES = {PROPOSED, VALIDATED, REJECTED}


class ContractStatusError(ValueError):
    """Transition de statut interdite."""


def contract_status(contract: dict) -> str:
    status = contract.get("status", VALIDATED)

    if status not in CONTRACT_STATUSES:
        raise ContractStatusError(
            f"Statut de contrat inconnu : {status}"
        )

    return status


def _review(
    contract: dict,
    *,
    status: str,
    reviewer: str,
    comment: str | None,
    reviewed_at: datetime | None,
) -> dict:
    current = contract_status(contract)

    if current != PROPOSED:
        raise ContractStatusError(
            f"Seul un contrat PROPOSED peut être revu "
            f"(statut actuel : {current})."
        )

    if not reviewer or not reviewer.strip():
        raise ContractStatusError(
            "La revue d'un contrat exige un relecteur."
        )

    reviewed = copy.deepcopy(contract)
    reviewed["status"] = status
    reviewed["review"] = {
        "status": status,
        "reviewed_by": reviewer.strip(),
        "reviewed_at": (
            reviewed_at or datetime.now(timezone.utc)
        ).isoformat(),
        "comment": comment,
    }

    return reviewed


def approve_contract(
    contract: dict,
    reviewer: str,
    comment: str | None = None,
    reviewed_at: datetime | None = None,
) -> dict:
    """Valide un contrat proposé. Le contrat d'origine est inchangé."""

    return _review(
        contract,
        status=VALIDATED,
        reviewer=reviewer,
        comment=comment,
        reviewed_at=reviewed_at,
    )


def reject_contract(
    contract: dict,
    reviewer: str,
    reason: str,
    reviewed_at: datetime | None = None,
) -> dict:
    """Rejette un contrat proposé ; un motif est obligatoire."""

    if not reason or not reason.strip():
        raise ContractStatusError(
            "Le rejet d'un contrat exige un motif."
        )

    return _review(
        contract,
        status=REJECTED,
        reviewer=reviewer,
        comment=reason,
        reviewed_at=reviewed_at,
    )


def load_contract_file(
    path: str | Path,
    contracts_dir: str | Path,
) -> tuple[Path, dict]:
    """
    Charge un contrat en refusant tout chemin situé hors du
    répertoire des contrats.
    """

    root = Path(contracts_dir).resolve()
    source = Path(path).resolve()

    if not source.is_relative_to(root):
        raise ContractStatusError(
            f"Le contrat doit se trouver dans {Path(contracts_dir)}."
        )

    if not source.is_file():
        raise FileNotFoundError(f"Contrat introuvable : {path}")

    return source, json.loads(source.read_text(encoding="utf-8"))


def approve_contract_file(
    path: str | Path,
    reviewer: str,
    comment: str | None = None,
    contracts_dir: str | Path = "data/contracts",
) -> Path:
    """
    Approuve un contrat proposé et l'enregistre sous
    <contracts_dir>/<dataset>.json, sans jamais écraser
    un contrat existant.
    """

    _, contract = load_contract_file(path, contracts_dir)
    approved = approve_contract(contract, reviewer, comment)

    dataset = approved.get("dataset")

    if not dataset:
        raise ContractStatusError(
            "Un contrat sans dataset ne peut pas être validé."
        )

    destination = Path(contracts_dir) / f"{dataset}.json"

    if destination.exists():
        raise ContractStatusError(
            f"Un contrat existe déjà : {destination.as_posix()}"
        )

    return save_contract(approved, destination)


def reject_contract_file(
    path: str | Path,
    reviewer: str,
    reason: str,
    contracts_dir: str | Path = "data/contracts",
) -> Path:
    """Rejette un contrat proposé en place."""

    source, contract = load_contract_file(path, contracts_dir)

    return save_contract(
        reject_contract(contract, reviewer, reason),
        source,
    )


def save_contract(contract: dict, path: str | Path) -> Path:
    """Écrit le contrat en JSON lisible."""

    contract_status(contract)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(contract, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )

    return destination
