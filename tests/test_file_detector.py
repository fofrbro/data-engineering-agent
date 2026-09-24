import pytest

from src.discovery.file_detector import detect_file


def test_detect_file_returns_physical_information(tmp_path):
    source = tmp_path / "Sales.CSV"
    source.write_text("a,b\n1,2\n", encoding="utf-8")

    info = detect_file(source)

    assert info.name == "Sales.CSV"
    assert info.extension == ".csv"
    assert info.size_bytes == source.stat().st_size
    assert info.is_empty is False
    assert info.to_dict()["is_empty"] is False


def test_detect_empty_file(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_bytes(b"")

    info = detect_file(source)

    assert info.is_empty is True
    assert info.size_bytes == 0


def test_detect_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        detect_file(tmp_path / "missing.csv")


def test_detect_directory_is_rejected(tmp_path):
    with pytest.raises(IsADirectoryError):
        detect_file(tmp_path)
