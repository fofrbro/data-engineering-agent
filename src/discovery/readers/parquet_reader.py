from pathlib import Path

import pandas as pd

from src.discovery.format_detector import PARQUET, FormatInfo
from src.discovery.readers.base import DataSourceReader


class ParquetReader(DataSourceReader):
    """Lecteur Parquet."""

    formats = (PARQUET,)

    def read(
        self,
        path: str | Path,
        format_info: FormatInfo,
    ) -> pd.DataFrame:
        return pd.read_parquet(path)
