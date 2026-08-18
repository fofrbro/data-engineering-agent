from src.audit_store import append_audit, read_audits


def test_append_audit(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    audit = {
        "run_id": "run-001",
        "source_file": "data/sales.csv",
        "final_status": "SUCCESS",
    }

    path = append_audit(
        audit,
        audit_file,
    )

    assert path == audit_file
    assert audit_file.exists()

    lines = audit_file.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 1


def test_append_multiple_audits(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    append_audit(
        {
            "run_id": "run-001",
            "final_status": "SUCCESS",
        },
        audit_file,
    )

    append_audit(
        {
            "run_id": "run-002",
            "final_status": "REJECTED",
        },
        audit_file,
    )

    lines = audit_file.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 2


def test_read_audits(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    append_audit(
        {
            "run_id": "run-001",
            "final_status": "SUCCESS",
        },
        audit_file,
    )

    append_audit(
        {
            "run_id": "run-002",
            "final_status": "QUARANTINED",
        },
        audit_file,
    )

    audits = read_audits(audit_file)

    assert len(audits) == 2
    assert audits[0]["run_id"] == "run-001"
    assert audits[1]["run_id"] == "run-002"


def test_read_missing_audit_file(tmp_path):
    audit_file = tmp_path / "missing.jsonl"

    audits = read_audits(audit_file)

    assert audits == []
