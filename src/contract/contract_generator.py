"""
Proposition automatique d'un Data Contract.

Le contrat est déduit du profil de schéma et du profil sémantique.
Il suit le format lu par src.tools.contract_validation et porte
toujours le statut PROPOSED : il doit être revu avant usage.

Les contraintes restent volontairement générales : elles
traduisent le sens des colonnes (un prix n'est pas négatif), pas
les valeurs observées (le prix maximal de l'échantillon).
"""

from datetime import datetime, timezone
from pathlib import Path

from src.contract.contract_lifecycle import PROPOSED
from src.discovery.dataset_discovery import discover_dataset
from src.discovery.schema_profiler import (
    BOOLEAN,
    DATETIME,
    DECIMAL,
    INTEGER,
    ColumnProfile,
    SchemaProfile,
    name_tokens,
)
from src.semantic.semantic_profiler import (
    PRIMARY_KEY_CANDIDATE,
    ColumnSemantics,
    SemanticProfile,
    profile_semantics,
)
from src.semantic.vocabulary import (
    AMOUNT,
    MEASURE,
    PRICE,
    QUANTITY,
    RATIO,
)


CONTRACT_TYPES = {
    INTEGER: "integer",
    DECIMAL: "decimal",
    BOOLEAN: "boolean",
    DATETIME: "datetime",
}
DECIMAL_BUSINESS_ROLES = {AMOUNT, PRICE, RATIO}
DEFAULT_VERSION = "1.0"
GENERATOR_NAME = "contract_generator"


def dataset_name_from_path(path: str | Path) -> str:
    """ "Ventes Mars.csv" -> "ventes_mars". """

    return "_".join(name_tokens(Path(path).stem)) or "dataset"


def _bounds(
    profile: ColumnProfile,
    semantics: ColumnSemantics,
) -> tuple[dict, list[str]]:
    """
    Déduit min/max du rôle métier, uniquement si les données
    observées respectent déjà la borne proposée.
    """

    if semantics.semantic_role != MEASURE or profile.min is None:
        return {}, []

    role = semantics.business_role

    if role in (AMOUNT, PRICE) and profile.min >= 0:
        return {"min": 0}, [f"min=0 : un {role.lower()} n'est pas négatif"]

    if role == QUANTITY and profile.min >= 1:
        return {"min": 1}, ["min=1 : quantité strictement positive observée"]

    if role == QUANTITY and profile.min >= 0:
        return {"min": 0}, ["min=0 : une quantité n'est pas négative"]

    if role == RATIO and profile.min >= 0:
        maximum = 1 if profile.max <= 1 else 100 if profile.max <= 100 else None

        if maximum is None:
            return {"min": 0}, ["min=0 : un ratio n'est pas négatif"]

        return (
            {"min": 0, "max": maximum},
            [f"bornes 0..{maximum} : ratio exprimé sur {maximum}"],
        )

    return {}, []


def _column_rule(
    profile: ColumnProfile,
    semantics: ColumnSemantics,
    unique: bool,
) -> dict:
    nullable = profile.null_count > 0
    rationale = [
        f"type {profile.inferred_type} observé",
        (
            "nullable : valeurs nulles observées"
            if nullable
            else "non nullable : aucune valeur nulle observée"
        ),
    ]

    contract_type = CONTRACT_TYPES.get(profile.inferred_type, "string")

    if (
        contract_type == "integer"
        and semantics.semantic_role == MEASURE
        and semantics.business_role in DECIMAL_BUSINESS_ROLES
    ):
        # Des prix entiers dans l'échantillon n'excluent pas
        # des centimes dans les prochains fichiers.
        contract_type = "decimal"
        rationale[0] = (
            f"type decimal : {semantics.business_role.lower()} "
            "pouvant comporter des décimales"
        )

    rule = {
        "type": contract_type,
        "nullable": nullable,
    }

    bounds, bounds_rationale = _bounds(profile, semantics)
    rule.update(bounds)
    rationale.extend(bounds_rationale)

    if unique:
        rule["unique"] = True
        rationale.append("unique : clé primaire candidate")

    rule["semantics"] = {
        "semantic_role": semantics.semantic_role,
        "business_role": semantics.business_role,
        "entity": semantics.entity,
        "confidence": semantics.confidence,
    }
    rule["rationale"] = rationale

    return rule


def generate_contract(
    schema: SchemaProfile,
    semantics: SemanticProfile,
    *,
    dataset: str,
    source_file: str | None = None,
    version: str = DEFAULT_VERSION,
    generated_at: datetime | None = None,
) -> dict:
    """
    Construit un contrat PROPOSED à partir des profils.
    """

    candidate_keys = [
        relationship.column
        for relationship in semantics.relationships
        if relationship.relationship_type == PRIMARY_KEY_CANDIDATE
    ]
    column_semantics = {
        column.column: column
        for column in semantics.columns
    }

    quality_rules = []

    if schema.duplicate_rows == 0:
        quality_rules.append(
            {
                "rule": "no_duplicate_rows",
                "enforced_by": "validate_csv",
            }
        )

    return {
        "dataset": dataset,
        "version": version,
        "description": (
            f"Contrat proposé automatiquement pour {dataset}."
        ),
        "status": PROPOSED,
        "generated_by": GENERATOR_NAME,
        "generated_at": (
            generated_at or datetime.now(timezone.utc)
        ).isoformat(),
        "source_file": source_file,
        "domain": (
            semantics.domain.to_dict()
            if semantics.domain
            else None
        ),
        "candidate_keys": candidate_keys,
        "quality_rules": quality_rules,
        "review": None,
        "columns": {
            column.name: _column_rule(
                column,
                column_semantics[column.name],
                unique=column.name in candidate_keys,
            )
            for column in schema.columns
        },
    }


def propose_contract_for_file(
    path: str | Path,
    dataset: str | None = None,
) -> dict:
    """
    Découvre un fichier puis propose son contrat.
    """

    discovery = discover_dataset(path)

    return generate_contract(
        discovery.schema,
        profile_semantics(discovery.schema),
        dataset=dataset or dataset_name_from_path(path),
        source_file=discovery.file.path,
    )
