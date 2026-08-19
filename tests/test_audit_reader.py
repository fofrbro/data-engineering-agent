from src.audit_reader import (
    filter_audits,
    find_by_run_id,
    list_audits,
    summarize_audits,
)
from src.audit_store import append_audit


def create_test_audits(path):
    append_audit(
        {
            "run_id": "run-001",
            "source_file": "data/sales.csv",
            "decision": "INGEST",
            "final_status": "SUCCESS",
        },
        path,
    )

    append_audit(
        {
            "run_id": "run-002",
            "source_file": "data/test_quarantine.csv",
            "decision": "QUARANTINE",
            "final_status": "QUARANTINED",
        },
        path,
    )

    append_audit(
        {
            "run_id": "run-003",
            "source_file": "data/test_contract.csv",
            "decision": "REJECT",
            "final_status": "REJECTED",
        },
        path,
    )


def test_list_audits(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    audits = list_audits(audit_file)

    assert len(audits) == 3


def test_find_by_run_id(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    audit = find_by_run_id(
        "run-002",
        audit_file,
    )

    assert audit is not None
    assert audit["decision"] == "QUARANTINE"


def test_find_unknown_run_id(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    audit = find_by_run_id(
        "unknown",
        audit_file,
    )

    assert audit is None


def test_filter_by_decision(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    audits = filter_audits(
        decision="REJECT",
        input_path=audit_file,
    )

    assert len(audits) == 1
    assert audits[0]["run_id"] == "run-003"


def test_filter_by_status(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    audits = filter_audits(
        final_status="QUARANTINED",
        input_path=audit_file,
    )

    assert len(audits) == 1
    assert audits[0]["run_id"] == "run-002"


def test_filter_by_source_file(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    audits = filter_audits(
        source_file="data/sales.csv",
        input_path=audit_file,
    )

    assert len(audits) == 1
    assert audits[0]["run_id"] == "run-001"


def test_summarize_audits(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    summary = summarize_audits(audit_file)

    assert summary["total_runs"] == 3

    assert summary["decisions"] == {
        "INGEST": 1,
        "QUARANTINE": 1,
        "REJECT": 1,
    }

    assert summary["statuses"] == {
        "SUCCESS": 1,
        "QUARANTINED": 1,
        "REJECTED": 1,
    }
