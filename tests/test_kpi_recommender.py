import json

import pandas as pd

from src.discovery.schema_profiler import profile_schema
from src.recommendation.kpi_recommender import (
    recommend_kpis,
    recommend_kpis_for_file,
)
from src.semantic.semantic_profiler import profile_semantics


def kpis_for(frame, dataset="orders"):
    schema = profile_schema(frame)
    return recommend_kpis(schema, profile_semantics(schema), dataset)


def orders_frame():
    return pd.DataFrame(
        {
            "Order ID": range(1, 13),
            "customer_id": [1, 2, 3] * 4,
            "product": ["Laptop", "Mouse"] * 6,
            "country": ["FR", "SN", "CI"] * 4,
            "order_date": [f"2026-0{m}-15" for m in (1, 2, 3)] * 4,
            "quantity": [1, 2, 3] * 4,
            "unit_price": [10.5, 20.0, 30.0] * 4,
            "discount_rate": [0.1, 0.2, 0.0] * 4,
        }
    )


def names(recommendation):
    return [kpi.name for kpi in recommendation.kpis]


def test_sales_kpis_for_existing_file():
    recommendation = recommend_kpis_for_file("data/sales.csv")

    assert recommendation.status == "PROPOSED"
    assert recommendation.domain == "SALES"
    assert names(recommendation) == [
        "Revenue",
        "Number of Lines",
        "Quantity Sold",
        "Average Revenue per Line",
        "Customers",
        "Products",
        "Average Unit Price",
        "Revenue by Product",
    ]

    revenue = recommendation.kpi("Revenue")
    assert revenue.formula == "SUM(quantity * price)"
    assert revenue.source_columns == ["quantity", "price"]
    assert revenue.aggregation == "SUM"
    assert revenue.format == "currency"


def test_kpis_with_order_identifier_and_dates():
    recommendation = kpis_for(orders_frame())

    orders = recommendation.kpi("Orders")
    aov = recommendation.kpi("Average Order Value")
    by_month = recommendation.kpi("Revenue by Month")
    by_region = recommendation.kpi("Revenue by Region")

    assert orders.formula == "COUNT(DISTINCT order_id)"
    assert aov.formula == "SUM(quantity * unit_price) / COUNT(DISTINCT order_id)"
    assert by_month.kpi_type == "trend"
    assert by_month.dimension == "order_date"
    assert by_region.kpi_type == "breakdown"
    assert by_region.dimension == "country"
    assert recommendation.kpi("Average discount_rate").format == "percent"
    assert "Number of Lines" not in names(recommendation)


def test_breakdowns_follow_priority():
    breakdowns = [
        kpi.dimension
        for kpi in kpis_for(orders_frame()).kpis
        if kpi.kpi_type == "breakdown"
    ]

    assert breakdowns == ["product", "country"]


def test_amount_column_is_preferred_over_derivation():
    frame = orders_frame().assign(total_amount=lambda f: f.quantity * f.unit_price)

    revenue = kpis_for(frame).kpi("Revenue")

    assert revenue.formula == "SUM(total_amount)"


def test_confidence_never_exceeds_source_columns():
    frame = orders_frame()
    schema = profile_schema(frame)
    semantics = profile_semantics(schema)
    column_confidence = {
        column.column: column.confidence for column in semantics.columns
    }

    for kpi in recommend_kpis(schema, semantics).kpis:
        assert 0 < kpi.confidence < 1
        assert kpi.rationale

        for source in kpi.source_columns:
            original = "Order ID" if source == "order_id" else source
            assert kpi.confidence <= column_confidence[original]


def test_generic_dataset_does_not_invent_sales_kpis():
    frame = pd.DataFrame(
        {
            "sensor": ["A", "B"] * 6,
            "temperature": [20.5, 21.0] * 6,
        }
    )

    recommendation = kpis_for(frame, "sensors")

    assert recommendation.domain == "UNKNOWN"
    assert names(recommendation) == [
        "Number of Lines",
        "Total temperature",
        "Number of Lines by Sensor",
    ]
    assert recommendation.kpi("Total temperature").confidence < 0.6


def test_recommendation_is_json_serializable():
    json.dumps(kpis_for(orders_frame()).to_dict())
