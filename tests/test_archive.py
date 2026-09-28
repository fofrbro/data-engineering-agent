import io
import zipfile

import pytest

import src.discovery.archive as archive
from src.discovery.archive import ArchiveError, extract_data_files


SUPPORTED = {".csv", ".json"}


def make_zip(files: dict[str, bytes], encrypt_flag=False) -> bytes:
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in files.items():
            target.writestr(name, data)

    data = bytearray(buffer.getvalue())

    if encrypt_flag:
        # zipfile n'écrit pas d'archive chiffrée : on pose le drapeau
        # « chiffré » dans l'en-tête central de chaque fichier.
        start = 0
        while (index := data.find(b"PK\x01\x02", start)) != -1:
            data[index + 8] |= 0x1
            start = index + 4

    return bytes(data)


def test_data_files_are_extracted_with_flat_names():
    contents = make_zip(
        {
            "orders/2019.csv": b"a,1\n",
            "orders/2020.csv": b"b,2\n",
            "notes.txt": b"ignored: unsupported here",
            "__MACOSX/orders/._2019.csv": b"x",
            ".hidden.csv": b"x",
            "nested.zip": b"x",
        }
    )

    assert extract_data_files(contents, SUPPORTED) == [
        ("orders_2019.csv", b"a,1\n"),
        ("orders_2020.csv", b"b,2\n"),
    ]


def test_path_traversal_never_reaches_the_file_name():
    contents = make_zip({"../../etc/evil.csv": b"a\n"})

    assert extract_data_files(contents, SUPPORTED) == [("etc_evil.csv", b"a\n")]


def test_archive_without_data_files_is_refused():
    with pytest.raises(ArchiveError, match="aucun fichier"):
        extract_data_files(make_zip({"readme.md": b"x"}), SUPPORTED)


def test_unreadable_archive_is_refused():
    with pytest.raises(ArchiveError, match="illisible"):
        extract_data_files(b"not a zip", SUPPORTED)


def test_encrypted_archive_is_refused():
    with pytest.raises(ArchiveError, match="chiffrées"):
        extract_data_files(make_zip({"a.csv": b"x"}, encrypt_flag=True), SUPPORTED)


def test_duplicate_flat_names_are_refused():
    contents = make_zip({"a/b.csv": b"1", "a_b.csv": b"2"})

    with pytest.raises(ArchiveError, match="même nom"):
        extract_data_files(contents, SUPPORTED)


def test_decompressed_size_is_limited_by_bytes_actually_read(monkeypatch):
    monkeypatch.setattr(archive, "MAX_MEMBER_BYTES", 10)
    monkeypatch.setattr(archive, "CHUNK", 4)

    with pytest.raises(ArchiveError, match="taille autorisée"):
        extract_data_files(make_zip({"big.csv": b"0" * 1000}), SUPPORTED)


def test_total_size_is_limited(monkeypatch):
    monkeypatch.setattr(archive, "MAX_TOTAL_BYTES", 15)

    with pytest.raises(ArchiveError, match="taille autorisée"):
        extract_data_files(make_zip({"a.csv": b"0" * 10, "b.csv": b"0" * 10}), SUPPORTED)


def test_member_count_is_limited(monkeypatch):
    monkeypatch.setattr(archive, "MAX_MEMBERS", 1)

    with pytest.raises(ArchiveError, match="plus de 1"):
        extract_data_files(make_zip({"a.csv": b"1", "b.csv": b"2"}), SUPPORTED)
