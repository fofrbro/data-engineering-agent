"""
Analyse métier complète des données ingérées (Silver), après exécution.

Tout est calculé par le code, avec les mêmes formules que Gold et Power BI
(src.powerbi.kpi_dax.evaluate) et la même règle métier (lignes exclues,
par exemple les commandes annulées) :
- vue d'ensemble : lignes analysées et exclues, période couverte ;
- KPI du plan, avec leur valeur ;
- tendance mensuelle de la mesure principale : meilleur et moins bon mois,
  évolution du dernier mois, mois incomplets signalés ;
- répartitions par dimension : top 5, part du top 5, concentration
  (combien de valeurs font 80 % du total) ;
- distributions des mesures : quartiles et valeurs atypiques (règle
  1,5 × écart interquartile) ;
- moyennes des mesures de niveau (âge, température…) et des mesures sans
  rôle métier : globale, par mois et par dimension, car les additionner
  n'aurait pas de sens ;
- constats rédigés par des règles.
Le commentaire du LLM (voir analysis_commentary) ne s'appuie que sur ces
chiffres.
"""

import pandas as pd

from src.execution.gold_executor import apply_exclusion
from src.powerbi.kpi_dax import UnsupportedFormulaError, evaluate, parse_formula
from src.recommendation.kpi_recommender import (
    BREAKDOWN,
    SCALAR,
    TREND,
    KpiRecommendation,
)
from src.recommendation.pipeline_recommender import silver_column_name
from src.semantic.semantic_profiler import SemanticProfile
from src.semantic.vocabulary import (
    CATEGORY,
    CONTACT,
    CUSTOMER,
    DATE_PART,
    DIMENSION,
    GEOGRAPHY,
    IDENTIFIER,
    LEVEL,
    MEASURE,
    PRODUCT,
    STATUS,
    TEMPORAL,
)


TOP = 5
MAX_DIMENSIONS = 5
MAX_AVERAGED_MEASURES = 4
MAX_AVERAGE_DIMENSIONS = 2
# Au-delà, seules les valeurs extrêmes d'une dimension sont montrées.
MAX_AVERAGE_VALUES = 10
# Une moyenne sur moins de lignes n'est pas citée comme extrême.
MIN_GROUP_ROWS = 5
# En deçà de cet écart relatif, des moyennes sont dites « proches ».
CLOSE_SPREAD = 0.05
PARETO_SHARE = 0.8
# Au-delà de cette part, les valeurs hors de 1,5 × l'écart interquartile
# décrivent une distribution étalée (plusieurs gammes), pas des anomalies.
SPREAD_SHARE = 0.1

# Ordre de présentation des répartitions.
DIMENSION_PRIORITY = {PRODUCT: 0, CUSTOMER: 1, CATEGORY: 2, GEOGRAPHY: 3, STATUS: 4}


def fr_number(value, digits: int = 2) -> str:
    """ 1668735.18 -> « 1 668 735,18 » (espace fine insécable comme séparateur). """

    text = f"{value:,.{digits}f}"
    return text.replace(",", "\u202f").replace(".", ",")


def fr_percent(rate: float) -> str:
    """ 0.678 -> « 67,8 % » """

    return f"{fr_number(rate * 100, 1)}\u00a0%"


def _number(value):
    """Valeur sérialisable en JSON (None pour NaN)."""

    if value is None or pd.isna(value):
        return None

    return float(value) if not float(value).is_integer() else int(value)


COUNT_LABEL = "Nombre de lignes"


def _row_values(kpi, frame: pd.DataFrame) -> pd.Series | None:
    """Valeur ligne à ligne d'un KPI additif (somme ou comptage)."""

    try:
        formula = parse_formula(kpi.formula)
    except UnsupportedFormulaError:
        return None

    if formula.op == "exclude":
        formula = formula.args[0]

    if formula.op == "sum":
        return pd.to_numeric(frame[formula.args[0]], errors="coerce")

    if formula.op == "sum_product":
        left, right = formula.args
        return pd.to_numeric(frame[left], errors="coerce") * pd.to_numeric(frame[right], errors="coerce")

    if formula.op == "count_rows":
        return pd.Series(1, index=frame.index)

    return None


