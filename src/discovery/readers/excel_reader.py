from pathlib import Path

import pandas as pd

from src.discovery.format_detector import EXCEL, FormatInfo
from src.discovery.readers.base import DataSourceReader


class ExcelReader(DataSourceReader):
    """Lecteur Excel : lit la première feuille."""

    formats = (EXCEL,)

    def read(
        self,
        path: str | Path,
        format_info: FormatInfo,
    ) -> pd.DataFrame:
        return pd.read_excel(path, sheet_name=0)
