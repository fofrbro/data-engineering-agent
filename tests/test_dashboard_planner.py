import json

import pandas as pd
import pytest

from src.discovery.schema_profiler import profile_schema
from src.recommendation.dashboard_planner import (
    Chart,
    plan_dashboard,
    plan_dashboard_for_file,
)
from src.recommendation.kpi_recommender import recommend_kpis
from src.semantic.semantic_profiler import profile_semantics


def plan_for(frame, dataset="orders"):
    schema = profile_schema(frame)
    semantics = profile_semantics(schema)
    return plan_dashboard(recommend_kpis(schema, semantics, dataset), schema, semantics)


def orders_frame():
    return pd.DataFrame(
        {
            "order_id": range(1, 13),
            "product": ["Laptop", "Mouse", "Screen", "Dock"] * 3,
            "status": ["PAID", "SHIPPED", "CANCELLED"] * 4,
            "order_date": [f"2026-0{m}-15" for m in (1, 2, 3)] * 4,
            "quantity": [1, 2, 3] * 4,
            "unit_price": [10.5, 20.0, 30.0] * 4,
        }
    )


def charts_by_title(plan):
    return {chart.title: chart for chart in plan.charts}


def test_plan_for_existing_sales_file():
    plan = plan_dashboard_for_file("data/sales.csv")
    charts = charts_by_title(plan)

    assert plan.status == "PROPOSED"
    assert plan.title == "Suivi des ventes - Sales"
    assert plan.audience == "Direction commerciale et équipes ventes"
    assert [card["name"] for card in plan.kpis] == [
        "Revenue", "Number of Lines", "Quantity Sold",
        "Average Revenue per Line", "Customers", "Products",
    ]
    assert charts["Revenue by Product"].type == "bar"
    assert charts["Revenue by Product"].x_axis == "product"
    assert charts["Revenue by Product"].y_axis == "Revenue"
    assert charts["price vs quantity"].type == "scatter"
    assert plan.filters == [
        {"column": "product", "type": "list", "rationale": "4 valeurs sélectionnables."},
    ]
    assert plan.detail_tables[0].source_columns == [
        "customer_id", "product", "quantity", "price",
    ]


def test_trend_status_and_matrix_charts():
    plan = plan_for(orders_frame())
    charts = charts_by_title(plan)

    assert charts["Revenue by Month"].type == "line"
    assert charts["Revenue by Month"].x_axis == "MONTH(order_date)"
    stacked = charts["Revenue by Month and status"]
    assert stacked.type == "stacked_column"
    assert stacked.legend == "status"
    assert charts["Revenue by Status"].type == "donut"
    assert charts["Revenue by Product"].type == "bar"
    assert charts["Revenue by product and status"].type == "matrix"


def test_filters_start_with_period_and_are_capped():
    plan = plan_for(orders_frame())

    assert [f["column"] for f in plan.filters] == ["order_date", "product", "status"]
    assert plan.filters[0]["type"] == "date_range"


def test_every_chart_is_explained():
    plan = plan_for(orders_frame())

    for chart in [*plan.charts, *plan.detail_tables]:
        assert chart.rationale
        assert chart.source_columns


def test_generic_dataset_plan():
    frame = pd.DataFrame({"sensor": ["A", "B"] * 6, "temperature": [20.5, 21.0] * 6})

    plan = plan_for(frame, "sensors")

    assert plan.title == "Tableau de bord - Sensors"
    assert plan.audience == "Analystes métier"
    # Catégorie à 2 valeurs : part du total en anneau.
    assert [chart.type for chart in plan.charts] == ["donut"]


def test_unknown_chart_type_is_refused():
    with pytest.raises(ValueError):
        Chart("radar", "x", None, None, None, [], "r")


def test_plan_is_json_serializable():
    payload = plan_for(orders_frame()).to_dict()

    json.dumps(payload)

    assert set(payload) >= {
        "title", "description", "audience", "kpis", "charts",
        "filters", "detail_tables",
    }
