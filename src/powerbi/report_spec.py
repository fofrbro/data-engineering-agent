"""
Spécification du rapport Power BI.

Page 1 - AGENT OBSERVABILITY : cartes KPI, décisions, modes, runs dans le temps.
Page 2 - PIPELINE STEPS      : exécutions, statuts et durées par étape.
Page 3 - DATASET             : générée depuis un DashboardPlan APPROVED.

La spécification décrit les visuels (type Power BI, champs, mesures)
et les segments ; elle sert de référence pour construire le rapport.
Elle n'est pas importable telle quelle dans Power BI.
"""

import json
from pathlib import Path

from src.powerbi.kpi_dax import kpi_measures, parse_formula, to_dax
from src.powerbi.measures import RUNS, STEPS
from src.recommendation.dashboard_planner import DashboardPlan
from src.recommendation.dashboard_review import ensure_dashboard_approved
from src.recommendation.kpi_recommender import KpiRecommendation


# Types de graphiques du DashboardPlan -> visuels Power BI.
VISUAL_TYPES = {
    "card": "card",
    "bar": "clusteredBarChart",
    "column": "clusteredColumnChart",
    "line": "lineChart",
    "stacked_bar": "stackedBarChart",
    "stacked_column": "stackedColumnChart",
    "pie": "pieChart",
    "donut": "donutChart",
    "scatter": "scatterChart",
    "table": "tableEx",
    "matrix": "pivotTable",
}

RUN_FILTERS = [
    {"field": f"{RUNS}[source_file]", "slicer": "dropdown"},
    {"field": f"{RUNS}[decision]", "slicer": "dropdown"},
    {"field": f"{RUNS}[execution_mode]", "slicer": "dropdown"},
    {"field": f"{RUNS}[final_status]", "slicer": "dropdown"},
    {"field": f"{RUNS}[started_at]", "slicer": "between"},
]


def _card(measure: str) -> dict:
    return {"visual_type": "card", "title": measure, "fields": {"values": [f"[{measure}]"]}}


def observability_pages() -> list[dict]:
    return [
        {
            "name": "agent_observability",
            "title": "AGENT OBSERVABILITY",
            "visuals": [
                *[
                    _card(name)
                    for name in (
                        "Total Runs", "Successful Runs", "Assess Only Runs",
                        "Ingest Runs", "Quarantine Runs", "Reject Runs",
                        "Success Rate", "Average Duration (s)",
                    )
                ],
                {
                    "visual_type": "donutChart",
                    "title": "Decisions",
                    "fields": {"legend": f"{RUNS}[decision]", "values": ["[Total Runs]"]},
                },
                {
                    "visual_type": "clusteredColumnChart",
                    "title": "Execution Mode",
                    "fields": {"axis": f"{RUNS}[execution_mode]", "values": ["[Total Runs]"]},
                },
                {
                    "visual_type": "lineChart",
                    "title": "Runs over time",
                    "fields": {
                        "axis": f"{RUNS}[started_at]",
                        "date_granularity": "day",
                        "values": ["[Total Runs]"],
                    },
                },
            ],
            "slicers": RUN_FILTERS,
        },
        {
            "name": "pipeline_steps",
            "title": "PIPELINE STEPS",
            "visuals": [
                {
                    "visual_type": "clusteredBarChart",
                    "title": "Executions by step",
                    "fields": {"axis": f"{STEPS}[step_name]", "values": ["[Step Executions]"]},
                },
                {
                    "visual_type": "stackedBarChart",
                    "title": "Step status",
                    "fields": {
                        "axis": f"{STEPS}[step_name]",
                        "legend": f"{STEPS}[status]",
                        "values": ["[Step Executions]"],
                    },
                },
                {
                    "visual_type": "pivotTable",
                    "title": "Step x status",
                    "fields": {
                        "rows": f"{STEPS}[step_name]",
                        "columns": f"{STEPS}[status]",
                        "values": ["[Step Executions]"],
                    },
                },
                {
                    "visual_type": "clusteredBarChart",
                    "title": "Average duration by step",
                    "fields": {
                        "axis": f"{STEPS}[step_name]",
                        "values": ["[Average Step Duration (s)]"],
                    },
                },
                _card("Step Success Rate"),
            ],
            # Les filtres des runs s'appliquent aux étapes via run_id.
            "slicers": RUN_FILTERS,
        },
    ]


def _axis(table: str, axis: str | None) -> dict:
    if not axis:
        return {}

    if axis.startswith("MONTH(") and axis.endswith(")"):
        return {"axis": f"'{table}'[{axis[6:-1]}]", "date_granularity": "month"}

    return {"axis": f"'{table}'[{axis}]"}


def dataset_page(
    plan: DashboardPlan,
    kpis: KpiRecommendation,
    table: str,
) -> tuple[dict, list[dict]]:
    """
    Page DATASET et ses mesures DAX, depuis un plan APPROVED.
    """

    ensure_dashboard_approved(plan)

    measures, _ = kpi_measures(kpis, table)
    by_expression = {measure.expression: measure.name for measure in measures}

    def measure_ref(formula: str) -> str:
        return f"[{by_expression[to_dax(parse_formula(formula), table)]}]"

    visuals = [
        {
            "visual_type": "card",
            "title": card["name"],
            "fields": {"values": [measure_ref(card["measure"])]},
        }
        for card in plan.kpis
    ]

    for chart in plan.charts:
        fields = _axis(table, chart.x_axis)

        if chart.type == "scatter":
            fields = {
                "x": f"'{table}'[{chart.x_axis}]",
                "y": f"'{table}'[{chart.y_axis}]",
            }
        elif chart.type == "matrix":
            fields = {
                "rows": f"'{table}'[{chart.y_axis}]",
                "columns": f"'{table}'[{chart.x_axis}]",
                "values": [measure_ref(chart.measure)],
            }
        else:
            fields["values"] = [measure_ref(chart.measure)]

        if chart.legend:
            fields["legend"] = f"'{table}'[{chart.legend}]"

        visuals.append(
            {
                "visual_type": VISUAL_TYPES[chart.type],
                "title": chart.title,
                "fields": fields,
                "rationale": chart.rationale,
            }
        )

    for detail in plan.detail_tables:
        visuals.append(
            {
                "visual_type": VISUAL_TYPES[detail.type],
                "title": detail.title,
                "fields": {"columns": [f"'{table}'[{c}]" for c in detail.source_columns]},
            }
        )

    page = {
        "name": "dataset",
        "title": plan.title,
        "visuals": visuals,
        "slicers": [
            {
                "field": f"'{table}'[{item['column']}]",
                "slicer": "between" if item["type"] == "date_range" else "dropdown",
            }
            for item in plan.filters
        ],
    }

    dax = [
        {"name": m.name, "table": table, "expression": m.expression, "format": m.format}
        for m in measures
    ]

    return page, dax


def build_report_spec(
    plan: DashboardPlan | None = None,
    kpis: KpiRecommendation | None = None,
    table: str | None = None,
) -> dict:
    """Rapport complet ; la page DATASET n'est ajoutée que pour un plan APPROVED."""

    spec = {
        "report": "Data Engineering Agent",
        "pages": observability_pages(),
        "dataset_measures": [],
    }

    if plan is not None:
        page, measures = dataset_page(plan, kpis, table)
        spec["report"] = plan.title
        spec["pages"].append(page)
        spec["dataset_measures"] = measures

    return spec


def save_report_spec(spec: dict, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
