import json
from pathlib import Path

import pandas as pd
import pytest

from src.contract.contract_generator import propose_contract_for_file
from src.contract.contract_lifecycle import approve_contract, save_contract
from src.semantic.column_naming import check_naming, naming_input, value_shape
from src.workflow.file_preparation import (
    FROM_CONTRACT,
    FROM_FILE,
    FROM_LLM,
    GENERIC,
    prepare_files,
)
from src.workflow.workflow_service import WorkflowService
from tests.test_semantic_review import FakeClient


HEADER = "order_code,order_date,customer_email,product,quantity,unit_price\n"


def orders_rows(year, count=12):
    return "".join(
        f"SO{year}{i:03d},{year}-07-{i % 28 + 1:02d},client{i % 4}@exemple.com,"
        f'"Road-{i % 3}, 44",{i % 3 + 1},{10 + i}.50\n'
        for i in range(count)
    )


@pytest.fixture
def orders(tmp_path):
    """Deux fichiers sans en-tête et un fichier de référence avec en-tête."""

    folder = tmp_path / "files"
    folder.mkdir()
    for year in (2019, 2020):
        (folder / f"{year}.csv").write_text(orders_rows(year), encoding="utf-8")
    (folder / "reference.csv").write_text(HEADER + orders_rows(2018), encoding="utf-8")
    return folder


def validated_contract(orders, contracts, dataset="orders"):
    contract = propose_contract_for_file(orders / "reference.csv", dataset=dataset)
    save_contract(approve_contract(contract, "cheikhou"), contracts / f"{dataset}.json")


def paths(orders, *names):
    return [(orders / name).as_posix() for name in names]


def test_names_come_from_the_single_matching_contract(orders, tmp_path):
    contracts = tmp_path / "contracts"
    validated_contract(orders, contracts)

    prepared = prepare_files(paths(orders, "2019.csv", "2020.csv", "reference.csv"), contracts)

    assert [(p.header_source, p.dataset) for p in prepared] == [
        (FROM_CONTRACT, "orders"), (FROM_CONTRACT, "orders"), (FROM_FILE, None),
    ]
    assert prepared[2].path == prepared[2].original
    copy = pd.read_csv(prepared[0].path)
    assert list(copy.columns) == HEADER.strip().split(",")
    assert len(copy) == 12
    assert copy.iloc[0]["order_code"] == "SO2019000"


def test_cell_text_is_copied_unchanged(orders, tmp_path):
    source = orders / "2019.csv"
    source.write_text('007,2019-07-01,"a, b",1.50\n008,2019-07-02,c,2.00\n', encoding="utf-8")

    prepared = prepare_files([source.as_posix()], tmp_path / "contracts")[0]

    lines = Path(prepared.path).read_text(encoding="utf-8").splitlines()
    assert lines == [
        "column_1,column_2,column_3,column_4",
        '007,2019-07-01,"a, b",1.50',
        "008,2019-07-02,c,2.00",
    ]


def test_ambiguous_contracts_are_not_used(orders, tmp_path):
    contracts = tmp_path / "contracts"
    validated_contract(orders, contracts, "orders")
    validated_contract(orders, contracts, "orders_copy")

    prepared = prepare_files(paths(orders, "2019.csv"), contracts)[0]

    assert prepared.header_source == GENERIC


def test_llm_names_are_shared_by_files_of_the_same_structure(orders, tmp_path):
    client = FakeClient()
    names = ["OrderCode", "OrderDate", "CustomerEmail", "Product", "Quantity", "UnitPrice"]
    client.responses.create = lambda **kwargs: type(
        "R", (), {"output_text": json.dumps({"dataset": "sales_orders", "names": names})}
    )()

    prepared = prepare_files(paths(orders, "2019.csv", "2020.csv"), tmp_path / "contracts", client)

    assert {(p.header_source, p.dataset) for p in prepared} == {(FROM_LLM, "sales_orders")}
    assert all(list(pd.read_csv(p.path).columns) == names for p in prepared)


def test_invalid_llm_names_fall_back_to_generic_names(orders, tmp_path):
    client = FakeClient()
    client.responses.create = lambda **kwargs: type(
        "R", (), {"output_text": json.dumps({"dataset": None, "names": ["a", "b"]})}
    )()

    prepared = prepare_files(paths(orders, "2019.csv"), tmp_path / "contracts", client)[0]

    assert prepared.header_source == GENERIC
    assert prepared.note == "noms génériques (proposition du LLM refusée : 2 noms proposés pour 6 colonnes)"
    assert list(pd.read_csv(prepared.path).columns)[0] == "column_1"


def test_different_structures_are_named_separately(orders, tmp_path):
    (orders / "other.csv").write_text("A,1\nB,2\nC,3\n", encoding="utf-8")

    prepared = prepare_files(paths(orders, "2019.csv", "other.csv"), tmp_path / "contracts")

    assert [len(pd.read_csv(p.path).columns) for p in prepared] == [6, 2]


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"dataset": None, "names": ["a", "b"]}, None),
        ({"dataset": None, "names": ["a"]}, "1 noms proposés pour 2 colonnes"),
        ({"dataset": None, "names": ["a", "A"]}, "noms en double"),
        (
            {"dataset": None, "names": ["a", "prix unitaire"]},
            "noms invalides : prix unitaire (lettres, chiffres et _, sans espace "
            "ni accent, commençant par une lettre)",
        ),
        ({"dataset": "Ventes 2019", "names": ["a", "b"]}, "nom de dataset invalide : Ventes 2019"),
    ],
)
def test_check_naming(payload, reason):
    assert check_naming(payload, 2) == reason


def test_naming_input_hides_personal_values(orders, tmp_path):
    from src.discovery.header_detection import read_raw_delimited
    from src.workflow.file_preparation import _typed_profile

    profile = _typed_profile(read_raw_delimited(orders / "2019.csv"))
    columns = json.loads(naming_input(profile))["columns"]
    sent = json.dumps(columns)

    assert value_shape("Christy Zhu") == "Aaaaaaa Aaa"
    assert "exemple.com" not in sent
    assert "SO2019000" not in sent
    assert columns[0]["shapes"] == ["AA9999999"]
    assert columns[3]["values"] == ["Road-0, 44", "Road-1, 44", "Road-2, 44"]


def test_service_makes_one_plan_for_headerless_files(orders, tmp_path):
    contracts = tmp_path / "contracts"
    validated_contract(orders, contracts)
    service = WorkflowService(contracts_dir=contracts)

    views = service.create_plans(paths(orders, "2019.csv", "2020.csv"))

    assert len(views) == 1
    view = views[0]
    assert (view["dataset"], view["contract_origin"]) == ("orders", "REUSED")
    assert [p["decision"] for p in view["file_previews"]] == ["INGEST", "INGEST"]
    assert [p["header_source"] for p in view["file_preparations"]] == [FROM_CONTRACT] * 2
    assert "Sans en-tête :" in view["preview"]


def test_service_without_contract_nor_llm_uses_generic_names(orders, tmp_path):
    service = WorkflowService(contracts_dir=tmp_path / "contracts")

    views = service.create_plans(
        paths(orders, "2019.csv", "2020.csv"),
        display_names={(orders / "2019.csv").as_posix(): "ventes 2019.csv"},
    )

    assert len(views) == 1
    assert views[0]["dataset"] == "ventes_2019"
    assert views[0]["contract_status"] == "PROPOSED"
    contract = json.loads(Path(views[0]["contract_path"]).read_text(encoding="utf-8"))
    assert list(contract["columns"]) == [f"column_{i}" for i in range(1, 7)]
