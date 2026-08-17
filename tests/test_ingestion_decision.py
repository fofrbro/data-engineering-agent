from src.tools.ingestion_decision import determine_ingestion_decision


def test_ingestion_decision_ingest():
    contract_result = {
        "valid": True,
        "errors_count": 0,
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
    assert result["contract_errors"] == 0
    assert result["quality_issues"] == 0


def test_ingestion_decision_quarantine():
    contract_result = {
        "valid": True,
        "errors_count": 0,
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
    assert result["contract_errors"] == 1
    assert result["quality_issues"] == 1
