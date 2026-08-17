from pathlib import Path

import pandas as pd

from src.tools.ingestion import ingest_csv


def test_ingest_csv_and_idempotence(tmp_path, monkeypatch):
    source_file = tmp_path / "sales.csv"

    source_file.write_text(
        "customer_id,product,quantity,price\n"
        "1,Laptop,2,850\n"
        "2,Mouse,5,25\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    first_result = ingest_csv(
        str(source_file),
        "sales",
    )

    assert first_result["status"] == "INGESTED"
    assert first_result["rows"] == 2

    output_file = Path("data/bronze/sales.parquet")

    assert output_file.exists()

    df = pd.read_parquet(output_file)

    assert len(df) == 2
    assert "_source_hash" in df.columns
    assert "_ingestion_timestamp" in df.columns

    second_result = ingest_csv(
        str(source_file),
        "sales",
    )

    assert second_result["status"] == "SKIPPED"
    assert second_result["source_hash"] == first_result["source_hash"]
