import json

import pandas as pd
import pytest

from src.audit_explain import explain_run
from src.execution.silver_executor import SilverResult
from src.workflow.agent_workflow import (
    WorkflowError,
    approve_destructive_transformations,
    approve_plan_contract,
    plan_file,
)
from src.workflow.plan_executor import execute_plan, verify_outputs


@pytest.fixture
def workspace(tmp_path):
    return {
        "contracts_dir": tmp_path / "contracts",
        "output_root": tmp_path / "lake",
        "audit_path": tmp_path / "audit" / "runs.jsonl",
    }


def validated_plan(path, workspace):
    plan = plan_file(path, contracts_dir=workspace["contracts_dir"])
    approve_plan_contract(plan, "cheikhou")
    return plan


def execute(plan, workspace):
    return execute_plan(
        plan,
        output_root=workspace["output_root"],
        audit_path=workspace["audit_path"],
    )


def read_audits(workspace):
    return [
        json.loads(line)
        for line in workspace["audit_path"].read_text(encoding="utf-8").splitlines()
    ]


def test_unvalidated_plan_is_not_executed(workspace):
    plan = plan_file("data/sales.csv", contracts_dir=workspace["contracts_dir"])

    with pytest.raises(WorkflowError):
        execute(plan, workspace)

    assert not workspace["output_root"].exists()
    assert not workspace["audit_path"].exists()


def test_sales_file_end_to_end(workspace):
    plan = validated_plan("data/sales.csv", workspace)

    result = execute(plan, workspace)
    lake = workspace["output_root"]

    assert result.final_status == "SUCCESS"
    assert result.decision == "INGEST"
    assert plan.status == "EXECUTED"
    assert (lake / "bronze" / "sales_raw.parquet").exists()
    assert (lake / "silver" / "sales_clean.parquet").exists()
    assert pd.read_parquet(lake / "gold" / "sales_summary.parquet")[
        "total_sales"
    ].iloc[0] == 3110.0
    assert all(check["passed"] for check in result.verification)
    assert {c["check"] for c in result.verification} >= {
        "file:bronze", "file:silver", "row_reconciliation",
        "total:sales_by_product.total_sales",
    }


def test_run_is_audited_and_explainable(workspace):
    result = execute(validated_plan("data/sales.csv", workspace), workspace)

    audit = read_audits(workspace)[-1]
    explanation = explain_run(result.run_id, workspace["audit_path"])

    assert audit["execution_mode"] == "INGEST"
    assert audit["policy_rule"] == "ALL_CHECKS_PASSED"
    assert [step["name"] for step in audit["steps"]] == [
        "validate_csv", "validate_contract", "determine_ingestion_decision",
        "write_bronze", "transform_silver", "build_gold", "verify_outputs",
    ]
    assert all(step["duration_seconds"] is not None for step in audit["steps"])
    assert {output["layer"] for output in audit["outputs"]} == {"bronze", "silver", "gold"}
    assert explanation["meaning"].endswith("réellement été demandée.")
    assert "Sorties : bronze :" in result.explanation


def test_decision_is_recomputed_at_execution(tmp_path, workspace):
    source = tmp_path / "sales.csv"
    source.write_text(open("data/sales.csv", encoding="utf-8").read(), encoding="utf-8")
    plan = validated_plan(str(source), workspace)
    assert plan.decision_preview["decision"] == "INGEST"

    # Le fichier change entre la validation et l'exécution.
    source.write_text(
        "customer_id,product,quantity,price\n1,Laptop,-2,850\n",
        encoding="utf-8",
    )
    result = execute(plan, workspace)

    assert result.decision == "REJECT"
    assert result.final_status == "REJECTED"
    assert plan.status == "BLOCKED"
    assert (workspace["output_root"] / "rejected" / "sales.csv").exists()
    assert not (workspace["output_root"] / "silver").exists()
    assert read_audits(workspace)[-1]["steps"][-1]["name"] == "reject_file"


def test_destructive_steps_follow_approval(tmp_path, workspace):
    # Doublon exact et statut nul sur une colonne nullable :
    # avertissements qualité, le fichier est ingéré et corrigé en Silver.
    path = tmp_path / "orders.csv"
    frame = pd.DataFrame(
        {"order_id": [1, 2, 3], "status": ["paid", None, "paid"], "amount": [10.0, 20.0, 30.0]}
    )
    pd.concat([frame, frame.iloc[[0]]]).to_csv(path, index=False)

    plan = validated_plan(str(path), workspace)
    skipped = execute(plan, workspace)
    silver_skipped = pd.read_parquet(skipped.outputs["silver"])

    approve_destructive_transformations(plan, "cheikhou")
    applied = execute(plan, workspace)
    silver_applied = pd.read_parquet(applied.outputs["silver"])

    assert skipped.decision == "INGEST"
    assert read_audits(workspace)[0]["policy_rule"] == "PASSED_WITH_WARNINGS"
    assert len(silver_skipped) == 4
    assert silver_skipped["status"].isna().sum() == 1
    assert len(silver_applied) == 3
    assert silver_applied["status"].tolist() == ["PAID", "UNKNOWN", "PAID"]
    assert all(check["passed"] for check in applied.verification)


def test_failing_step_is_audited_then_raised(workspace, monkeypatch):
    import src.workflow.plan_executor as executor

    plan = validated_plan("data/sales.csv", workspace)

    def broken(*args, **kwargs):
        raise RuntimeError("disque plein")

    monkeypatch.setattr(executor, "build_gold_tables", broken)

    with pytest.raises(RuntimeError):
        execute(plan, workspace)

    audit = read_audits(workspace)[-1]

    assert plan.status == "FAILED"
    assert audit["final_status"] == "FAILED"
    assert audit["steps"][-1]["name"] == "build_gold"
    assert audit["steps"][-1]["error"] == "disque plein"


def test_verification_detects_inconsistent_gold(workspace):
    plan = validated_plan("data/sales.csv", workspace)
    result = execute(plan, workspace)


    silver = pd.read_parquet(result.outputs["silver"])
    gold = {
        name: pd.read_parquet(result.outputs[name])
        for name in ("fact_sales", "sales_dim_customer", "sales_dim_product", "sales_by_product", "sales_summary")
    }
    gold["sales_summary"]["total_sales"] = 0.0

    verification = verify_outputs(
        plan,
        pd.read_parquet(result.outputs["bronze"]),
        SilverResult(silver, silver.iloc[0:0], []),
        gold,
        {},
    )
    failed = [c["check"] for c in verification["checks"] if not c["passed"]]

    assert verification["status"] == "FAILED"
    assert failed == ["total:sales_summary.total_sales"]
