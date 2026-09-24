from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from src.discovery.format_detector import FormatInfo


class DataSourceReader(ABC):
    """
    Lecteur d'un ou plusieurs formats tabulaires.

    Pour ajouter un format : créer une sous-classe,
    déclarer ses formats puis l'enregistrer via register_reader().
    """

    formats: tuple[str, ...] = ()

    @abstractmethod
    def read(
        self,
        path: str | Path,
        format_info: FormatInfo,
    ) -> pd.DataFrame:
        """Lit le fichier et retourne un DataFrame."""
