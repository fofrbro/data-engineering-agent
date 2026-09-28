"""
Détection des fichiers délimités sans ligne d'en-tête.

Un fichier exporté sans en-tête commence directement par une ligne de
données : la lire normalement ferait de cette ligne les noms de colonnes
(« SO43701 », « Christy Zhu »…) et la retirerait des données.

Règle déterministe : une colonne est « typée » quand toutes ses valeurs
(hors première ligne) sont des nombres, ou toutes des dates. Le fichier
est sans en-tête quand il a au moins une colonne typée et que la
première ligne a, dans chacune de ces colonnes, une valeur du même type.
Un vrai en-tête porte des libellés (« Quantity », « OrderDate ») au-dessus
des nombres et des dates. Sans colonne typée, on ne peut pas trancher :
le fichier est considéré comme ayant un en-tête (lecture habituelle).
"""

import re
import warnings
from pathlib import Path

import pandas as pd

from src.discovery.file_detector import detect_file
from src.discovery.format_detector import CSV, TSV, detect_format


# Lignes examinées : la décision ne dépend pas de la taille du fichier.
SAMPLE_ROWS = 200

NUMBER = "number"
DATE = "date"

_HAS_DIGIT = re.compile(r"\d")


def read_raw_delimited(path: str | Path, nrows: int | None = None) -> pd.DataFrame | None:
    """
    Lit un fichier délimité sans interpréter d'en-tête ni de type :
    chaque cellule reste le texte du fichier. None pour un autre format.
    """

    format_info = detect_format(detect_file(path))

    if format_info.format not in (CSV, TSV):
        return None

    default = "\t" if format_info.format == TSV else ","

    return pd.read_csv(
        path,
        sep=format_info.delimiter or default,
        header=None,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
        nrows=nrows,
    )


def value_kind(values: pd.Series) -> str | None:
    """NUMBER si toutes les valeurs non vides sont des nombres, DATE si des dates."""

    values = values[values.str.strip() != ""]

    if values.empty:
        return None

    if pd.to_numeric(values, errors="coerce").notna().all():
        return NUMBER

    if not values.str.contains(_HAS_DIGIT).all():
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(values, errors="coerce", format="mixed")

    return DATE if parsed.notna().all() else None


def has_header(raw: pd.DataFrame) -> bool:
    """Applique la règle du module à un fichier lu par read_raw_delimited."""

    if len(raw) < 2:
        return True

    body = raw.iloc[1:SAMPLE_ROWS]
    first = raw.iloc[0]
    typed = 0

    for column in raw.columns:
        kind = value_kind(body[column])

        if kind is None:
            continue

        typed += 1

        if value_kind(pd.Series([first[column]])) != kind:
            return True

    return typed == 0


def file_has_header(path: str | Path) -> bool:
    """True si le fichier a un en-tête ou n'est pas un fichier délimité."""

    raw = read_raw_delimited(path, nrows=SAMPLE_ROWS)

    return True if raw is None else has_header(raw)
