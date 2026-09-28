import json

import pytest

from src.recommendation.dashboard_review import DashboardReviewError
from src.workflow.agent_workflow import WorkflowError
from src.workflow.workflow_service import WorkflowService


@pytest.fixture
def service(tmp_path):
    return WorkflowService(
        contracts_dir=tmp_path / "contracts",
        output_root=tmp_path / "lake",
        audit_path=tmp_path / "runs.jsonl",
        fabric_export_root=tmp_path / "fabric_export",
        results_dir=tmp_path / "results",
    )


def test_full_workflow_through_the_service(service):
    view = service.create_plan("data/sales.csv")
    plan_id = view["plan_id"]

    assert view["contract_status"] == "PROPOSED"
    assert view["validation"]["ready_to_execute"] is False
    assert view["preview"].startswith("AGENT PLAN")

    with pytest.raises(WorkflowError):
        service.execute(plan_id)

    service.approve_contract(plan_id, "cheikhou")
    service.review_dashboard(plan_id, "APPROVE", "cheikhou")
    result = service.execute(plan_id)

    assert result["final_status"] == "SUCCESS"
    assert result["decision"] == "INGEST"
    assert result["fabric_export"].endswith("fabric_export/gold/sales")
    assert "sales" in result["analysis_report"]
    assert result["analysis_files"]["text"].endswith("results/sales_analysis.txt")
    assert result["analysis_error"] is None
    assert service.view(plan_id)["status"] == "EXECUTED"
    assert [entry["action"] for entry in service.view(plan_id)["history"]] == [
        "APPROVE_CONTRACT", "APPROVE_DASHBOARD",
    ]


def test_views_are_json_serializable(service):
    view = service.create_plan("data/sales.csv")
    service.approve_contract(view["plan_id"], "cheikhou")

    json.dumps(service.view(view["plan_id"]))
    json.dumps(service.execute(view["plan_id"]))


def test_dashboard_modify_and_reject(service):
    plan_id = service.create_plan("data/sales.csv")["plan_id"]

    modified = service.review_dashboard(
        plan_id, "MODIFY", "cheikhou", changes={"title": "Ventes"},
    )
    rejected = service.review_dashboard(plan_id, "REJECT", "cheikhou", comment="Inutile")

    assert modified["dashboard"]["title"] == "Ventes"
    assert rejected["dashboard"]["status"] == "REJECTED"

    with pytest.raises(DashboardReviewError):
        service.review_dashboard(plan_id, "PUBLISH", "cheikhou")


def test_unknown_plan(service):
    with pytest.raises(KeyError):
        service.view("missing")


def test_analysis_failure_does_not_change_the_run_result(service, monkeypatch):
    import src.workflow.workflow_service as module

    def broken(*args, **kwargs):
        raise RuntimeError("analyse impossible")

    monkeypatch.setattr(module, "analyze_business_data", broken)
    plan_id = service.create_plan("data/sales.csv")["plan_id"]
    service.approve_contract(plan_id, "cheikhou")

    result = service.execute(plan_id)

    assert result["final_status"] == "SUCCESS"
    assert result["analysis_report"] is None
    assert result["analysis_error"] == "analyse impossible"


def test_second_file_of_a_dataset_runs_without_new_contract_approval(service):
    first = service.create_plan("data/sales.csv")["plan_id"]
    service.approve_contract(first, "cheikhou")
    service.execute(first)

    second = service.create_plan("data/sales.csv")

    assert second["contract_origin"] == "REUSED"
    assert service.execute(second["plan_id"])["final_status"] == "SUCCESS"


def test_create_plans_makes_one_plan_per_dataset(service, tmp_path):
    uploaded_sales = tmp_path / "a1_sales.csv"
    uploaded_sales.write_text(open("data/sales.csv", encoding="utf-8").read(), encoding="utf-8")

    views = service.create_plans(
        ["data/samples/ventes_2025_2026.csv", str(uploaded_sales), "data/samples/ventes_rejet.csv"],
        display_names={str(uploaded_sales): "sales.csv"},
    )

    assert [(v["dataset"], len(v["files"])) for v in views] == [
        ("ventes_2025_2026", 2), ("sales", 1),
    ]
    assert [p["decision"] for p in views[0]["file_previews"]] == ["QUARANTINE", "QUARANTINE"]


