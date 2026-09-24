import pandas as pd
import pytest

from src.discovery.errors import (
    EmptyFileError,
    UnsupportedFormatError,
)
from src.discovery.file_detector import detect_file
from src.discovery.format_detector import detect_format


def detect(path):
    return detect_format(detect_file(path))


def test_csv_with_comma(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text("id,product\n1,Laptop\n", encoding="utf-8")

    result = detect(source)

    assert result.format == "csv"
    assert result.detected_by == "extension"
    assert result.delimiter == ","


def test_csv_with_semicolon(tmp_path):
    source = tmp_path / "ventes.csv"
    source.write_text("id;produit\n1;Laptop\n2;Mouse\n", encoding="utf-8")

    assert detect(source).delimiter == ";"


def test_tsv_extension(tmp_path):
    source = tmp_path / "data.tsv"
    source.write_text("a\tb\n1\t2\n", encoding="utf-8")

    result = detect(source)

    assert result.format == "tsv"
    assert result.delimiter == "\t"


def test_json_and_jsonl_extensions(tmp_path):
    json_file = tmp_path / "data.json"
    json_file.write_text('[{"a": 1}]', encoding="utf-8")
    jsonl_file = tmp_path / "data.jsonl"
    jsonl_file.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")

    assert detect(json_file).format == "json"
    assert detect(jsonl_file).format == "jsonl"


def test_parquet_detected_by_signature(tmp_path):
    source = tmp_path / "data.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(source)

    result = detect(source)

    assert result.format == "parquet"
    assert result.detected_by == "signature"


def test_excel_detected_by_signature(tmp_path):
    source = tmp_path / "data.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(source, index=False)

    assert detect(source).format == "excel"


def test_signature_wins_over_misleading_extension(tmp_path):
    source = tmp_path / "actually_parquet.csv"
    pd.DataFrame({"a": [1]}).to_parquet(source)

    assert detect(source).format == "parquet"


def test_binary_extension_without_signature_is_rejected(tmp_path):
    source = tmp_path / "fake.parquet"
    source.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        detect(source)


def test_unknown_extension_detected_from_content(tmp_path):
    delimited = tmp_path / "export.txt"
    delimited.write_text("a;b\n1;2\n3;4\n", encoding="utf-8")
    json_like = tmp_path / "payload.dat"
    json_like.write_text('{"a": 1}', encoding="utf-8")
    jsonl_like = tmp_path / "events.log"
    jsonl_like.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")

    assert detect(delimited).format == "csv"
    assert detect(delimited).delimiter == ";"
    assert detect(delimited).detected_by == "content"
    assert detect(json_like).format == "json"
    assert detect(jsonl_like).format == "jsonl"


def test_empty_file_is_rejected(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_bytes(b"")

    with pytest.raises(EmptyFileError):
        detect(source)


def test_unrecognized_content_is_rejected(tmp_path):
    source = tmp_path / "notes.bin"
    source.write_text("juste une phrase", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        detect(source)
