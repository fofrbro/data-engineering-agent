"""
Validation d'un DashboardPlan par l'utilisateur.

    PROPOSED ──APPROVE──▶ APPROVED
       │  ▲
       │  └── MODIFY (le plan modifié reste PROPOSED)
       └────REJECT────▶ REJECTED

Une proposition de l'agent n'est jamais considérée comme validée :
seul APPROVE, avec un relecteur identifié, autorise la création
du tableau de bord.
"""

import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.recommendation.dashboard_planner import (
    PROPOSED,
    Chart,
    DashboardPlan,
)


APPROVED = "APPROVED"
REJECTED = "REJECTED"

APPROVE = "APPROVE"
MODIFY = "MODIFY"
REJECT = "REJECT"

SUPPORTED_CHANGES = {
    "title",
    "audience",
    "remove_kpis",
    "remove_charts",
    "remove_filters",
    "change_chart_types",
}


class DashboardReviewError(ValueError):
    """Revue impossible ou modification invalide."""


# ----------------------------------------------------------------------
# Aperçu
# ----------------------------------------------------------------------


def _numbered(lines: list[str]) -> list[str]:
    if not lines:
        return ["(aucun)"]

    return [f"{index}. {line}" for index, line in enumerate(lines, start=1)]


def _chart_line(chart: Chart) -> str:
    parts = [f"{chart.title} ({chart.type})"]

    if chart.x_axis:
        parts.append(f"axe : {chart.x_axis}")

    if chart.y_axis:
        parts.append(f"valeur : {chart.y_axis}")

    if chart.legend:
        parts.append(f"légende : {chart.legend}")

    return " - ".join(parts)


def render_dashboard_preview(plan: DashboardPlan) -> str:
    """
    Aperçu texte à présenter avant toute création.
    """

    lines = [
        "DASHBOARD PLAN",
        f"Statut : {plan.status}",
        "",
        "Titre :",
        plan.title,
        "",
        "Description :",
        plan.description,
        "",
        "Public :",
        plan.audience,
        "",
        "KPI :",
        *_numbered([
            f"{card['name']} = {card['measure']}"
            for card in plan.kpis
        ]),
        "",
        "Graphiques :",
        *_numbered([_chart_line(chart) for chart in plan.charts]),
        "",
        "Filtres :",
        *_numbered([
            f"{item['column']} ({item['type']})"
            for item in plan.filters
        ]),
        "",
        "Tables de détail :",
        *_numbered([
            f"{table.title} : {', '.join(table.source_columns)}"
            for table in plan.detail_tables
        ]),
    ]

    if plan.status == PROPOSED:
        lines += ["", "Actions possibles : APPROVE / MODIFY / REJECT"]

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Revue
# ----------------------------------------------------------------------


def _check_reviewable(plan: DashboardPlan, reviewer: str) -> str:
    if plan.status != PROPOSED:
        raise DashboardReviewError(
            f"Seul un plan PROPOSED peut être revu (statut : {plan.status})."
        )

    if not reviewer or not reviewer.strip():
        raise DashboardReviewError("La revue exige un relecteur.")

    return reviewer.strip()


def _history(
    plan: DashboardPlan,
    action: str,
    reviewer: str,
    comment: str | None,
    reviewed_at: datetime | None,
    changes: dict | None = None,
) -> list[dict]:
    entry = {
        "action": action,
        "reviewed_by": reviewer,
        "reviewed_at": (reviewed_at or datetime.now(timezone.utc)).isoformat(),
        "comment": comment,
    }

    if changes is not None:
        entry["changes"] = changes

    return [*copy.deepcopy(plan.review_history), entry]


def approve_dashboard(
    plan: DashboardPlan,
    reviewer: str,
    comment: str | None = None,
    reviewed_at: datetime | None = None,
) -> DashboardPlan:
    """Approuve le plan. Le plan d'origine n'est pas modifié."""

    reviewer = _check_reviewable(plan, reviewer)

    return replace(
        copy.deepcopy(plan),
        status=APPROVED,
        review_history=_history(plan, APPROVE, reviewer, comment, reviewed_at),
    )


