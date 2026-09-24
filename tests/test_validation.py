from src.tools.data_validation import validate_csv


def test_valid_sales_file():
    result = validate_csv("data/sales.csv")

    assert result["valid"] is True
    assert result["issues_count"] == 0
    assert result["rows"] == 5


def test_invalid_quantity():
    result = validate_csv("data/test_contract.csv") 

    assert result["valid"] is False

    quantity_issues = [
        issue
        for issue in result["issues"]
        if issue["column"] == "quantity"
    ]

    assert len(quantity_issues) == 1
    assert quantity_issues[0]["rule"] == "quantity_numeric"


def write_contract(tmp_path, columns):
    import json

    path = tmp_path / "contract.json"
    path.write_text(
        json.dumps({"dataset": "sales", "version": "1.0", "columns": columns}),
        encoding="utf-8",
    )
    return str(path)


def severities(result):
    return {issue["rule"]: issue["severity"] for issue in result["issues"]}


def test_exact_duplicates_are_warnings():
    result = validate_csv("data/test_quality.csv")

    assert result["valid"] is True
    assert result["blocking_count"] == 0
    assert result["warnings_count"] == 1
    assert severities(result) == {"no_duplicates": "WARNING"}


def test_nulls_depend_on_contract_nullability(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text(
        "customer_id,product,quantity,price,comment\n1,Laptop,2,850,\n",
        encoding="utf-8",
    )
    nullable = write_contract(tmp_path, {"comment": {"type": "string", "nullable": True}})

    without_contract = validate_csv(str(source))
    with_contract = validate_csv(str(source), nullable)

    assert without_contract["valid"] is False
    assert severities(without_contract)["no_nulls"] == "BLOCKING"
    assert with_contract["valid"] is True
    assert severities(with_contract)["no_nulls"] == "WARNING"


def test_business_rule_violations_stay_blocking(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text(
        "customer_id,product,quantity,price\n1,Laptop,0,-5\n1,Laptop,0,-5\n",
        encoding="utf-8",
    )

    result = validate_csv(str(source))

    assert result["valid"] is False
    assert severities(result) == {
        "no_duplicates": "WARNING",
        "quantity_positive": "BLOCKING",
        "price_non_negative": "BLOCKING",
    }
