import pandas as pd

from src.fabric.incremental_load import (
    LocalLakehouse,
    load_audit_incrementally,
    select_new_runs,
)


def run(run_id, decision="INGEST"):
    return {
        "run_id": run_id,
        "source_file": "data/sales.csv",
        "contract_path": "data/contracts/sales.json",
        "decision": decision,
        "execution_mode": "ASSESS_ONLY",
        "final_status": "SUCCESS",
        "started_at": "2026-09-24T10:00:00+00:00",
        "finished_at": "2026-09-24T10:00:02+00:00",
        "duration_seconds": 2.0,
        "error": None,
    }


def steps(run_id, count=2):
    return [
        {"run_id": run_id, "step_order": order, "step_name": f"step_{order}", "status": "SUCCESS"}
        for order in range(1, count + 1)
    ]


def source(run_ids):
    runs = pd.DataFrame([run(run_id) for run_id in run_ids])
    step_rows = [row for run_id in run_ids for row in steps(run_id)]
    return runs, pd.DataFrame(step_rows)


def test_first_load_creates_tables(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)

    result = load_audit_incrementally(lakehouse, *source(["r1", "r2"]))

    assert result.inserted_runs == 2
    assert result.inserted_steps == 4
    assert len(lakehouse.read_table("pipeline_runs")) == 2


def test_five_existing_runs_plus_one_new_run_gives_six(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    load_audit_incrementally(lakehouse, *source([f"r{i}" for i in range(1, 6)]))

    result = load_audit_incrementally(
        lakehouse, *source([f"r{i}" for i in range(1, 7)])
    )

    assert result.inserted_runs == 1
    assert result.new_run_ids == ["r6"]
    assert result.inserted_steps == 2
    assert result.total_runs == 6
    assert len(lakehouse.read_table("pipeline_runs")) == 6
    assert len(lakehouse.read_table("pipeline_steps")) == 12


def test_six_runs_plus_no_new_run_stays_six(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    runs, step_rows = source([f"r{i}" for i in range(1, 7)])
    load_audit_incrementally(lakehouse, runs, step_rows)

    result = load_audit_incrementally(lakehouse, runs, step_rows)

    assert result.inserted_runs == 0
    assert result.inserted_steps == 0
    assert len(lakehouse.read_table("pipeline_runs")) == 6
    assert len(lakehouse.read_table("pipeline_steps")) == 12


def test_existing_runs_are_never_rewritten(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    load_audit_incrementally(lakehouse, *source(["r1"]))

    changed = pd.DataFrame([run("r1", decision="REJECT")])
    load_audit_incrementally(lakehouse, changed, pd.DataFrame(steps("r1")))

    assert lakehouse.read_table("pipeline_runs")["decision"].tolist() == ["INGEST"]


def test_duplicate_run_id_in_source_is_loaded_once(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    runs, step_rows = source(["r1"])

    result = load_audit_incrementally(
        lakehouse,
        pd.concat([runs, runs], ignore_index=True),
        pd.concat([step_rows, step_rows], ignore_index=True),
    )

    assert result.inserted_runs == 1
    assert result.inserted_steps == 2


def test_orphan_steps_are_ignored(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    runs, step_rows = source(["r1"])
    orphans = pd.DataFrame(steps("unknown"))

    result = load_audit_incrementally(
        lakehouse, runs, pd.concat([step_rows, orphans], ignore_index=True),
    )

    assert result.inserted_steps == 2
    assert set(lakehouse.read_table("pipeline_steps")["run_id"]) == {"r1"}


def test_interrupted_load_recovers_missing_steps(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    runs, step_rows = source(["r1"])
    # Simule un chargement interrompu : le run est présent, pas ses étapes.
    lakehouse.append("pipeline_runs", runs)

    result = load_audit_incrementally(lakehouse, runs, step_rows)

    assert result.inserted_runs == 0
    assert result.inserted_steps == 2


def test_loaded_schema_is_stable_and_utc(tmp_path):
    lakehouse = LocalLakehouse(tmp_path)
    load_audit_incrementally(lakehouse, *source(["r1"]))

    loaded = lakehouse.read_table("pipeline_runs")

    assert list(loaded.columns) == [
        "run_id", "source_file", "contract_path", "decision",
        "execution_mode", "final_status", "started_at", "finished_at",
        "duration_seconds", "error",
    ]
    assert str(loaded["started_at"].dt.tz) == "UTC"
    assert list(lakehouse.read_table("pipeline_steps").columns) == [
        "run_id", "step_order", "step_name", "status",
    ]


def test_select_new_runs_against_empty_table():
    runs, _ = source(["r1", "r2"])

    assert len(select_new_runs(runs, pd.DataFrame(columns=["run_id"]))) == 2
