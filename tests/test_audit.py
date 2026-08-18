from src.audit import (
    create_audit_record,
    create_run_id,
    finish_audit,
    record_output,
    record_step,
)


def test_create_run_id():
    run_id = create_run_id()

    assert isinstance(run_id, str)
    assert len(run_id) > 0


def test_create_audit_record():
    run_id = create_run_id()

    audit = create_audit_record(
        run_id=run_id,
        source_file="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
    )

    assert audit["run_id"] == run_id
    assert audit["source_file"] == "data/sales.csv"
    assert audit["final_status"] == "RUNNING"
    assert audit["steps"] == []
    assert audit["outputs"] == []


def test_record_step():
    audit = create_audit_record(
        run_id="run-123",
        source_file="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
    )

    record_step(
        audit,
        name="validate_csv",
        status="SUCCESS",
        result={
            "valid": True,
            "issues_count": 0,
        },
    )

    assert len(audit["steps"]) == 1
    assert audit["steps"][0]["name"] == "validate_csv"
    assert audit["steps"][0]["status"] == "SUCCESS"


def test_record_output():
    audit = create_audit_record(
        run_id="run-123",
        source_file="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
    )

    record_output(
        audit,
        path="data/silver/sales.parquet",
        layer="silver",
    )

    assert audit["outputs"] == [
        {
            "path": "data/silver/sales.parquet",
            "layer": "silver",
        }
    ]


def test_finish_audit():
    audit = create_audit_record(
        run_id="run-123",
        source_file="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
    )

    result = finish_audit(
        audit,
        status="SUCCESS",
        decision="INGEST",
    )

    assert result["final_status"] == "SUCCESS"
    assert result["decision"] == "INGEST"
    assert result["finished_at"] is not None
    assert result["error"] is None
