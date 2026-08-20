import pandas as pd

from src.audit_parquet import (
    export_audit_to_parquet,
    read_audit_parquet,
)
from src.audit_store import append_audit
from src.audit_parquet import (
    export_audit_to_parquet,
    normalize_run_table,
    normalize_step_table,
    read_audit_parquet,
)


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


def test_export_audit_to_parquet(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"
    runs_file = tmp_path / "pipeline_runs.parquet"
    steps_file = tmp_path / "pipeline_steps.parquet"

    create_test_audits(audit_file)

    runs_path, steps_path = export_audit_to_parquet(
        audit_file,
        runs_file,
        steps_file,
    )

    assert runs_path.exists()
    assert steps_path.exists()


def test_read_audit_parquet(tmp_path):
    audit_file = tmp_path / "pipeline_runs.jsonl"
    runs_file = tmp_path / "pipeline_runs.parquet"
    steps_file = tmp_path / "pipeline_steps.parquet"

    create_test_audits(audit_file)

    export_audit_to_parquet(
        audit_file,
        runs_file,
        steps_file,
    )

    runs, steps = read_audit_parquet(
        runs_file,
        steps_file,
    )

    assert isinstance(runs, pd.DataFrame)
    assert isinstance(steps, pd.DataFrame)

    assert len(runs) == 2
    assert len(steps) == 4

    assert set(runs["decision"]) == {
        "INGEST",
        "QUARANTINE",
    }

    assert "step_name" in steps.columns
    assert "step_order" in steps.columns


def test_export_empty_audit(tmp_path):
    audit_file = tmp_path / "empty.jsonl"
    runs_file = tmp_path / "pipeline_runs.parquet"
    steps_file = tmp_path / "pipeline_steps.parquet"

    runs_path, steps_path = export_audit_to_parquet(
        audit_file,
        runs_file,
        steps_file,
    )

    assert runs_path.exists()
    assert steps_path.exists()

    runs, steps = read_audit_parquet(
        runs_file,
        steps_file,
    )

    assert runs.empty
    assert steps.empty


def test_normalize_run_table():
    table = pd.DataFrame(
        [
            {
                "run_id": "run-001",
                "decision": "INGEST",
                "execution_mode": "ASSESS_ONLY",
                "final_status": "SUCCESS",
                "duration_seconds": "0.25",
            }
        ]
    )

    normalized = normalize_run_table(table)

    assert list(normalized.columns) == [
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

    assert str(
        normalized["run_id"].dtype
    ) == "string"

    assert normalized[
        "duration_seconds"
    ].iloc[0] == 0.25


def test_normalize_step_table():
    table = pd.DataFrame(
        [
            {
                "run_id": "run-001",
                "step_order": "1",
                "step_name": "validate_csv",
                "status": "SUCCESS",
            }
        ]
    )

    normalized = normalize_step_table(table)

    assert list(normalized.columns) == [
        "run_id",
        "step_order",
        "step_name",
        "status",
    ]

    assert normalized[
        "step_order"
    ].iloc[0] == 1
