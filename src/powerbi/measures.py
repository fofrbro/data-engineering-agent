"""
Mesures Power BI décrites comme des données.

Chaque MeasureSpec produit son expression DAX et peut aussi être
évaluée avec pandas : les tests vérifient ainsi que les mesures ont
la même sémantique que les KPI Python, sans exécuter de DAX.

Modèle attendu : pipeline_steps[run_id] (plusieurs) -> pipeline_runs[run_id]
(un), filtrage de runs vers steps, pour que les filtres posés sur les
runs (fichier, décision, mode, statut, date) s'appliquent aux étapes.
"""

from dataclasses import dataclass

import pandas as pd


COUNT_ROWS = "count_rows"
COUNT_WHERE = "count_where"
COUNT_NOT_WHERE = "count_not_where"
AVERAGE = "average"
DIVIDE = "divide"

RUNS = "pipeline_runs"
STEPS = "pipeline_steps"


@dataclass(frozen=True)
class MeasureSpec:
    name: str
    kind: str
    table: str
    display_folder: str
    format_string: str = "0"
    column: str | None = None
    value: str | None = None
    numerator: str | None = None
    denominator: str | None = None


def _ref(name: str) -> str:
    return f"[{name}]"


def _column(table: str, column: str) -> str:
    return f"{table}[{column}]"


def to_dax(spec: MeasureSpec, measures: dict[str, MeasureSpec]) -> str:
    """Expression DAX de la mesure."""

    if spec.kind == COUNT_ROWS:
        return f"COUNTROWS({spec.table})"

    if spec.kind == COUNT_WHERE:
        # COALESCE : une carte affiche 0 plutôt que « -- » quand aucun
        # run ne correspond (par exemple aucun échec).
        return (
            f"COALESCE(CALCULATE(COUNTROWS({spec.table}), "
            f'{_column(spec.table, spec.column)} = "{spec.value}"), 0)'
        )

    if spec.kind == COUNT_NOT_WHERE:
        return (
            f"CALCULATE(COUNTROWS({spec.table}), "
            f'{_column(spec.table, spec.column)} <> "{spec.value}")'
        )

    if spec.kind == AVERAGE:
        return f"AVERAGE({_column(spec.table, spec.column)})"

    if spec.kind == DIVIDE:
        for name in (spec.numerator, spec.denominator):
            if name not in measures:
                raise ValueError(f"Mesure inconnue dans {spec.name} : {name}")

        return f"DIVIDE({_ref(spec.numerator)}, {_ref(spec.denominator)}, 0)"

    raise ValueError(f"Type de mesure inconnu : {spec.kind}")


def evaluate(
    spec: MeasureSpec,
    tables: dict[str, pd.DataFrame],
    measures: dict[str, MeasureSpec],
):
    """
    Valeur de la mesure sans filtre, calculée avec pandas selon la
    sémantique DAX (DIVIDE par zéro -> 0, AVERAGE ignore les vides,
    AVERAGE d'une colonne vide -> vide).
    """

    table = tables.get(spec.table)

    if spec.kind == COUNT_ROWS:
        return len(table)

    if spec.kind == COUNT_WHERE:
        return int((table[spec.column] == spec.value).sum())

    if spec.kind == COUNT_NOT_WHERE:
        # En DAX, BLANK() <> "X" est vrai : les vides sont comptés.
        return int((table[spec.column] != spec.value).sum())

    if spec.kind == AVERAGE:
        known = pd.to_numeric(table[spec.column], errors="coerce").dropna()
        return float(known.mean()) if len(known) else None

    if spec.kind == DIVIDE:
        numerator = evaluate(measures[spec.numerator], tables, measures)
        denominator = evaluate(measures[spec.denominator], tables, measures)
        return numerator / denominator if denominator else 0

    raise ValueError(f"Type de mesure inconnu : {spec.kind}")


RUN_FOLDER = "Agent Observability"
STEP_FOLDER = "Pipeline Steps"
PERCENT = "0.0%"
SECONDS = "0.00"

OBSERVABILITY_MEASURES = [
    MeasureSpec("Total Runs", COUNT_ROWS, RUNS, RUN_FOLDER),
    MeasureSpec("Successful Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="final_status", value="SUCCESS"),
    MeasureSpec("Failed Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="final_status", value="FAILED"),
    MeasureSpec("Assess Only Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="execution_mode", value="ASSESS_ONLY"),
    # Mode d'exécution (ingestion demandée) et décision sont distincts :
    # un fichier rejeté lors d'une exécution INGEST compte dans
    # « Ingest Mode Runs » et dans « Reject Runs », pas dans
    # « Ingest Decision Runs ».
    MeasureSpec("Ingest Mode Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="execution_mode", value="INGEST"),
    MeasureSpec("Ingest Decision Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="decision", value="INGEST"),
    MeasureSpec("Quarantine Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="decision", value="QUARANTINE"),
    MeasureSpec("Reject Runs", COUNT_WHERE, RUNS, RUN_FOLDER, column="decision", value="REJECT"),
    MeasureSpec("Success Rate", DIVIDE, RUNS, RUN_FOLDER, PERCENT, numerator="Successful Runs", denominator="Total Runs"),
    MeasureSpec("Quarantine Rate", DIVIDE, RUNS, RUN_FOLDER, PERCENT, numerator="Quarantine Runs", denominator="Total Runs"),
    MeasureSpec("Reject Rate", DIVIDE, RUNS, RUN_FOLDER, PERCENT, numerator="Reject Runs", denominator="Total Runs"),
    MeasureSpec("Average Duration (s)", AVERAGE, RUNS, RUN_FOLDER, SECONDS, column="duration_seconds"),
    MeasureSpec("Step Executions", COUNT_ROWS, STEPS, STEP_FOLDER),
    MeasureSpec("Failed Steps", COUNT_WHERE, STEPS, STEP_FOLDER, column="status", value="FAILED"),
    MeasureSpec("Succeeded Steps", COUNT_NOT_WHERE, STEPS, STEP_FOLDER, column="status", value="FAILED"),
    MeasureSpec("Step Success Rate", DIVIDE, STEPS, STEP_FOLDER, PERCENT, numerator="Succeeded Steps", denominator="Step Executions"),
    MeasureSpec("Average Step Duration (s)", AVERAGE, STEPS, STEP_FOLDER, SECONDS, column="duration_seconds"),
]

OBSERVABILITY_BY_NAME = {spec.name: spec for spec in OBSERVABILITY_MEASURES}


def render_measures_script(
    measures: list[MeasureSpec] = OBSERVABILITY_MEASURES,
) -> str:
    """
    Script DAX lisible : une définition par mesure, avec son dossier
    d'affichage et son format, à recréer dans le modèle sémantique.
    """

    by_name = {spec.name: spec for spec in measures}
    blocks = [
        "// Mesures générées par src/powerbi/measures.py - ne pas modifier à la main.",
        "// Relation attendue : pipeline_steps[run_id] (*) -> pipeline_runs[run_id] (1).",
        "",
    ]

    for spec in measures:
        blocks += [
            f"// Table : {spec.table} | Dossier : {spec.display_folder} | Format : {spec.format_string}",
            f"{_ref(spec.name)} = {to_dax(spec, by_name)}",
            "",
        ]

    return "\n".join(blocks)
