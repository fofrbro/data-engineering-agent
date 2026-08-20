import pandas as pd

from src.audit_report import build_observability_report
from src.audit_store import append_audit


def create_test_audits(path):
    append_audit(
        {
            "run_id": "run-001",
            "source_file": "data/sales.csv",
            "contract_path": "data/contracts/sales_contract.json",
            "decision": "INGEST",
            "execution_mode": "ASSESS_ONLY",
            "final_status": "SUCCESS",
            "started_at": "2026-08-20T10:00:00+00:00",
            "finished_at": "2026-08-20T10:00:05+00:00",
            "duration_seconds": 5.0,
            "error": None,
            "steps": [
                {
                    "name": "validate_csv",
                    "status": "SUCCESS",
                },
                {
                    "name": "validate_contract",
                    "status": "SUCCESS",
                },
            ],
        },
        path,
    )

    append_audit(
        {
            "run_id": "run-002",
            "source_file": "data/test_contract.csv",
            "contract_path": "data/contracts/sales_contract.json",
            "decision": "REJECT",
            "execution_mode": "ASSESS_ONLY",
            "final_status": "REJECTED",
            "started_at": "2026-08-20T11:00:00+00:00",
            "finished_at": "2026-08-20T11:00:10+00:00",
            "duration_seconds": 10.0,
            "error": None,
            "steps": [
                {
                    "name": "validate_contract",
                    "status": "SUCCESS",
                },
                {
                    "name": "reject_csv",
                    "status": "REJECTED",
                },
            ],
        },
        path,
    )


def test_build_observability_report(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    report = build_observability_report(
        audit_file
    )

    assert isinstance(report, dict)

    assert report["kpis"]["total_runs"] == 2
    assert report["kpis"]["assess_only_runs"] == 2
    assert report["kpis"]["ingest_runs"] == 0
    assert report["kpis"]["reject_runs"] == 1

    assert isinstance(
        report["runs"],
        pd.DataFrame,
    )

    assert len(report["runs"]) == 2

    assert isinstance(
        report["steps"],
        pd.DataFrame,
    )

    assert len(report["steps"]) == 3

    assert report["steps"]["count"].sum() == 4


def test_observability_report_filters_old_runs(
    tmp_path,
):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    append_audit(
        {
            "run_id": "old-run",
            "source_file": "data/old.csv",
            "contract_path": "data/contracts/old.json",
            "decision": "INGEST",
            "execution_mode": None,
            "final_status": "SUCCESS",
            "duration_seconds": 1.0,
            "steps": [],
        },
        audit_file,
    )

    report = build_observability_report(
        audit_file
    )

    assert report["kpis"]["total_runs"] == 2
    assert "old-run" not in set(
        report["runs"]["run_id"]
    )
