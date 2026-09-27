import pandas as pd
import pytest

from src.discovery.readers import read_dataframe
from src.discovery.schema_profiler import profile_schema
from src.powerbi.kpi_dax import evaluate_kpi, parse_formula, to_dax
from src.recommendation.business_rules import cancellation_exclusion, with_exclusion
from src.recommendation.kpi_recommender import recommend_kpis
from src.semantic.semantic_profiler import profile_semantics


SAMPLE = "data/samples/ventes_2025_2026.csv"


def profiles(frame):
    schema = profile_schema(frame)
    return schema, profile_semantics(schema)


def orders(statuses):
    return pd.DataFrame(
        {
            "order_id": range(1, 13),
            "product": ["Laptop", "Mouse"] * 6,
            "status": (statuses * 12)[:12],
            "quantity": [1, 2, 3] * 4,
            "unit_price": [10.0, 20.0, 30.0] * 4,
        }
    )


@pytest.mark.parametrize("value", ["CANCELLED", "canceled", "Annulée", "ANNULE"])
def test_cancellation_values_are_detected(value):
    exclusion = cancellation_exclusion(*profiles(orders(["PAID", value])))

    assert exclusion == {"column": "status", "exclude": [value.strip().upper()]}


def test_no_exclusion_without_cancellation_value():
    assert cancellation_exclusion(*profiles(orders(["PAID", "SHIPPED"]))) is None


def test_no_exclusion_outside_sales_domain():
    frame = pd.DataFrame(
        {"sensor": ["A", "B"] * 6, "status": ["OK", "CANCELLED"] * 6, "temperature": [1.5, 2.5] * 6}
    )

    assert cancellation_exclusion(*profiles(frame)) is None


def test_with_exclusion_keeps_grouping_last():
    exclusion = {"column": "status", "exclude": ["CANCELLED"]}

    assert with_exclusion("SUM(amount) GROUP BY product", exclusion) == (
        "SUM(amount) WHERE status NOT IN ('CANCELLED') GROUP BY product"
    )
    assert with_exclusion("COUNT(*)", exclusion) == "COUNT(*) WHERE status NOT IN ('CANCELLED')"


def test_every_sales_kpi_excludes_cancelled_orders():
    kpis = recommend_kpis(*profiles(read_dataframe(SAMPLE)), "ventes_2025_2026")

    assert all(kpi.exclusion == {"column": "status", "exclude": ["CANCELLED"]} for kpi in kpis.kpis)
    assert kpis.kpi("Revenue").formula == (
        "SUM(quantity * unit_price) WHERE status NOT IN ('CANCELLED')"
    )
    assert kpis.kpi("Revenue by Month").formula == (
        "SUM(quantity * unit_price) WHERE status NOT IN ('CANCELLED') GROUP BY MONTH(order_date)"
    )


def test_dax_filters_cancelled_orders():
    formula = parse_formula(
        "SUM(quantity * unit_price) / COUNT(DISTINCT order_id) WHERE status NOT IN ('CANCELLED')"
    )

    assert to_dax(formula, "fact") == (
        "CALCULATE(DIVIDE(SUMX('fact', 'fact'[quantity] * 'fact'[unit_price]), "
        "DISTINCTCOUNT('fact'[order_id])), NOT 'fact'[status] IN {\"CANCELLED\"})"
    )


def test_kpi_values_exclude_cancelled_orders():
    frame = read_dataframe(SAMPLE)
    kpis = recommend_kpis(*profiles(frame), "ventes_2025_2026")
    kept = frame[frame["status"] != "CANCELLED"]

    assert evaluate_kpi(kpis.kpi("Revenue"), frame) == pytest.approx(
        (kept["quantity"] * kept["unit_price"]).sum()
    )
    assert evaluate_kpi(kpis.kpi("Orders"), frame) == kept["order_id"].nunique()
    assert evaluate_kpi(kpis.kpi("Orders"), frame) < len(frame)
