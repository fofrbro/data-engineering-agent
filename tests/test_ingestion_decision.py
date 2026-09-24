import pytest

from src.tools.ingestion_decision import determine_ingestion_decision


def test_ingestion_decision_ingest():
    contract_result = {
        "valid": True,
        "errors_count": 0,
        "contract_status": "VALIDATED",
    }

    quality_result = {
        "valid": True,
        "issues_count": 0,
    }

    result = determine_ingestion_decision(
        contract_result,
        quality_result,
    )

    assert result["decision"] == "INGEST"
    assert result["policy_rule"] == "ALL_CHECKS_PASSED"
    assert result["contract_errors"] == 0
    assert result["quality_issues"] == 0


def test_ingestion_decision_quarantine():
    contract_result = {
        "valid": True,
        "errors_count": 0,
        "contract_status": "VALIDATED",
    }

    quality_result = {
        "valid": False,
        "issues_count": 1,
    }

    result = determine_ingestion_decision(
        contract_result,
        quality_result,
    )

    assert result["decision"] == "QUARANTINE"
    assert result["policy_rule"] == "QUALITY_ISSUES"
    assert result["contract_errors"] == 0
    assert result["quality_issues"] == 1


def test_ingestion_decision_reject():
    contract_result = {
        "valid": False,
        "errors_count": 1,
    }

    quality_result = {
        "valid": False,
        "issues_count": 1,
    }

    result = determine_ingestion_decision(
        contract_result,
        quality_result,
    )

    assert result["decision"] == "REJECT"
    assert result["policy_rule"] == "CONTRACT_VIOLATION"
    assert result["contract_errors"] == 1
    assert result["quality_issues"] == 1


@pytest.mark.parametrize(
    "contract_status",
    ["PROPOSED", "REJECTED", None, "missing"],
)
def test_untrusted_contract_never_ingests(contract_status):
    contract_result = {"valid": True, "errors_count": 0}

    if contract_status != "missing":
        contract_result["contract_status"] = contract_status

    result = determine_ingestion_decision(
        contract_result,
        {"valid": True, "issues_count": 0},
    )

    assert result["decision"] == "QUARANTINE"
    assert result["policy_rule"] == "CONTRACT_NOT_VALIDATED"
    assert "VALIDATED" in result["reason"]


def test_contract_violation_wins_over_untrusted_contract():
    result = determine_ingestion_decision(
        {"valid": False, "errors_count": 2, "contract_status": "PROPOSED"},
        {"valid": True, "issues_count": 0},
    )

    assert result["decision"] == "REJECT"
    assert result["contract_status"] == "PROPOSED"


def test_decision_on_real_files_with_proposed_then_validated_contract(tmp_path):
    from src.contract.contract_generator import propose_contract_for_file
    from src.contract.contract_lifecycle import approve_contract, save_contract
    from src.tools.contract_validation import validate_contract
    from src.tools.data_validation import validate_csv

    proposed = propose_contract_for_file("data/sales.csv")
    proposed_path = save_contract(proposed, tmp_path / "proposed.json")
    validated_path = save_contract(
        approve_contract(proposed, "cheikhou"),
        tmp_path / "validated.json",
    )
    quality = validate_csv("data/sales.csv")

    before_review = determine_ingestion_decision(
        validate_contract("data/sales.csv", str(proposed_path)), quality,
    )
    after_review = determine_ingestion_decision(
        validate_contract("data/sales.csv", str(validated_path)), quality,
    )
    without_contract = determine_ingestion_decision(
        validate_contract("data/sales.csv", None), quality,
    )

    assert before_review["decision"] == "QUARANTINE"
    assert after_review["decision"] == "INGEST"
    assert without_contract["decision"] == "QUARANTINE"


def test_quality_warnings_only_lead_to_ingest_with_warnings():
    result = determine_ingestion_decision(
        {"valid": True, "errors_count": 0, "contract_status": "VALIDATED"},
        {"valid": True, "issues_count": 1, "warnings_count": 1},
    )

    assert result["decision"] == "INGEST"
    assert result["policy_rule"] == "PASSED_WITH_WARNINGS"
    assert result["quality_warnings"] == 1
    assert "1 avertissement(s)" in result["reason"]


def test_duplicate_file_is_ingested_with_warnings_under_validated_contract(tmp_path):
    from src.contract.contract_generator import propose_contract_for_file
    from src.contract.contract_lifecycle import approve_contract, save_contract
    from src.tools.contract_validation import validate_contract
    from src.tools.data_validation import validate_csv

    contract = save_contract(
        approve_contract(propose_contract_for_file("data/test_quarantine.csv"), "cheikhou"),
        tmp_path / "contract.json",
    )

    result = determine_ingestion_decision(
        validate_contract("data/test_quarantine.csv", str(contract)),
        validate_csv("data/test_quarantine.csv", str(contract)),
    )

    assert result["decision"] == "INGEST"
    assert result["policy_rule"] == "PASSED_WITH_WARNINGS"
