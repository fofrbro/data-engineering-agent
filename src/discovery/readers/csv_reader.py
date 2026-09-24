from pathlib import Path

import pandas as pd

from src.discovery.format_detector import CSV, TSV, FormatInfo
from src.discovery.readers.base import DataSourceReader


class CSVReader(DataSourceReader):
    """Lecteur des fichiers délimités (CSV, TSV)."""

    formats = (CSV, TSV)

    def read(
        self,
        path: str | Path,
        format_info: FormatInfo,
    ) -> pd.DataFrame:
        default = "\t" if format_info.format == TSV else ","

        return pd.read_csv(
            path,
            sep=format_info.delimiter or default,
            encoding="utf-8-sig",
        )
