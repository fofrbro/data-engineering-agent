"""
Workflow agent : PLAN -> VALIDATE -> EXECUTE -> VERIFY -> AUDIT.

PLAN     : découverte, sémantique, contrat, décision prévisionnelle,
           pipeline Bronze/Silver/Gold, KPI et tableau de bord.
VALIDATE : l'utilisateur valide le contrat, les transformations
           destructives et le tableau de bord. Rien n'est validé
           implicitement.

Toutes les étapes sont déterministes. Seule la relecture sémantique,
facultative, fait appel à un LLM : ses suggestions sont vérifiées par
le code et ne s'appliquent qu'après acceptation par un relecteur.
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
import pandas as pd

from src.discovery.dataset_discovery import DiscoveryResult, discover_dataset
from src.discovery.readers import read_dataset
from src.discovery.schema_profiler import SchemaProfile, profile_schema
from src.recommendation.dashboard_planner import DashboardPlan, plan_dashboard
from src.recommendation.dashboard_review import (
    APPROVED,
    approve_dashboard,
    render_dashboard_preview,
)
from src.recommendation.kpi_recommender import KpiRecommendation, recommend_kpis
from src.recommendation.pipeline_recommender import (
    PipelineRecommendation,
    Transformation,
    recommend_pipeline,
)
from src.semantic.column_naming import (
    DATASET_PATTERN,
    invalid_names_reason,
    normalize_column_names,
)
from src.semantic.semantic_profiler import SemanticProfile, profile_semantics
from src.semantic.semantic_review import (
    ACCEPTED,
    COMPLETED,
    REJECTED,
    SemanticReview,
    apply_semantic_overrides,
    review_semantics,
)
from src.tools.contract_validation import validate_contract
from src.tools.data_validation import validate_csv
from src.tools.ingestion_decision import determine_ingestion_decision


PLANNED = "PLANNED"
READY = "READY"
EXECUTED = "EXECUTED"
FAILED = "FAILED"
BLOCKED = "BLOCKED"

DEFAULT_CONTRACTS_DIR = Path("data/contracts")

# Origine du contrat utilisé par un plan.
CONTRACT_PROVIDED = "PROVIDED"
CONTRACT_REUSED = "REUSED"
CONTRACT_PROPOSED = "PROPOSED"


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
    contract_origin: str = CONTRACT_PROPOSED
    file_paths: list[str] = field(default_factory=list)
    file_previews: list[dict] = field(default_factory=list)
    # Fichiers sur lesquels portent profil et recommandations.
    profiled_files: list[str] = field(default_factory=list)
    enrichments: list[dict] = field(default_factory=list)
    quality_preview: dict = field(default_factory=dict)
    destructive_approval: dict | None = None
    # Fichiers sans en-tête préparés avant le plan (original, copie
    # avec en-tête, origine des noms) ; vide si aucun.
    file_preparations: list[dict] = field(default_factory=list)
    # Noms des colonnes des fichiers sans en-tête : proposés, puis validés
    # (ou modifiés) par un relecteur avant le contrat. None sans objet.
    column_naming: dict | None = None
    # Instructions de l'utilisateur et leur interprétation (voir
    # src.workflow.instructions).
    instructions: dict | None = None
    semantic_review: SemanticReview | None = None
    # Rôles acceptés par un relecteur, par colonne : ils remplacent
    # l'interprétation déterministe à chaque recalcul du profil.
    semantic_overrides: dict[str, dict] = field(default_factory=dict)
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


ENRICHMENT_SOURCES = {
    "arithmetic": lambda op: [op.get("left"), op.get("right")],
    "concat": lambda op: list(op.get("columns") or []),
    "date_part": lambda op: [op.get("source")],
    "constant": lambda op: [],
}
ARITHMETIC_OPERATORS = {"add", "subtract", "multiply", "divide"}
DATE_PARTS = {"year", "month", "day", "quarter", "weekday"}


def enrichment_transformations(
    recommendation: PipelineRecommendation,
    enrichments: list[dict],
) -> list[Transformation]:
    """
    Transforme les enrichissements déclaratifs en étapes Silver.

    Les colonnes sont désignées par leur nom Silver ; elles doivent
    exister après les transformations recommandées (ou être créées
    par un enrichissement précédent). Aucun code n'est évalué.
    """

    available = set(recommendation.bronze["columns"])
    steps = []

    for step in recommendation.transformations:
        if step.type == "rename":
            available = {step.parameters["mapping"].get(c, c) for c in available}
        if step.type == "derive":
            derived = [step.parameters.get("target"), *step.parameters.get("targets", [])]
            available |= {column for column in derived if column}

    for operation in enrichments:
        kind = operation.get("type")
        target = operation.get("target")

        if kind not in ENRICHMENT_SOURCES:
            raise WorkflowError(f"Type d'enrichissement inconnu : {kind}")

        if not isinstance(target, str) or not target or target in available:
            raise WorkflowError(f"Colonne cible invalide ou déjà existante : {target}")

        sources = ENRICHMENT_SOURCES[kind](operation)
        missing = [c for c in sources if c not in available]

        if missing or (kind == "concat" and not sources):
            raise WorkflowError(f"Colonnes absentes pour {target} : {missing or sources}")

        if kind == "arithmetic" and operation.get("operator", "multiply") not in ARITHMETIC_OPERATORS:
            raise WorkflowError(f"Opérateur inconnu pour {target} : {operation.get('operator')}")

        if kind == "date_part" and operation.get("part", "year") not in DATE_PARTS:
            raise WorkflowError(f"Partie de date inconnue pour {target} : {operation.get('part')}")

        available.add(target)
        steps.append(
            Transformation(
                id=f"enrich_{target}",
                type="enrich",
                columns=sources,
                description=f"Enrichissement {kind} : créer {target}.",
                rationale="Enrichissement demandé par l'utilisateur.",
                parameters={"operation": dict(operation)},
            )
        )

    return steps


def _refresh(plan: AgentPlan) -> None:
    """
    Recalcule ce qui dépend du contrat : décisions prévisionnelles par
    fichier (non auditées ; la décision qui compte est recalculée à
    l'exécution), puis profil et recommandations.

    Dans un lot, le profil ne porte que sur les fichiers qui seront
    ingérés : un fichier refusé ne doit pas influencer Silver, Gold,
    les KPI ni le tableau de bord (par exemple rendre une clé non unique).
    """

    previews = []

    for path in plan.file_paths:
        quality = validate_csv(path, plan.contract_path)
        decision = determine_ingestion_decision(
            validate_contract(path, plan.contract_path),
            quality,
        )
        previews.append({"file": path, "quality": quality, "decision": decision})

    plan.file_previews = [
        {
            "file": preview["file"],
            "rows": preview["quality"]["rows"],
            "decision": preview["decision"]["decision"],
            "policy_rule": preview["decision"]["policy_rule"],
            "reason": preview["decision"]["reason"],
        }
        for preview in previews
    ]

    if len(previews) == 1:
        plan.quality_preview = previews[0]["quality"]
        plan.decision_preview = previews[0]["decision"]
    else:
        plan.quality_preview = {
            "issues": [
                {**issue, "file": preview["file"]}
                for preview in previews
                for issue in preview["quality"]["issues"]
            ]
        }
        plan.decision_preview = _batch_decision(plan.file_previews)

    admitted = [p["file"] for p in plan.file_previews if p["decision"] == "INGEST"]
    profiled = admitted or plan.file_paths

    if profiled != plan.profiled_files:
        _reprofile(plan, profiled)

    plan.recommendation = recommend_pipeline(
        plan.discovery.schema, plan.semantics, plan.contract, plan.dataset,
    )
    plan.recommendation.transformations.extend(
        enrichment_transformations(plan.recommendation, plan.enrichments)
    )


def _reprofile(plan: AgentPlan, file_paths: list[str]) -> None:
    """Recalcule profil, sémantique, KPI et tableau de bord sur ces fichiers."""

    discovery = _discover(file_paths)
    plan.discovery, plan.semantics = _restrict_to_contract(
        discovery, profile_semantics(discovery.schema), plan.contract,
    )
    plan.semantics = apply_semantic_overrides(
        plan.semantics, plan.discovery.schema, plan.semantic_overrides,
    )
    plan.kpis = recommend_kpis(plan.discovery.schema, plan.semantics, plan.dataset)

    if plan.dashboard is not None and plan.dashboard.status != "PROPOSED":
        # Le tableau de bord revu portait sur un autre profil : il doit
        # être revu à nouveau.
        plan.history.append(
            {
                "action": "DASHBOARD_RESET",
                "reviewed_by": None,
                "reviewed_at": _now().isoformat(),
                "comment": "Profil recalculé sur les fichiers admis : tableau de bord à revoir.",
            }
        )

    plan.dashboard = plan_dashboard(plan.kpis, plan.discovery.schema, plan.semantics)
    plan.profiled_files = list(file_paths)


def _batch_decision(file_previews: list[dict]) -> dict:
    """Synthèse des décisions prévisionnelles d'un lot de fichiers."""

    decisions = [preview["decision"] for preview in file_previews]

    if len(set(decisions)) == 1:
        return {
            "decision": decisions[0],
            "policy_rule": "PER_FILE",
            "reason": f"Même décision pour les {len(decisions)} fichiers.",
        }

    counts = ", ".join(
        f"{decisions.count(decision)} {decision}"
        for decision in ("INGEST", "QUARANTINE", "REJECT")
        if decision in decisions
    )

    return {
        "decision": "PARTIAL",
        "policy_rule": "PER_FILE",
        "reason": (
            f"Décision par fichier : {counts}. Seuls les fichiers INGEST "
            "seront combinés ; les autres seront isolés."
        ),
    }


def _restrict_to_contract(
    discovery: DiscoveryResult,
    semantics: SemanticProfile,
    contract: dict,
) -> tuple[DiscoveryResult, SemanticProfile]:
    """
    Les recommandations suivent le contrat : une colonne hors contrat
    (signalée comme inattendue par la validation) n'est ni transformée
    ni utilisée dans Gold, les KPI ou le tableau de bord. Sans colonnes
    dans le contrat, le profil complet est gardé ; sans aucune colonne
    commune aussi : le fichier sera rejeté, mais son plan reste lisible.
    """

    contract_columns = set(contract.get("columns") or {})
    schema = discovery.schema
    kept = [c for c in schema.columns if c.name in contract_columns]

    if not kept or len(kept) == len(schema.columns):
        return discovery, semantics

    restricted = SchemaProfile(
        row_count=schema.row_count,
        column_count=len(kept),
        duplicate_rows=schema.duplicate_rows,
        columns=kept,
    )

    return (
        DiscoveryResult(file=discovery.file, format=discovery.format, schema=restricted),
        profile_semantics(restricted),
    )


def _discover(file_paths: list[str]) -> DiscoveryResult:
    """
    Découverte d'un fichier ou d'un lot : pour un lot, le profil de
    schéma porte sur l'ensemble des lignes de tous les fichiers.
    """

    if len(file_paths) == 1:
        return discover_dataset(file_paths[0])

    datasets = [read_dataset(path) for path in file_paths]
    combined = pd.concat([frame for _, _, frame in datasets], ignore_index=True)
    file_info, format_info, _ = datasets[0]

    return DiscoveryResult(
        file=file_info,
        format=format_info,
        schema=profile_schema(combined),
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
    file_path: str | list[str],
    contract_path: str | None = None,
    dataset: str | None = None,
    contracts_dir: str | Path = DEFAULT_CONTRACTS_DIR,
    enrichments: list[dict] | None = None,
) -> AgentPlan:
    """
    PLAN : analyse le fichier et propose tout ce qui est nécessaire
    à son traitement. Les enrichissements déclaratifs demandés
    deviennent des transformations Silver.

    Contrat utilisé, par ordre de priorité :
    1. le contrat fourni ;
    2. le contrat VALIDATED existant du dataset
       (<contracts_dir>/<dataset>.json), réutilisé tel quel ;
    3. sinon, un contrat PROPOSED généré dans <contracts_dir>/proposed/.
    Un contrat réutilisé est confronté au nouveau fichier comme tout
    autre : s'il ne correspond plus, la décision sera REJECT.

    file_path peut être une liste : les fichiers forment alors un seul
    dataset (voir src.workflow.batch.group_files) ; chaque fichier aura
    sa propre décision.
    """

    file_paths = [file_path] if isinstance(file_path, str) else list(file_path)

    if not file_paths:
        raise WorkflowError("Aucun fichier à planifier.")

    file_path = file_paths[0]
    discovery = _discover(file_paths)
    semantics = profile_semantics(discovery.schema)
    contract_origin = CONTRACT_PROVIDED

    if not contract_path:
        dataset = dataset or dataset_name_from_path(file_path)
        existing = Path(contracts_dir) / f"{dataset}.json"

        if existing.is_file():
            _, candidate = load_contract_file(existing, contracts_dir)

            if contract_status(candidate) == VALIDATED:
                contract_path = existing.as_posix()
                contract_origin = CONTRACT_REUSED

    if contract_path:
        _, contract = load_contract_file(contract_path, contracts_dir)
        dataset = dataset or contract.get("dataset")
    else:
        contract_origin = CONTRACT_PROPOSED
        contract = generate_contract(
            discovery.schema,
            semantics,
            dataset=dataset,
            source_file=", ".join(file_paths),
        )
        contract_path = save_contract(
            contract,
            Path(contracts_dir) / "proposed" / f"{dataset}.json",
        ).as_posix()

    discovery, semantics = _restrict_to_contract(discovery, semantics, contract)
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
        contract_origin=contract_origin,
        file_paths=file_paths,
        profiled_files=list(file_paths),
        enrichments=list(enrichments or []),
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

    if plan.column_naming and plan.column_naming["status"] != VALIDATED:
        raise WorkflowError("Validez d'abord les noms de colonnes : le contrat en dépend.")

    path = approve_contract_file(
        plan.contract_path, reviewer, comment, plan.contracts_dir,
    )
    _, plan.contract = load_contract_file(path, plan.contracts_dir)
    plan.contract_path = path.as_posix()
    _refresh(plan)
    _record(plan, "APPROVE_CONTRACT", reviewer, comment)

    return plan


def review_plan_semantics(plan: AgentPlan, client) -> AgentPlan:
    """
    Demande au LLM une relecture de l'interprétation des colonnes.
    Rien n'est appliqué : les suggestions attendent une décision.
    """

    plan.semantic_review = review_semantics(
        client, plan.discovery.schema, plan.semantics, plan.dataset,
    )
    review = plan.semantic_review
    plan.history.append(
        {
            "action": "SEMANTIC_REVIEW",
            "reviewed_by": None,
            "reviewed_at": review.reviewed_at,
            "comment": (
                f"{len(review.suggestions)} suggestion(s), "
                f"{len(review.discarded)} écartée(s) par les contrôles."
                if review.status == COMPLETED
                else review.error
            ),
        }
    )

    return plan


def decide_semantic_suggestions(
    plan: AgentPlan,
    reviewer: str,
    accepted_ids: list[str],
    comment: str | None = None,
) -> AgentPlan:
    """
    Accepte les suggestions listées et rejette les autres. Les rôles
    acceptés sont appliqués et le plan est recalculé ; un contrat
    encore proposé est régénéré avec ces rôles, un contrat validé
    n'est jamais modifié.
    """

    reviewer = _check_reviewer(reviewer)
    review = plan.semantic_review

    if review is None or review.status != COMPLETED:
        raise WorkflowError("Aucune relecture sémantique à décider.")

    if not review.pending:
        raise WorkflowError("Les suggestions de cette relecture sont déjà décidées.")

    unknown = set(accepted_ids) - {s.id for s in review.pending}

    if unknown:
        raise WorkflowError(f"Suggestions inconnues : {', '.join(sorted(unknown))}")

    accepted = []

    for suggestion in review.pending:
        if suggestion.id in accepted_ids:
            suggestion.status = ACCEPTED
            accepted.append(suggestion)
            plan.semantic_overrides[suggestion.column] = {
                "semantic_role": suggestion.semantic_role,
                "business_role": suggestion.business_role,
                "reason": suggestion.reason,
                "accepted_by": reviewer,
            }
        else:
            suggestion.status = REJECTED

    review.decided_by = reviewer
    review.decided_at = _now().isoformat()

    if accepted:
        _reprofile(plan, plan.profiled_files)

        if plan.contract_status != VALIDATED:
            plan.contract = generate_contract(
                plan.discovery.schema,
                plan.semantics,
                dataset=plan.dataset,
                source_file=", ".join(plan.file_paths),
            )
            save_contract(plan.contract, plan.contract_path)

        _refresh(plan)

    summary = f"{len(accepted)} acceptée(s) sur {len(review.suggestions)}"

    if accepted and plan.contract_status == VALIDATED:
        summary += " ; contrat validé inchangé"

    _record(
        plan,
        "DECIDE_SEMANTIC_SUGGESTIONS",
        reviewer,
        f"{summary}. {comment}" if comment else f"{summary}.",
    )

    return plan


def _rewrite_header(path: str, names: list[str]) -> None:
    """Remplace l'en-tête d'une copie préparée ; les cellules sont inchangées."""

    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.set_axis(names, axis=1).to_csv(path, index=False, encoding="utf-8")


def review_plan_column_names(
    plan: AgentPlan,
    reviewer: str,
    names: list[str] | None = None,
    dataset: str | None = None,
    comment: str | None = None,
) -> AgentPlan:
    """
    Valide les noms de colonnes proposés, ou les remplace. Des noms
    modifiés sont écrits dans les copies préparées et le plan est
    recalculé (profil, contrat, recommandations) : le plan renvoyé
    remplace l'ancien, sous le même identifiant.

    Si le contrat du plan est déjà validé, les noms ne peuvent changer
    qu'avec un autre nom de dataset : ils ne correspondraient plus à ce
    contrat. Les noms sont normalisés (sans accent, espace ni tiret).
    """

    reviewer = _check_reviewer(reviewer)
    naming = plan.column_naming

    if naming is None:
        raise WorkflowError("Ce plan n'a pas de noms de colonnes à valider.")

    names = normalize_column_names(names) if names else list(naming["names"])
    renamed = names != naming["names"]
    new_dataset = dataset if dataset and dataset != plan.dataset else None

    if renamed and not naming["editable"]:
        raise WorkflowError(
            "Un fichier du lot a un en-tête : ses noms de colonnes s'imposent aux autres."
        )

    if len(names) != len(naming["names"]):
        raise WorkflowError(f"{len(names)} noms pour {len(naming['names'])} colonnes.")

    reason = invalid_names_reason(names)

    if reason:
        raise WorkflowError(f"Noms de colonnes : {reason}.")

    if new_dataset and not DATASET_PATTERN.match(new_dataset):
        raise WorkflowError(
            f"Nom de dataset invalide : {new_dataset} (minuscules, chiffres et _)."
        )

    if not renamed and not new_dataset:
        naming.update(status=VALIDATED, validated_by=reviewer, validated_at=_now().isoformat())
        _record(plan, "VALIDATE_COLUMN_NAMES", reviewer, comment)
        return plan

    if renamed and plan.contract_status == VALIDATED and not new_dataset:
        raise WorkflowError(
            f"Ces noms ne correspondent plus au contrat validé « {plan.dataset} » : "
            "indiquez un autre nom de dataset."
        )

    for preparation in plan.file_preparations:
        _rewrite_header(preparation["path"], names)

    updated = plan_file(
        plan.file_paths,
        contract_path=plan.contract_path if plan.contract_origin == CONTRACT_PROVIDED else None,
        dataset=new_dataset or plan.dataset,
        contracts_dir=plan.contracts_dir,
        enrichments=plan.enrichments,
    )
    updated.plan_id = plan.plan_id
    updated.created_at = plan.created_at
    updated.history = plan.history
    updated.instructions = plan.instructions
    source = "USER" if renamed else naming["source"]
    updated.file_preparations = [
        {**preparation, "header_source": source, "note": f"noms validés par {reviewer}"}
        for preparation in plan.file_preparations
    ]
    updated.column_naming = {
        **naming,
        "names": names,
        "source": source,
        "status": VALIDATED,
        "validated_by": reviewer,
        "validated_at": _now().isoformat(),
    }
    changes = [f"noms modifiés : {', '.join(names)}"] if renamed else []
    changes += [f"dataset {plan.dataset} -> {updated.dataset}"] if new_dataset else []
    detail = "; ".join(changes)
    _record(updated, "RENAME_COLUMNS", reviewer, f"{detail}. {comment}" if comment else detail)

    return updated


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

    names_validated = plan.column_naming is None or plan.column_naming["status"] == VALIDATED

    if not names_validated:
        blockers.append("Noms de colonnes à valider, puis le contrat.")

    if plan.contract_status != VALIDATED:
        blockers.append(
            f"Contrat {plan.contract_status} : validation requise avant exécution."
        )

    warnings = quality_warnings(plan)

    return {
        "column_names_validated": names_validated,
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


CONTRACT_ORIGIN_LABELS = {
    CONTRACT_PROVIDED: "fourni",
    CONTRACT_REUSED: "contrat validé existant réutilisé",
    CONTRACT_PROPOSED: "proposé par l'agent",
}


def render_plan_preview(plan: AgentPlan) -> str:
    """Aperçu complet du plan, à présenter avant toute validation."""

    schema = plan.discovery.schema
    status = validation_status(plan)
    decision = plan.decision_preview
    if len(plan.file_paths) > 1:
        source = [
            f"Fichiers : {len(plan.file_paths)} "
            f"({sum(p['rows'] for p in plan.file_previews)} lignes au total)",
            *[
                f"  - {preview['file']} : {preview['rows']} lignes, "
                f"décision prévue {preview['decision']} ({preview['policy_rule']})"
                for preview in plan.file_previews
            ],
            f"Profil et recommandations : {len(plan.profiled_files)} fichier(s) "
            f"{'admis' if plan.profiled_files != plan.file_paths else 'du lot'}, "
            f"{schema.row_count} lignes, {schema.column_count} colonnes",
        ]
    else:
        source = [
            f"Fichier : {plan.file_path} ({plan.discovery.format.format}, "
            f"{schema.row_count} lignes, {schema.column_count} colonnes)",
        ]

    for preparation in plan.file_preparations:
        source.append(
            f"  Sans en-tête : {preparation['original']} -> {preparation['path']} "
            f"({preparation['note']})"
        )

    if plan.column_naming:
        naming = plan.column_naming
        source.append(
            f"Noms de colonnes ({naming['source']}, {naming['status']}) : "
            f"{', '.join(naming['names'])}"
        )

    if plan.instructions:
        source.append(f"Instructions : {plan.instructions['text']}")
        source.append(
            "  -> " + (plan.instructions.get("message") or plan.instructions.get("error") or "")
        )

    lines = [
        "AGENT PLAN",
        *source,
        f"Dataset : {plan.dataset}",
        f"Métier détecté : {plan.recommendation.domain}",
        f"Contrat : {plan.contract_path} ({plan.contract_status}, "
        f"{CONTRACT_ORIGIN_LABELS[plan.contract_origin]})",
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
