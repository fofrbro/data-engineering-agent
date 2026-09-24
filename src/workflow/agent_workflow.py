"""
Workflow agent : PLAN -> VALIDATE -> EXECUTE -> VERIFY -> AUDIT.

PLAN     : découverte, sémantique, contrat, décision prévisionnelle,
           pipeline Bronze/Silver/Gold, KPI et tableau de bord.
VALIDATE : l'utilisateur valide le contrat, les transformations
           destructives et le tableau de bord. Rien n'est validé
           implicitement.

Toutes les étapes sont déterministes ; aucun LLM n'intervient.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.contract.contract_generator import (
    dataset_name_from_path,
    generate_contract,
)
from src.contract.contract_lifecycle import (
    VALIDATED,
    approve_contract_file,
    contract_status,
    load_contract_file,
    save_contract,
)
from src.discovery.dataset_discovery import DiscoveryResult, discover_dataset
from src.recommendation.dashboard_planner import DashboardPlan, plan_dashboard
from src.recommendation.dashboard_review import (
    APPROVED,
    approve_dashboard,
    render_dashboard_preview,
)
from src.recommendation.kpi_recommender import KpiRecommendation, recommend_kpis
from src.recommendation.pipeline_recommender import (
    PipelineRecommendation,
    recommend_pipeline,
)
from src.semantic.semantic_profiler import SemanticProfile, profile_semantics
from src.tools.contract_validation import validate_contract
from src.tools.data_validation import validate_csv
from src.tools.ingestion_decision import determine_ingestion_decision


PLANNED = "PLANNED"
READY = "READY"
EXECUTED = "EXECUTED"
FAILED = "FAILED"
BLOCKED = "BLOCKED"

DEFAULT_CONTRACTS_DIR = Path("data/contracts")


class WorkflowError(ValueError):
    """Action de workflow impossible dans l'état actuel du plan."""


@dataclass
class AgentPlan:
    plan_id: str
    file_path: str
    dataset: str
    created_at: str
    discovery: DiscoveryResult
    semantics: SemanticProfile
    contract: dict
    contract_path: str
    decision_preview: dict
    recommendation: PipelineRecommendation
    kpis: KpiRecommendation
    dashboard: DashboardPlan
    contracts_dir: str
    quality_preview: dict = field(default_factory=dict)
    destructive_approval: dict | None = None
    status: str = PLANNED
    history: list[dict] = field(default_factory=list)

    @property
    def contract_status(self) -> str:
        return contract_status(self.contract)

    @property
    def destructive_transformations(self) -> list[str]:
        return [
            step.id
            for step in self.recommendation.transformations
            if step.requires_approval
        ]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Avertissements qualité et transformation Silver qui les corrige.
CORRECTING_TRANSFORMATIONS = {
    "no_duplicates": "deduplicate_rows",
    "no_nulls": "fill_null_dimensions",
}


def _refresh(plan: AgentPlan) -> None:
    """
    Recalcule ce qui dépend du contrat, dont la décision
    prévisionnelle. Elle n'est pas auditée : la décision qui compte
    est recalculée au moment de l'exécution.
    """

    schema = plan.discovery.schema
    plan.recommendation = recommend_pipeline(
        schema, plan.semantics, plan.contract, plan.dataset,
    )
    plan.quality_preview = validate_csv(plan.file_path, plan.contract_path)
    plan.decision_preview = determine_ingestion_decision(
        validate_contract(plan.file_path, plan.contract_path),
        plan.quality_preview,
    )


