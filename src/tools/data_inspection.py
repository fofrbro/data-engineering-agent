import pandas as pd


def inspect_csv(file_path: str) -> dict:
    """
    Inspecte un fichier CSV et retourne des informations
    utiles pour le Data Engineering.
    """

    df = pd.read_csv(file_path)

    return {
        "file": file_path,
        "rows": len(df),
        "columns": list(df.columns),
        "dtypes": df.dtypes.astype(str).to_dict(),
        "nulls": df.isnull().sum().to_dict(),
        "duplicates": int(df.duplicated().sum()),
    }
