from pathlib import Path
from datetime import datetime, timezone
import hashlib

import pandas as pd


def calculate_file_hash(file_path: str) -> str:
    """
    Calcule le SHA-256 du fichier source.
    """

    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:

        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def ingest_csv(
    file_path: str,
    dataset: str = "sales"
) -> dict:
    """
    Ingère un fichier CSV dans la zone Bronze au format Parquet.
    """

    source = Path(file_path)

    if not source.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {file_path}"
        )

    # -----------------------------------------
    # Lecture
    # -----------------------------------------

    df = pd.read_csv(source)

    # -----------------------------------------
    # Hash du fichier source
    # -----------------------------------------

    file_hash = calculate_file_hash(file_path)

    # -----------------------------------------
    # Métadonnées d'ingestion
    # -----------------------------------------

    ingestion_timestamp = datetime.now(
        timezone.utc
    ).isoformat()

    df["_source_file"] = source.name

    df["_source_hash"] = file_hash

    df["_ingestion_timestamp"] = ingestion_timestamp

    # -----------------------------------------
    # Destination Bronze
    # -----------------------------------------

    bronze_dir = Path("data/bronze")

    bronze_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path = (
        bronze_dir / f"{dataset}.parquet"
    )

    # -----------------------------------------
    # Idempotence simple
    # -----------------------------------------

    if output_path.exists():

        existing = pd.read_parquet(
            output_path
        )

        if "_source_hash" in existing.columns:

            if file_hash in existing["_source_hash"].values:

                return {
                    "status": "SKIPPED",
                    "reason": "Fichier déjà ingéré.",
                    "source_file": str(source),
                    "source_hash": file_hash,
                    "output_file": str(output_path),
                    "rows": len(df)
                }

    # -----------------------------------------
    # Écriture Parquet
    # -----------------------------------------

    df.to_parquet(
        output_path,
        index=False
    )

    return {
        "status": "INGESTED",
        "source_file": str(source),
        "source_hash": file_hash,
        "output_file": str(output_path),
        "rows": len(df),
        "columns": list(df.columns),
        "ingestion_timestamp": ingestion_timestamp
    }

    
def quarantine_csv(
    file_path: str,
    reason: str
) -> dict:
    """
    Place un fichier dans la zone de quarantaine.
    """

    source = Path(file_path)

    if not source.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {file_path}"
        )

    quarantine_dir = Path("data/quarantine")

    quarantine_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    destination = quarantine_dir / source.name

    # Copie du fichier source
    import shutil

    shutil.copy2(
        source,
        destination
    )

    return {
        "status": "QUARANTINED",
        "source_file": str(source),
        "quarantine_file": str(destination),
        "reason": reason
    }


def reject_csv(
    file_path: str,
    reason: str
) -> dict:
    """
    Place un fichier rejeté dans la zone rejected.
    """

    source = Path(file_path)

    if not source.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {file_path}"
        )

    rejected_dir = Path("data/rejected")

    rejected_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    destination = rejected_dir / source.name

    import shutil

    shutil.copy2(
        source,
        destination
    )

    return {
        "status": "REJECTED",
        "source_file": str(source),
        "rejected_file": str(destination),
        "reason": reason
    }
