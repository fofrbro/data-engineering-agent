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
from src.powerbi.measures import OBSERVABILITY_MEASURES, RUNS, STEPS
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


# ----------------------------------------------------------------------
# Guide de construction lisible (interface Power BI en français)
# ----------------------------------------------------------------------

VISUAL_LABELS_FR = {
    "card": "Carte",
    "clusteredBarChart": "Graphique à barres groupées",
    "clusteredColumnChart": "Histogramme groupé",
    "lineChart": "Graphique en courbes",
    "stackedBarChart": "Graphique à barres empilées",
    "stackedColumnChart": "Histogramme empilé",
    "pieChart": "Graphique en secteurs",
    "donutChart": "Graphique en anneau",
    "scatterChart": "Nuage de points",
    "tableEx": "Table",
    "pivotTable": "Matrice",
}

# Zones de champs du volet « Générer un visuel ». Dans un graphique à
# barres, les catégories sont sur l'axe Y et les valeurs sur l'axe X.
WELLS_FR = {
    "card": {"values": "Champs"},
    "clusteredBarChart": {"axis": "Axe Y", "values": "Axe X", "legend": "Légende"},
    "stackedBarChart": {"axis": "Axe Y", "values": "Axe X", "legend": "Légende"},
    "clusteredColumnChart": {"axis": "Axe X", "values": "Axe Y", "legend": "Légende"},
    "stackedColumnChart": {"axis": "Axe X", "values": "Axe Y", "legend": "Légende"},
    "lineChart": {"axis": "Axe X", "values": "Axe Y", "legend": "Légende"},
    "pieChart": {"legend": "Légende", "values": "Valeurs", "axis": "Légende"},
    "donutChart": {"legend": "Légende", "values": "Valeurs", "axis": "Légende"},
    "scatterChart": {"x": "Axe X", "y": "Axe Y"},
    "tableEx": {"columns": "Colonnes"},
    "pivotTable": {"rows": "Lignes", "columns": "Colonnes", "values": "Valeurs"},
}

GRANULARITY_FR = {"day": "jour", "month": "mois"}

# Formats d'affichage : « Outils de mesure » > Format.
FORMATS_FR = {
    "0": "Nombre entier",
    "0.0%": "Pourcentage, 1 décimale",
    "0.00": "Nombre décimal, 2 décimales",
    "currency": "Devise, 2 décimales",
    "integer": "Nombre entier",
    "number": "Nombre décimal, 2 décimales",
    "percent": "Pourcentage, 1 décimale",
}


def _date_column(field: str) -> tuple[str, str, str]:
    """ "t[started_at]" -> ("t", "started_at", "started_at_date"). """

    table, column = field.rstrip("]").split("[", 1)
    table = table.strip(chr(39))
    return table, column, f"{column}_date"


def _field_label(field: str) -> str:
    """ "[Total Runs]" -> "mesure Total Runs" ; "t[col]" -> "t > col". """

    if field.startswith("[") and field.endswith("]"):
        return f"mesure « {field[1:-1]} »"

    table, column = field.rstrip("]").split("[", 1)
    return f"« {table.strip(chr(39))} > {column} »"


def _visual_lines(visual: dict) -> list[str]:
    wells = WELLS_FR[visual["visual_type"]]
    lines = [f"- **{visual['title']}** : {VISUAL_LABELS_FR[visual['visual_type']]}"]
    placed = set()

    granularity = visual["fields"].get("date_granularity")

    for key, value in visual["fields"].items():
        if key == "date_granularity":
            continue

        if key == "axis" and granularity == "day":
            # Un horodatage donnerait un point par instant : on passe
            # par une colonne de date sans l'heure.
            table, column, date_column = _date_column(value)
            lines.append(
                f"  - Créer d'abord, dans la table {table}, une colonne calculée "
                f"(« Nouvelle colonne ») : `{date_column} = DATE(YEAR({table}[{column}]), "
                f"MONTH({table}[{column}]), DAY({table}[{column}]))`. "
                "Si « Nouvelle colonne » est indisponible (modèle Direct Lake), "
                "voir powerbi/README.md."
            )
            value = f"{table}[{date_column}]"

        well = wells[key]
        values = value if isinstance(value, list) else [value]
        label = ", ".join(_field_label(v) for v in values)

        # Un anneau n'a qu'une zone Légende : l'axe et la légende s'y confondent.
        if (well, label) in placed:
            continue

        placed.add((well, label))
        lines.append(f"  - {well} : {label}")

    if granularity == "day":
        lines.append(
            "  - Dans l'axe, choisir le champ lui-même et non sa hiérarchie de "
            "dates, pour obtenir un point par jour."
        )

    if granularity == "month":
        lines.append(
            "  - Dans l'axe, garder la hiérarchie de dates avec seulement Année "
            "et Mois, pour obtenir un point par mois."
        )

    return lines


