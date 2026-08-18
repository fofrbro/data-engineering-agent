import json
from types import SimpleNamespace

from src.pipeline_planner import generate_pipeline_plan


def test_generate_ingest_pipeline_plan(monkeypatch):

    expected_plan = {
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
        "quarantine": False,
        "reject": False,
        "steps": [
            "inspect",
            "profile",
            "validate_quality",
            "validate_contract",
            "decision",
            "ingest",
            "transform_to_silver",
            "build_gold",
        ],
    }

    fake_response = SimpleNamespace(
        output_text=json.dumps(expected_plan)
    )

    class FakeResponses:
        def create(self, **kwargs):
            return fake_response

    fake_client = SimpleNamespace(
        responses=FakeResponses()
    )

    plan = generate_pipeline_plan(
        fake_client,
        "Analyse et ingère data/sales.csv avec "
        "le contrat data/contracts/sales_contract.json.",
    )

    assert plan.file_path == "data/sales.csv"
    assert plan.contract_path == (
        "data/contracts/sales_contract.json"
    )

    assert plan.inspect is True
    assert plan.profile is True
    assert plan.validate_quality is True
    assert plan.validate_contract is True
    assert plan.decision is True
    assert plan.ingest is True
    assert plan.transform_to_silver is True
    assert plan.build_gold is True

    assert plan.quarantine is False
    assert plan.reject is False


def test_generate_plan_rejects_incoherent_plan():

    invalid_plan = {
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
        "quarantine": True,
        "reject": False,
        "steps": [],
    }

    fake_response = SimpleNamespace(
        output_text=json.dumps(invalid_plan)
    )

    class FakeResponses:
        def create(self, **kwargs):
            return fake_response

    fake_client = SimpleNamespace(
        responses=FakeResponses()
    )

    import pytest

    with pytest.raises(ValueError):
        generate_pipeline_plan(
            fake_client,
            "Demande quelconque",
        )


def test_generate_plan_for_ingestion_requires_quality_and_contract(
    monkeypatch
):
    expected_plan = {
        "file_path": "data/sales.csv",
        "contract_path": "data/contracts/sales_contract.json",
        "inspect": False,
        "profile": False,
        "validate_quality": True,
        "validate_contract": True,
        "decision": True,
        "ingest": True,
        "transform_to_silver": True,
        "build_gold": True,
        "quarantine": False,
        "reject": False,
        "steps": [
            "validate_quality",
            "validate_contract",
            "decision",
            "ingest",
            "transform_to_silver",
            "build_gold",
        ],
    }

    fake_response = SimpleNamespace(
        output_text=json.dumps(expected_plan)
    )

    class FakeResponses:
        def create(self, **kwargs):
            return fake_response

    fake_client = SimpleNamespace(
        responses=FakeResponses()
    )

    plan = generate_pipeline_plan(
        fake_client,
        "Transforme et ingère data/sales.csv.",
    )

    assert plan.validate_quality is True
    assert plan.validate_contract is True
    assert plan.decision is True
    assert plan.ingest is True
    assert plan.transform_to_silver is True
    assert plan.build_gold is True
