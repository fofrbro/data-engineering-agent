from pathlib import Path

import pandas as pd

from src.tools.silver_transformation import transform_to_silver


def test_transform_to_silver(tmp_path):
    bronze_file = tmp_path / "bronze.parquet"
    silver_file = tmp_path / "silver.parquet"

    df = pd.DataFrame({
        "customer_id": [1, 2],
        "product": [" Laptop ", "Mouse"],
        "quantity": [2, 5],
        "price": [850, 25],
        "_source_file": ["sales.csv", "sales.csv"],
        "_source_hash": ["hash123", "hash123"],
        "_ingestion_timestamp": [
            "2026-08-17T09:45:34+00:00",
            "2026-08-17T09:45:34+00:00",
        ],
    })

    df.to_parquet(bronze_file, index=False)

    result = transform_to_silver(
        str(bronze_file),
        str(silver_file),
    )

    assert result["status"] == "TRANSFORMED"
    assert result["rows"] == 2

    assert Path(silver_file).exists()

    silver = pd.read_parquet(silver_file)

    assert silver["product"].tolist() == ["Laptop", "Mouse"]
    assert silver["line_amount"].tolist() == [1700, 125]

    assert "_source_hash" in silver.columns
    assert "_ingestion_timestamp" in silver.columns
