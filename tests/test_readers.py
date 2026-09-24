import pandas as pd
import pytest

import src.discovery.readers as readers
from src.discovery.errors import (
    UnreadableFileError,
    UnsupportedFormatError,
)
from src.discovery.readers import (
    DataSourceReader,
    get_reader,
    read_dataset,
    register_reader,
    supported_formats,
)


EXPECTED = pd.DataFrame(
    {
        "customer_id": [1, 2],
        "product": ["Laptop", "Mouse"],
        "price": [850.0, 25.5],
    }
)


def assert_expected(frame):
    pd.testing.assert_frame_equal(
        frame.reset_index(drop=True),
        EXPECTED,
        check_dtype=False,
    )


def test_supported_formats():
    assert supported_formats() == [
        "csv", "excel", "json", "jsonl", "parquet", "tsv",
    ]


def test_read_csv_with_semicolon(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text(
        "customer_id;product;price\n1;Laptop;850\n2;Mouse;25.5\n",
        encoding="utf-8",
    )

    file_info, format_info, frame = read_dataset(source)

    assert format_info.format == "csv"
    assert file_info.name == "sales.csv"
    assert_expected(frame)


def test_read_tsv(tmp_path):
    source = tmp_path / "sales.tsv"
    EXPECTED.to_csv(source, sep="\t", index=False)

    assert_expected(read_dataset(source)[2])


def test_read_excel(tmp_path):
    source = tmp_path / "sales.xlsx"
    EXPECTED.to_excel(source, index=False)

    assert_expected(read_dataset(source)[2])


def test_read_parquet(tmp_path):
    source = tmp_path / "sales.parquet"
    EXPECTED.to_parquet(source, index=False)

    assert_expected(read_dataset(source)[2])


def test_read_json_records_and_data_key(tmp_path):
    records = tmp_path / "records.json"
    EXPECTED.to_json(records, orient="records")
    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(
        '{"data": ' + EXPECTED.to_json(orient="records") + "}",
        encoding="utf-8",
    )

    assert_expected(read_dataset(records)[2])
    assert_expected(read_dataset(wrapped)[2])


def test_read_json_flattens_nested_objects(tmp_path):
    source = tmp_path / "nested.json"
    source.write_text(
        '[{"id": 1, "customer": {"city": "Paris"}}]',
        encoding="utf-8",
    )

    frame = read_dataset(source)[2]

    assert list(frame.columns) == ["id", "customer.city"]


def test_read_jsonl(tmp_path):
    source = tmp_path / "sales.jsonl"
    EXPECTED.to_json(source, orient="records", lines=True)

    assert_expected(read_dataset(source)[2])


def test_invalid_json_raises_unreadable(tmp_path):
    source = tmp_path / "broken.json"
    source.write_text('[{"a": 1,', encoding="utf-8")

    with pytest.raises(UnreadableFileError):
        read_dataset(source)


def test_unknown_format_has_no_reader():
    with pytest.raises(UnsupportedFormatError):
        get_reader("xml")


def test_register_custom_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "_READERS", dict(readers._READERS))

    class CustomCSVReader(DataSourceReader):
        formats = ("csv",)

        def read(self, path, format_info):
            return pd.DataFrame({"custom": [True]})

    register_reader(CustomCSVReader())
    source = tmp_path / "a.csv"
    source.write_text("a\n1\n", encoding="utf-8")

    assert list(read_dataset(source)[2].columns) == ["custom"]
