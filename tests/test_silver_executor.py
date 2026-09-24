import pandas as pd
import pytest

from src.contract.contract_generator import generate_contract
from src.contract.contract_lifecycle import approve_contract
from src.discovery.schema_profiler import profile_schema
from src.execution.silver_executor import (
    TransformationError,
    apply_silver_transformations,
)
from src.recommendation.pipeline_recommender import (
    Transformation,
    recommend_pipeline,
)
from src.semantic.semantic_profiler import profile_semantics


def recommendation_for(frame):
    schema = profile_schema(frame)
    semantics = profile_semantics(schema)
    contract = approve_contract(
        generate_contract(schema, semantics, dataset="orders"), "cheikhou",
    )
    return recommend_pipeline(schema, semantics, contract)


def orders():
    frame = pd.DataFrame(
        {
            "Order ID": [1, 2, 3, 4],
            "status": [" paid", "shipped ", None, "paid"],
            "order_date": ["2026-01-15", "2026-02-15", "2026-02-20", "2026-03-01"],
            "quantity": [1, 2, 3, 1],
            "unit_price": [10, 20, 30, 10],
        }
    )
    return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)


def reports_by_id(result):
    return {report.id: report for report in result.reports}


def test_recommended_transformations_are_applied_when_approved():
    frame = orders()
    recommendation = recommendation_for(frame)

    result = apply_silver_transformations(
        frame, recommendation.transformations, destructive_approved=True,
    )
    silver = result.data

    assert list(silver.columns)[:2] == ["order_id", "status"]
    assert silver["status"].tolist() == ["PAID", "SHIPPED", "UNKNOWN", "PAID"]
    assert str(silver["order_date"].dt.tz) == "UTC"
    assert silver["unit_price"].dtype == "float64"
    assert silver["line_amount"].tolist() == [10.0, 40.0, 90.0, 10.0]
    assert silver["month"].tolist() == [1, 2, 2, 3]
    assert len(silver) == 4
    assert reports_by_id(result)["deduplicate_rows"].rows_after == 4


def test_destructive_steps_are_skipped_without_approval():
    frame = orders()
    recommendation = recommendation_for(frame)

    result = apply_silver_transformations(frame, recommendation.transformations)
    reports = reports_by_id(result)

    assert reports["deduplicate_rows"].status == "SKIPPED_NOT_APPROVED"
    assert reports["fill_null_dimensions"].status == "SKIPPED_NOT_APPROVED"
    assert len(result.data) == 5
    assert result.data["status"].isna().sum() == 1


def test_contract_violations_go_to_quarantine():
    frame = pd.DataFrame({"quantity": [1, -2, 3], "price": [10.0, 5.0, None]})
    step = Transformation(
        id="validate_business_rules",
        type="check",
        columns=["quantity", "price"],
        description="",
        rationale="",
        parameters={
            "rules": {
                "quantity": {"min": 0},
                "price": {"nullable": False},
            }
        },
    )

    result = apply_silver_transformations(frame, [step])

    assert result.data["quantity"].tolist() == [1]
    assert result.quarantined["quantity"].tolist() == [-2, 3]
    assert result.reports[0].quarantined_rows == 2


def test_cast_that_would_lose_values_is_refused():
    frame = pd.DataFrame({"order_date": ["2026-01-01", "pas une date"]})
    step = Transformation(
        id="cast_types", type="cast", columns=["order_date"],
        description="", rationale="",
        parameters={"types": {"order_date": "datetime"}},
    )

    with pytest.raises(TransformationError):
        apply_silver_transformations(frame, [step])


def test_unknown_transformation_is_refused():
    step = Transformation(id="drop_table", type="sql", columns=[], description="", rationale="")

    with pytest.raises(TransformationError):
        apply_silver_transformations(pd.DataFrame({"a": [1]}), [step])


def test_source_dataframe_is_not_modified():
    frame = orders()
    before = frame.copy()

    apply_silver_transformations(
        frame, recommendation_for(frame).transformations, destructive_approved=True,
    )

    pd.testing.assert_frame_equal(frame, before)
