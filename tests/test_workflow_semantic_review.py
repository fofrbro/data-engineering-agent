import json
from pathlib import Path

import pytest

from src.workflow.agent_workflow import (
    WorkflowError,
    approve_plan_contract,
    decide_semantic_suggestions,
    plan_file,
    review_plan_semantics,
)
from src.workflow.workflow_service import WorkflowService
from tests.test_semantic_review import FakeClient, sales_frame, suggestion


NET_VALUE_IS_AMOUNT = suggestion("net_value", "MEASURE", "AMOUNT", "Valeur nette de la ligne.")
STATUS_IS_CATEGORY = suggestion("status", "DIMENSION", "CATEGORY")


@pytest.fixture
def sales_file(tmp_path):
    path = tmp_path / "ventes_nettes.csv"
    sales_frame().to_csv(path, index=False)
    return path.as_posix()


def reviewed_plan(sales_file, tmp_path, suggestions):
    plan = plan_file(sales_file, contracts_dir=tmp_path / "contracts")
    return review_plan_semantics(plan, FakeClient(suggestions))


def revenue(plan):
    return plan.kpis.kpi("Revenue").formula


def test_review_applies_nothing_before_a_decision(sales_file, tmp_path):
    plan = reviewed_plan(sales_file, tmp_path, [NET_VALUE_IS_AMOUNT])

    assert [s.status for s in plan.semantic_review.suggestions] == ["PROPOSED"]
    assert plan.semantic_overrides == {}
    assert revenue(plan) == "SUM(quantity * unit_price)"
    assert plan.history[-1]["action"] == "SEMANTIC_REVIEW"


def test_accepted_suggestion_changes_kpis_and_proposed_contract(sales_file, tmp_path):
    plan = reviewed_plan(sales_file, tmp_path, [NET_VALUE_IS_AMOUNT, STATUS_IS_CATEGORY])

    decide_semantic_suggestions(plan, "cheikhou", ["s1"])

    assert [s.status for s in plan.semantic_review.suggestions] == ["ACCEPTED", "REJECTED"]
    assert revenue(plan) == "SUM(net_value)"
    assert plan.semantics.column("status").business_role == "STATUS"
    saved = json.loads(Path(plan.contract_path).read_text(encoding="utf-8"))
    assert saved["status"] == "PROPOSED"
    assert saved["columns"]["net_value"]["semantics"]["business_role"] == "AMOUNT"
    assert saved["columns"]["net_value"]["min"] == 0
    assert plan.history[-1]["comment"] == "1 acceptée(s) sur 2."


def test_accepted_roles_survive_contract_approval(sales_file, tmp_path):
    plan = reviewed_plan(sales_file, tmp_path, [NET_VALUE_IS_AMOUNT])
    decide_semantic_suggestions(plan, "cheikhou", ["s1"])

    approve_plan_contract(plan, "cheikhou")

    assert plan.contract["columns"]["net_value"]["semantics"]["business_role"] == "AMOUNT"
    assert revenue(plan) == "SUM(net_value)"


def test_validated_contract_is_never_modified(sales_file, tmp_path):
    contracts = tmp_path / "contracts"
    approve_plan_contract(plan_file(sales_file, contracts_dir=contracts), "cheikhou")
    validated = contracts / "ventes_nettes.json"
    before = validated.read_text(encoding="utf-8")

    plan = review_plan_semantics(
        plan_file(sales_file, contracts_dir=contracts), FakeClient([NET_VALUE_IS_AMOUNT]),
    )
    decide_semantic_suggestions(plan, "cheikhou", ["s1"])

    assert plan.contract_origin == "REUSED"
    assert validated.read_text(encoding="utf-8") == before
    assert revenue(plan) == "SUM(net_value)"
    assert plan.history[-1]["comment"] == "1 acceptée(s) sur 1 ; contrat validé inchangé."


def test_decision_errors(sales_file, tmp_path):
    plan = plan_file(sales_file, contracts_dir=tmp_path / "contracts")

    with pytest.raises(WorkflowError, match="Aucune relecture"):
        decide_semantic_suggestions(plan, "cheikhou", [])

    review_plan_semantics(plan, FakeClient([NET_VALUE_IS_AMOUNT]))

    with pytest.raises(WorkflowError, match="relecteur"):
        decide_semantic_suggestions(plan, " ", ["s1"])

    with pytest.raises(WorkflowError, match="inconnues : s9"):
        decide_semantic_suggestions(plan, "cheikhou", ["s9"])

    decide_semantic_suggestions(plan, "cheikhou", [])

    with pytest.raises(WorkflowError, match="déjà décidées"):
        decide_semantic_suggestions(plan, "cheikhou", ["s1"])


def test_unavailable_review_cannot_be_decided(sales_file, tmp_path):
    plan = plan_file(sales_file, contracts_dir=tmp_path / "contracts")
    review_plan_semantics(plan, None)

    assert plan.semantic_review.status == "UNAVAILABLE"

    with pytest.raises(WorkflowError):
        decide_semantic_suggestions(plan, "cheikhou", [])


def test_service_without_llm_still_executes(sales_file, tmp_path):
    service = WorkflowService(
        contracts_dir=tmp_path / "contracts",
        output_root=tmp_path / "lake",
        audit_path=tmp_path / "runs.jsonl",
        fabric_export_root=tmp_path / "fabric_export",
        results_dir=tmp_path / "results",
    )
    plan_id = service.create_plan(sales_file)["plan_id"]

    view = service.review_semantics(plan_id)
    service.approve_contract(plan_id, "cheikhou")

    assert view["semantic_review"]["status"] == "UNAVAILABLE"
    assert service.execute(plan_id)["final_status"] == "SUCCESS"


def test_service_review_and_decision_are_serializable(sales_file, tmp_path):
    service = WorkflowService(
        contracts_dir=tmp_path / "contracts",
        llm_client=FakeClient([NET_VALUE_IS_AMOUNT]),
    )
    plan_id = service.create_plan(sales_file)["plan_id"]

    service.review_semantics(plan_id)
    view = service.decide_semantics(plan_id, "cheikhou", ["s1"])

    json.dumps(view)
    assert view["semantic_review"]["suggestions"][0]["status"] == "ACCEPTED"
    assert view["semantic_overrides"]["net_value"]["accepted_by"] == "cheikhou"
