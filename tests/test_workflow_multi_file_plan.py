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


def test_batch_is_profiled_on_admitted_files_within_the_contract(validated_contract):
    plan = plan_file(BATCH, dataset="ventes_2025_2026", contracts_dir=validated_contract)

    # Seul le fichier admis (1 500 lignes) pilote le profil.
    assert plan.profiled_files == [BATCH[0]]
    assert plan.discovery.schema.row_count == 1500
    # La colonne commentaire, hors contrat, ne pilote aucune recommandation.
    assert "commentaire" not in [c.name for c in plan.discovery.schema.columns]
    assert all(
        "commentaire" not in step.columns for step in plan.recommendation.transformations
    )


def test_proposed_contract_keeps_every_profiled_column(tmp_path):
    plan = plan_file(BATCH[:2], dataset="ventes_mix", contracts_dir=tmp_path / "contracts")

    assert plan.contract_origin == "PROPOSED"
    assert "commentaire" in plan.contract["columns"]
    assert "commentaire" in [c.name for c in plan.discovery.schema.columns]


def test_batch_preview_lists_every_file(validated_contract):
    plan = plan_file(BATCH, dataset="ventes_2025_2026", contracts_dir=validated_contract)

    preview = render_plan_preview(plan)

    assert "Fichiers : 3 (2100 lignes au total)" in preview
    assert "Profil et recommandations : 1 fichier(s) admis, 1500 lignes, 9 colonnes" in preview
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


def test_refused_files_do_not_change_the_recommended_tables(validated_contract):
    alone = plan_file(BATCH[0], dataset="ventes_2025_2026", contracts_dir=validated_contract)
    batch = plan_file(
        [BATCH[0], BATCH[2]], dataset="ventes_2025_2026", contracts_dir=validated_contract,
    )

    # ventes_rejet reprend 300 commandes : profilé avec le lot, order_id
    # ne serait plus unique et une dimension « commande » apparaîtrait.
    gold = [table.name for table in batch.recommendation.gold]
    assert gold == [table.name for table in alone.recommendation.gold]
    assert "ventes_2025_2026_dim_order" not in gold


def test_whole_batch_is_profiled_when_no_file_is_admitted_yet(tmp_path):
    plan = plan_file(BATCH[:2], dataset="ventes_mix", contracts_dir=tmp_path / "contracts")

    # Contrat proposé : aucun fichier admis, le profil couvre tout le lot.
    assert plan.profiled_files == BATCH[:2]
    assert plan.discovery.schema.row_count == 1800


def test_contract_approval_reprofiles_on_admitted_files(tmp_path):
    plan = plan_file(
        [BATCH[0], BATCH[2]], dataset="ventes_2025_2026", contracts_dir=tmp_path / "contracts",
    )
    before = plan.profiled_files

    approve_plan_contract(plan, "cheikhou")

    assert before == [BATCH[0], BATCH[2]]
    assert plan.profiled_files == [BATCH[0]]
    # Le contrat proposé sur le lot voit les quantités à -1 : il n'impose
    # pas de minimum ; c'est le contrôle qualité (quantité <= 0, bloquant)
    # qui met ventes_rejet en quarantaine.
    assert [p["decision"] for p in plan.file_previews] == ["INGEST", "QUARANTINE"]



def test_file_sharing_no_column_with_the_reused_contract_is_rejected(tmp_path):
    import shutil

    # Cas réel : l'ancien data/sales.csv, nommé « sales » lui aussi,
    # face au contrat validé Adventure Works : aucune colonne commune.
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    shutil.copy("data/contracts/sales.json", contracts / "sales.json")

    plan = plan_file("data/sales.csv", contracts_dir=contracts)

    assert plan.contract_origin == "REUSED"
    assert plan.decision_preview["decision"] == "REJECT"
    assert [c.name for c in plan.discovery.schema.columns] == [
        "customer_id", "product", "quantity", "price",
    ]