def quality_warnings(plan: AgentPlan) -> list[dict]:
    """
    Avertissements qualité, avec la transformation qui les corrige
    et l'indication qu'elle sera réellement appliquée ou non.
    """

    planned = {step.id: step for step in plan.recommendation.transformations}
    warnings = []

    for issue in plan.quality_preview.get("issues", []):
        if issue.get("severity") != "WARNING":
            continue

        correction = CORRECTING_TRANSFORMATIONS.get(issue["rule"])
        step = planned.get(correction)

        # La correction doit porter sur la colonne concernée.
        if step and issue.get("column") and issue["column"] not in step.columns:
            step = None
        corrected = step is not None and (
            not step.requires_approval or plan.destructive_approval is not None
        )
        warnings.append(
            {
                "rule": issue["rule"],
                "column": issue.get("column"),
                "message": issue["message"],
                "correction": correction if step else None,
                "corrected": corrected,
            }
        )

    return warnings


def plan_file(
    file_path: str,
    contract_path: str | None = None,
    dataset: str | None = None,
    contracts_dir: str | Path = DEFAULT_CONTRACTS_DIR,
) -> AgentPlan:
    """
    PLAN : analyse le fichier et propose tout ce qui est nécessaire
    à son traitement. Sans contrat fourni, un contrat PROPOSED est
    généré dans <contracts_dir>/proposed/.
    """

    discovery = discover_dataset(file_path)
    semantics = profile_semantics(discovery.schema)

    if contract_path:
        _, contract = load_contract_file(contract_path, contracts_dir)
        dataset = dataset or contract.get("dataset")
    else:
        dataset = dataset or dataset_name_from_path(file_path)
        contract = generate_contract(
            discovery.schema,
            semantics,
            dataset=dataset,
            source_file=file_path,
        )
        contract_path = save_contract(
            contract,
            Path(contracts_dir) / "proposed" / f"{dataset}.json",
        ).as_posix()

    kpis = recommend_kpis(discovery.schema, semantics, dataset)

    plan = AgentPlan(
        plan_id=str(uuid4()),
        file_path=file_path,
        dataset=dataset,
        created_at=_now().isoformat(),
        discovery=discovery,
        semantics=semantics,
        contract=contract,
        contract_path=str(contract_path),
        decision_preview={},
        recommendation=None,
        kpis=kpis,
        dashboard=plan_dashboard(kpis, discovery.schema, semantics),
        contracts_dir=str(contracts_dir),
    )
    _refresh(plan)

    return plan


# ----------------------------------------------------------------------
# VALIDATE
# ----------------------------------------------------------------------


def _record(plan: AgentPlan, action: str, reviewer: str, comment=None) -> None:
    plan.history.append(
        {
            "action": action,
            "reviewed_by": reviewer,
            "reviewed_at": _now().isoformat(),
            "comment": comment,
        }
    )


def _check_reviewer(reviewer: str) -> str:
    if not reviewer or not reviewer.strip():
        raise WorkflowError("La validation exige un relecteur.")

    return reviewer.strip()


def approve_plan_contract(
    plan: AgentPlan,
    reviewer: str,
    comment: str | None = None,
) -> AgentPlan:
    """Valide le contrat proposé et recalcule le plan qui en dépend."""

    reviewer = _check_reviewer(reviewer)

    if plan.contract_status == VALIDATED:
        raise WorkflowError("Le contrat est déjà VALIDATED.")

    path = approve_contract_file(
        plan.contract_path, reviewer, comment, plan.contracts_dir,
    )
    _, plan.contract = load_contract_file(path, plan.contracts_dir)
    plan.contract_path = path.as_posix()
    _refresh(plan)
    _record(plan, "APPROVE_CONTRACT", reviewer, comment)

    return plan


def approve_destructive_transformations(
    plan: AgentPlan,
    reviewer: str,
    comment: str | None = None,
) -> AgentPlan:
    """Autorise les transformations destructives listées dans le plan."""

    reviewer = _check_reviewer(reviewer)

    if not plan.destructive_transformations:
        raise WorkflowError("Aucune transformation destructive à approuver.")

    plan.destructive_approval = {
        "transformations": plan.destructive_transformations,
        "approved_by": reviewer,
    }
    _record(plan, "APPROVE_DESTRUCTIVE_TRANSFORMATIONS", reviewer, comment)

    return plan


