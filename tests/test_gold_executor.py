import pandas as pd
import pytest

from src.contract.contract_generator import propose_contract_for_file
from src.contract.contract_lifecycle import approve_contract
from src.discovery.readers import read_dataframe
from src.execution.gold_executor import GoldBuildError, build_gold_table, build_gold_tables
from src.execution.silver_executor import apply_silver_transformations
from src.recommendation.pipeline_recommender import (
    GoldTable,
    Metric,
    recommend_pipeline_for_file,
)
from src.tools.gold_transformation import build_sales_gold
from src.tools.silver_transformation import transform_to_silver


def sales_silver_and_gold():
    contract = approve_contract(propose_contract_for_file("data/sales.csv"), "cheikhou")
    recommendation = recommend_pipeline_for_file("data/sales.csv", contract)
    silver = apply_silver_transformations(
        read_dataframe("data/sales.csv"),
        recommendation.transformations,
        destructive_approved=True,
    ).data
    return silver, build_gold_tables(silver, recommendation.gold)


def test_sales_gold_matches_existing_sales_pipeline(tmp_path):
    _, gold = sales_silver_and_gold()

    # Référence : parcours ventes existant (Bronze -> Silver -> Gold).
    bronze = tmp_path / "bronze.parquet"
    silver_path = tmp_path / "silver.parquet"
    gold_path = tmp_path / "gold.parquet"
    read_dataframe("data/sales.csv").to_parquet(bronze)
    transform_to_silver(str(bronze), str(silver_path))
    build_sales_gold(str(silver_path), str(gold_path))
    expected = pd.read_parquet(gold_path).sort_values("product").reset_index(drop=True)

    actual = gold["sales_by_product"].sort_values("product").reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual[expected.columns], expected, check_dtype=False,
    )


def test_all_recommended_sales_tables_are_built():
    silver, gold = sales_silver_and_gold()

    assert list(gold) == [
        "fact_sales", "sales_dim_customer", "sales_dim_product", "sales_by_product", "sales_summary",
    ]
    assert len(gold["fact_sales"]) == len(silver)
    assert gold["sales_dim_product"]["product"].tolist() == ["Keyboard", "Laptop", "Monitor", "Mouse"]
    assert gold["sales_summary"]["total_sales"].iloc[0] == silver["line_amount"].sum()


def test_monthly_aggregate_and_date_dimension():
    silver = pd.DataFrame(
        {
            "order_date": pd.to_datetime(["2026-01-15", "2026-01-20", "2026-02-01"], utc=True),
            "year": [2026, 2026, 2026],
            "month": [1, 1, 2],
            "amount": [10.0, 20.0, 5.0],
        }
    )
    by_month = GoldTable(
        "orders_by_month", "aggregate", ["year", "month"], ["year", "month"],
        [Metric("total_amount", "SUM(amount)", ["amount"])], "",
    )
    dim_date = GoldTable("orders_dim_date", "dimension", ["date"], [], [], "")

    tables = build_gold_tables(silver, [by_month, dim_date], date_column="order_date")

    assert tables["orders_by_month"]["total_amount"].tolist() == [30.0, 5.0]
    assert tables["orders_dim_date"]["quarter"].tolist() == [1, 1, 1]
    assert len(tables["orders_dim_date"]) == 3


@pytest.mark.parametrize(
    "expression",
    ["SUM(amount) * 2", "__import__('os')", "MEDIAN(amount)"],
)
def test_unsupported_metric_expressions_are_refused(expression):
    table = GoldTable("t", "aggregate", [], [], [Metric("m", expression, [])], "")

    with pytest.raises(GoldBuildError):
        build_gold_table(pd.DataFrame({"amount": [1.0]}), table)


def test_missing_silver_column_is_refused():
    table = GoldTable("fact", "fact", [], ["missing"], [], "")

    with pytest.raises(GoldBuildError):
        build_gold_table(pd.DataFrame({"amount": [1.0]}), table)
