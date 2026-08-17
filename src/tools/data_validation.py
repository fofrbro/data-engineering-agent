import pandas as pd


def validate_csv(file_path: str) -> dict:
    """
    Vérifie les règles de qualité d'un fichier CSV.

    L'outil ne doit jamais planter à cause d'une donnée invalide.
    Toute anomalie doit être retournée dans 'issues'.
    """

    df = pd.read_csv(file_path)

    issues = []

    # 1. Valeurs nulles
    nulls = df.isnull().sum()

    for column, count in nulls.items():

        if count > 0:
            issues.append({
                "rule": "no_nulls",
                "column": column,
                "count": int(count),
                "message": (
                    f"{count} valeur(s) nulle(s) détectée(s)."
                )
            })

    # 2. Doublons exacts
    duplicate_count = int(
        df.duplicated().sum()
    )

    if duplicate_count > 0:
        issues.append({
            "rule": "no_duplicates",
            "count": duplicate_count,
            "message": (
                f"{duplicate_count} doublon(s) exact(s) détecté(s)."
            )
        })

    # 3. Quantités positives
    if "quantity" in df.columns:

        # Conversion temporaire vers numérique.
        # Les valeurs impossibles deviennent NaN.
        quantity_numeric = pd.to_numeric(
            df["quantity"],
            errors="coerce"
        )

        invalid_type = int(
            quantity_numeric.isna().sum()
        )

        if invalid_type > 0:
            issues.append({
                "rule": "quantity_numeric",
                "column": "quantity",
                "count": invalid_type,
                "message": (
                    f"{invalid_type} quantité(s) "
                    "non numérique(s) détectée(s)."
                )
            })

        # On ne compare que les valeurs numériques.
        invalid_quantity = int(
            (quantity_numeric.notna()
            & (quantity_numeric <= 0)
        ).sum()
        )

        if invalid_quantity > 0:
            issues.append({
                "rule": "quantity_positive",
                "column": "quantity",
                "count": invalid_quantity,
                "message": (
                    f"{invalid_quantity} quantité(s) "
                    "inférieure(s) ou égale(s) à zéro."
                )
            })

    # 4. Prix positifs ou nuls
    if "price" in df.columns:

        price_numeric = pd.to_numeric(
            df["price"],
            errors="coerce"
        )

        invalid_type = int(
            price_numeric.isna().sum()
        )

        if invalid_type > 0:
            issues.append({
                "rule": "price_numeric",
                "column": "price",
                "count": invalid_type,
                "message": (
                    f"{invalid_type} prix non numérique(s) "
                    "détecté(s)."
                )
            })

        invalid_price = int(
            (
                price_numeric.notna()
                & (price_numeric < 0)
            ).sum()
        )

        if invalid_price > 0:
            issues.append({
                "rule": "price_non_negative",
                "column": "price",
                "count": invalid_price,
                "message": (
                    f"{invalid_price} prix négatif(s) détecté(s)."
                )
            })

    # 5. Produit non vide
    if "product" in df.columns:

        empty_product = int(
            df["product"]
            .fillna("")
            .astype(str)
            .str.strip()
            .eq("")
            .sum()
        )

        if empty_product > 0:
            issues.append({
                "rule": "product_not_empty",
                "column": "product",
                "count": empty_product,
                "message": (
                    f"{empty_product} produit(s) "
                    "vide(s) détecté(s)."
                )
            })

    return {
        "file": file_path,
        "rows": len(df),
        "valid": len(issues) == 0,
        "issues_count": len(issues),
        "issues": issues,
    }
