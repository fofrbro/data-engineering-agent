"""
Application des transformations Silver recommandées.

Garanties :
- une transformation destructive n'est appliquée que si elle a été
  approuvée ; sinon elle est ignorée et signalée ;
- une conversion de type qui rendrait des valeurs nulles est
  refusée (elle est présentée comme non destructive) ;
- les lignes qui violent les règles du contrat sont mises en
  quarantaine, jamais supprimées silencieusement ;
- aucun code n'est évalué : chaque type d'opération est codé ici.
"""

import warnings
from dataclasses import asdict, dataclass

import pandas as pd

from src.recommendation.pipeline_recommender import Transformation
from src.execution.enrichment import enrich_dataframe


APPLIED = "APPLIED"
SKIPPED_NOT_APPROVED = "SKIPPED_NOT_APPROVED"


class TransformationError(ValueError):
    """Transformation impossible sans perte de données ou inconnue."""


@dataclass
class TransformationReport:
    id: str
    status: str
    rows_before: int
    rows_after: int
    quarantined_rows: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SilverResult:
    data: pd.DataFrame
    quarantined: pd.DataFrame
    reports: list[TransformationReport]


def _cast(df: pd.DataFrame, column: str, target: str) -> pd.Series:
    source = df[column]

    if target == "datetime":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            converted = pd.to_datetime(
                source, errors="coerce", format="mixed", utc=True,
            )
    elif target == "integer":
        try:
            converted = pd.to_numeric(source, errors="coerce").astype("Int64")
        except (TypeError, ValueError) as exc:
            raise TransformationError(
                f"Conversion de {column} en entier refusée : "
                "valeurs décimales présentes."
            ) from exc
    elif target == "decimal":
        converted = pd.to_numeric(source, errors="coerce").astype("float64")
    else:
        raise TransformationError(f"Type cible inconnu : {target}")

    lost = int((source.notna() & converted.isna()).sum())

    if lost:
        raise TransformationError(
            f"Conversion de {column} en {target} refusée : "
            f"{lost} valeur(s) seraient perdues."
        )

    return converted


def _rule_violations(df: pd.DataFrame, rules: dict) -> pd.Series:
    """Masque des lignes violant au moins une règle du contrat."""

    invalid = pd.Series(False, index=df.index)

    for column, rule in rules.items():
        if column not in df.columns:
            continue

        values = df[column]

        if rule.get("nullable") is False:
            invalid |= values.isna()

        numeric = pd.to_numeric(values, errors="coerce")

        if "min" in rule:
            invalid |= numeric < rule["min"]

        if "max" in rule:
            invalid |= numeric > rule["max"]

        if rule.get("unique") is True:
            invalid |= values.notna() & values.duplicated(keep="first")

    return invalid


def _apply(
    df: pd.DataFrame,
    step: Transformation,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (données, lignes mises en quarantaine)."""

    empty = df.iloc[0:0]
    params = step.parameters

    if step.type == "rename":
        return df.rename(columns=params["mapping"]), empty

    if step.type == "clean":
        df = df.copy()
        for column in step.columns:
            df[column] = df[column].astype("string").str.strip()
        return df, empty

    if step.type == "cast":
        df = df.copy()
        for column, target in params["types"].items():
            df[column] = _cast(df, column, target)
        return df, empty

    if step.type == "normalize":
        df = df.copy()
        for column in step.columns:
            df[column] = df[column].astype("string").str.strip().str.upper()
        return df, empty

    if step.type == "impute":
        df = df.copy()
        for column in step.columns:
            df[column] = df[column].fillna(params["value"])
        return df, empty

    if step.type == "filter":
        return df.dropna(subset=step.columns), empty

    if step.type == "null_policy":
        return df, empty

    if step.type == "deduplicate":
        return df.drop_duplicates(), empty

    if step.type == "check":
        invalid = _rule_violations(df, params["rules"])
        return df[~invalid], df[invalid]

    if step.type == "derive" and "target" in params:
        left, right = step.columns
        df = df.copy()
        # Sans arrondi par ligne : le total Gold reste égal à la mesure
        # Power BI SUMX(quantité * prix), même avec des prix à 4 décimales.
        df[params["target"]] = pd.to_numeric(df[left]) * pd.to_numeric(df[right])
        return df, empty

    if step.type == "derive" and "targets" in params:
        dates = pd.to_datetime(df[step.columns[0]], utc=True)
        df = df.copy()
        for part in params["targets"]:
            df[part] = getattr(dates.dt, part)
        return df, empty

    if step.type == "enrich":
        try:
            enriched, _ = enrich_dataframe(df, [params["operation"]])
        except ValueError as exc:
            raise TransformationError(str(exc)) from exc
        return enriched, empty

    raise TransformationError(f"Transformation inconnue : {step.id}")


def apply_silver_transformations(
    bronze: pd.DataFrame,
    transformations: list[Transformation],
    destructive_approved: bool = False,
) -> SilverResult:
    """
    Applique les transformations dans l'ordre recommandé.
    """

    data = bronze.copy()
    quarantined = []
    reports = []

    for step in transformations:
        rows_before = len(data)

        if step.destructive and not destructive_approved:
            reports.append(
                TransformationReport(step.id, SKIPPED_NOT_APPROVED, rows_before, rows_before)
            )
            continue

        data, rejected = _apply(data, step)

        if len(rejected):
            quarantined.append(rejected)

        reports.append(
            TransformationReport(
                step.id, APPLIED, rows_before, len(data), len(rejected),
            )
        )

    return SilverResult(
        data=data.reset_index(drop=True),
        quarantined=(
            pd.concat(quarantined, ignore_index=True)
            if quarantined
            else data.iloc[0:0]
        ),
        reports=reports,
    )
