"""
Planification d'un tableau de bord (TBO) à partir des KPI.

Le plan est une proposition (statut PROPOSED) : il doit être
présenté à l'utilisateur et approuvé avant toute création dans
Power BI. Le choix des visuels est déterministe.

Convention des axes : x_axis porte les catégories ou le temps,
y_axis porte la valeur mesurée, y compris pour les barres
horizontales.
"""

from dataclasses import asdict, dataclass, field

from src.discovery.schema_profiler import SchemaProfile
from src.recommendation.kpi_recommender import (
    BREAKDOWN,
    SCALAR,
    TREND,
    KPI,
    KpiRecommendation,
)
from src.recommendation.pipeline_recommender import (
    MAX_GROUP_BY_DISTINCT,
    silver_column_name,
)
from src.semantic.semantic_profiler import SALES_DOMAIN, SemanticProfile
from src.semantic.vocabulary import (
    CATEGORY,
    DATE_PART,
    DIMENSION,
    FLAG,
    IDENTIFIER,
    MEASURE,
    STATUS,
    TEMPORAL,
)


PROPOSED = "PROPOSED"

CHART_TYPES = {
    "card", "bar", "column", "line", "stacked_bar", "stacked_column",
    "pie", "donut", "scatter", "table", "matrix",
}

MAX_KPI_CARDS = 6
MAX_FILTERS = 5
MAX_DETAIL_COLUMNS = 10
# Un anneau reste lisible jusqu'à 5 parts.
MAX_DONUT_SLICES = 5
PART_TO_WHOLE_ROLES = {STATUS, CATEGORY, FLAG}


