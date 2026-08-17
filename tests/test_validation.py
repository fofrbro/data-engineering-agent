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