def _main_measure(kpis: KpiRecommendation, frame: pd.DataFrame) -> tuple[str, pd.Series, str]:
    """
    Mesure principale ligne à ligne, avec son libellé et son format :
    celle que les KPI suivent dans le temps et par dimension (le chiffre
    d'affaires d'un dataset de ventes, sinon le nombre de lignes). Une
    mesure de niveau n'en est jamais une : on ne l'additionne pas.
    """

    grouped = [k for k in kpis.kpis if k.kpi_type in (TREND, BREAKDOWN) and k.aggregation in ("SUM", "COUNT")]
    scalars = [k for k in kpis.kpis if k.kpi_type == SCALAR and k.aggregation == "SUM"]

    for kpi in [*grouped, *scalars]:
        values = _row_values(kpi, frame)

        if values is not None:
            label = kpi.name.split(" by ")[0]

            if kpi.aggregation == "COUNT":
                return COUNT_LABEL, values, "integer"

            return label, values, kpi.format

    return COUNT_LABEL, pd.Series(1, index=frame.index), "integer"


def _kpi_values(kpis: KpiRecommendation, frame: pd.DataFrame) -> list[dict]:
    values = []

    for kpi in kpis.kpis:
        if kpi.kpi_type != SCALAR:
            continue

        try:
            value = evaluate(parse_formula(kpi.formula), frame)
        except (UnsupportedFormulaError, KeyError, ValueError):
            continue

        values.append(
            {
                "name": kpi.name,
                "description": kpi.description,
                "value": _number(value),
                "format": "integer" if kpi.aggregation in ("COUNT", "COUNT_DISTINCT") else kpi.format,
            }
        )

    return values


def _columns(semantics: SemanticProfile, frame: pd.DataFrame, role: str) -> list:
    return [
        column
        for column in semantics.columns
        if column.semantic_role == role and silver_column_name(column.column) in frame.columns
    ]


