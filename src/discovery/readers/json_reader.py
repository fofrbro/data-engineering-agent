import json
from pathlib import Path

import pandas as pd

from src.discovery.format_detector import JSON, JSONL, FormatInfo
from src.discovery.readers.base import DataSourceReader


class JSONReader(DataSourceReader):
    """
    Lecteur JSON et JSON Lines.

    Un objet JSON racine contenant une clé "data" est lu
    comme la liste d'enregistrements de cette clé ; un autre
    objet racine est lu comme un enregistrement unique.
    Les objets imbriqués sont aplatis (a.b).
    """

    formats = (JSON, JSONL)

    def read(
        self,
        path: str | Path,
        format_info: FormatInfo,
    ) -> pd.DataFrame:
        if format_info.format == JSONL:
            return pd.read_json(path, lines=True)

        payload = json.loads(
            Path(path).read_text(encoding="utf-8-sig")
        )

        if isinstance(payload, dict):
            payload = payload.get("data", [payload])

        return pd.json_normalize(payload)
