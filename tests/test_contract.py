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
