import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.semantic.column_naming import parse_column_names
from src.workflow.agent_workflow import WorkflowError
from src.workflow.file_preparation import PreparationError, prepare_files
from src.workflow.instructions import interpret_instructions
from src.workflow.workflow_service import WorkflowService
from tests.test_file_preparation import HEADER, orders, paths, validated_contract  # noqa: F401
from tests.test_semantic_review import FakeClient


NAMES = ["code", "jour", "email", "produit", "qte", "prix"]


def answering(payload):
    """Client LLM de test qui renvoie toujours ce JSON."""

    client = FakeClient()
    client.responses.create = lambda **kwargs: SimpleNamespace(output_text=json.dumps(payload))
    return client


def instructions_payload(dataset=None, column_names=None, unsupported=None):
    return {
        "dataset": dataset,
        "column_names": column_names,
        "unsupported": unsupported,
        "message": "Application des noms demandés.",
    }


@pytest.fixture
def service(tmp_path):
    return WorkflowService(contracts_dir=tmp_path / "contracts")


def test_parse_column_names():
    assert parse_column_names("a, b; c\nd,,") == ["a", "b", "c", "d"]
    assert parse_column_names(None) == []


def test_names_are_normalized():
    assert parse_column_names("numéro de commande, e-mail, Prix unitaire (HT)") == [
        "numero_de_commande", "e_mail", "Prix_unitaire_HT",
    ]


def test_user_names_take_priority_over_the_matching_contract(orders, tmp_path):
    contracts = tmp_path / "contracts"
    validated_contract(orders, contracts)

    prepared = prepare_files(paths(orders, "2019.csv"), contracts, column_names=NAMES)[0]

    assert (prepared.header_source, prepared.note) == ("USER", "noms fournis par l'utilisateur")
    assert list(pd.read_csv(prepared.path).columns) == NAMES


def test_user_names_of_the_wrong_length_are_ignored_with_a_note(orders, tmp_path):
    prepared = prepare_files(paths(orders, "2019.csv"), tmp_path / "c", column_names=["a", "b"])[0]

    assert prepared.header_source == "GENERIC"
    assert prepared.note.endswith("noms fournis ignorés : 2 noms pour 6 colonnes")


def test_invalid_user_names_are_refused(orders, tmp_path):
    # Même normalisé, un nom doit commencer par une lettre.
    with pytest.raises(PreparationError, match="noms invalides : 2019"):
        prepare_files(paths(orders, "2019.csv"), tmp_path / "c", column_names=["2019", "b"])


def test_plan_with_proposed_names_blocks_the_contract(orders, service):
    view = service.create_plans(paths(orders, "2019.csv"))[0]

    naming = view["column_naming"]
    assert (naming["source"], naming["status"], naming["editable"]) == ("GENERIC", "PROPOSED", True)
    assert naming["samples"][0][0] == "SO2019000"
    assert "Noms de colonnes à valider, puis le contrat." in view["validation"]["blockers"]

    with pytest.raises(WorkflowError, match="noms de colonnes"):
        service.approve_contract(view["plan_id"], "cheikhou")


def test_validating_unchanged_names_unblocks_the_contract(orders, service):
    plan_id = service.create_plans(paths(orders, "2019.csv"))[0]["plan_id"]

    view = service.review_column_names(plan_id, "cheikhou")
    view = service.approve_contract(plan_id, "cheikhou")

    assert view["column_naming"]["validated_by"] == "cheikhou"
    assert view["contract_status"] == "VALIDATED"
    assert view["history"][-2]["action"] == "VALIDATE_COLUMN_NAMES"


def test_renamed_columns_rebuild_the_plan_and_its_proposed_contract(orders, service):
    view = service.create_plans(paths(orders, "2019.csv", "2020.csv"))[0]
    plan_id = view["plan_id"]
    before = json.loads(Path(view["contract_path"]).read_text(encoding="utf-8"))

    view = service.review_column_names(plan_id, "cheikhou", NAMES)

    assert view["plan_id"] == plan_id
    assert view["column_naming"]["names"] == NAMES
    assert view["column_naming"]["source"] == "USER"
    assert all(list(pd.read_csv(p["path"]).columns) == NAMES for p in view["file_preparations"])
    contract = json.loads(Path(view["contract_path"]).read_text(encoding="utf-8"))
    assert list(contract["columns"]) == NAMES
    # La sémantique suit les nouveaux noms : « qte » est une quantité.
    assert before["columns"]["column_5"]["semantics"]["business_role"] is None
    assert contract["columns"]["qte"]["semantics"]["business_role"] == "QUANTITY"
    assert view["history"][-1]["action"] == "RENAME_COLUMNS"
    assert service.approve_contract(plan_id, "cheikhou")["contract_status"] == "VALIDATED"


