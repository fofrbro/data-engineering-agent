import json

import pandas as pd
import pytest

from src.tools.contract_validation import validate_contract
from src.tools.data_validation import validate_csv


SALES = pd.DataFrame(
    {
        "customer_id": [1, 2, 3],
        "product": ["Laptop", "Mouse", "Keyboard"],
        "quantity": [2, 5, 3],
        "price": [850.0, 25.5, 45.0],
    }
)


def write(tmp_path, fmt):
    if fmt == "parquet":
        path = tmp_path / "sales.parquet"
        SALES.to_parquet(path, index=False)
    elif fmt == "excel":
        path = tmp_path / "sales.xlsx"
        SALES.to_excel(path, index=False)
    elif fmt == "json":
        path = tmp_path / "sales.json"
        SALES.to_json(path, orient="records")
    else:
        path = tmp_path / "sales.csv"
        SALES.to_csv(path, sep=";", index=False)

    return str(path)


@pytest.fixture
def contract(tmp_path):
    path = tmp_path / "contract.json"
    path.write_text(
        json.dumps(
            {
                "dataset": "sales",
                "version": "1.0",
                "status": "VALIDATED",
                "columns": {
                    "customer_id": {"type": "integer", "nullable": False},
                    "product": {"type": "string", "nullable": False},
                    "quantity": {"type": "integer", "nullable": False, "min": 1},
                    "price": {"type": "decimal", "nullable": False, "min": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.mark.parametrize("fmt", ["parquet", "excel", "json", "semicolon_csv"])
def test_assessment_tools_accept_supported_formats(tmp_path, contract, fmt):
    path = write(tmp_path, fmt)

    assert validate_csv(path)["valid"] is True
    assert validate_contract(path, contract)["valid"] is True
