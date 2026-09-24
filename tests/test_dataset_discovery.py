import json

import pandas as pd
import pytest

from src.discovery.dataset_discovery import discover_dataset
from src.discovery.errors import EmptyFileError


def test_discover_existing_sales_csv():
    result = discover_dataset("data/sales.csv")

    payload = result.to_dict()
    json.dumps(payload)

    assert payload["format"]["format"] == "csv"
    assert payload["schema"]["row_count"] == 5
    assert payload["schema"]["column_names"] == [
        "customer_id", "product", "quantity", "price",
    ]
    assert payload["schema"]["numeric_columns"] == [
        "customer_id", "quantity", "price",
    ]
    assert payload["schema"]["categorical_columns"] == ["product"]
    assert payload["schema"]["identifier_candidates"] == ["customer_id"]


def test_discover_same_data_across_formats(tmp_path):
    frame = pd.DataFrame(
        {"order_id": [1, 2], "sold_at": ["2026-01-01", "2026-01-02"]}
    )
    sources = [tmp_path / "a.csv", tmp_path / "a.xlsx", tmp_path / "a.parquet"]
    frame.to_csv(sources[0], index=False)
    frame.to_excel(sources[1], index=False)
    frame.to_parquet(sources[2], index=False)

    for source in sources:
        schema = discover_dataset(source).schema

        assert schema.row_count == 2
        assert schema.temporal_columns == ["sold_at"]
        assert schema.identifier_candidates == ["order_id"]


def test_discover_header_only_csv(tmp_path):
    source = tmp_path / "header_only.csv"
    source.write_text("id,name\n", encoding="utf-8")

    schema = discover_dataset(source).schema

    assert schema.row_count == 0
    assert schema.column_count == 2


def test_discover_empty_file(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_bytes(b"")

    with pytest.raises(EmptyFileError):
        discover_dataset(source)
