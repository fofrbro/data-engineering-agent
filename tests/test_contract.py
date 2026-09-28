from src.tools.contract_validation import validate_contract


def write_sales_contract(tmp_path):
    contract = tmp_path / "sales_test_contract.json"
    contract.write_text(
        '{"dataset": "sales", "version": "1.0", "columns": {'
        '"customer_id": {"type": "integer", "nullable": false}, '
        '"product": {"type": "string", "nullable": false}, '
        '"quantity": {"type": "integer", "nullable": false, "min": 1}, '
        '"price": {"type": "decimal", "nullable": false, "min": 0}'
        '}}',
        encoding="utf-8",
    )
    return str(contract)


def test_valid_contract(tmp_path):
    contract = write_sales_contract(tmp_path)
    result = validate_contract(
        "data/sales.csv",
        contract,
    )

    assert result["valid"] is True
    assert result["errors_count"] == 0


def test_invalid_type_contract(tmp_path):
    contract = write_sales_contract(tmp_path)
    result = validate_contract(
        "data/test_contract.csv",
        contract,
    )

    assert result["valid"] is False
    assert result["errors_count"] >= 1

    type_errors = [
        error
        for error in result["errors"]
        if error["type"] == "invalid_type"
    ]

    assert len(type_errors) >= 1
    assert type_errors[0]["column"] == "quantity"


def test_missing_column_contract(tmp_path):
    contract = write_sales_contract(tmp_path)
    csv_file = tmp_path / "missing_column.csv"

    csv_file.write_text(
        "customer_id,product,quantity\n"
        "1,Laptop,2\n",
        encoding="utf-8",
    )

    result = validate_contract(
        str(csv_file),
        contract,
    )

    assert result["valid"] is False

    missing_columns = [
        error
        for error in result["errors"]
        if error["type"] == "missing_column"
    ]

    assert len(missing_columns) >= 1
    assert missing_columns[0]["column"] == "price"


def write_json(path, payload):
    import json

    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def error_types(result):
    return sorted(error["type"] for error in result["errors"])


def test_datetime_and_boolean_types(tmp_path):
    contract = write_json(
        tmp_path / "contract.json",
        {
            "dataset": "events",
            "version": "1.0",
            "columns": {
                "created_at": {"type": "datetime", "nullable": False},
                "active": {"type": "boolean", "nullable": False},
            },
        },
    )
    valid_csv = tmp_path / "valid.csv"
    valid_csv.write_text(
        "created_at,active\n2026-01-01,True\n2026-01-02 10:00,false\n",
        encoding="utf-8",
    )
    invalid_csv = tmp_path / "invalid.csv"
    invalid_csv.write_text(
        "created_at,active\nhier,oui\n",
        encoding="utf-8",
    )

    assert validate_contract(str(valid_csv), contract)["valid"] is True
    assert error_types(
        validate_contract(str(invalid_csv), contract)
    ) == ["invalid_type", "invalid_type"]


def test_max_and_unique_rules(tmp_path):
    contract = write_json(
        tmp_path / "contract.json",
        {
            "dataset": "orders",
            "version": "1.0",
            "columns": {
                "order_id": {"type": "integer", "nullable": False, "unique": True},
                "discount_rate": {"type": "decimal", "nullable": False, "min": 0, "max": 1},
            },
        },
    )
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text(
        "order_id,discount_rate\n1,0.1\n1,1.5\n2,-0.2\n",
        encoding="utf-8",
    )

    result = validate_contract(str(csv_file), contract)

    assert error_types(result) == [
        "duplicate_values", "max_value", "min_value",
    ]


def test_unknown_type_is_still_rejected(tmp_path):
    contract = write_json(
        tmp_path / "contract.json",
        {"dataset": "x", "version": "1.0", "columns": {"a": {"type": "geometry"}}},
    )
    csv_file = tmp_path / "x.csv"
    csv_file.write_text("a\n1\n", encoding="utf-8")

    assert error_types(validate_contract(str(csv_file), contract)) == [
        "invalid_type",
    ]


def test_integers_read_as_floats_are_integers(tmp_path):
    from src.tools.contract_validation import is_type_compatible
    import pandas as pd

    # Entiers avec un vide, ou écrits « 10.0 » : lus en float par pandas.
    assert is_type_compatible(pd.Series([1, None, 3]), "integer")
    assert is_type_compatible(pd.Series([10.0, 40.0]), "integer")
    assert not is_type_compatible(pd.Series([10.5, 40.0]), "integer")


def test_proposed_contract_accepts_its_nullable_integer_source(tmp_path):
    import pandas as pd
    from src.contract.contract_generator import propose_contract_for_file
    from src.contract.contract_lifecycle import save_contract

    source = tmp_path / "stock.csv"
    pd.DataFrame(
        {"sku": [f"P{i}" for i in range(12)], "stock": [5, None, 7] * 4}
    ).to_csv(source, index=False)
    contract = save_contract(propose_contract_for_file(str(source)), tmp_path / "stock.json")

    result = validate_contract(str(source), str(contract))

    assert result["valid"] is True, result["errors"]
