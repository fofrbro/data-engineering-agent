import json
from datetime import datetime, timezone

import pytest

from src.contract.contract_generator import propose_contract_for_file
from src.contract.contract_lifecycle import (
    ContractStatusError,
    approve_contract,
    approve_contract_file,
    contract_status,
    reject_contract,
    reject_contract_file,
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


def proposed_file(tmp_path):
    return save_contract(
        propose_contract_for_file("data/sales.csv"),
        tmp_path / "contracts" / "proposed" / "sales.json",
    )


def test_approve_contract_file_saves_validated_contract(tmp_path):
    path = approve_contract_file(
        proposed_file(tmp_path), "cheikhou", contracts_dir=tmp_path / "contracts",
    )

    assert path == tmp_path / "contracts" / "sales.json"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "VALIDATED"


def test_contract_files_outside_contracts_dir_are_refused(tmp_path):
    outside = tmp_path / "elsewhere.json"
    outside.write_text('{"status": "PROPOSED", "dataset": "x"}', encoding="utf-8")

    with pytest.raises(ContractStatusError):
        approve_contract_file(outside, "cheikhou", contracts_dir=tmp_path / "contracts")


def test_approval_never_overwrites_existing_contract(tmp_path):
    proposed = proposed_file(tmp_path)
    approve_contract_file(proposed, "cheikhou", contracts_dir=tmp_path / "contracts")

    with pytest.raises(ContractStatusError):
        approve_contract_file(proposed, "cheikhou", contracts_dir=tmp_path / "contracts")


def test_reject_contract_file_in_place(tmp_path):
    path = reject_contract_file(
        proposed_file(tmp_path), "cheikhou", "Types erronés",
        contracts_dir=tmp_path / "contracts",
    )
    contract = json.loads(path.read_text(encoding="utf-8"))

    assert contract["status"] == "REJECTED"
    assert contract["review"]["comment"] == "Types erronés"