def _dates(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(frame[column], errors="coerce", utc=True).dt.tz_localize(None)


def _trend(
    frame: pd.DataFrame,
    measure: pd.Series,
    date_column: str,
    coverage: pd.Series,
) -> dict | None:
    """
    coverage : dates de toutes les lignes, avant exclusion. La période
    couverte ne dépend pas des lignes exclues (un dernier jour fait
    uniquement d'annulations ne rend pas le mois incomplet).
    """

    dates = _dates(frame, date_column)
    known = dates.notna()

    if not known.any():
        return None

    months = dates[known].dt.to_period("M")
    covered = coverage.dropna().dt.normalize()
    start, end = covered.min(), covered.max()

    # Tous les mois de la période, y compris ceux sans ligne (valeur 0) :
    # des mois sans embauche ne doivent ni disparaître ni fausser les
    # comparaisons.
    calendar = pd.period_range(start.to_period("M"), end.to_period("M"), freq="M")
    grouped = (
        measure[known].groupby(months).agg(["sum", "count"])
        .reindex(calendar, fill_value=0)
    )

    series = [
        {"month": str(period), "value": _number(row["sum"]), "rows": int(row["count"])}
        for period, row in grouped.iterrows()
    ]
    incomplete = [
        str(period)
        for period in (calendar[0], calendar[-1])
        if (period == calendar[0] and start.day > 1)
        or (period == calendar[-1] and end.day < period.days_in_month)
    ]
    trend = {
        "date_column": date_column,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "months": series,
        "incomplete_months": sorted(set(incomplete)),
    }

    by_year = grouped["sum"].groupby(grouped.index.year)
    trend["years"] = [
        {
            "year": int(year),
            "value": _number(values.sum()),
            "months": int(len(values)),
            # Année entièrement couverte par la période du fichier.
            "complete": len(values) == 12
            and not any(str(p) in trend["incomplete_months"] for p in values.index),
        }
        for year, values in by_year
    ]
    complete_years = {y["year"]: y for y in trend["years"] if y["complete"]}
    last_year = max(complete_years, default=None)

    # Deux années complètes et consécutives, jamais 2024 face à 2022.
    if last_year and last_year - 1 in complete_years and complete_years[last_year - 1]["value"]:
        last, previous = complete_years[last_year], complete_years[last_year - 1]
        trend["year_change"] = {
            "year": last["year"],
            "previous": previous["year"],
            "rate": _number((last["value"] - previous["value"]) / previous["value"]),
        }

    complete = [m for m in series if m["month"] not in trend["incomplete_months"]] or series
    best = max(complete, key=lambda m: m["value"] or 0)
    worst = min(complete, key=lambda m: m["value"] or 0)
    trend.update(best=best, worst=worst, average=_number(sum(m["value"] or 0 for m in complete) / len(complete)))

    if len(complete) >= 2:
        last, previous = complete[-1], complete[-2]
        trend["last_change"] = {
            "month": last["month"],
            "previous": previous["month"],
            "rate": _number((last["value"] - previous["value"]) / previous["value"]) if previous["value"] else None,
        }

    return trend


def _breakdown(frame: pd.DataFrame, measure: pd.Series, column, name: str) -> dict:
    totals = measure.groupby(frame[name].astype("string").fillna("(vide)")).sum().sort_values(ascending=False)
    grand_total = float(totals.sum())
    shares = totals / grand_total if grand_total else totals * 0
    cumulative = shares.cumsum()

    return {
        "column": name,
        "entity": column.entity,
        "business_role": column.business_role,
        "distinct": int(len(totals)),
        "top": [
            {"value": str(value), "total": _number(total), "share": _number(shares[value])}
            for value, total in totals.head(TOP).items()
        ],
        "top_share": _number(shares.head(TOP).sum()),
        # Nombre de valeurs qui, ensemble, font 80 % du total.
        "pareto_share": PARETO_SHARE,
        "values_for_80_percent": int((cumulative < PARETO_SHARE).sum() + 1) if grand_total else None,
    }


def _distribution(values: pd.Series, name: str) -> dict | None:
    values = pd.to_numeric(values, errors="coerce").dropna()

    if values.empty:
        return None

    if values.min() == values.max():
        return {"column": name, "count": int(len(values)), "constant": _number(values.min())}

    q1, median, q3 = values.quantile([0.25, 0.5, 0.75])
    spread = q3 - q1
    low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
    outliers = values[(values < low) | (values > high)]

    return {
        "column": name,
        "count": int(len(values)),
        "min": _number(values.min()),
        "q1": _number(q1),
        "median": _number(median),
        "q3": _number(q3),
        "max": _number(values.max()),
        "mean": _number(values.mean()),
        "std": _number(values.std()) if len(values) > 1 else None,
        "outliers": int(len(outliers)),
        "outlier_share": _number(len(outliers) / len(values)),
        "largest": [_number(v) for v in values.nlargest(3)],
    }


def _mean_by(values: pd.Series, groups: pd.Series) -> list[dict]:
    stats = values.groupby(groups).agg(["mean", "count"]).dropna().sort_values("mean", ascending=False)

    if len(stats) > MAX_AVERAGE_VALUES:
        half = MAX_AVERAGE_VALUES // 2
        stats = pd.concat([stats.head(half), stats.tail(half)])

    return [
        {"value": str(value), "mean": _number(row["mean"]), "count": int(row["count"])}
        for value, row in stats.iterrows()
    ]


def _averages(
    frame: pd.DataFrame,
    columns: list,
    date_column: str | None,
    dimensions: list[str],
) -> list[dict]:
    """Moyenne globale, par mois et par dimension de chaque mesure."""

    averages = []
    months = _dates(frame, date_column).dt.to_period("M").astype("string") if date_column else None

    for column in columns[:MAX_AVERAGED_MEASURES]:
        name = silver_column_name(column.column)
        values = pd.to_numeric(frame[name], errors="coerce")

        if values.dropna().nunique() < 2:
            continue

        average = {
            "column": name,
            "business_role": column.business_role,
            "mean": _number(values.mean()),
            "min": _number(values.min()),
            "max": _number(values.max()),
            "by_month": [
                {"month": item["value"], "mean": item["mean"], "count": item["count"]}
                for item in sorted(_mean_by(values, months), key=lambda i: i["value"])
            ] if months is not None else [],
            "by_dimension": [
                {"column": dimension, "values": _mean_by(values, frame[dimension].astype("string"))}
                for dimension in dimensions[:MAX_AVERAGE_DIMENSIONS]
            ],
        }
        averages.append(average)

    return averages


def _extremes_insight(name: str, groups: list[dict], mean: float, prefix: str, axis: str) -> str | None:
    """
    Moyennes la plus haute et la plus basse d'un axe, sur les groupes d'au
    moins MIN_GROUP_ROWS lignes ; « proches » si l'écart est faible.
    """

    groups = [g for g in groups if g["count"] >= MIN_GROUP_ROWS]

    if len(groups) < 2:
        return None

    high = max(groups, key=lambda g: g["mean"])
    low = min(groups, key=lambda g: g["mean"])
    spread = high["mean"] - low["mean"]

    if mean and abs(spread / mean) < CLOSE_SPREAD:
        return (
            f"Moyennes de {name} proches d'un {axis} à l'autre "
            f"(de {fr_number(low['mean'])} à {fr_number(high['mean'])})."
        )

    return (
        f"Moyenne de {name} la plus élevée {prefix} {high['value']} ({fr_number(high['mean'])}), "
        f"la plus basse {prefix} {low['value']} ({fr_number(low['mean'])})."
    )


def _insights(analysis: dict) -> list[str]:
    insights = []
    overview = analysis["overview"]

    if overview["excluded_rows"]:
        insights.append(
            f"{overview['excluded_rows']} ligne(s) exclue(s) des indicateurs "
            f"({overview['exclusion']})."
        )

    trend = analysis.get("trend")

    if trend:
        label = analysis["measure"]
        digits = 0 if analysis["measure_format"] == "integer" else 2

        if label == COUNT_LABEL:
            insights.append(
                f"Mois le plus chargé : {trend['best']['month']} "
                f"({fr_number(trend['best']['value'], 0)} ligne(s))."
            )
            insights.append(
                f"Mois le moins chargé : {trend['worst']['month']} "
                f"({fr_number(trend['worst']['value'], 0)} ligne(s))."
            )
        else:
            insights.append(f"Meilleur mois : {trend['best']['month']} ({label} {fr_number(trend['best']['value'], digits)}).")
            insights.append(f"Mois le plus faible : {trend['worst']['month']} ({label} {fr_number(trend['worst']['value'], digits)}).")

        year_change = trend.get("year_change")

        if year_change:
            direction = "hausse" if year_change["rate"] >= 0 else "baisse"
            insights.append(
                f"{year_change['year']} : {direction} de {fr_percent(abs(year_change['rate']))} "
                f"par rapport à {year_change['previous']} (années complètes)."
            )

        change = trend.get("last_change")

        if change and change["rate"] is not None:
            direction = "hausse" if change["rate"] >= 0 else "baisse"
            insights.append(
                f"{change['month']} : {direction} de {fr_percent(abs(change['rate']))} par rapport à {change['previous']}."
            )

        if trend["incomplete_months"]:
            insights.append(
                f"Mois incomplets (écartés des comparaisons) : {', '.join(trend['incomplete_months'])}."
            )

    for breakdown in analysis["breakdowns"]:
        if breakdown["distinct"] > TOP and breakdown["top_share"] is not None:
            insights.append(
                f"{breakdown['column']} : le top {TOP} représente {fr_percent(breakdown['top_share'])} du total ; "
                f"{fr_number(breakdown['values_for_80_percent'], 0)} valeur(s) sur "
                f"{fr_number(breakdown['distinct'], 0)} font 80\u00a0%."
            )

    for average in analysis["averages"]:
        name = average["column"]
        insights.append(
            f"{name} : moyenne {fr_number(average['mean'])} "
            f"(de {fr_number(average['min'])} à {fr_number(average['max'])})."
        )

        for dimension in average["by_dimension"]:
            insight = _extremes_insight(
                name, dimension["values"], average["mean"], f"pour {dimension['column']} =", dimension["column"],
            )

            if insight:
                insights.append(insight)

        months = [
            {**m, "value": m["month"]}
            for m in average["by_month"]
            if not trend or m["month"] not in trend["incomplete_months"]
        ]
        insight = _extremes_insight(name, months, average["mean"], "en", "mois")

        if insight:
            insights.append(insight)

    for distribution in analysis["distributions"]:
        share = distribution.get("outlier_share")

        if "constant" in distribution:
            insights.append(f"{distribution['column']} vaut toujours {distribution['constant']}.")
        elif share and share >= SPREAD_SHARE:
            insights.append(
                f"{distribution['column']} : distribution très étalée (médiane {fr_number(distribution['median'])}, "
                f"maximum {fr_number(distribution['max'])}) : {fr_percent(share)} des valeurs sont loin de la médiane, "
                "signe de plusieurs gammes plutôt que d'anomalies."
            )
        elif share and share >= 0.01:
            insights.append(
                f"{distribution['column']} : {distribution['outliers']} valeur(s) atypique(s) "
                f"({fr_percent(share)}), jusqu'à {fr_number(distribution['max'])}."
            )

    return insights


def analyze_business_data(
    frame: pd.DataFrame,
    kpis: KpiRecommendation,
    semantics: SemanticProfile,
    dataset: str,
    quality: dict | None = None,
) -> dict:
    """Analyse complète d'un DataFrame Silver ; résultat sérialisable en JSON."""

    exclusion = next((kpi.exclusion for kpi in kpis.kpis if kpi.exclusion), None)
    analysed = apply_exclusion(frame, exclusion) if exclusion and exclusion["column"] in frame else frame
    label, measure, measure_format = _main_measure(kpis, analysed)

    analysis = {
        "dataset": dataset,
        "domain": semantics.domain.name if semantics.domain else None,
        "measure": label,
        "measure_format": measure_format,
        "overview": {
            "rows": int(len(frame)),
            "analysed_rows": int(len(analysed)),
            "excluded_rows": int(len(frame) - len(analysed)),
            "exclusion": (
                f"{exclusion['column']} : {', '.join(exclusion['exclude'])}" if exclusion else None
            ),
            "columns": int(len(frame.columns)),
        },
        "kpis": _kpi_values(kpis, frame),
        "trend": None,
        "breakdowns": [],
        "distributions": [],
        "averages": [],
        "quality": quality or {},
    }

    temporal = _columns(semantics, analysed, TEMPORAL)
    date_column = silver_column_name(temporal[0].column) if temporal else None

    if date_column:
        analysis["trend"] = _trend(analysed, measure, date_column, _dates(frame, date_column))

    dimensions = [
        column
        for column in _columns(semantics, analysed, DIMENSION)
        if column.business_role not in (DATE_PART, CONTACT)
    ]
    dimensions.sort(
        key=lambda c: DIMENSION_PRIORITY.get(c.entity, DIMENSION_PRIORITY.get(c.business_role, 9))
    )
    analysis["breakdowns"] = [
        _breakdown(analysed, measure, column, silver_column_name(column.column))
        for column in dimensions[:MAX_DIMENSIONS]
    ]

    measures = [
        column
        for column in _columns(semantics, analysed, MEASURE)
        if column.semantic_role != IDENTIFIER
    ]
    analysis["distributions"] = [
        d
        for d in (_distribution(analysed[silver_column_name(c.column)], silver_column_name(c.column)) for c in measures)
        if d
    ]
    analysis["averages"] = _averages(
        analysed,
        [c for c in measures if c.business_role in (LEVEL, None)],
        date_column,
        [b["column"] for b in analysis["breakdowns"]],
    )
    analysis["insights"] = _insights(analysis)

    return analysis


def render_analysis_text(analysis: dict) -> str:
    """Version texte de l'analyse (fichier results/<dataset>_analysis.txt)."""

    overview = analysis["overview"]
    lines = [
        f"ANALYSE DES DONNÉES - {analysis['dataset']}",
        f"Lignes analysées : {overview['analysed_rows']} sur {overview['rows']}"
        + (f" (exclues : {overview['exclusion']})" if overview["excluded_rows"] else ""),
        "",
        "Indicateurs :",
        *[f"  - {kpi['name']} : {kpi['value']}" for kpi in analysis["kpis"]],
    ]

    trend = analysis.get("trend")

    if trend:
        lines += ["", f"Période : {trend['start']} -> {trend['end']} ({len(trend['months'])} mois)"]
        lines += [f"  {m['month']} : {m['value']}" for m in trend["months"]]

    for breakdown in analysis["breakdowns"]:
        lines += ["", f"Top {TOP} par {breakdown['column']} ({breakdown['distinct']} valeurs) :"]
        lines += [f"  - {t['value']} : {t['total']} ({t['share']:.1%})" for t in breakdown["top"]]

    for average in analysis.get("averages", []):
        lines += ["", f"Moyenne de {average['column']} : {average['mean']} (de {average['min']} à {average['max']})"]

        for dimension in average["by_dimension"]:
            lines += [f"  par {dimension['column']} :"]
            lines += [f"    - {g['value']} : {g['mean']} ({g['count']} lignes)" for g in dimension["values"]]

    for distribution in analysis["distributions"]:
        if "constant" in distribution:
            continue

        lines += [
            "",
            f"{distribution['column']} : min {distribution['min']}, médiane {distribution['median']}, "
            f"max {distribution['max']}, moyenne {distribution['mean']}, "
            f"{distribution['outliers']} valeur(s) atypique(s)",
        ]

    lines += ["", "Constats :", *[f"  - {insight}" for insight in analysis["insights"]]]

    commentary = analysis.get("commentary") or {}

    if commentary.get("text"):
        lines += ["", "Commentaire (texte généré par le LLM à partir des chiffres ci-dessus) :", commentary["text"]]

    return "\n".join(lines)
