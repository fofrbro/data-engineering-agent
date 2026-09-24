"""
Profil de schéma générique d'un DataFrame.

Le profil reste factuel (types, nulls, cardinalités) et ne pose
que des indicateurs structurels simples (numérique, catégoriel,
temporel, identifiant candidat). L'interprétation métier, avec
scores de confiance, relève du semantic profiler.
"""

import math
import re
import unicodedata
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import pandas as pd


EMPTY = "empty"
BOOLEAN = "boolean"
INTEGER = "integer"
DECIMAL = "decimal"
DATETIME = "datetime"
STRING = "string"

# Au-delà de ce nombre de valeurs distinctes, une colonne texte
# n'est catégorielle que si sa cardinalité relative reste faible.
CATEGORICAL_MAX_DISTINCT = 50
CATEGORICAL_MAX_RATIO = 0.5

# L'unicité seule ne suffit pas à suggérer un identifiant
# sur un trop petit échantillon.
IDENTIFIER_MIN_ROWS = 10

# Part minimale des valeurs texte devant ressembler à une date.
DATE_MIN_RATIO = 0.9

SAMPLE_VALUES = 5

DATE_PATTERN = re.compile(
    r"^\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})"
)
IDENTIFIER_TOKENS = {"id", "uuid", "guid"}
IDENTIFIER_SUFFIXES = {"key", "code", "ref", "number", "num", "no"}


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    inferred_type: str
    null_count: int
    null_ratio: float
    distinct_count: int
    cardinality_ratio: float
    is_unique: bool
    is_numeric: bool
    is_categorical: bool
    is_temporal: bool
    is_identifier_candidate: bool
    identifier_reasons: list[str] = field(default_factory=list)
    min: object = None
    max: object = None
    sample_values: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SchemaProfile:
    row_count: int
    column_count: int
    duplicate_rows: int
    columns: list[ColumnProfile]

    def _names(self, flag: str) -> list[str]:
        return [
            column.name
            for column in self.columns
            if getattr(column, flag)
        ]

    @property
    def numeric_columns(self) -> list[str]:
        return self._names("is_numeric")

    @property
    def categorical_columns(self) -> list[str]:
        return self._names("is_categorical")

    @property
    def temporal_columns(self) -> list[str]:
        return self._names("is_temporal")

    @property
    def identifier_candidates(self) -> list[str]:
        return self._names("is_identifier_candidate")

    def to_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "column_names": [column.name for column in self.columns],
            "duplicate_rows": self.duplicate_rows,
            "numeric_columns": self.numeric_columns,
            "categorical_columns": self.categorical_columns,
            "temporal_columns": self.temporal_columns,
            "identifier_candidates": self.identifier_candidates,
            "columns": [column.to_dict() for column in self.columns],
        }


def _to_builtin(value):
    """Convertit une valeur pandas/numpy en type JSON-sérialisable."""

    if value is None:
        return None

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()

    if hasattr(value, "item"):
        value = value.item()

    if isinstance(value, float) and math.isnan(value):
        return None

    if isinstance(value, (bool, int, float, str)):
        return value

    return str(value)


def _hashable(series: pd.Series) -> pd.Series:
    """Les colonnes JSON peuvent contenir des listes non hachables."""

    try:
        series.nunique()
        return series
    except TypeError:
        return series.astype(str).where(series.notna())


def _parse_dates(values: pd.Series) -> pd.Series | None:
    """
    Retourne les dates parsées si les valeurs texte ressemblent
    majoritairement à des dates, sinon None.
    """

    text = values.astype(str)

    if text.str.match(DATE_PATTERN).mean() < DATE_MIN_RATIO:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(
            text,
            errors="coerce",
            format="mixed",
            utc=True,
        )

    if parsed.notna().mean() < DATE_MIN_RATIO:
        return None

    return parsed


