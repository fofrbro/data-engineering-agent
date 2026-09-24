from datetime import datetime, timezone

import pytest

from src.recommendation.dashboard_planner import plan_dashboard_for_file
from src.recommendation.dashboard_review import (
    DashboardReviewError,
    approve_dashboard,
    ensure_dashboard_approved,
    load_dashboard_plan,
    modify_dashboard,
    reject_dashboard,
    render_dashboard_preview,
    save_dashboard_plan,
)


REVIEW_TIME = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def plan():
    return plan_dashboard_for_file("data/sales.csv")


def test_preview_follows_expected_layout(plan):
    preview = render_dashboard_preview(plan)
    lines = preview.splitlines()

    assert lines[0] == "DASHBOARD PLAN"
    assert "Statut : PROPOSED" in lines
    assert lines[lines.index("Titre :") + 1] == "Suivi des ventes - Sales"
    assert lines[lines.index("KPI :") + 1] == "1. Revenue = SUM(quantity * price)"
    assert lines[lines.index("Graphiques :") + 1] == (
        "1. Revenue by Product (bar) - axe : product - valeur : Revenue"
    )
    assert lines[lines.index("Filtres :") + 1] == "1. product (list)"
    assert lines[-1] == "Actions possibles : APPROVE / MODIFY / REJECT"


def test_proposed_plan_is_not_approved(plan):
    with pytest.raises(DashboardReviewError):
        ensure_dashboard_approved(plan)


def test_approve(plan):
    approved = approve_dashboard(plan, " cheikhou ", "OK", reviewed_at=REVIEW_TIME)

    ensure_dashboard_approved(approved)
    assert approved.status == "APPROVED"
    assert approved.review_history == [
        {
            "action": "APPROVE",
            "reviewed_by": "cheikhou",
            "reviewed_at": "2026-09-24T12:00:00+00:00",
            "comment": "OK",
        }
    ]
    assert plan.status == "PROPOSED"
    assert plan.review_history == []
    assert "Actions possibles" not in render_dashboard_preview(approved)


def test_reject_requires_reason(plan):
    with pytest.raises(DashboardReviewError):
        reject_dashboard(plan, "cheikhou", " ")

    rejected = reject_dashboard(plan, "cheikhou", "Pas utile")

    assert rejected.status == "REJECTED"
    with pytest.raises(DashboardReviewError):
        ensure_dashboard_approved(rejected)


def test_modify_keeps_plan_proposed_until_approved(plan):
    modified = modify_dashboard(
        plan,
        "cheikhou",
        {
            "title": "Ventes 2026",
            "remove_kpis": ["Products"],
            "remove_charts": ["price vs quantity"],
            "change_chart_types": {"Revenue by Product": "column"},
        },
        comment="Plus simple",
    )

    assert modified.status == "PROPOSED"
    assert modified.title == "Ventes 2026"
    assert "Products" not in [card["name"] for card in modified.kpis]
    assert [(c.title, c.type) for c in modified.charts] == [
        ("Revenue by Product", "column"),
    ]
    assert modified.review_history[0]["action"] == "MODIFY"
    assert modified.review_history[0]["changes"]["title"] == "Ventes 2026"

    approved = approve_dashboard(modified, "cheikhou")

    assert [entry["action"] for entry in approved.review_history] == [
        "MODIFY", "APPROVE",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"add_chart": {}},
        {"remove_kpis": ["Inconnu"]},
        {"remove_charts": ["Inconnu"]},
        {"remove_filters": ["inconnu"]},
        {"change_chart_types": {"Revenue by Product": "radar"}},
        {"title": "  "},
    ],
)
def test_invalid_modifications_are_refused(plan, changes):
    with pytest.raises(ValueError):
        modify_dashboard(plan, "cheikhou", changes)


def test_only_proposed_plans_can_be_reviewed(plan):
    approved = approve_dashboard(plan, "cheikhou")

    with pytest.raises(DashboardReviewError):
        approve_dashboard(approved, "cheikhou")

    with pytest.raises(DashboardReviewError):
        modify_dashboard(approved, "cheikhou", {"title": "x"})

    with pytest.raises(DashboardReviewError):
        approve_dashboard(plan, "")


def test_save_and_load_round_trip(plan, tmp_path):
    modified = modify_dashboard(plan, "cheikhou", {"audience": "Direction"})

    loaded = load_dashboard_plan(save_dashboard_plan(modified, tmp_path / "plan.json"))

    assert loaded == modified
    assert approve_dashboard(loaded, "cheikhou").status == "APPROVED"
