from decimal import Decimal

import pandas as pd


def transform_to_silver(file_path: str, output_path: str) -> dict:
    """
    Transforme un fichier Bronze Parquet en fichier Silver Parquet.

    Transformations :
    - nettoyage des chaînes ;
    - conversion des types ;
    - conversion du prix en décimal ;
    - calcul du montant de ligne ;
    - conservation des métadonnées d'ingestion.
    """

    df = pd.read_parquet(file_path)

    required_columns = [
        "customer_id",
        "product",
        "quantity",
        "price",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        # Dataset générique : on conserve le schéma et on nettoie les chaînes.
        for column in df.select_dtypes(include=["object", "string"]).columns:
            df[column] = df[column].astype("string").str.strip()

        df.to_parquet(output_path, index=False)

        return {
            "status": "TRANSFORMED",
            "mode": "generic",
            "source_file": file_path,
            "output_file": output_path,
            "rows": len(df),
            "columns": df.columns.tolist(),
        }

    # --------------------------------------------------
    # 1. Nettoyage du produit
    # --------------------------------------------------

    df["product"] = (
        df["product"]
        .astype("string")
        .str.strip()
    )

    # --------------------------------------------------
    # 2. Conversion des types
    # --------------------------------------------------

    df["customer_id"] = pd.to_numeric(
        df["customer_id"],
        errors="raise"
    ).astype("int64")

    df["quantity"] = pd.to_numeric(
        df["quantity"],
        errors="raise"
    ).astype("int64")

    df["price"] = pd.to_numeric(
        df["price"],
        errors="raise"
    ).round(2)

    # --------------------------------------------------
    # 3. Calcul du montant de ligne
    # --------------------------------------------------

    df["line_amount"] = (
        df["quantity"] * df["price"]
    ).round(2)

    # --------------------------------------------------
    # 4. Écriture Silver
    # --------------------------------------------------

    df.to_parquet(
        output_path,
        index=False
    )

    return {
        "status": "TRANSFORMED",
        "source_file": file_path,
        "output_file": output_path,
        "rows": len(df),
        "columns": df.columns.tolist(),
    }