def _infer_type(values: pd.Series) -> tuple[str, pd.Series]:
    """
    Déduit le type logique d'une série sans nulls.

    Retourne le type et la série éventuellement convertie
    (dates texte parsées), utilisée pour min/max.
    """

    if values.empty:
        return EMPTY, values

    if pd.api.types.is_bool_dtype(values):
        return BOOLEAN, values

    if pd.api.types.is_datetime64_any_dtype(values):
        return DATETIME, values

    if pd.api.types.is_integer_dtype(values):
        return INTEGER, values

    if pd.api.types.is_float_dtype(values):
        # Des entiers avec nulls sont lus en float.
        if (values % 1 == 0).all():
            return INTEGER, values
        return DECIMAL, values

    parsed = _parse_dates(values)

    if parsed is not None:
        return DATETIME, parsed.dropna()

    return STRING, values


def name_tokens(name) -> list[str]:
    """
    Découpe un nom de colonne en mots normalisés :
    camelCase séparé, minuscules, accents retirés.

    Exemple : "QuantitéVendue" -> ["quantite", "vendue"].
    """

    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)

    return [
        token
        for token in re.split(r"[^a-z0-9]+", snake.lower())
        if token
    ]


def _identifier_name_hint(name: str) -> bool:
    tokens = name_tokens(name)

    if not tokens:
        return False

    return (
        any(token in IDENTIFIER_TOKENS for token in tokens)
        or tokens[-1] in IDENTIFIER_SUFFIXES
    )


def profile_column(
    series: pd.Series,
    row_count: int,
) -> ColumnProfile:
    values = _hashable(series)
    non_null = values.dropna()

    null_count = int(values.isna().sum())
    distinct_count = int(non_null.nunique())
    non_null_count = len(non_null)

    inferred_type, typed_values = _infer_type(non_null)

    is_unique = (
        row_count > 0
        and null_count == 0
        and distinct_count == row_count
    )

    identifier_reasons = []

    if _identifier_name_hint(series.name):
        identifier_reasons.append("name")

    if (
        is_unique
        and row_count >= IDENTIFIER_MIN_ROWS
        and inferred_type in {INTEGER, STRING}
    ):
        identifier_reasons.append("unique_values")

    is_identifier_candidate = bool(identifier_reasons)
    is_numeric = inferred_type in {INTEGER, DECIMAL}
    is_temporal = inferred_type == DATETIME
    cardinality_ratio = (
        distinct_count / non_null_count
        if non_null_count
        else 0.0
    )

    is_categorical = inferred_type == BOOLEAN or (
        inferred_type == STRING
        and not is_identifier_candidate
        and (
            distinct_count <= CATEGORICAL_MAX_DISTINCT
            or cardinality_ratio <= CATEGORICAL_MAX_RATIO
        )
    )

    minimum = maximum = None

    if is_numeric or is_temporal:
        minimum = _to_builtin(typed_values.min())
        maximum = _to_builtin(typed_values.max())

    return ColumnProfile(
        name=str(series.name),
        dtype=str(series.dtype),
        inferred_type=inferred_type,
        null_count=null_count,
        null_ratio=null_count / row_count if row_count else 0.0,
        distinct_count=distinct_count,
        cardinality_ratio=cardinality_ratio,
        is_unique=is_unique,
        is_numeric=is_numeric,
        is_categorical=is_categorical,
        is_temporal=is_temporal,
        is_identifier_candidate=is_identifier_candidate,
        identifier_reasons=identifier_reasons,
        min=minimum,
        max=maximum,
        sample_values=[
            _to_builtin(value)
            for value in non_null.unique()[:SAMPLE_VALUES]
        ],
    )


def _count_duplicate_rows(df: pd.DataFrame) -> int:
    try:
        return int(df.duplicated().sum())
    except TypeError:
        return int(df.astype(str).duplicated().sum())


def profile_schema(df: pd.DataFrame) -> SchemaProfile:
    """
    Produit le profil de schéma d'un DataFrame.
    """

    row_count = len(df)

    return SchemaProfile(
        row_count=row_count,
        column_count=len(df.columns),
        duplicate_rows=_count_duplicate_rows(df),
        columns=[
            profile_column(df[column], row_count)
            for column in df.columns
        ],
    )
