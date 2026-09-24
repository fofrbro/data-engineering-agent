import json
import warnings

import pandas as pd

from src.contract.contract_lifecycle import contract_status


BOOLEAN_TEXT_VALUES = {"true", "false"}


def load_contract(contract_path: str) -> dict:
    """Charge un contrat de données JSON."""

    with open(contract_path, "r", encoding="utf-8") as file:
        return json.load(file)


def _is_datetime_compatible(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    if not (
        pd.api.types.is_string_dtype(series)
        or series.dtype == object
    ):
        return False

    values = series.dropna().astype(str)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(
            values,
            errors="coerce",
            format="mixed",
        )

    return bool(parsed.notna().all())


def _is_boolean_compatible(series: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(series):
        return True

    values = series.dropna().astype(str).str.lower()

    return bool(values.isin(BOOLEAN_TEXT_VALUES).all())


def is_type_compatible(series: pd.Series, expected_type: str) -> bool:
    """
    Vérifie qu'une colonne est compatible avec le type du contrat.
    Un type inconnu n'est jamais compatible.
    """

    if expected_type == "integer":
        return pd.api.types.is_integer_dtype(series)

    if expected_type == "decimal":
        return (
            pd.api.types.is_integer_dtype(series)
            or pd.api.types.is_float_dtype(series)
        )

    if expected_type == "string":
        return (
            pd.api.types.is_string_dtype(series)
            or series.dtype == object
        )

    if expected_type == "boolean":
        return _is_boolean_compatible(series)

    if expected_type == "datetime":
        return _is_datetime_compatible(series)

    return False


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
            "contract_status": None,
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

        if not is_type_compatible(df[column], expected_type):
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
    # 5. Vérification des valeurs minimales et maximales
    # --------------------------------------------------

    for column, rules in expected_columns.items():

        if column not in df.columns:
            continue

        # Si le type de la colonne est déjà invalide,
        # on ne tente pas de comparaison numérique.
        expected_type = rules["type"]

        if expected_type not in ("integer", "decimal"):
            continue

        if not is_type_compatible(df[column], expected_type):
            continue

        if "min" in rules:

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

        if "max" in rules:

            maximum = rules["max"]

            invalid_count = int(
                (df[column] > maximum).sum()
            )

            if invalid_count > 0:
                errors.append({
                    "type": "max_value",
                    "column": column,
                    "expected_max": maximum,
                    "count": invalid_count,
                    "message": (
                        f"{invalid_count} valeur(s) de '{column}' "
                        f"sont supérieures à {maximum}."
                    )
                })

    # --------------------------------------------------
    # 6. Vérification de l'unicité
    # --------------------------------------------------

    for column, rules in expected_columns.items():

        if column not in df.columns:
            continue

        if rules.get("unique") is not True:
            continue

        duplicate_count = int(
            df[column].dropna().duplicated().sum()
        )

        if duplicate_count > 0:
            errors.append({
                "type": "duplicate_values",
                "column": column,
                "count": duplicate_count,
                "message": (
                    f"{duplicate_count} valeur(s) dupliquée(s) "
                    f"dans '{column}', déclarée unique."
                )
            })

    # --------------------------------------------------
    # Résultat final
    # --------------------------------------------------

    return {
        "dataset": contract.get("dataset"),
        "contract_version": contract.get("version"),
        "contract_status": contract_status(contract),
        "file": file_path,
        "valid": len(errors) == 0,
        "errors_count": len(errors),
        "warnings_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
