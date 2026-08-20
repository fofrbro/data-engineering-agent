import pandas as pd

from src.audit_analysis import (
    calculate_pipeline_kpis,
    load_audit_tables,
)
from src.audit_store import append_audit


def create_test_audits(path):
    append_audit(
        {
            "run_id": "run-001",
            "source_file": "data/sales.csv",
            "contract_path": "data/contracts/sales_contract.json",
            "decision": "INGEST",
            "final_status": "SUCCESS",
            "started_at": "2026-08-19T10:00:00+00:00",
            "finished_at": "2026-08-19T10:00:05+00:00",
            "duration_seconds": 5.0,
            "error": None,
            "execution_mode": "INGEST",
            "steps": [
                {
                    "name": "validate_csv",
                    "status": "SUCCESS",
                },
                {
                    "name": "ingest_csv",
                    "status": "SKIPPED",
                },
            ],
        },
        path,
    )

    append_audit(
        {
            "run_id": "run-002",
            "source_file": "data/test_quarantine.csv",
            "contract_path": "data/contracts/sales_contract.json",
            "decision": "QUARANTINE",
            "execution_mode": "ASSESS_ONLY",
            "final_status": "QUARANTINED",
            "started_at": "2026-08-19T11:00:00+00:00",
            "finished_at": "2026-08-19T11:00:10+00:00",
            "duration_seconds": 10.0,
            "error": None,
            "steps": [
                {
                    "name": "validate_csv",
                    "status": "SUCCESS",
                },
                {
                    "name": "quarantine_csv",
                    "status": "QUARANTINED",
                },
            ],
        },
        path,
    )

    append_audit(
        {
            "run_id": "run-003",
            "source_file": "data/test_contract.csv",
            "contract_path": "data/contracts/sales_contract.json",
            "decision": "REJECT",
            "execution_mode": "ASSESS_ONLY",
            "final_status": "REJECTED",
            "started_at": "2026-08-19T12:00:00+00:00",
            "finished_at": "2026-08-19T12:00:20+00:00",
            "duration_seconds": 20.0,
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


def test_load_audit_tables(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"

    create_test_audits(audit_file)

    pipeline_runs, pipeline_steps = load_audit_tables(
        audit_file
    )

    assert isinstance(pipeline_runs, pd.DataFrame)
    assert isinstance(pipeline_steps, pd.DataFrame)

    assert len(pipeline_runs) == 3
    assert len(pipeline_steps) == 6

    assert list(pipeline_runs.columns) == [
        "run_id",
        "source_file",
        "contract_path",
        "decision",
        "execution_mode",
        "final_status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "error",
    ]


def test_calculate_pipeline_kpis():
    pipeline_runs = pd.DataFrame(
        [
            {
                "run_id": "run-001",
                "decision": "INGEST",
                "final_status": "SUCCESS",
                "duration_seconds": 5.0,
            },
            {
                "run_id": "run-002",
                "decision": "QUARANTINE",
                "final_status": "QUARANTINED",
                "duration_seconds": 10.0,
            },
            {
                "run_id": "run-003",
                "decision": "REJECT",
                "final_status": "REJECTED",
                "duration_seconds": 20.0,
            },
            {
                "run_id": "run-004",
                "decision": "INGEST",
                "final_status": "SUCCESS",
                "duration_seconds": 25.0,
            },
        ]
    )

    kpis = calculate_pipeline_kpis(
        pipeline_runs
    )

    assert kpis["total_runs"] == 4
    assert kpis["success_rate"] == 0.5
    assert kpis["quarantine_rate"] == 0.25
    assert kpis["reject_rate"] == 0.25
    assert kpis["average_duration_seconds"] == 15.0


def test_calculate_pipeline_kpis_empty():
    pipeline_runs = pd.DataFrame(
        columns=[
            "run_id",
            "decision",
            "final_status",
            "duration_seconds",
        ]
    )

    kpis = calculate_pipeline_kpis(
        pipeline_runs
    )

    assert kpis == {
        "total_runs": 0,
        "success_rate": 0.0,
        "quarantine_rate": 0.0,
        "reject_rate": 0.0,
        "average_duration_seconds": 0.0,
    }
