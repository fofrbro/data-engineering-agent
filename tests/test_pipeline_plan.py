import pytest

from src.pipeline_plan import PipelinePlan


def test_ingest_plan_is_valid():
    plan = PipelinePlan(
        file_path="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
        inspect=True,
        profile=True,
        validate_quality=True,
        validate_contract=True,
        decision=True,
        ingest=True,
        transform_to_silver=True,
        build_gold=True,
    )

    plan.validate()


def test_quarantine_plan_is_valid():
    plan = PipelinePlan(
        file_path="data/test_quarantine.csv",
        contract_path="data/contracts/sales_contract.json",
        validate_quality=True,
        validate_contract=True,
        decision=True,
        quarantine=True,
    )

    plan.validate()


def test_reject_plan_is_valid():
    plan = PipelinePlan(
        file_path="data/test_contract.csv",
        contract_path="data/contracts/sales_contract.json",
        validate_quality=True,
        validate_contract=True,
        decision=True,
        reject=True,
    )

    plan.validate()


def test_silver_without_ingest_is_invalid():
    plan = PipelinePlan(
        file_path="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
        transform_to_silver=True,
    )

    with pytest.raises(ValueError):
        plan.validate()


def test_gold_without_silver_is_invalid():
    plan = PipelinePlan(
        file_path="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
        build_gold=True,
    )

    with pytest.raises(ValueError):
        plan.validate()


def test_reject_cannot_build_silver():
    plan = PipelinePlan(
        file_path="data/test_contract.csv",
        contract_path="data/contracts/sales_contract.json",
        reject=True,
        transform_to_silver=True,
    )

    with pytest.raises(ValueError):
        plan.validate()
