from pathlib import Path

import pandas as pd

from src.discovery.errors import (
    UnreadableFileError,
    UnsupportedFormatError,
)
from src.discovery.file_detector import FileInfo, detect_file
from src.discovery.format_detector import FormatInfo, detect_format
from src.discovery.readers.base import DataSourceReader
from src.discovery.readers.csv_reader import CSVReader
from src.discovery.readers.excel_reader import ExcelReader
from src.discovery.readers.json_reader import JSONReader
from src.discovery.readers.parquet_reader import ParquetReader


_READERS: dict[str, DataSourceReader] = {}


def register_reader(reader: DataSourceReader) -> None:
    """Enregistre un lecteur pour chacun de ses formats."""

    for format_name in reader.formats:
        _READERS[format_name] = reader


def get_reader(format_name: str) -> DataSourceReader:
    reader = _READERS.get(format_name)

    if reader is None:
        raise UnsupportedFormatError(
            f"Aucun lecteur pour le format : {format_name}"
        )

    return reader


def supported_formats() -> list[str]:
    return sorted(_READERS)


for _reader in (
    CSVReader(),
    ExcelReader(),
    JSONReader(),
    ParquetReader(),
):
    register_reader(_reader)


def read_dataset(
    path: str | Path,
) -> tuple[FileInfo, FormatInfo, pd.DataFrame]:
    """
    Détecte le fichier et son format, puis le lit.

    Les erreurs de lecture sont converties en UnreadableFileError.
    """

    file_info = detect_file(path)
    format_info = detect_format(file_info)
    reader = get_reader(format_info.format)

    try:
        frame = reader.read(file_info.path, format_info)
    except Exception as exc:
        raise UnreadableFileError(
            f"Lecture impossible de {file_info.path} "
            f"({format_info.format}) : {exc}"
        ) from exc

    return file_info, format_info, frame
