"""
Enrichissements déclaratifs de Silver (colonnes calculées).

Chaque opération est décrite en données, jamais évaluée comme du code :
arithmétique entre deux colonnes, concaténation, partie de date ou
constante. Une colonne cible existante ou une colonne source absente
est refusée.
"""

from typing import Any

import pandas as pd


DATE_PARTS = {"year", "month", "day", "quarter", "weekday"}


def enrich_dataframe(
    df: pd.DataFrame,
    operations: list[dict[str, Any]] | None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Applique les opérations ; retourne le DataFrame et les opérations appliquées."""

    enriched = df.copy()
    applied = []

    for operation in operations or []:
        kind = operation.get("type")
        target = operation.get("target")

        if not isinstance(target, str) or not target or target in enriched.columns:
            raise ValueError(f"Colonne cible invalide ou déjà existante : {target}")

        if kind == "arithmetic":
            left, right = operation.get("left"), operation.get("right")

            if left not in enriched.columns or right not in enriched.columns:
                raise ValueError(f"Colonnes absentes pour {target}: {left}, {right}")

            operator = operation.get("operator", "multiply")
            operators = {
                "add": enriched[left] + enriched[right],
                "subtract": enriched[left] - enriched[right],
                "multiply": enriched[left] * enriched[right],
                "divide": enriched[left] / enriched[right].replace(0, pd.NA),
            }

            if operator not in operators:
                raise ValueError(f"Opérateur arithmétique inconnu : {operator}")

            enriched[target] = operators[operator]
        elif kind == "concat":
            columns = operation.get("columns", [])

            if not columns or any(column not in enriched.columns for column in columns):
                raise ValueError(f"Colonnes absentes pour concaténation : {columns}")

            separator = str(operation.get("separator", " "))
            enriched[target] = (
                enriched[columns].astype("string").fillna("").agg(separator.join, axis=1).str.strip()
            )
        elif kind == "date_part":
            source = operation.get("source")
            part = operation.get("part", "year")

            if source not in enriched.columns or part not in DATE_PARTS:
                raise ValueError(f"Opération date invalide pour {target}")

            dates = pd.to_datetime(enriched[source], errors="coerce")
            enriched[target] = getattr(dates.dt, part)
        elif kind == "constant":
            enriched[target] = operation.get("value")
        else:
            raise ValueError(f"Type d'enrichissement inconnu : {kind}")

        applied.append({"type": kind, "target": target})

    return enriched, applied
