"""
Construction des tables Gold recommandées à partir de Silver.

Seules des expressions de mesure simples sont acceptées :
SUM(col), AVG(col), COUNT(col). Aucun code n'est évalué.
"""

import re

import pandas as pd

from src.recommendation.pipeline_recommender import GoldTable


METRIC_PATTERN = re.compile(r"^(SUM|AVG|COUNT)\((\w+)\)$")
AGGREGATIONS = {"SUM": "sum", "AVG": "mean", "COUNT": "count"}


class GoldBuildError(ValueError):
    """Table Gold impossible à construire."""


def _require(silver: pd.DataFrame, columns: list[str], table: str) -> None:
    missing = [column for column in columns if column not in silver.columns]

    if missing:
        raise GoldBuildError(f"{table} : colonnes absentes de Silver : {missing}")


def apply_exclusion(frame: pd.DataFrame, exclusion: dict | None) -> pd.DataFrame:
    """Retire les lignes exclues par une règle métier."""

    if not exclusion:
        return frame

    return frame[~frame[exclusion["column"]].isin(exclusion["exclude"])]


def _aggregate(silver: pd.DataFrame, table: GoldTable) -> pd.DataFrame:
    named = {}
    exclusions = {str(metric.exclusion) for metric in table.metrics}

    if len(exclusions) > 1:
        raise GoldBuildError(
            f"{table.name} : les mesures d'une table doivent partager la même exclusion."
        )

    if table.metrics and table.metrics[0].exclusion:
        _require(silver, [table.metrics[0].exclusion["column"]], table.name)
        silver = apply_exclusion(silver, table.metrics[0].exclusion)

    for metric in table.metrics:
        match = METRIC_PATTERN.match(metric.expression)

        if not match:
            raise GoldBuildError(
                f"{table.name} : expression non prise en charge : {metric.expression}"
            )

        function, column = match.groups()
        _require(silver, [column], table.name)
        named[metric.name] = (column, AGGREGATIONS[function])

    _require(silver, table.grain, table.name)

    if not table.grain:
        return pd.DataFrame(
            {
                name: [silver[column].agg(function)]
                for name, (column, function) in named.items()
            }
        )

    return silver.groupby(table.grain, as_index=False, dropna=False).agg(**named)


def _date_dimension(silver: pd.DataFrame, date_column: str | None) -> pd.DataFrame:
    if not date_column or date_column not in silver.columns:
        raise GoldBuildError("dim_date : colonne de date inconnue.")

    dates = pd.to_datetime(silver[date_column], utc=True).dt.normalize()
    dates = pd.Series(dates.dropna().unique()).sort_values(ignore_index=True)

    return pd.DataFrame(
        {
            "date": dates,
            "year": dates.dt.year,
            "quarter": dates.dt.quarter,
            "month": dates.dt.month,
            "day": dates.dt.day,
        }
    )


def build_gold_table(
    silver: pd.DataFrame,
    table: GoldTable,
    date_column: str | None = None,
) -> pd.DataFrame:
    if table.table_type == "aggregate":
        return _aggregate(silver, table)

    if table.name == "dim_date":
        return _date_dimension(silver, date_column)

    _require(silver, table.columns, table.name)

    if table.table_type == "dimension":
        return (
            silver[table.columns]
            .drop_duplicates(subset=table.grain)
            .sort_values(table.grain)
            .reset_index(drop=True)
        )

    if table.table_type == "fact":
        return silver[table.columns].reset_index(drop=True)

    raise GoldBuildError(f"Type de table inconnu : {table.table_type}")


def build_gold_tables(
    silver: pd.DataFrame,
    tables: list[GoldTable],
    date_column: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Construit toutes les tables Gold, dans l'ordre recommandé."""

    return {
        table.name: build_gold_table(silver, table, date_column)
        for table in tables
    }
