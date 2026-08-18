import pytest

from src.pipeline_plan import build_pipeline_plan


def test_build_valid_ingest_plan():
    data = {
        "file_path": "data/sales.csv",
        "contract_path": "data/contracts/sales_contract.json",
        "inspect": True,
        "profile": True,
        "validate_quality": True,
        "validate_contract": True,
        "decision": True,
        "ingest": True,
        "transform_to_silver": True,
        "build_gold": True,
    }

    plan = build_pipeline_plan(data)

    assert plan.file_path == "data/sales.csv"
    assert plan.contract_path == "data/contracts/sales_contract.json"
    assert plan.ingest is True
    assert plan.transform_to_silver is True
    assert plan.build_gold is True


def test_build_quarantine_plan():
    data = {
        "file_path": "data/test_quarantine.csv",
        "contract_path": "data/contracts/sales_contract.json",
        "validate_quality": True,
        "validate_contract": True,
        "decision": True,
        "quarantine": True,
    }

    plan = build_pipeline_plan(data)

    assert plan.quarantine is True
    assert plan.ingest is False
    assert plan.transform_to_silver is False
    assert plan.build_gold is False


def test_missing_required_field():
    data = {
        "file_path": "data/sales.csv",
    }

    with pytest.raises(ValueError, match="contract_path"):
        build_pipeline_plan(data)


def test_invalid_plan_is_rejected():
    data = {
        "file_path": "data/test_contract.csv",
        "contract_path": "data/contracts/sales_contract.json",
        "reject": True,
        "transform_to_silver": True,
    }

    with pytest.raises(ValueError):
        build_pipeline_plan(data)
