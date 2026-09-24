import pandas as pd

from src.discovery.readers import read_dataframe


def profile_csv(file_path: str) -> dict:
    """
    Produit un profil statistique simple d'un fichier CSV.
    """

    df = read_dataframe(file_path)

    numeric_columns = df.select_dtypes(
        include="number"
    ).columns.tolist()

    profile = {}

    for column in numeric_columns:
        profile[column] = {
            "min": float(df[column].min()),
            "max": float(df[column].max()),
            "mean": float(df[column].mean()),
            "median": float(df[column].median()),
        }

    return {
        "file": file_path,
        "rows": len(df),
        "numeric_columns": numeric_columns,
     
   "profile": profile,
    }