@dataclass
class Chart:
    type: str
    title: str
    x_axis: str | None
    y_axis: str | None
    measure: str | None
    source_columns: list[str]
    rationale: str
    legend: str | None = None
    filters: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.type not in CHART_TYPES:
            raise ValueError(f"Type de graphique inconnu : {self.type}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DashboardPlan:
    title: str
    description: str
    audience: str
    kpis: list[dict]
    charts: list[Chart]
    filters: list[dict]
    detail_tables: list[Chart]
    dataset: str
    status: str = PROPOSED
    review_history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "audience": self.audience,
            "dataset": self.dataset,
            "status": self.status,
            "kpis": self.kpis,
            "charts": [chart.to_dict() for chart in self.charts],
            "filters": self.filters,
            "detail_tables": [table.to_dict() for table in self.detail_tables],
            "review_history": self.review_history,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "DashboardPlan":
        return cls(
            title=payload["title"],
            description=payload["description"],
            audience=payload["audience"],
            kpis=list(payload["kpis"]),
            charts=[Chart(**chart) for chart in payload["charts"]],
            filters=list(payload["filters"]),
            detail_tables=[Chart(**table) for table in payload["detail_tables"]],
            dataset=payload["dataset"],
            status=payload.get("status", PROPOSED),
            review_history=list(payload.get("review_history", [])),
        )


class _Columns:
    """Rôles et cardinalités par nom de colonne Silver."""

    def __init__(self, schema: SchemaProfile, semantics: SemanticProfile):
        self.distinct = {
            silver_column_name(column.name): column.distinct_count
            for column in schema.columns
        }
        self.roles = {
            silver_column_name(column.column): column
            for column in semantics.columns
        }

    def with_role(self, semantic_role: str) -> list[str]:
        return [
            name
            for name, role in self.roles.items()
            if role.semantic_role == semantic_role
        ]

    def analysis_dimensions(self) -> list[str]:
        return [
            name
            for name in self.with_role(DIMENSION)
            if self.roles[name].business_role != DATE_PART
            and self.distinct.get(name, 0) <= MAX_GROUP_BY_DISTINCT
        ]

    def is_part_to_whole(self, name: str) -> bool:
        role = self.roles.get(name)

        return (
            role is not None
            and role.business_role in PART_TO_WHOLE_ROLES
            and self.distinct.get(name, 0) <= MAX_DONUT_SLICES
        )


def _measure_label(kpi: KPI) -> str:
    """ "Revenue by Month" -> "Revenue". """

    return kpi.name.split(" by ")[0]


def _card(kpi: KPI) -> dict:
    return {
        "type": "card",
        "name": kpi.name,
        "measure": kpi.formula,
        "format": kpi.format,
        "source_columns": kpi.source_columns,
        "confidence": kpi.confidence,
    }


def _trend_charts(kpi: KPI, cols: _Columns) -> list[Chart]:
    charts = [
        Chart(
            type="line",
            title=kpi.name,
            x_axis=f"MONTH({kpi.dimension})",
            y_axis=_measure_label(kpi),
            measure=kpi.formula,
            source_columns=kpi.source_columns,
            rationale="Une courbe montre l'évolution dans le temps.",
        )
    ]

    split = next(
        (
            name
            for name in cols.analysis_dimensions()
            if cols.is_part_to_whole(name)
        ),
        None,
    )

    if split:
        charts.append(
            Chart(
                type="stacked_column",
                title=f"{kpi.name} and {split}",
                x_axis=f"MONTH({kpi.dimension})",
                y_axis=_measure_label(kpi),
                measure=kpi.formula,
                legend=split,
                source_columns=[*kpi.source_columns, split],
                rationale=(
                    f"Décompose l'évolution mensuelle par {split}, "
                    "dimension à peu de valeurs."
                ),
            )
        )

    return charts


def _breakdown_chart(kpi: KPI, cols: _Columns) -> Chart:
    if cols.is_part_to_whole(kpi.dimension):
        return Chart(
            type="donut",
            title=kpi.name,
            x_axis=kpi.dimension,
            y_axis=_measure_label(kpi),
            measure=kpi.formula,
            legend=kpi.dimension,
            source_columns=kpi.source_columns,
            rationale=(
                f"Part de chaque {kpi.dimension} dans le total : "
                f"{cols.distinct.get(kpi.dimension)} valeurs au plus."
            ),
        )

    return Chart(
        type="bar",
        title=kpi.name,
        x_axis=kpi.dimension,
        y_axis=_measure_label(kpi),
        measure=kpi.formula,
        source_columns=kpi.source_columns,
        rationale=(
            f"Barres horizontales triées : compare les valeurs "
            f"de {kpi.dimension}, libellés lisibles."
        ),
    )


def _extra_charts(cols: _Columns, main: KPI | None) -> list[Chart]:
    charts = []
    measures = [
        name
        for name in cols.with_role(MEASURE)
        if cols.roles[name].business_role is not None
    ]

    if len(measures) >= 2:
        x, y = measures[:2]
        charts.append(
            Chart(
                type="scatter",
                title=f"{y} vs {x}",
                x_axis=x,
                y_axis=y,
                measure=None,
                source_columns=[x, y],
                rationale=f"Met en évidence la relation entre {x} et {y}.",
            )
        )

    dimensions = cols.analysis_dimensions()

    if main and len(dimensions) >= 2:
        rows, columns = dimensions[:2]
        charts.append(
            Chart(
                type="matrix",
                title=f"{main.name} by {rows} and {columns}",
                x_axis=columns,
                y_axis=rows,
                measure=main.formula,
                source_columns=[*main.source_columns, rows, columns],
                rationale=f"Croise {rows} et {columns} sur la mesure principale.",
            )
        )

    return charts


def _filters(cols: _Columns) -> list[dict]:
    filters = [
        {
            "column": name,
            "type": "date_range",
            "rationale": "Restreindre la période analysée.",
        }
        for name in cols.with_role(TEMPORAL)[:1]
    ]

    filters.extend(
        {
            "column": name,
            "type": "list",
            "rationale": f"{cols.distinct.get(name)} valeurs sélectionnables.",
        }
        for name in cols.analysis_dimensions()
    )

    return filters[:MAX_FILTERS]


def _detail_table(cols: _Columns) -> Chart:
    columns = [
        *cols.with_role(IDENTIFIER),
        *cols.with_role(TEMPORAL),
        *cols.with_role(DIMENSION),
        *cols.with_role(MEASURE),
    ][:MAX_DETAIL_COLUMNS]

    return Chart(
        type="table",
        title="Détail des lignes",
        x_axis=None,
        y_axis=None,
        measure=None,
        source_columns=columns,
        rationale="Permet de vérifier les valeurs derrière les indicateurs.",
    )


def _header(dataset: str, domain: str) -> tuple[str, str, str]:
    label = dataset.replace("_", " ").title()

    if domain == SALES_DOMAIN:
        return (
            f"Suivi des ventes - {label}",
            "Chiffre d'affaires, volumes et répartition des ventes.",
            "Direction commerciale et équipes ventes",
        )

    return (
        f"Tableau de bord - {label}",
        "Indicateurs clés et répartition des données.",
        "Analystes métier",
    )


def plan_dashboard(
    kpis: KpiRecommendation,
    schema: SchemaProfile,
    semantics: SemanticProfile,
) -> DashboardPlan:
    """
    Propose un tableau de bord adapté aux KPI du dataset.
    """

    cols = _Columns(schema, semantics)
    scalars = [kpi for kpi in kpis.kpis if kpi.kpi_type == SCALAR]
    main = scalars[0] if scalars and scalars[0].aggregation == "SUM" else None

    charts = []

    for kpi in kpis.kpis:
        if kpi.kpi_type == TREND:
            charts.extend(_trend_charts(kpi, cols))
        elif kpi.kpi_type == BREAKDOWN:
            charts.append(_breakdown_chart(kpi, cols))

    charts.extend(_extra_charts(cols, main))

    title, description, audience = _header(kpis.dataset, kpis.domain)

    return DashboardPlan(
        title=title,
        description=description,
        audience=audience,
        kpis=[_card(kpi) for kpi in scalars[:MAX_KPI_CARDS]],
        charts=charts,
        filters=_filters(cols),
        detail_tables=[_detail_table(cols)],
        dataset=kpis.dataset,
    )


def plan_dashboard_for_file(path: str, dataset: str | None = None) -> DashboardPlan:
    """Découvre un fichier, propose ses KPI puis son tableau de bord."""

    from src.contract.contract_generator import dataset_name_from_path
    from src.discovery.dataset_discovery import discover_dataset
    from src.recommendation.kpi_recommender import recommend_kpis
    from src.semantic.semantic_profiler import profile_semantics

    schema = discover_dataset(path).schema
    semantics = profile_semantics(schema)
    kpis = recommend_kpis(
        schema,
        semantics,
        dataset or dataset_name_from_path(path),
    )

    return plan_dashboard(kpis, schema, semantics)
