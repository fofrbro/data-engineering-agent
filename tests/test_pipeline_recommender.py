import json

import pandas as pd

from src.contract.contract_generator import generate_contract, propose_contract_for_file
from src.contract.contract_lifecycle import approve_contract
from src.discovery.schema_profiler import profile_schema
from src.recommendation.pipeline_recommender import (
    recommend_pipeline,
    recommend_pipeline_for_file,
)
from src.semantic.semantic_profiler import profile_semantics


def recommend(frame, dataset="orders", validated=True):
    schema = profile_schema(frame)
    semantics = profile_semantics(schema)
    contract = generate_contract(schema, semantics, dataset=dataset)

    if validated:
        contract = approve_contract(contract, "cheikhou")

    return recommend_pipeline(schema, semantics, contract)


def orders_frame():
    frame = pd.DataFrame(
        {
            "Order ID": range(1, 13),
            "customer_id": [1, 2, 3] * 4,
            "status": ["paid", "shipped", None] * 4,
            "order_date": [f"2026-0{m}-15" for m in (1, 2, 3)] * 4,
            "quantity": [1, 2, 3] * 4,
            "unit_price": [10, 20, 30] * 4,
        }
    )
    return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)


def by_id(recommendation):
    return {step.id: step for step in recommendation.transformations}


def gold_names(recommendation):
    return [table.name for table in recommendation.gold]


def test_existing_sales_file_matches_current_sales_pipeline():
    contract = approve_contract(propose_contract_for_file("data/sales.csv"), "cheikhou")

    recommendation = recommend_pipeline_for_file("data/sales.csv", contract)
    steps = by_id(recommendation)
    by_product = next(t for t in recommendation.gold if t.name == "sales_by_product")

    assert recommendation.status == "PROPOSED"
    assert recommendation.bronze["table"] == "sales_raw"
    assert recommendation.silver["table"] == "sales_clean"
    assert steps["cast_types"].parameters["types"] == {"price": "decimal"}
    assert steps["derive_line_amount"].parameters["expression"] == "quantity * price"
    assert "deduplicate_rows" not in steps
    assert [m.name for m in by_product.metrics] == [
        "total_sales", "total_quantity", "avg_unit_price", "number_of_lines",
    ]
    assert by_product.metrics[0].expression == "SUM(line_amount)"
    assert gold_names(recommendation) == [
        "fact_sales", "dim_customer", "dim_product",
        "sales_by_product", "sales_summary",
    ]


def test_silver_transformations_for_messy_orders():
    steps = by_id(recommend(orders_frame()))

    assert steps["standardize_column_names"].parameters["mapping"] == {
        "Order ID": "order_id",
    }
    assert steps["cast_types"].parameters["types"] == {
        "order_date": "datetime",
        "unit_price": "decimal",
    }
    assert steps["normalize_categories"].columns == ["status"]
    assert steps["fill_null_dimensions"].columns == ["status"]
    assert steps["deduplicate_rows"].destructive is True
    assert "customer_id" in steps["validate_business_rules"].parameters["rules"]
    assert steps["derive_date_parts"].columns == ["order_date"]


def test_destructive_steps_require_approval_and_others_do_not():
    recommendation = recommend(orders_frame())

    destructive = {
        step.id for step in recommendation.transformations if step.requires_approval
    }

    assert destructive == {"fill_null_dimensions", "deduplicate_rows"}
    assert recommendation.to_dict()["requires_approval"] is True


def test_gold_tables_for_orders():
    recommendation = recommend(orders_frame())
    tables = {table.name: table for table in recommendation.gold}

    assert tables["fact_orders"].table_type == "fact"
    assert tables["dim_customer"].grain == ["customer_id"]
    assert tables["dim_date"].table_type == "dimension"
    assert tables["orders_by_status"].grain == ["status"]
    assert tables["orders_by_month"].grain == ["year", "month"]
    assert tables["orders_summary"].grain == []


def test_null_keys_and_measures():
    frame = pd.DataFrame(
        {
            "customer_id": [1, None, 3, 4],
            "amount": [10.5, None, 3.0, 4.0],
        }
    )

    steps = by_id(recommend(frame))

    assert steps["drop_rows_with_null_keys"].destructive is True
    assert steps["keep_null_measures"].columns == ["amount"]
    assert steps["keep_null_measures"].destructive is False
    assert steps["cast_types"].parameters["types"] == {"customer_id": "integer"}


def test_warnings_for_unvalidated_contract_and_generic_data():
    frame = pd.DataFrame({"sensor": ["A", "B"] * 6, "label": ["x", "y"] * 6})

    recommendation = recommend(frame, dataset="sensors", validated=False)

    assert len(recommendation.warnings) == 4
    assert "VALIDATED" in recommendation.warnings[0]
    assert gold_names(recommendation) == ["sensors_by_sensor", "sensors_by_label", "sensors_summary"]
    assert recommendation.gold[-1].metrics[0].expression == "COUNT(sensor)"


def test_recommendation_without_contract():
    schema = profile_schema(orders_frame())

    recommendation = recommend_pipeline(schema, profile_semantics(schema))

    assert recommendation.dataset == "dataset"
    assert recommendation.contract_status is None
    assert "validate_business_rules" not in by_id(recommendation)


def test_recommendation_is_json_serializable():
    payload = recommend(orders_frame()).to_dict()

    json.dumps(payload)

    assert payload["silver"]["transformations"][0]["requires_approval"] is False
