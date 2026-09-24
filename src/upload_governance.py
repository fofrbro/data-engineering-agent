"""
Contrôle de gouvernance des fichiers uploadés via l'API.

Chaque fichier passe par l'orchestrateur déterministe en mode
ASSESS_ONLY (inspection, profil, qualité, contrat, décision) :
la décision est calculée par le Policy Engine et auditée.
Le traitement Silver/Gold n'est autorisé que si tous les fichiers
obtiennent la décision INGEST.

Aucun LLM n'intervient dans ce module.
"""

from pathlib import Path

from src.contract.contract_generator import propose_contract_for_file
from src.contract.contract_lifecycle import save_contract
from src.pipeline_orchestrator import execute_pipeline
from src.pipeline_plan import PipelinePlan
from src.tools.contract_validation import validate_contract
from src.tools.data_inspection import inspect_csv
from src.tools.data_profiling import profile_csv
from src.tools.data_validation import validate_csv
from src.tools.ingestion import quarantine_csv, reject_csv
from src.tools.ingestion_decision import (
    RULE_CONTRACT_NOT_VALIDATED,
    determine_ingestion_decision,
)


DEFAULT_PROPOSED_CONTRACTS_DIR = Path("data/contracts/proposed")

ASSESSMENT_TOOLS = {
    "inspect_csv": lambda args: inspect_csv(args["file_path"]),
    "profile_csv": lambda args: profile_csv(args["file_path"]),
    "validate_csv": lambda args: validate_csv(
        args["file_path"],
        args.get("contract_path"),
    ),
    "validate_contract": lambda args: validate_contract(
        args["file_path"],
        args.get("contract_path"),
    ),
    "determine_ingestion_decision": lambda args: determine_ingestion_decision(
        args["contract_result"],
        args["quality_result"],
    ),
    "quarantine_csv": lambda args: quarantine_csv(
        args["file_path"],
        args["reason"],
    ),
    "reject_csv": lambda args: reject_csv(
        args["file_path"],
        args["reason"],
    ),
}


def execute_assessment_tool(name: str, arguments: dict):
    """
    Exécuteur limité aux outils d'évaluation : l'ingestion
    Bronze/Silver/Gold n'est pas accessible depuis ce contrôle.
    """

    if name not in ASSESSMENT_TOOLS:
        raise ValueError(
            f"Outil non autorisé pendant l'évaluation : {name}"
        )

    return ASSESSMENT_TOOLS[name](arguments)


def assess_file(
    file_path: str,
    contract_path: str | None,
    tool_executor=execute_assessment_tool,
) -> dict:
    plan = PipelinePlan(
        file_path=file_path,
        contract_path=contract_path or "",
        inspect=True,
        profile=True,
        validate_quality=True,
        validate_contract=True,
        decision=True,
    )

    audit = execute_pipeline(plan, tool_executor)["audit"]

    return {
        "file": file_path,
        "run_id": audit["run_id"],
        "decision": audit["decision"],
        "policy_rule": audit["policy_rule"],
        "reason": audit["decision_reason"],
        "final_status": audit["final_status"],
    }


def assess_uploads(
    file_paths: list[str],
    contract_path: str | None,
    dataset_name: str | None = None,
    *,
    tool_executor=execute_assessment_tool,
    proposed_contracts_dir: str | Path = DEFAULT_PROPOSED_CONTRACTS_DIR,
) -> dict:
    """
    Évalue un lot de fichiers.

    Sans contrat fourni, un contrat est proposé à partir du premier
    fichier et enregistré avec le statut PROPOSED : il doit être
    approuvé avant que le lot puisse être traité.
    """

    assessments = [
        assess_file(path, contract_path, tool_executor)
        for path in file_paths
    ]

    allowed = bool(assessments) and all(
        assessment["decision"] == "INGEST"
        for assessment in assessments
    )

    result = {
        "allowed": allowed,
        "contract_path": contract_path or None,
        "assessments": assessments,
        "proposed_contract_path": None,
    }

    needs_contract = any(
        assessment["policy_rule"] == RULE_CONTRACT_NOT_VALIDATED
        for assessment in assessments
    )

    if not allowed and needs_contract and not contract_path:
        contract = propose_contract_for_file(
            file_paths[0],
            dataset=dataset_name,
        )
        path = save_contract(
            contract,
            Path(proposed_contracts_dir) / f"{contract['dataset']}.json",
        )
        result["proposed_contract_path"] = path.as_posix()

    return result