def test_contract_names_change_only_with_another_dataset(orders, tmp_path):
    contracts = tmp_path / "contracts"
    validated_contract(orders, contracts)
    service = WorkflowService(contracts_dir=contracts)
    view = service.create_plans(paths(orders, "2019.csv"))[0]

    assert view["column_naming"]["status"] == "VALIDATED"

    with pytest.raises(WorkflowError, match="autre nom de dataset"):
        service.review_column_names(view["plan_id"], "cheikhou", NAMES)

    view = service.review_column_names(view["plan_id"], "cheikhou", NAMES, dataset="orders_fr")

    assert (view["dataset"], view["contract_origin"], view["contract_status"]) == (
        "orders_fr", "PROPOSED", "PROPOSED",
    )


@pytest.mark.parametrize(
    "names, dataset, message",
    [
        (["a", "b"], None, "2 noms pour 6 colonnes"),
        (["a", "b", "c", "d", "e", "A"], None, "noms en double"),
        (NAMES, "Ventes AE", "Nom de dataset invalide"),
    ],
)
def test_invalid_reviews_are_refused(orders, service, names, dataset, message):
    plan_id = service.create_plans(paths(orders, "2019.csv"))[0]["plan_id"]

    with pytest.raises(WorkflowError, match=message):
        service.review_column_names(plan_id, "cheikhou", names, dataset)


def test_file_header_imposes_the_names(orders, service):
    view = service.create_plans(paths(orders, "2019.csv", "reference.csv"), dataset="orders")[0]

    assert view["column_naming"]["editable"] is False
    assert view["column_naming"]["validated_by"] == "en-tête d'un fichier du lot"

    with pytest.raises(WorkflowError, match="en-tête"):
        service.review_column_names(view["plan_id"], "cheikhou", NAMES)


def test_instructions_are_checked_before_being_applied():
    interpreted = interpret_instructions(
        answering(instructions_payload("2026 ventes", ["a", "a"], "trier par date")),
        "appelle le dataset 2026 ventes",
    )

    assert (interpreted.dataset, interpreted.column_names) == (None, None)
    assert interpreted.discarded == [
        "nom de dataset invalide : 2026_ventes", "noms de colonnes : noms en double",
    ]
    assert interpreted.unsupported == "trier par date"


def test_instructions_are_normalized():
    interpreted = interpret_instructions(
        answering(instructions_payload("Ventes AE", ["numéro de commande", "e-mail"])),
        "...",
    )

    assert interpreted.dataset == "ventes_ae"
    assert interpreted.column_names == ["numero_de_commande", "e_mail"]


def test_instructions_without_llm_are_reported_not_applied():
    interpreted = interpret_instructions(None, "colonnes : a, b")

    assert interpreted.status == "UNAVAILABLE"
    assert "non appliquées" in interpreted.error


def test_instructions_name_the_dataset_and_the_columns(orders, tmp_path):
    service = WorkflowService(
        contracts_dir=tmp_path / "contracts",
        llm_client=answering(instructions_payload("ventes_ae", NAMES)),
    )

    view = service.create_plans(paths(orders, "2019.csv"), instructions="les colonnes sont ...")[0]

    assert view["dataset"] == "ventes_ae"
    assert view["column_naming"]["names"] == NAMES
    assert view["instructions"]["message"] == "Application des noms demandés."
    assert "Instructions : les colonnes sont ..." in view["preview"]


def test_explicit_fields_win_over_instructions(orders, tmp_path):
    service = WorkflowService(
        contracts_dir=tmp_path / "contracts",
        llm_client=answering(instructions_payload("ventes_ae", NAMES)),
    )
    explicit = ["c1", "c2", "c3", "c4", "c5", "c6"]

    view = service.create_plans(
        paths(orders, "2019.csv"), dataset="ventes_explicite",
        column_names=explicit, instructions="...",
    )[0]

    assert view["dataset"] == "ventes_explicite"
    assert view["column_naming"]["names"] == explicit
