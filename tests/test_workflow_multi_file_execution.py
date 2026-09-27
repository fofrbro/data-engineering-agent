import json

import pandas as pd
import pytest

from src.workflow.agent_workflow import approve_plan_contract, plan_file
from src.workflow.plan_executor import execute_plan


SAMPLES = "data/samples"
BATCH = [
    f"{SAMPLES}/ventes_2025_2026.csv",
    f"{SAMPLES}/ventes_quarantaine.csv",
    f"{SAMPLES}/ventes_rejet.csv",
]


@pytest.fixture
def workspace(tmp_path):
    contracts = tmp_path / "contracts"
    approve_plan_contract(plan_file(BATCH[0], contracts_dir=contracts), "cheikhou")
    return {
        "contracts": contracts,
        "lake": tmp_path / "lake",
        "audit": tmp_path / "runs.jsonl",
    }


def run(files, workspace):
    plan = plan_file(files, dataset="ventes_2025_2026", contracts_dir=workspace["contracts"])
    return plan, execute_plan(plan, output_root=workspace["lake"], audit_path=workspace["audit"])


def audits(workspace):
    return [json.loads(line) for line in workspace["audit"].read_text(encoding="utf-8").splitlines()]


def test_valid_files_are_ingested_and_refused_ones_isolated(workspace):
    plan, result = run(BATCH, workspace)
    lake = workspace["lake"]

    assert [(r["file"], r["decision"]) for r in result.file_results] == [
        (BATCH[0], "INGEST"), (BATCH[1], "QUARANTINE"), (BATCH[2], "REJECT"),
    ]
    assert result.final_status == "SUCCESS"
    assert plan.status == "EXECUTED"
    assert (lake / "quarantine" / "ventes_quarantaine.csv").exists()
    assert (lake / "rejected" / "ventes_rejet.csv").exists()
    # Seul le fichier admis alimente Bronze.
    assert len(pd.read_parquet(result.outputs["bronze"])) == 1500
    assert all(check["passed"] for check in result.verification)


def test_one_audited_run_per_outcome_sharing_a_batch_id(workspace):
    _, result = run(BATCH, workspace)
    logged = audits(workspace)

    assert [(a["decision"], a["final_status"]) for a in logged] == [
        ("QUARANTINE", "QUARANTINED"), ("REJECT", "REJECTED"), ("INGEST", "SUCCESS"),
    ]
    assert len({a["batch_id"] for a in logged}) == 1
    assert len({a["run_id"] for a in logged}) == 3
    assert logged[2]["run_id"] == result.run_id
    assert [r["run_id"] for r in result.file_results if r["decision"] != "INGEST"] == [
        logged[0]["run_id"], logged[1]["run_id"],
    ]


def test_several_valid_files_are_combined_in_one_run(tmp_path, workspace):
    source = pd.read_csv(BATCH[0])
    first, second = tmp_path / "ventes_t1.csv", tmp_path / "ventes_t2.xlsx"
    source.iloc[:800].to_csv(first, index=False)
    source.iloc[800:].to_excel(second, index=False)

    _, result = run([str(first), str(second)], workspace)
    combined = audits(workspace)[-1]
    summary = pd.read_parquet(result.outputs["ventes_2025_2026_summary"]).iloc[0]

    assert len(audits(workspace)) == 1
    assert combined["source_file"] == f"{first}, {second}"
    assert [s["name"] for s in combined["steps"]][:6] == [
        "validate_csv", "validate_contract", "determine_ingestion_decision",
    ] * 2
    assert combined["steps"][6]["result"]["rows_by_file"] == {str(first): 800, str(second): 700}
    # Même résultat que le fichier d'origine en un seul morceau.
    assert summary["total_sales"] == pytest.approx(811954.17)
    assert summary["number_of_lines"] == 1375


def test_batch_without_any_valid_file_is_blocked(workspace):
    plan, result = run(BATCH[1:], workspace)

    assert plan.status == "BLOCKED"
    assert result.final_status == "BLOCKED"
    assert result.decision == "PARTIAL"
    assert [r["final_status"] for r in result.file_results] == ["QUARANTINED", "REJECTED"]
    assert not (workspace["lake"] / "bronze").exists()
    assert len(audits(workspace)) == 2


def test_single_refused_file_result_is_unchanged(workspace):
    _, result = run([BATCH[2]], workspace)

    assert result.decision == "REJECT"
    assert result.final_status == "REJECTED"
    assert result.file_results[0]["decision"] == "REJECT"
