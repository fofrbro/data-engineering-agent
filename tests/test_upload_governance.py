import json

import pandas as pd
import pytest

from src.contract.contract_lifecycle import (
    ContractStatusError,
    approve_contract_file,
    reject_contract_file,
)
from src.upload_governance import (
    assess_uploads,
    execute_assessment_tool,
)


def sandboxed_executor(name, arguments):
    """Évite l'écriture dans data/quarantine et data/rejected."""

    if name == "quarantine_csv":
        return {"status": "QUARANTINED"}

    if name == "reject_csv":
        return {"status": "REJECTED"}

    return execute_assessment_tool(name, arguments)


def assess(file_paths, contract_path, tmp_path, dataset_name=None):
    return assess_uploads(
        file_paths,
        contract_path,
        dataset_name,
        tool_executor=sandboxed_executor,
        proposed_contracts_dir=tmp_path / "contracts" / "proposed",
    )


def test_ingestion_tools_are_not_reachable():
    with pytest.raises(ValueError):
        execute_assessment_tool("ingest_csv", {})


def test_upload_without_contract_is_blocked_and_contract_proposed(tmp_path):
    result = assess(["data/sales.csv"], None, tmp_path, "ventes")

    assert result["allowed"] is False
    assert result["assessments"][0]["decision"] == "QUARANTINE"
    assert result["assessments"][0]["policy_rule"] == "CONTRACT_NOT_VALIDATED"
    assert result["assessments"][0]["run_id"]

    proposed = json.loads(
        open(result["proposed_contract_path"], encoding="utf-8").read()
    )

    assert result["proposed_contract_path"].endswith("proposed/ventes.json")
    assert proposed["status"] == "PROPOSED"
    assert proposed["dataset"] == "ventes"


def test_approved_contract_unlocks_upload(tmp_path):
    blocked = assess(["data/sales.csv"], None, tmp_path, "sales")

    validated_path = approve_contract_file(
        blocked["proposed_contract_path"],
        "cheikhou",
        contracts_dir=tmp_path / "contracts",
    )
    allowed = assess(["data/sales.csv"], str(validated_path), tmp_path)

    assert validated_path == tmp_path / "contracts" / "sales.json"
    assert allowed["allowed"] is True
    assert allowed["assessments"][0]["decision"] == "INGEST"
    assert allowed["proposed_contract_path"] is None


def test_one_invalid_file_blocks_the_batch(tmp_path):
    blocked = assess(["data/sales.csv"], None, tmp_path, "sales")
    contract = approve_contract_file(
        blocked["proposed_contract_path"],
        "cheikhou",
        contracts_dir=tmp_path / "contracts",
    )

    result = assess(
        ["data/sales.csv", "data/test_contract.csv"],
        str(contract),
        tmp_path,
    )

    assert result["allowed"] is False
    assert [item["decision"] for item in result["assessments"]] == [
        "INGEST", "REJECT",
    ]
    assert result["proposed_contract_path"] is None


def test_non_csv_upload_is_assessed(tmp_path):
    source = tmp_path / "sales.xlsx"
    pd.read_csv("data/sales.csv").to_excel(source, index=False)

    result = assess([str(source)], None, tmp_path)

    assert result["assessments"][0]["decision"] == "QUARANTINE"
    assert result["proposed_contract_path"] is not None


def test_contract_files_outside_contracts_dir_are_refused(tmp_path):
    outside = tmp_path / "elsewhere.json"
    outside.write_text('{"status": "PROPOSED", "dataset": "x"}', encoding="utf-8")

    with pytest.raises(ContractStatusError):
        approve_contract_file(outside, "cheikhou", contracts_dir=tmp_path / "contracts")


def test_approval_never_overwrites_existing_contract(tmp_path):
    blocked = assess(["data/sales.csv"], None, tmp_path, "sales")
    approve_contract_file(
        blocked["proposed_contract_path"], "cheikhou",
        contracts_dir=tmp_path / "contracts",
    )

    with pytest.raises(ContractStatusError):
        approve_contract_file(
            blocked["proposed_contract_path"], "cheikhou",
            contracts_dir=tmp_path / "contracts",
        )


def test_reject_contract_file_in_place(tmp_path):
    blocked = assess(["data/sales.csv"], None, tmp_path, "sales")

    path = reject_contract_file(
        blocked["proposed_contract_path"],
        "cheikhou",
        "Types erronés",
        contracts_dir=tmp_path / "contracts",
    )
    contract = json.loads(path.read_text(encoding="utf-8"))

    assert contract["status"] == "REJECTED"
    assert contract["review"]["comment"] == "Types erronés"
