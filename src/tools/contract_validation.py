import json

import pandas as pd


def load_contract(contract_path: str) -> dict:
    """Charge un contrat de données JSON."""

    with open(contract_path, "r", encoding="utf-8") as file:
        return json.load(file)


def validate_contract(
    file_path: str,
    contract_path: str | None
) -> dict:
    """
    Compare le schéma et certaines contraintes d'un CSV
    avec un contrat de données JSON.
    """

    df = pd.read_csv(file_path)

    # Un contrat absent signifie que le schéma est accepté après inspection.
    # Les contrôles de qualité généraux restent exécutés séparément.
    if not contract_path:
        return {
            "dataset": None,
            "contract_version": "inferred",
            "file": file_path,
            "valid": True,
            "errors_count": 0,
            "warnings_count": 0,
            "errors": [],
            "warnings": [],
            "inferred_schema": {
                column: str(dtype)
                for column, dtype in df.dtypes.items()
            },
        }

    contract = load_contract(contract_path)

    errors = []
    warnings = []

    expected_columns = contract["columns"]
    actual_columns = df.columns.tolist()

    # --------------------------------------------------
    # 1. Colonnes manquantes
    # --------------------------------------------------

    for column in expected_columns:

        if column not in actual_columns:
            errors.append({
                "type": "missing_column",
                "column": column,
                "message": f"La colonne '{column}' est absente."
            })

    # --------------------------------------------------
    # 2. Colonnes supplémentaires
    # --------------------------------------------------

    for column in actual_columns:

        if column not in expected_columns:
            warnings.append({
                "type": "unexpected_column",
                "column": column,
                "message": (
                    f"La colonne '{column}' n'est pas définie "
                    "dans le contrat."
                )
            })

    # --------------------------------------------------
    # 3. Vérification des types
    # --------------------------------------------------

    for column, rules in expected_columns.items():

        if column not in df.columns:
            continue

        expected_type = rules["type"]
        actual_type = str(df[column].dtype)

        compatible = False

        if expected_type == "integer":
            compatible = pd.api.types.is_integer_dtype(df[column])

        elif expected_type == "decimal":
            compatible = (
                pd.api.types.is_integer_dtype(df[column])
                or pd.api.types.is_float_dtype(df[column])
            )

        elif expected_type == "string":
            compatible = (
                pd.api.types.is_string_dtype(df[column])
                or df[column].dtype == object
            )

        if not compatible:
            errors.append({
                "type": "invalid_type",
                "column": column,
                "expected": expected_type,
                "actual": actual_type,
                "message": (
                    f"Type incompatible pour '{column}': "
                    f"attendu {expected_type}, obtenu {actual_type}."
                )
            })

    # --------------------------------------------------
    # 4. Vérification des valeurs nulles
    # --------------------------------------------------

    for column, rules in expected_columns.items():

        if column not in df.columns:
            continue

        if rules.get("nullable") is False:

            null_count = int(df[column].isnull().sum())

            if null_count > 0:
                errors.append({
                    "type": "null_values",
                    "column": column,
                    "count": null_count,
                    "message": (
                        f"{null_count} valeur(s) nulle(s) "
                        f"dans '{column}'."
                    )
                })

    # --------------------------------------------------
    # 5. Vérification des valeurs minimales
    # --------------------------------------------------

    for column, rules in expected_columns.items():

        if column not in df.columns:
            continue

        if "min" not in rules:
            continue

        # Si le type de la colonne est déjà invalide,
        # on ne tente pas de comparaison numérique.
        expected_type = rules["type"]

        if expected_type in ("integer", "decimal"):

            if expected_type == "integer":
                compatible = pd.api.types.is_integer_dtype(df[column])

            else:
                compatible = (
                    pd.api.types.is_integer_dtype(df[column])
                    or pd.api.types.is_float_dtype(df[column])
                )

            if not compatible:
                continue

            minimum = rules["min"]

            invalid_count = int(
                (df[column] < minimum).sum()
            )

            if invalid_count > 0:
                errors.append({
                    "type": "min_value",
                    "column": column,
                    "expected_min": minimum,
                    "count": invalid_count,
                    "message": (
                        f"{invalid_count} valeur(s) de '{column}' "
                        f"sont inférieures à {minimum}."
                    )
                })

    # --------------------------------------------------
    # Résultat final
    # --------------------------------------------------

    return {
        "dataset": contract.get("dataset"),
        "contract_version": contract.get("version"),
        "file": file_path,
        "valid": len(errors) == 0,
        "errors_count": len(errors),
        "warnings_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
