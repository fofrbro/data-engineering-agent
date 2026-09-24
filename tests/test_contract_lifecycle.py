import json
from datetime import datetime, timezone

import pytest

from src.contract.contract_lifecycle import (
    ContractStatusError,
    approve_contract,
    contract_status,
    reject_contract,
    save_contract,
)
from src.tools.contract_validation import validate_contract


REVIEW_TIME = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def proposed_contract():
    return {
        "dataset": "sales",
        "version": "1.0",
        "status": "PROPOSED",
        "review": None,
        "columns": {"customer_id": {"type": "integer", "nullable": False}},
    }


def test_contract_without_status_is_legacy_validated():
    assert contract_status({"dataset": "sales", "columns": {}}) == "VALIDATED"


def test_unknown_status_is_refused():
    with pytest.raises(ContractStatusError):
        contract_status({"status": "DRAFT"})


def test_approve_proposed_contract():
    original = proposed_contract()

    approved = approve_contract(
        original, "  cheikhou ", comment="OK", reviewed_at=REVIEW_TIME,
    )

    assert approved["status"] == "VALIDATED"
    assert approved["review"] == {
        "status": "VALIDATED",
        "reviewed_by": "cheikhou",
        "reviewed_at": "2026-09-24T12:00:00+00:00",
        "comment": "OK",
    }
    assert original["status"] == "PROPOSED"
    assert original["review"] is None


def test_reject_requires_reason():
    with pytest.raises(ContractStatusError):
        reject_contract(proposed_contract(), "cheikhou", reason=" ")

    rejected = reject_contract(
        proposed_contract(), "cheikhou", reason="Types erronés",
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["review"]["comment"] == "Types erronés"


def test_review_requires_reviewer():
    with pytest.raises(ContractStatusError):
        approve_contract(proposed_contract(), "")


@pytest.mark.parametrize("status", ["VALIDATED", "REJECTED"])
def test_only_proposed_contracts_can_be_reviewed(status):
    contract = {**proposed_contract(), "status": status}

    with pytest.raises(ContractStatusError):
        approve_contract(contract, "cheikhou")

    with pytest.raises(ContractStatusError):
        reject_contract(contract, "cheikhou", reason="non")


def test_save_contract_round_trip(tmp_path):
    path = save_contract(proposed_contract(), tmp_path / "contracts" / "sales.json")

    assert json.loads(path.read_text(encoding="utf-8")) == proposed_contract()


def test_validation_result_exposes_contract_status(tmp_path):
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text("customer_id\n1\n", encoding="utf-8")
    proposed = save_contract(proposed_contract(), tmp_path / "proposed.json")
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps({"dataset": "sales", "version": "1.0", "columns": {}}),
        encoding="utf-8",
    )

    assert validate_contract(str(csv_file), str(proposed))["contract_status"] == "PROPOSED"
    assert validate_contract(str(csv_file), str(legacy))["contract_status"] == "VALIDATED"
    assert validate_contract(str(csv_file), None)["contract_status"] is None
