import json
from pathlib import Path

import pytest

from src.powerbi.measures import OBSERVABILITY_BY_NAME
from src.powerbi.report_spec import (
    VISUAL_TYPES,
    build_report_spec,
    observability_pages,
)
from src.recommendation.dashboard_planner import CHART_TYPES
from src.recommendation.dashboard_review import DashboardReviewError
from src.workflow.agent_workflow import approve_plan_dashboard, plan_file


def measure_refs(spec):
    return {
        value[1:-1]
        for page in spec["pages"]
        for visual in page["visuals"]
        for value in visual["fields"].get("values", [])
    }


def test_every_chart_type_has_a_power_bi_visual():
    assert set(VISUAL_TYPES) == CHART_TYPES


def test_observability_pages_follow_the_target_layout():
    pages = {page["name"]: page for page in observability_pages()}
    page1 = pages["agent_observability"]

    assert [v["title"] for v in page1["visuals"] if v["visual_type"] == "card"] == [
        "Total Runs", "Successful Runs", "Assess Only Runs", "Ingest Runs",
        "Quarantine Runs", "Reject Runs", "Success Rate", "Average Duration (s)",
    ]
    assert {v["title"] for v in page1["visuals"]} >= {
        "Decisions", "Execution Mode", "Runs over time",
    }
    assert [s["field"] for s in page1["slicers"]] == [
        "pipeline_runs[source_file]", "pipeline_runs[decision]",
        "pipeline_runs[execution_mode]", "pipeline_runs[final_status]",
        "pipeline_runs[started_at]",
    ]
    assert {v["title"] for v in pages["pipeline_steps"]["visuals"]} >= {
        "Executions by step", "Step status", "Step x status", "Average duration by step",
    }


def test_observability_visuals_only_use_defined_measures():
    assert measure_refs({"pages": observability_pages()}) <= set(OBSERVABILITY_BY_NAME)


def test_dataset_page_requires_an_approved_dashboard(tmp_path):
    plan = plan_file("data/sales.csv", contracts_dir=tmp_path)

    with pytest.raises(DashboardReviewError):
        build_report_spec(plan.dashboard, plan.kpis, "sales_clean")


def test_dataset_page_from_approved_dashboard(tmp_path):
    plan = plan_file("data/sales.csv", contracts_dir=tmp_path)
    approve_plan_dashboard(plan, "cheikhou")

    spec = build_report_spec(plan.dashboard, plan.kpis, "sales_clean")
    page = spec["pages"][2]
    visuals = {v["title"]: v for v in page["visuals"]}
    measures = {m["name"]: m for m in spec["dataset_measures"]}

    assert spec["report"] == "Suivi des ventes - Sales"
    assert [p["name"] for p in spec["pages"]] == [
        "agent_observability", "pipeline_steps", "dataset",
    ]
    assert visuals["Revenue"]["fields"]["values"] == ["[Revenue]"]
    assert visuals["Revenue by Product"]["visual_type"] == "clusteredBarChart"
    assert visuals["Revenue by Product"]["fields"] == {
        "axis": "'sales_clean'[product]", "values": ["[Revenue]"],
    }
    assert visuals["price vs quantity"]["visual_type"] == "scatterChart"
    assert page["slicers"] == [{"field": "'sales_clean'[product]", "slicer": "dropdown"}]
    assert measures["Revenue"]["expression"] == (
        "SUMX('sales_clean', 'sales_clean'[quantity] * 'sales_clean'[price])"
    )
    assert {
        value[1:-1] for v in page["visuals"] for value in v["fields"].get("values", [])
    } <= set(measures)
    json.dumps(spec)


def test_versioned_observability_spec_is_up_to_date():
    versioned = json.loads(
        Path("powerbi/observability_report.json").read_text(encoding="utf-8")
    )

    assert versioned == build_report_spec()