def approve_plan_dashboard(
    plan: AgentPlan,
    reviewer: str,
    comment: str | None = None,
) -> AgentPlan:
    plan.dashboard = approve_dashboard(plan.dashboard, reviewer, comment)
    _record(plan, "APPROVE_DASHBOARD", reviewer.strip(), comment)

    return plan


def validation_status(plan: AgentPlan) -> dict:
    """
    État des validations. L'exécution exige un contrat VALIDATED ;
    les transformations destructives non approuvées ne sont pas
    bloquantes, elles seront ignorées. Le tableau de bord n'est
    requis que pour sa création dans Power BI.
    """

    destructive = plan.destructive_transformations
    destructive_approved = bool(destructive) and plan.destructive_approval is not None
    blockers = []

    if plan.contract_status != VALIDATED:
        blockers.append(
            f"Contrat {plan.contract_status} : validation requise avant exécution."
        )

    warnings = quality_warnings(plan)

    return {
        "contract_validated": plan.contract_status == VALIDATED,
        "quality_warnings": warnings,
        "uncorrected_warnings": [w for w in warnings if not w["corrected"]],
        "destructive_transformations": destructive,
        "destructive_approved": destructive_approved,
        "skipped_if_not_approved": [] if destructive_approved else destructive,
        "dashboard_approved": plan.dashboard.status == APPROVED,
        "ready_to_execute": not blockers,
        "blockers": blockers,
    }


def render_plan_preview(plan: AgentPlan) -> str:
    """Aperçu complet du plan, à présenter avant toute validation."""

    schema = plan.discovery.schema
    status = validation_status(plan)
    decision = plan.decision_preview
    lines = [
        "AGENT PLAN",
        f"Fichier : {plan.file_path} ({plan.discovery.format.format}, "
        f"{schema.row_count} lignes, {schema.column_count} colonnes)",
        f"Dataset : {plan.dataset}",
        f"Métier détecté : {plan.recommendation.domain}",
        f"Contrat : {plan.contract_path} ({plan.contract_status})",
        f"Décision prévisionnelle : {decision['decision']} "
        f"({decision['policy_rule']}) - {decision['reason']}",
        "",
        f"Bronze : {plan.recommendation.bronze['table']}",
        f"Silver : {plan.recommendation.silver['table']}",
    ]

    for step in plan.recommendation.transformations:
        flag = " [DESTRUCTIVE - validation requise]" if step.requires_approval else ""
        lines.append(f"  - {step.id} : {step.description}{flag}")

    lines.append("Gold :")
    lines += [
        f"  - {table.name} ({table.table_type})"
        for table in plan.recommendation.gold
    ]

    if status["quality_warnings"]:
        lines.append("Avertissements qualité :")

        for warning in status["quality_warnings"]:
            target = f" ({warning['column']})" if warning["column"] else ""
            outcome = (
                f"corrigé par {warning['correction']}"
                if warning["corrected"]
                else "NON CORRIGÉ : " + (
                    f"approuver {warning['correction']}"
                    if warning["correction"]
                    else "aucune correction prévue"
                )
            )
            lines.append(f"  - {warning['rule']}{target} : {warning['message']} -> {outcome}")

    lines += ["", f"KPI proposés : {len(plan.kpis.kpis)}", ""]
    lines.append(render_dashboard_preview(plan.dashboard))
    lines += ["", "Validations :"]
    lines.append(
        "  - contrat : " + ("OK" if status["contract_validated"] else "À VALIDER")
    )

    if status["destructive_transformations"]:
        lines.append(
            "  - transformations destructives : "
            + ("approuvées" if status["destructive_approved"] else "non approuvées (seront ignorées)")
        )

    lines.append(
        "  - tableau de bord : "
        + ("APPROVED" if status["dashboard_approved"] else plan.dashboard.status)
    )
    lines.append(
        "Prêt à exécuter : " + ("oui" if status["ready_to_execute"] else "non")
    )

    return "\n".join(lines)
