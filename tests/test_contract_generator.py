import json
from datetime import datetime, timezone

import pandas as pd

from src.contract.contract_generator import (
    dataset_name_from_path,
    generate_contract,
    propose_contract_for_file,
)
from src.contract.contract_lifecycle import approve_contract, save_contract
from src.discovery.schema_profiler import profile_schema
from src.semantic.semantic_profiler import profile_semantics
from src.tools.contract_validation import validate_contract


def contract_for(frame, **kwargs):
    schema = profile_schema(frame)
    return generate_contract(
        schema,
        profile_semantics(schema),
        dataset="orders",
        **kwargs,
    )


def orders_frame(rows=12):
    return pd.DataFrame(
        {
            "order_id": range(1, rows + 1),
            "customer_id": [1, 2, 3] * (rows // 3),
            "status": ["PAID", None] * (rows // 2),
            "order_date": [f"2026-01-{day:02d}" for day in range(1, rows + 1)],
            "quantity": [1, 2, 3] * (rows // 3),
            "unit_price": [10, 20] * (rows // 2),
            "discount_rate": [0.1, 0.2] * (rows // 2),
            "margin": [-5.0, 12.5] * (rows // 2),
        }
    )


def test_dataset_name_from_path():
    assert dataset_name_from_path("data/Ventes Mars.csv") == "ventes_mars"
    assert dataset_name_from_path("data/sales.csv") == "sales"
    assert dataset_name_from_path("data/---.csv") == "dataset"


def test_contract_is_proposed_with_metadata():
    generated_at = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)

    contract = contract_for(
        orders_frame(),
        source_file="data/orders.csv",
        generated_at=generated_at,
    )

    assert contract["status"] == "PROPOSED"
    assert contract["review"] is None
    assert contract["dataset"] == "orders"
    assert contract["version"] == "1.0"
    assert contract["generated_at"] == "2026-09-24T08:00:00+00:00"
    assert contract["source_file"] == "data/orders.csv"
    assert contract["domain"]["name"] == "SALES"
    assert contract["candidate_keys"] == ["order_id"]
    assert contract["quality_rules"] == [
        {"rule": "no_duplicate_rows", "enforced_by": "validate_csv"},
    ]


def test_column_rules():
    columns = contract_for(orders_frame())["columns"]

    def core(name):
        return {
            key: value
            for key, value in columns[name].items()
            if key not in ("semantics", "rationale")
        }

    assert core("order_id") == {"type": "integer", "nullable": False, "unique": True}
    assert core("customer_id") == {"type": "integer", "nullable": False}
    assert core("status") == {"type": "string", "nullable": True}
    assert core("order_date") == {"type": "datetime", "nullable": False}
    assert core("quantity") == {"type": "integer", "nullable": False, "min": 1}
    # Prix entiers observés mais type décimal proposé.
    assert core("unit_price") == {"type": "decimal", "nullable": False, "min": 0}
    assert core("discount_rate") == {
        "type": "decimal", "nullable": False, "min": 0, "max": 1,
    }
    # Valeurs négatives observées : aucune borne inventée.
    assert core("margin") == {"type": "decimal", "nullable": False}


def test_each_rule_is_explained_and_carries_semantics():
    columns = contract_for(orders_frame())["columns"]

    for rule in columns.values():
        assert rule["rationale"]
        assert 0 < rule["semantics"]["confidence"] < 1

    assert columns["unit_price"]["semantics"]["business_role"] == "PRICE"
    assert "min=0" in " ".join(columns["unit_price"]["rationale"])


def test_duplicates_disable_no_duplicate_rule():
    frame = pd.DataFrame({"a": [1, 1], "b": ["x", "x"]})

    assert contract_for(frame)["quality_rules"] == []


def test_proposed_contract_validates_its_source_file(tmp_path):
    contract = propose_contract_for_file("data/sales.csv")
    path = save_contract(contract, tmp_path / "sales.json")

    result = validate_contract("data/sales.csv", str(path))

    assert contract["dataset"] == "sales"
    assert contract["columns"]["price"]["type"] == "decimal"
    assert contract["columns"]["quantity"]["min"] == 1
    assert result["valid"] is True
    assert result["contract_status"] == "PROPOSED"


def test_proposed_contract_detects_invalid_file(tmp_path):
    contract = approve_contract(
        propose_contract_for_file("data/sales.csv"), "cheikhou",
    )
    path = save_contract(contract, tmp_path / "sales.json")

    result = validate_contract("data/test_contract.csv", str(path))

    assert result["valid"] is False
    assert result["contract_status"] == "VALIDATED"


def test_contract_is_json_serializable():
    json.dumps(contract_for(orders_frame()))


def test_tax_column_is_a_non_negative_decimal():
    contract = contract_for(orders_frame().assign(tax_amount=[2, 4] * 6))

    rule = contract["columns"]["tax_amount"]

    assert rule["type"] == "decimal"
    assert rule["min"] == 0
    assert rule["semantics"]["business_role"] == "TAX"
