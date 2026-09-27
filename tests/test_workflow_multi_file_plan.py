import pytest

from src.workflow.agent_workflow import (
    WorkflowError,
    approve_plan_contract,
    plan_file,
    render_plan_preview,
    validation_status,
)


SAMPLES = "data/samples"
BATCH = [
    f"{SAMPLES}/ventes_2025_2026.csv",
    f"{SAMPLES}/ventes_quarantaine.csv",
    f"{SAMPLES}/ventes_rejet.csv",
]


@pytest.fixture
def validated_contract(tmp_path):
    contracts = tmp_path / "contracts"
    approve_plan_contract(
        plan_file(BATCH[0], contracts_dir=contracts), "cheikhou",
    )
    return contracts


def test_single_file_plan_is_unchanged(tmp_path):
    plan = plan_file("data/sales.csv", contracts_dir=tmp_path)

    assert plan.file_paths == ["data/sales.csv"]
    assert plan.file_path == "data/sales.csv"
    assert len(plan.file_previews) == 1
    assert render_plan_preview(plan).splitlines()[1].startswith("Fichier : data/sales.csv")


def test_batch_plan_has_one_decision_per_file(validated_contract):
    plan = plan_file(BATCH, dataset="ventes_2025_2026", contracts_dir=validated_contract)

    assert plan.file_paths == BATCH
    assert plan.contract_origin == "REUSED"
    assert [p["decision"] for p in plan.file_previews] == ["INGEST", "QUARANTINE", "REJECT"]
    assert plan.decision_preview["decision"] == "PARTIAL"
    assert "1 INGEST, 1 QUARANTINE, 1 REJECT" in plan.decision_preview["reason"]
    assert validation_status(plan)["ready_to_execute"] is True


def test_batch_schema_is_profiled_on_all_rows(validated_contract):
    plan = plan_file(BATCH, dataset="ventes_2025_2026", contracts_dir=validated_contract)

    # 1 500 + 300 + 300 lignes ; la colonne commentaire du fichier en quarantaine.
    assert plan.discovery.schema.row_count == 2100
    assert "commentaire" in [c.name for c in plan.discovery.schema.columns]


def test_batch_preview_lists_every_file(validated_contract):
    plan = plan_file(BATCH, dataset="ventes_2025_2026", contracts_dir=validated_contract)

    preview = render_plan_preview(plan)

    assert "Fichiers : 3 (2100 lignes au total" in preview
    assert f"  - {BATCH[1]} : 300 lignes, décision prévue QUARANTINE (QUALITY_ISSUES)" in preview
    assert "Décision prévisionnelle : PARTIAL (PER_FILE)" in preview


def test_batch_with_same_decision_everywhere(validated_contract):
    plan = plan_file(
        [BATCH[0], BATCH[0]], dataset="ventes_2025_2026", contracts_dir=validated_contract,
    )

    assert plan.decision_preview["decision"] == "INGEST"
    assert plan.decision_preview["reason"] == "Même décision pour les 2 fichiers."


def test_proposed_contract_of_a_batch_names_all_sources(tmp_path):
    plan = plan_file([BATCH[0], BATCH[2]], contracts_dir=tmp_path / "contracts")

    assert plan.contract["source_file"] == f"{BATCH[0]}, {BATCH[2]}"
    assert plan.dataset == "ventes_2025_2026"


def test_empty_file_list_is_refused(tmp_path):
    with pytest.raises(WorkflowError):
        plan_file([], contracts_dir=tmp_path)