def _format_lines(spec: dict, observability: bool = True) -> list[str]:
    measures = (
        [(m.name, m.format_string) for m in OBSERVABILITY_MEASURES]
        if observability
        else []
    )
    measures += [(m["name"], m["format"]) for m in spec.get("dataset_measures", [])]

    lines = [
        "## Formats des mesures",
        "",
        "Dans Fabric : ouvrir le modèle sémantique, « Ouvrir le modèle de données »,",
        "cliquer sur la mesure dans le volet « Données », puis régler « Format » et",
        "le nombre de décimales dans le volet « Propriétés » (section « Mise en",
        "forme »). Dans Power BI Desktop : ruban « Outils de mesure ».",
        "",
    ]
    lines += [f"- {name} : {FORMATS_FR[fmt]}" for name, fmt in measures]
    lines.append("")

    return lines


def render_report_guide(
    spec: dict,
    observability: bool = True,
    first_page: int = 1,
) -> str:
    """
    Guide pas à pas pour construire le rapport dans Power BI.
    observability=False omet les formats des mesures d'observabilité
    (guide d'une page dataset seule).
    """

    lines = [
        f"# Guide de construction du rapport « {spec['report']} »",
        "",
        "Généré par `src/powerbi/report_spec.py` - ne pas modifier à la main.",
        "",
        "Pour chaque visuel : cliquer sur l'icône du visuel dans le volet",
        "« Visualisations », puis faire glisser les champs indiqués depuis le volet",
        "« Données » dans les zones du volet « Générer un visuel ».",
        "",
        *_format_lines(spec, observability),
    ]

    for number, page in enumerate(spec["pages"], start=first_page):
        lines += [f"## Page {number} - {page['title']}", ""]
        lines.append(f"Renommer la page : « {page['title']} ».")
        lines += ["", "### Visuels", ""]

        for visual in page["visuals"]:
            lines += _visual_lines(visual)

        lines += ["", "### Segments (filtres de page)", ""]

        for slicer in page["slicers"]:
            style = "Entre (plage de dates)" if slicer["slicer"] == "between" else "Liste déroulante"
            lines.append(f"- Segment sur {_field_label(slicer['field'])}, style : {style}")

        lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Export de la page DATASET d'un tableau de bord approuvé
# ----------------------------------------------------------------------

def render_dataset_measures_script(measures: list[dict]) -> str:
    """Script DAX des mesures de la page DATASET."""

    lines = [
        "// Mesures générées par src/powerbi/report_spec.py - ne pas modifier à la main.",
        "",
    ]

    for measure in measures:
        lines += [
            f"// Table : {measure['table']} | Format : {FORMATS_FR[measure['format']]}",
            f"[{measure['name']}] = {measure['expression']}",
            "",
        ]

    return "\n".join(lines)


def export_dataset_report(
    plan: DashboardPlan,
    kpis: KpiRecommendation,
    table: str,
    output_dir: str | Path = "powerbi",
) -> dict[str, Path]:
    """
    Écrit, pour un tableau de bord APPROVED : le plan revu (traçabilité),
    le script DAX de ses mesures et le guide de construction de sa page.
    """

    from src.recommendation.dashboard_review import save_dashboard_plan

    page, measures = dataset_page(plan, kpis, table)
    spec = {"report": plan.title, "pages": [page], "dataset_measures": measures}
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)

    guide = folder / f"{plan.dataset}_report_guide.md"
    dax = folder / f"{plan.dataset}_measures.dax"
    # Les pages 1 et 2 sont celles de l'observabilité.
    guide.write_text(
        render_report_guide(spec, observability=False, first_page=3),
        encoding="utf-8",
        newline="\n",
    )
    dax.write_text(render_dataset_measures_script(measures), encoding="utf-8", newline="\n")

    return {
        "plan": save_dashboard_plan(plan, folder / "dashboards" / f"{plan.dataset}.json"),
        "guide": guide,
        "measures": dax,
    }
