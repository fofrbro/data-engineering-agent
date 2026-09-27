"""
Traduction des formules de KPI en mesures DAX.

Les formules produites par le kpi_recommender sont analysées en une
petite structure, qui sert à la fois à générer le DAX et à calculer la
valeur avec pandas. Une formule non reconnue est refusée : aucune
traduction n'est devinée.

Formules prises en charge :
    SUM(col)            -> SUM(t[col])
    SUM(a * b)          -> SUMX(t, t[a] * t[b])
    AVG(col)            -> AVERAGE(t[col])
    COUNT(*)            -> COUNTROWS(t)
    COUNT(DISTINCT col) -> DISTINCTCOUNT(t[col])
    X / Y               -> DIVIDE(X, Y)
    X GROUP BY ...      -> X (le regroupement est porté par l'axe du visuel)
"""

import re
from dataclasses import dataclass

import pandas as pd

from src.recommendation.kpi_recommender import KPI, KpiRecommendation


IDENT = r"([A-Za-z_][A-Za-z0-9_]*)"

PATTERNS = [
    ("sum_product", re.compile(rf"^SUM\({IDENT} \* {IDENT}\)$")),
    ("sum", re.compile(rf"^SUM\({IDENT}\)$")),
    ("avg", re.compile(rf"^AVG\({IDENT}\)$")),
    ("count_rows", re.compile(r"^COUNT\(\*\)$")),
    ("distinct_count", re.compile(rf"^COUNT\(DISTINCT {IDENT}\)$")),
]

GROUP_BY = re.compile(r"^(.*?) GROUP BY (?:MONTH\()?([A-Za-z_][A-Za-z0-9_]*)\)?$")
WHERE_NOT_IN = re.compile(
    r"^(.*) WHERE ([A-Za-z_][A-Za-z0-9_]*) NOT IN \(('[^']*'(?:, '[^']*')*)\)$"
)


class UnsupportedFormulaError(ValueError):
    """Formule de KPI sans traduction DAX connue."""


@dataclass(frozen=True)
class Formula:
    op: str
    args: tuple


def parse_formula(formula: str) -> Formula:
    text = formula.strip()
    grouped = GROUP_BY.match(text)

    if grouped:
        text = grouped.group(1).strip()

    excluded = WHERE_NOT_IN.match(text)

    if excluded:
        inner, column, values = excluded.groups()
        return Formula(
            "exclude",
            (
                parse_formula(inner),
                column,
                tuple(value.strip("'") for value in values.split(", ")),
            ),
        )

    if " / " in text:
        left, right = text.split(" / ", 1)
        return Formula("divide", (parse_formula(left), parse_formula(right)))

    for op, pattern in PATTERNS:
        match = pattern.match(text)

        if match:
            return Formula(op, match.groups())

    raise UnsupportedFormulaError(f"Formule non prise en charge : {formula}")


def grouping_column(formula: str) -> str | None:
    """Colonne de regroupement (axe du visuel), si la formule en a une."""

    grouped = GROUP_BY.match(formula.strip())
    return grouped.group(2) if grouped else None


def to_dax(formula: Formula, table: str) -> str:
    def column(name: str) -> str:
        return f"'{table}'[{name}]"

    if formula.op == "sum":
        return f"SUM({column(formula.args[0])})"

    if formula.op == "sum_product":
        left, right = formula.args
        return f"SUMX('{table}', {column(left)} * {column(right)})"

    if formula.op == "avg":
        return f"AVERAGE({column(formula.args[0])})"

    if formula.op == "count_rows":
        return f"COUNTROWS('{table}')"

    if formula.op == "distinct_count":
        return f"DISTINCTCOUNT({column(formula.args[0])})"

    if formula.op == "divide":
        left, right = formula.args
        return f"DIVIDE({to_dax(left, table)}, {to_dax(right, table)})"

    if formula.op == "exclude":
        inner, name, values = formula.args
        listed = ", ".join(f'"{value}"' for value in values)
        return f"CALCULATE({to_dax(inner, table)}, NOT {column(name)} IN {{{listed}}})"

    raise UnsupportedFormulaError(f"Opération inconnue : {formula.op}")


def evaluate(formula: Formula, frame: pd.DataFrame):
    """Valeur de la formule sur un DataFrame, avec la sémantique DAX."""

    if formula.op == "sum":
        return float(pd.to_numeric(frame[formula.args[0]]).sum())

    if formula.op == "sum_product":
        left, right = formula.args
        return float((pd.to_numeric(frame[left]) * pd.to_numeric(frame[right])).sum())

    if formula.op == "avg":
        known = pd.to_numeric(frame[formula.args[0]]).dropna()
        return float(known.mean()) if len(known) else None

    if formula.op == "count_rows":
        return len(frame)

    if formula.op == "distinct_count":
        return int(frame[formula.args[0]].nunique(dropna=False))

    if formula.op == "exclude":
        inner, name, values = formula.args
        return evaluate(inner, frame[~frame[name].isin(values)])

    if formula.op == "divide":
        numerator = evaluate(formula.args[0], frame)
        denominator = evaluate(formula.args[1], frame)
        # DIVIDE sans valeur alternative renvoie BLANK.
        return numerator / denominator if denominator else None

    raise UnsupportedFormulaError(f"Opération inconnue : {formula.op}")


@dataclass
class DaxMeasure:
    name: str
    expression: str
    format: str
    source_kpis: list[str]


def kpi_measures(
    kpis: KpiRecommendation,
    table: str,
) -> tuple[list[DaxMeasure], dict[str, str]]:
    """
    Mesures DAX d'un ensemble de KPI.

    Les KPI qui partagent la même expression (ex. "Revenue" et
    "Revenue by Month") utilisent une seule mesure : le regroupement
    est porté par l'axe du visuel. Retourne les mesures et, pour
    chaque KPI, le nom de la mesure à utiliser.
    """

    measures: dict[str, DaxMeasure] = {}
    kpi_to_measure = {}

    for kpi in kpis.kpis:
        expression = to_dax(parse_formula(kpi.formula), table)

        if expression not in measures:
            measures[expression] = DaxMeasure(
                name=kpi.name.split(" by ")[0],
                expression=expression,
                format=kpi.format,
                source_kpis=[],
            )

        measures[expression].source_kpis.append(kpi.name)
        kpi_to_measure[kpi.name] = measures[expression].name

    return list(measures.values()), kpi_to_measure


def evaluate_kpi(kpi: KPI, frame: pd.DataFrame):
    """Valeur globale (sans regroupement) d'un KPI."""

    return evaluate(parse_formula(kpi.formula), frame)