def test_create_plans_with_dataset_name_and_duplicate_names(service, tmp_path):
    other = tmp_path / "sales.xlsx"
    import pandas as pd
    pd.DataFrame({"code": ["A"], "label": ["x"]}).to_excel(other, index=False)

    single = service.create_plans(
        ["data/sales.csv", "data/sales.csv"], dataset="lot_ventes",
    )
    split = service.create_plans(["data/sales.csv", str(other)])

    assert [v["dataset"] for v in single] == ["lot_ventes"]
    assert [v["dataset"] for v in split] == ["sales", "sales_2"]


def test_execute_reports_each_file(service):
    first = service.create_plans(["data/samples/ventes_2025_2026.csv"])[0]["plan_id"]
    service.approve_contract(first, "cheikhou")

    view = service.create_plans(
        ["data/samples/ventes_2025_2026.csv", "data/samples/ventes_rejet.csv"],
        dataset="ventes_2025_2026",
    )[0]
    result = service.execute(view["plan_id"])

    assert [(r["decision"], r["final_status"]) for r in result["file_results"]] == [
        ("INGEST", "SUCCESS"), ("REJECT", "REJECTED"),
    ]
    assert result["fabric_export"].endswith("fabric_export/gold/ventes_2025_2026")


def test_execute_exports_every_audited_run_for_fabric(service):
    import pandas as pd

    first = service.create_plans(["data/samples/ventes_2025_2026.csv"])[0]["plan_id"]
    service.approve_contract(first, "cheikhou")

    view = service.create_plans(
        ["data/samples/ventes_2025_2026.csv", "data/samples/ventes_rejet.csv"],
        dataset="ventes_2025_2026",
    )[0]
    result = service.execute(view["plan_id"])

    assert result["audit_export_error"] is None
    assert result["audit_export"]["runs"].endswith("fabric_export/audit/pipeline_runs_structured.parquet")
    runs = pd.read_parquet(result["audit_export"]["runs"])
    steps = pd.read_parquet(result["audit_export"]["steps"])
    # Le run refusé est exporté comme le run ingéré.
    run_ids = {r["run_id"] for r in result["file_results"]}
    assert run_ids <= set(runs["run_id"])
    assert run_ids <= set(steps["run_id"])


def test_audit_export_failure_does_not_change_the_run_result(service, monkeypatch):
    import src.workflow.workflow_service as module

    def broken(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr(module, "export_structured_audit_to_parquet", broken)
    plan_id = service.create_plan("data/sales.csv")["plan_id"]
    service.approve_contract(plan_id, "cheikhou")

    result = service.execute(plan_id)

    assert result["final_status"] == "SUCCESS"
    assert result["audit_export"] is None
    assert result["audit_export_error"] == "disque plein"


def test_analysis_matches_gold_and_the_business_rule(service):
    import pandas as pd

    plan_id = service.create_plans(["data/samples/ventes_2025_2026.csv"])[0]["plan_id"]
    service.approve_contract(plan_id, "cheikhou")

    result = service.execute(plan_id)
    analysis = result["analysis"]
    summary = pd.read_parquet(f"{result['fabric_export']}/ventes_2025_2026_summary.parquet")
    revenue = next(k["value"] for k in analysis["kpis"] if k["name"] == "Revenue")

    # Mêmes chiffres que Gold (annulations exclues) : 811 954,17 sur 1 375 lignes.
    assert revenue == pytest.approx(summary["total_sales"].iloc[0])
    assert analysis["overview"]["analysed_rows"] == summary["number_of_lines"].iloc[0]
    assert analysis["overview"]["exclusion"] == "status : CANCELLED"
    assert analysis["commentary"]["status"] == "UNAVAILABLE"
    assert all(check["passed"] for check in analysis["quality"]["checks"])


def test_gold_export_failure_does_not_change_the_run_result(service, monkeypatch):
    import src.workflow.workflow_service as module

    def broken(*args, **kwargs):
        raise FileNotFoundError("chemin trop long")

    monkeypatch.setattr(module, "export_gold_for_fabric", broken)
    plan_id = service.create_plan("data/sales.csv")["plan_id"]
    service.approve_contract(plan_id, "cheikhou")

    result = service.execute(plan_id)

    assert result["final_status"] == "SUCCESS"
    assert result["fabric_export"] is None
    assert result["fabric_export_error"] == "Export Fabric impossible : chemin trop long"
    assert result["analysis"] is not None
