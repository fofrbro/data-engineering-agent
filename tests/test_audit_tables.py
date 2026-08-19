from src.audit import create_audit_record, finish_audit, record_step
from src.audit_tables import (
    audit_to_run_row,
    audit_to_step_rows,
    audits_to_run_rows,
    audits_to_step_rows,
)


def make_audit():
    audit = create_audit_record(
        run_id="run-001",
        source_file="data/sales.csv",
        contract_path="data/contracts/sales_contract.json",
    )

    record_step(
        audit,
        name="validate_csv",
        status="SUCCESS",
    )

    record_step(
        audit,
        name="validate_contract",
        status="SUCCESS",
    )

    finish_audit(
        audit,
        status="SUCCESS",
        decision="INGEST",
    )

    return audit


def test_finish_audit_calculates_duration():
    audit = make_audit()

    assert audit["duration_seconds"] is not None
    assert audit["duration_seconds"] >= 0


def test_audit_to_run_row():
    audit = make_audit()

    row = audit_to_run_row(audit)

    assert row["run_id"] == "run-001"
    assert row["source_file"] == "data/sales.csv"
    assert row["decision"] == "INGEST"
    assert row["final_status"] == "SUCCESS"
    assert row["duration_seconds"] >= 0


def test_audit_to_step_rows():
    audit = make_audit()

    rows = audit_to_step_rows(audit)

    assert len(rows) == 2

    assert rows[0] == {
        "run_id": "run-001",
        "step_order": 1,
        "step_name": "validate_csv",
        "status": "SUCCESS",
    }

    assert rows[1]["step_order"] == 2
    assert rows[1]["step_name"] == "validate_contract"


def test_audits_to_run_rows():
    audits = [
        make_audit(),
        make_audit(),
    ]

    rows = audits_to_run_rows(audits)

    assert len(rows) == 2
    assert all(
        row["run_id"] == "run-001"
        for row in rows
    )


def test_audits_to_step_rows():
    audits = [
        make_audit(),
        make_audit(),
    ]

    rows = audits_to_step_rows(audits)

    assert len(rows) == 4
