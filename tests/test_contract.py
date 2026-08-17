from src.tools.contract_validation import validate_contract


CONTRACT = "data/contracts/sales_contract.json"


def test_valid_contract():
    result = validate_contract(
        "data/sales.csv",
        CONTRACT,
    )

    assert result["valid"] is True
    assert result["errors_count"] == 0


def test_invalid_type_contract():
    result = validate_contract(
        "data/test_contract.csv",
        CONTRACT,
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
    csv_file = tmp_path / "missing_column.csv"

    csv_file.write_text(
        "customer_id,product,quantity\n"
        "1,Laptop,2\n",
        encoding="utf-8",
    )

    result = validate_contract(
        str(csv_file),
        CONTRACT,
    )

    assert result["valid"] is False

    missing_columns = [
        error
        for error in result["errors"]
        if error["type"] == "missing_column"
    ]

    assert len(missing_columns) >= 1
    assert missing_columns[0]["column"] == "price"
