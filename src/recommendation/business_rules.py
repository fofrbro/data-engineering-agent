"""
Règles métier déterministes appliquées aux recommandations.

Exclusion des commandes annulées : dans un dataset de ventes, une
colonne de statut contenant une valeur d'annulation (CANCELLED,
ANNULÉE...) signifie que ces lignes ne doivent compter ni dans le
chiffre d'affaires ni dans les autres indicateurs. La règle est
appliquée de la même façon aux KPI (et donc aux mesures DAX) et aux
agrégats Gold, pour que les chiffres restent cohérents.

Limite : la détection s'appuie sur les valeurs d'exemple du profil de
schéma (au plus 5 valeurs distinctes par colonne).
"""

from src.discovery.schema_profiler import SchemaProfile, name_tokens
from src.semantic.semantic_profiler import SALES_DOMAIN, SemanticProfile
from src.semantic.vocabulary import DIMENSION, STATUS


CANCELLATION_TOKENS = {
    "cancelled", "canceled", "cancel", "annule", "annulee", "annulation",
}


def _is_cancellation(value) -> bool:
    return any(token in CANCELLATION_TOKENS for token in name_tokens(value))


def cancellation_exclusion(
    schema: SchemaProfile,
    semantics: SemanticProfile,
) -> dict | None:
    """
    Exclusion à appliquer, ou None :
    {"column": <nom Silver>, "exclude": [<valeurs en majuscules>]}.

    Les valeurs sont en majuscules : la transformation Silver
    normalize_categories met les statuts en majuscules.
    """

    if not semantics.domain or semantics.domain.name != SALES_DOMAIN:
        return None

    profiles = {column.name: column for column in schema.columns}

    for column in semantics.columns:
        if column.semantic_role != DIMENSION or column.business_role != STATUS:
            continue

        values = sorted(
            {
                str(value).strip().upper()
                for value in profiles[column.column].sample_values
                if _is_cancellation(value)
            }
        )

        if values:
            return {
                "column": "_".join(name_tokens(column.column)) or column.column,
                "exclude": values,
            }

    return None


def exclusion_clause(exclusion: dict) -> str:
    """ {"column": "status", "exclude": ["CANCELLED"]} -> status NOT IN ('CANCELLED') """

    values = ", ".join(f"'{value}'" for value in exclusion["exclude"])
    return f"{exclusion['column']} NOT IN ({values})"


def with_exclusion(formula: str, exclusion: dict) -> str:
    """Ajoute la clause WHERE à une formule de KPI, avant un éventuel GROUP BY."""

    clause = f" WHERE {exclusion_clause(exclusion)}"

    if " GROUP BY " in formula:
        expression, grouping = formula.split(" GROUP BY ", 1)
        return f"{expression}{clause} GROUP BY {grouping}"

    return f"{formula}{clause}"