def reject_dashboard(
    plan: DashboardPlan,
    reviewer: str,
    reason: str,
    reviewed_at: datetime | None = None,
) -> DashboardPlan:
    """Rejette le plan ; un motif est obligatoire."""

    reviewer = _check_reviewable(plan, reviewer)

    if not reason or not reason.strip():
        raise DashboardReviewError("Le rejet exige un motif.")

    return replace(
        copy.deepcopy(plan),
        status=REJECTED,
        review_history=_history(plan, REJECT, reviewer, reason, reviewed_at),
    )


def _names_must_exist(requested: list[str], existing: list[str], label: str) -> None:
    unknown = [name for name in requested if name not in existing]

    if unknown:
        raise DashboardReviewError(f"{label} inconnu(s) : {unknown}")


def modify_dashboard(
    plan: DashboardPlan,
    reviewer: str,
    changes: dict,
    comment: str | None = None,
    reviewed_at: datetime | None = None,
) -> DashboardPlan:
    """
    Applique des modifications structurées. Le plan modifié reste
    PROPOSED : il doit être approuvé à nouveau.

    Modifications prises en charge :
    - title, audience : nouvelle valeur ;
    - remove_kpis : noms de KPI ;
    - remove_charts : titres de graphiques ;
    - remove_filters : colonnes filtrées ;
    - change_chart_types : {titre: nouveau type}.
    """

    reviewer = _check_reviewable(plan, reviewer)

    unsupported = set(changes) - SUPPORTED_CHANGES

    if unsupported or not changes:
        raise DashboardReviewError(
            f"Modification non prise en charge : {sorted(unsupported) or 'aucune'}"
        )

    updated = copy.deepcopy(plan)
    chart_titles = [chart.title for chart in updated.charts]

    if len(set(chart_titles)) != len(chart_titles):
        raise DashboardReviewError("Titres de graphiques ambigus.")

    for key in ("title", "audience"):
        if key in changes:
            value = str(changes[key]).strip()

            if not value:
                raise DashboardReviewError(f"{key} ne peut pas être vide.")

            setattr(updated, key, value)

    remove_kpis = changes.get("remove_kpis", [])
    _names_must_exist(remove_kpis, [card["name"] for card in updated.kpis], "KPI")
    updated.kpis = [card for card in updated.kpis if card["name"] not in remove_kpis]

    remove_charts = changes.get("remove_charts", [])
    _names_must_exist(remove_charts, chart_titles, "Graphique(s)")
    updated.charts = [chart for chart in updated.charts if chart.title not in remove_charts]

    remove_filters = changes.get("remove_filters", [])
    _names_must_exist(remove_filters, [item["column"] for item in updated.filters], "Filtre(s)")
    updated.filters = [item for item in updated.filters if item["column"] not in remove_filters]

    new_types = changes.get("change_chart_types", {})
    _names_must_exist(list(new_types), [chart.title for chart in updated.charts], "Graphique(s)")
    updated.charts = [
        replace(chart, type=new_types[chart.title]) if chart.title in new_types else chart
        for chart in updated.charts
    ]

    updated.review_history = _history(plan, MODIFY, reviewer, comment, reviewed_at, changes)

    return updated


def ensure_dashboard_approved(plan: DashboardPlan) -> None:
    """À appeler avant toute création du tableau de bord."""

    if plan.status != APPROVED:
        raise DashboardReviewError(
            f"Le tableau de bord doit être APPROVED avant sa création "
            f"(statut : {plan.status})."
        )


# ----------------------------------------------------------------------
# Persistance
# ----------------------------------------------------------------------


def save_dashboard_plan(plan: DashboardPlan, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    return destination


def load_dashboard_plan(path: str | Path) -> DashboardPlan:
    return DashboardPlan.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
