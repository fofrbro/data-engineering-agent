"""Deterministic ingestion, cleaning and enrichment for tabular uploads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


SUPPORTED_EXTENSIONS = {
    ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".xlsx", ".xls",
    ".parquet", ".txt",
}


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return value[:80] or "dataset"


def read_tabular_file(path: str | Path) -> pd.DataFrame:
    """Read common tabular formats with a predictable interface."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(source)
    if suffix == ".tsv":
        return pd.read_csv(source, sep="\t")
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(source, lines=True)
    if suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("data", [payload])
        return pd.json_normalize(payload)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(source)
    if suffix == ".parquet":
        return pd.read_parquet(source)
    if suffix == ".txt":
        return pd.read_csv(source, sep=None, engine="python")
    raise ValueError(f"Format non supporté : {suffix or 'inconnu'}")


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "column_names": [str(column) for column in df.columns],
        "dtypes": {str(column): str(dtype) for column, dtype in df.dtypes.items()},
        "nulls": {str(column): int(value) for column, value in df.isna().sum().items()},
        "duplicates": int(df.duplicated().sum()),
    }


def clean_dataframe(df: pd.DataFrame, drop_duplicates: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    cleaned = df.copy()
    before = len(cleaned)
    cleaned.columns = [str(column).strip() for column in cleaned.columns]
    for column in cleaned.select_dtypes(include=["object", "string"]).columns:
        cleaned[column] = cleaned[column].astype("string").str.strip()
    if drop_duplicates:
        cleaned = cleaned.drop_duplicates()
    return cleaned, {
        "rows_before": before,
        "rows_after": int(len(cleaned)),
        "duplicates_removed": int(before - len(cleaned)),
        "nulls_after": {str(column): int(value) for column, value in cleaned.isna().sum().items()},
    }


def enrich_dataframe(df: pd.DataFrame, operations: list[dict[str, Any]] | None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply safe, declarative enrichment operations; never evaluate code."""
    enriched = df.copy()
    applied = []
    for operation in operations or []:
        kind = operation.get("type")
        target = operation.get("target")
        if not isinstance(target, str) or not target or target in enriched.columns:
            raise ValueError(f"Colonne cible invalide ou déjà existante : {target}")
        if kind == "arithmetic":
            left, right = operation.get("left"), operation.get("right")
            if left not in enriched.columns or right not in enriched.columns:
                raise ValueError(f"Colonnes absentes pour {target}: {left}, {right}")
            operator = operation.get("operator", "multiply")
            operators = {
                "add": enriched[left] + enriched[right],
                "subtract": enriched[left] - enriched[right],
                "multiply": enriched[left] * enriched[right],
                "divide": enriched[left] / enriched[right].replace(0, pd.NA),
            }
            if operator not in operators:
                raise ValueError(f"Opérateur arithmétique inconnu : {operator}")
            enriched[target] = operators[operator]
        elif kind == "concat":
            columns = operation.get("columns", [])
            if not columns or any(column not in enriched.columns for column in columns):
                raise ValueError(f"Colonnes absentes pour concaténation : {columns}")
            separator = str(operation.get("separator", " "))
            enriched[target] = enriched[columns].astype("string").fillna("").agg(separator.join, axis=1).str.strip()
        elif kind == "date_part":
            source = operation.get("source")
            part = operation.get("part", "year")
            if source not in enriched.columns or part not in {"year", "month", "day", "quarter", "weekday"}:
                raise ValueError(f"Opération date invalide pour {target}")
            dates = pd.to_datetime(enriched[source], errors="coerce")
            enriched[target] = getattr(dates.dt, part)
        elif kind == "constant":
            enriched[target] = operation.get("value")
        else:
            raise ValueError(f"Type d'enrichissement inconnu : {kind}")
        applied.append({"type": kind, "target": target})
    return enriched, applied


def process_uploads(
    file_paths: list[str],
    dataset_name: str,
    enrichment_operations: list[dict[str, Any]] | None = None,
    drop_duplicates: bool = True,
) -> dict[str, Any]:
    frames = [read_tabular_file(path) for path in file_paths]
    profiles = [profile_dataframe(frame) for frame in frames]
    combined = pd.concat(frames, ignore_index=True, sort=False)
    cleaned, cleaning = clean_dataframe(combined, drop_duplicates)
    enriched, applied = enrich_dataframe(cleaned, enrichment_operations)
    output_name = _safe_name(dataset_name)
    silver_path = Path("data/silver") / f"{output_name}.parquet"
    gold_path = Path("data/gold") / f"{output_name}.parquet"
    silver_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_parquet(silver_path, index=False)
    gold = enriched.copy()
    numeric = gold.select_dtypes(include="number").columns
    if len(numeric):
        summary = gold[numeric].describe().T.reset_index().rename(columns={"index": "metric"})
        summary.to_parquet(gold_path, index=False)
    else:
        gold.to_parquet(gold_path, index=False)
    return {
        "status": "TRANSFORMED",
        "dataset_name": output_name,
        "files": file_paths,
        "profiles": profiles,
        "combined_profile": profile_dataframe(enriched),
        "cleaning": cleaning,
        "enrichments": applied,
        "silver_file": str(silver_path),
        "gold_file": str(gold_path),
    }