from src.pipeline_orchestrator import execute_pipeline
from src.pipeline_plan import PipelinePlan


def make_plan(
    file_path="data/sales.csv",
    inspect=True,
    profile=True,
    validate_quality=True,
    validate_contract=True,
    decision=True,
    ingest=True,
    transform_to_silver=True,
    build_gold=True,
):
    return PipelinePlan(
        file_path=file_path,
        contract_path="data/contracts/sales_contract.json",
        inspect=inspect,
        profile=profile,
        validate_quality=validate_quality,
        validate_contract=validate_contract,
        decision=decision,
        ingest=ingest,
        transform_to_silver=transform_to_silver,
        build_gold=build_gold,
    )


def test_orchestrator_ingest_to_gold():

    calls = []

    def fake_tool(name, arguments):
        calls.append((name, arguments))

        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": True,
                "errors_count": 0,
            }

        if name == "validate_csv":
            return {
                "valid": True,
                "issues_count": 0,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "INGEST",
            }

        return {"status": "OK"}

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    assert result["decision"]["decision"] == "INGEST"

    assert [name for name, _ in calls] == [
        "inspect_csv",
        "profile_csv",
        "validate_csv",
        "validate_contract",
        "determine_ingestion_decision",
        "ingest_csv",
        "transform_to_silver",
        "build_sales_gold",
    ]


def test_orchestrator_quarantine_stops_pipeline():

    calls = []

    def fake_tool(name, arguments):
        calls.append(name)

        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": True,
                "errors_count": 0,
            }

        if name == "validate_csv":
            return {
                "valid": False,
                "issues_count": 1,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "QUARANTINE",
            }

        return {"status": "OK"}

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    assert result["decision"]["decision"] == "QUARANTINE"

    assert calls[-1] == "quarantine_csv"

    assert "ingest_csv" not in calls
    assert "transform_to_silver" not in calls
    assert "build_sales_gold" not in calls


def test_orchestrator_reject_stops_pipeline():

    calls = []

    def fake_tool(name, arguments):
        calls.append(name)

        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": False,
                "errors_count": 1,
            }

        if name == "validate_csv":
            return {
                "valid": False,
                "issues_count": 1,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "REJECT",
            }

        return {"status": "OK"}

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    assert result["decision"]["decision"] == "REJECT"

    assert calls[-1] == "reject_csv"

    assert "ingest_csv" not in calls
    assert "transform_to_silver" not in calls
    assert "build_sales_gold" not in calls


def test_orchestrator_continues_after_skipped_ingestion():

    calls = []

    def fake_tool(name, arguments):
        calls.append(name)

        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": True,
                "errors_count": 0,
            }

        if name == "validate_csv":
            return {
                "valid": True,
                "issues_count": 0,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "INGEST",
            }

        if name == "ingest_csv":
            return {
                "status": "SKIPPED",
                "reason": "Fichier déjà ingéré.",
            }

        return {
            "status": "OK",
        }

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    assert result["ingest"]["status"] == "SKIPPED"

    assert calls[-2:] == [
        "transform_to_silver",
        "build_sales_gold",
    ]


def test_orchestrator_audit_success():

    def fake_tool(name, arguments):
        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": True,
                "errors_count": 0,
            }

        if name == "validate_csv":
            return {
                "valid": True,
                "issues_count": 0,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "INGEST",
            }

        if name == "ingest_csv":
            return {
                "status": "INGESTED",
            }

        return {
            "status": "TRANSFORMED",
        }

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    audit = result["audit"]

    assert audit["run_id"]
    assert audit["source_file"] == "data/sales.csv"
    assert audit["contract_path"] == (
        "data/contracts/sales_contract.json"
    )
    assert audit["decision"] == "INGEST"
    assert audit["final_status"] == "SUCCESS"
    assert audit["finished_at"] is not None
    assert audit["error"] is None

    step_names = [
        step["name"]
        for step in audit["steps"]
    ]

    assert "validate_csv" in step_names
    assert "validate_contract" in step_names
    assert "determine_ingestion_decision" in step_names
    assert "ingest_csv" in step_names


def test_orchestrator_audit_quarantine():

    def fake_tool(name, arguments):
        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": True,
                "errors_count": 0,
            }

        if name == "validate_csv":
            return {
                "valid": False,
                "issues_count": 1,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "QUARANTINE",
            }

        return {
            "status": "QUARANTINED",
        }

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    audit = result["audit"]

    assert audit["decision"] == "QUARANTINE"
    assert audit["final_status"] == "QUARANTINED"

    assert audit["steps"][-1]["name"] == "quarantine_csv"


def test_orchestrator_audit_reject():

    def fake_tool(name, arguments):
        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": False,
                "errors_count": 1,
            }

        if name == "validate_csv":
            return {
                "valid": False,
                "issues_count": 1,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "REJECT",
            }

        return {
            "status": "REJECTED",
        }

    result = execute_pipeline(
        make_plan(),
        fake_tool,
    )

    audit = result["audit"]

    assert audit["decision"] == "REJECT"
    assert audit["final_status"] == "REJECTED"

    assert audit["steps"][-1]["name"] == "reject_csv"
