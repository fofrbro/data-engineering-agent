import pandas as pd
import pytest

from src.contract.contract_generator import propose_contract_for_file
from src.contract.contract_lifecycle import approve_contract
from src.discovery.readers import read_dataframe
from src.execution.gold_executor import build_gold_tables
from src.execution.silver_executor import apply_silver_transformations
from src.powerbi.kpi_dax import (
    UnsupportedFormulaError,
    evaluate,
    evaluate_kpi,
    grouping_column,
    kpi_measures,
    parse_formula,
    to_dax,
)
from src.recommendation.kpi_recommender import recommend_kpis_for_file
from src.recommendation.pipeline_recommender import recommend_pipeline_for_file


def dax(formula, table="sales_clean"):
    return to_dax(parse_formula(formula), table)


@pytest.mark.parametrize(
    "formula, expected",
    [
        ("SUM(amount)", "SUM('sales_clean'[amount])"),
        ("SUM(quantity * price)", "SUMX('sales_clean', 'sales_clean'[quantity] * 'sales_clean'[price])"),
        ("AVG(price)", "AVERAGE('sales_clean'[price])"),
        ("COUNT(*)", "COUNTROWS('sales_clean')"),
        ("COUNT(DISTINCT customer_id)", "DISTINCTCOUNT('sales_clean'[customer_id])"),
        (
            "SUM(quantity * price) / COUNT(DISTINCT order_id)",
            "DIVIDE(SUMX('sales_clean', 'sales_clean'[quantity] * 'sales_clean'[price]), "
            "DISTINCTCOUNT('sales_clean'[order_id]))",
        ),
        ("SUM(amount) GROUP BY MONTH(order_date)", "SUM('sales_clean'[amount])"),
        ("SUM(amount) GROUP BY product", "SUM('sales_clean'[amount])"),
    ],
)
def test_formula_to_dax(formula, expected):
    assert dax(formula) == expected


def test_grouping_column():
    assert grouping_column("SUM(amount) GROUP BY MONTH(order_date)") == "order_date"
    assert grouping_column("SUM(amount) GROUP BY product") == "product"
    assert grouping_column("SUM(amount)") is None


@pytest.mark.parametrize(
    "formula",
    ["MEDIAN(price)", "SUM(a + b)", "SUM(amount); DROP TABLE x", "EVALUATE x"],
)
def test_unknown_formulas_are_refused(formula):
    with pytest.raises(UnsupportedFormulaError):
        parse_formula(formula)


def test_sales_kpis_map_to_shared_measures():
    measures, kpi_to_measure = kpi_measures(
        recommend_kpis_for_file("data/sales.csv"), "sales_clean",
    )

    assert [m.name for m in measures] == [
        "Revenue", "Number of Lines", "Quantity Sold",
        "Average Revenue per Line", "Customers", "Products", "Average Unit Price",
    ]
    assert kpi_to_measure["Revenue by Product"] == "Revenue"
    assert measures[0].source_kpis == ["Revenue", "Revenue by Product"]
    assert measures[0].format == "currency"


def test_kpi_values_match_executed_gold_tables():
    kpis = recommend_kpis_for_file("data/sales.csv")
    contract = approve_contract(propose_contract_for_file("data/sales.csv"), "cheikhou")
    recommendation = recommend_pipeline_for_file("data/sales.csv", contract)
    silver = apply_silver_transformations(
        read_dataframe("data/sales.csv"), recommendation.transformations,
    ).data
    summary = build_gold_tables(silver, recommendation.gold)["sales_summary"].iloc[0]

    assert evaluate_kpi(kpis.kpi("Revenue"), silver) == summary["total_sales"] == 3110.0
    assert evaluate_kpi(kpis.kpi("Quantity Sold"), silver) == summary["total_quantity"]
    assert evaluate_kpi(kpis.kpi("Average Unit Price"), silver) == pytest.approx(
        summary["avg_unit_price"]
    )
    assert evaluate_kpi(kpis.kpi("Number of Lines"), silver) == summary["number_of_lines"]
    assert evaluate_kpi(kpis.kpi("Customers"), silver) == 5
    assert evaluate_kpi(kpis.kpi("Average Revenue per Line"), silver) == 622.0


def test_divide_by_zero_is_blank():
    formula = parse_formula("SUM(amount) / COUNT(*)")

    assert evaluate(formula, pd.DataFrame({"amount": []})) is None
