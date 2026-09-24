import json

import pandas as pd
import pytest

from src.fabric.gold_export import (
    GoldExportError,
    export_gold_for_fabric,
    load_gold_from_manifest,
)
from src.fabric.incremental_load import LocalLakehouse
from src.workflow.agent_workflow import approve_plan_contract, plan_file
from src.workflow.plan_executor import ExecutionResult, execute_plan


@pytest.fixture
def executed(tmp_path):
    plan = plan_file("data/sales.csv", contracts_dir=tmp_path / "contracts")
    approve_plan_contract(plan, "cheikhou")
    result = execute_plan(
        plan, output_root=tmp_path / "lake", audit_path=tmp_path / "runs.jsonl",
    )
    return plan, result


def test_export_writes_gold_files_and_manifest(executed, tmp_path):
    plan, result = executed

    folder = export_gold_for_fabric(plan, result, tmp_path / "export")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    assert folder == tmp_path / "export" / "gold" / "sales"
    assert manifest["run_id"] == result.run_id
    assert [t["table_name"] for t in manifest["tables"]] == [
        "fact_sales", "dim_customer", "dim_product", "sales_by_product", "sales_summary",
    ]
    assert manifest["tables"][0]["rows"] == 5
    assert (folder / "sales_summary.parquet").exists()


def test_only_successful_runs_are_exported(executed, tmp_path):
    plan, result = executed
    blocked = ExecutionResult(run_id="r", final_status="QUARANTINED", decision="QUARANTINE")

    with pytest.raises(GoldExportError):
        export_gold_for_fabric(plan, blocked, tmp_path / "export")


def test_load_replaces_tables_and_logs_the_run(executed, tmp_path):
    plan, result = executed
    lakehouse = LocalLakehouse(tmp_path / "lakehouse")
    folder = export_gold_for_fabric(plan, result, tmp_path / "export")

    loaded = load_gold_from_manifest(lakehouse, folder)
    replay = load_gold_from_manifest(lakehouse, folder)

    assert loaded["status"] == "LOADED"
    assert replay["status"] == "SKIPPED"
    assert lakehouse.read_table("sales_summary")["total_sales"].iloc[0] == 3110.0
    loads = lakehouse.read_table("gold_loads")
    assert len(loads) == 5
    assert set(loads["run_id"]) == {result.run_id}


def test_new_run_replaces_previous_gold(tmp_path):
    lakehouse = LocalLakehouse(tmp_path / "lakehouse")
    source = tmp_path / "sales.csv"
    source.write_text(open("data/sales.csv", encoding="utf-8").read(), encoding="utf-8")
    plan = plan_file(str(source), contracts_dir=tmp_path / "contracts")
    approve_plan_contract(plan, "cheikhou")

    def run_and_load():
        result = execute_plan(
            plan, output_root=tmp_path / "lake", audit_path=tmp_path / "runs.jsonl",
        )
        load_gold_from_manifest(lakehouse, export_gold_for_fabric(plan, result, tmp_path / "export"))

    run_and_load()
    source.write_text(
        "customer_id,product,quantity,price\n1,Laptop,1,100\n", encoding="utf-8",
    )
    run_and_load()

    assert lakehouse.read_table("sales_summary")["total_sales"].tolist() == [100.0]
    assert len(lakehouse.read_table("gold_loads")["run_id"].unique()) == 2


def test_manifest_row_count_mismatch_is_refused(executed, tmp_path):
    plan, result = executed
    folder = export_gold_for_fabric(plan, result, tmp_path / "export")
    pd.DataFrame({"x": [1]}).to_parquet(folder / "fact_sales.parquet")

    with pytest.raises(GoldExportError):
        load_gold_from_manifest(LocalLakehouse(tmp_path / "lakehouse"), folder)
