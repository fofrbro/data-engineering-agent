import json

import pandas as pd
import pytest

from src.workflow.agent_workflow import (
    WorkflowError,
    approve_destructive_transformations,
    approve_plan_contract,
    approve_plan_dashboard,
    plan_file,
    render_plan_preview,
    validation_status,
)


@pytest.fixture
def contracts_dir(tmp_path):
    return tmp_path / "contracts"


def orders_file(tmp_path):
    path = tmp_path / "orders.xlsx"
    frame = pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4],
            "status": ["paid", None, "paid", "shipped"],
            "quantity": [1, 2, 3, 1],
            "price": [10.0, 20.0, 30.0, 10.0],
        }
    )
    pd.concat([frame, frame.iloc[[0]]]).to_excel(path, index=False)
    return str(path)


def test_plan_without_contract_proposes_one_and_is_not_ready(contracts_dir):
    plan = plan_file("data/sales.csv", contracts_dir=contracts_dir)
    status = validation_status(plan)

    assert plan.dataset == "sales"
    assert plan.contract_status == "PROPOSED"
    assert plan.contract_path.endswith("contracts/proposed/sales.json")
    assert plan.decision_preview["decision"] == "QUARANTINE"
    assert plan.decision_preview["policy_rule"] == "CONTRACT_NOT_VALIDATED"
    assert plan.recommendation.status == "PROPOSED"
    assert plan.dashboard.status == "PROPOSED"
    assert status["ready_to_execute"] is False
    assert "Contrat PROPOSED" in status["blockers"][0]


def test_contract_approval_makes_plan_ready(contracts_dir):
    plan = plan_file("data/sales.csv", contracts_dir=contracts_dir)

    approve_plan_contract(plan, "cheikhou", "Contrat relu")

    assert plan.contract_status == "VALIDATED"
    assert plan.contract_path.endswith("contracts/sales.json")
    assert plan.decision_preview["decision"] == "INGEST"
    assert plan.recommendation.contract_status == "VALIDATED"
    assert validation_status(plan)["ready_to_execute"] is True
    assert plan.history[0]["action"] == "APPROVE_CONTRACT"

    with pytest.raises(WorkflowError):
        approve_plan_contract(plan, "cheikhou")


def test_plan_with_validated_contract_file(contracts_dir):
    first = plan_file("data/sales.csv", contracts_dir=contracts_dir)
    approve_plan_contract(first, "cheikhou")

    plan = plan_file(
        "data/sales.csv",
        contract_path=first.contract_path,
        contracts_dir=contracts_dir,
    )

    assert plan.contract_status == "VALIDATED"
    assert validation_status(plan)["ready_to_execute"] is True


def test_destructive_transformations_need_explicit_approval(tmp_path, contracts_dir):
    plan = plan_file(orders_file(tmp_path), contracts_dir=contracts_dir)
    approve_plan_contract(plan, "cheikhou")

    before = validation_status(plan)
    approve_destructive_transformations(plan, "cheikhou")
    after = validation_status(plan)

    assert before["destructive_transformations"] == [
        "fill_null_dimensions", "deduplicate_rows",
    ]
    assert before["skipped_if_not_approved"] == before["destructive_transformations"]
    assert after["destructive_approved"] is True
    assert after["skipped_if_not_approved"] == []


def test_nothing_destructive_to_approve(contracts_dir):
    plan = plan_file("data/sales.csv", contracts_dir=contracts_dir)

    with pytest.raises(WorkflowError):
        approve_destructive_transformations(plan, "cheikhou")


def test_reviewer_is_required(contracts_dir):
    plan = plan_file("data/sales.csv", contracts_dir=contracts_dir)

    with pytest.raises(WorkflowError):
        approve_plan_contract(plan, " ")


def test_dashboard_approval_is_separate(contracts_dir):
    plan = plan_file("data/sales.csv", contracts_dir=contracts_dir)

    approve_plan_dashboard(plan, "cheikhou")

    assert validation_status(plan)["dashboard_approved"] is True
    assert validation_status(plan)["ready_to_execute"] is False


def test_preview_lists_everything_to_validate(tmp_path, contracts_dir):
    plan = plan_file(orders_file(tmp_path), contracts_dir=contracts_dir)

    preview = render_plan_preview(plan)

    assert preview.startswith("AGENT PLAN")
    assert "(excel, 5 lignes, 4 colonnes)" in preview
    assert "Décision prévisionnelle : QUARANTINE (CONTRACT_NOT_VALIDATED)" in preview
    assert "  - deduplicate_rows : Supprimer les lignes strictement identiques. [DESTRUCTIVE - validation requise]" in preview
    assert "DASHBOARD PLAN" in preview
    assert "  - contrat : À VALIDER" in preview
    assert preview.endswith("Prêt à exécuter : non")


def test_proposed_contract_is_saved_for_review(contracts_dir):
    plan = plan_file("data/sales.csv", contracts_dir=contracts_dir)

    saved = json.loads(open(plan.contract_path, encoding="utf-8").read())

    assert saved["status"] == "PROPOSED"


def test_quality_warnings_show_whether_they_will_be_corrected(tmp_path, contracts_dir):
    plan = plan_file(orders_file(tmp_path), contracts_dir=contracts_dir)
    approve_plan_contract(plan, "cheikhou")

    before = validation_status(plan)
    preview_before = render_plan_preview(plan)
    approve_destructive_transformations(plan, "cheikhou")
    after = validation_status(plan)

    assert plan.decision_preview["policy_rule"] == "PASSED_WITH_WARNINGS"
    assert {(w["rule"], w["correction"]) for w in before["quality_warnings"]} == {
        ("no_nulls", "fill_null_dimensions"),
        ("no_duplicates", "deduplicate_rows"),
    }
    assert len(before["uncorrected_warnings"]) == 2
    assert "NON CORRIGÉ : approuver deduplicate_rows" in preview_before
    assert after["uncorrected_warnings"] == []
    assert "corrigé par deduplicate_rows" in render_plan_preview(plan)


def test_null_measure_warning_is_not_marked_corrected(tmp_path, contracts_dir):
    path = tmp_path / "orders.csv"
    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "status": ["paid", None, "paid"],
            "amount": [10.0, None, 30.0],
        }
    ).to_csv(path, index=False)

    plan = plan_file(str(path), contracts_dir=contracts_dir)
    approve_plan_contract(plan, "cheikhou")
    approve_destructive_transformations(plan, "cheikhou")
    warnings = {w["column"]: w for w in validation_status(plan)["quality_warnings"]}

    assert warnings["status"]["corrected"] is True
    # Une mesure nulle n'est jamais imputée.
    assert warnings["amount"]["correction"] is None
    assert warnings["amount"]["corrected"] is False
