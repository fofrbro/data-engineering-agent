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
