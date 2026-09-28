"""
Noms de colonnes proposés par un LLM pour un fichier sans en-tête.

Le LLM propose, le code vérifie : autant de noms que de colonnes, noms
valides et uniques, nom de dataset valide. Une proposition invalide ou
un LLM indisponible donne None : l'appelant garde des noms génériques.
Les noms proposés deviennent ceux du contrat PROPOSED, que le relecteur
valide avant toute exécution.

Données envoyées : type et statistiques de chaque colonne, et la forme
des valeurs texte (« Christy Zhu » -> « Aaaaaaa Aaa », chiffres -> 9),
qui aide à reconnaître un code, un nom ou un e-mail sans en révéler le
contenu. Les valeurs réelles ne sont envoyées que pour les colonnes
catégorielles sans « @ ».
"""

import json
import re
from dataclasses import dataclass

from src.discovery.schema_profiler import DATETIME, SchemaProfile


MODEL = "gpt-5.6"

MAX_SHAPES = 3
MAX_SHAPE_LENGTH = 40

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
DATASET_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

NAMING_SCHEMA = {
    "type": "object",
    "properties": {
        "dataset": {"type": ["string", "null"]},
        "names": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dataset", "names"],
    "additionalProperties": False,
}

NAMING_INSTRUCTIONS = """
Un fichier de données n'a pas de ligne d'en-tête. À partir de la
description de ses colonnes (dans l'ordre), propose :
- names : un nom par colonne, dans le même ordre, en anglais ou en
  français selon ce qui est le plus clair, en PascalCase ou snake_case,
  sans espace ni accent (par exemple OrderDate, customer_name) ;
- dataset : un nom court en snake_case minuscule pour le jeu de données
  (par exemple sales_orders), ou null.

Les valeurs texte sont décrites par leur forme : A = majuscule,
a = minuscule, 9 = chiffre ; les autres caractères sont conservés.
Si le rôle d'une colonne est incertain, choisis un nom descriptif du
contenu (par exemple Code, Label, Amount).
"""


@dataclass
class ColumnNaming:
    names: list[str]
    dataset: str | None


def value_shape(value) -> str:
    """ "SO43701" -> "AA99999", "Christy Zhu" -> "Aaaaaaa Aaa". """

    text = str(value)[:MAX_SHAPE_LENGTH]
    text = re.sub(r"[A-Z]", "A", text)
    text = re.sub(r"[a-z]", "a", text)

    return re.sub(r"\d", "9", text)


def naming_input(schema: SchemaProfile) -> str:
    columns = []

    for position, profile in enumerate(schema.columns, start=1):
        column = {
            "position": position,
            "type": profile.inferred_type,
            "distinct_count": profile.distinct_count,
            "null_ratio": round(profile.null_ratio, 3),
        }

        if profile.is_numeric or profile.inferred_type == DATETIME:
            column["min"] = str(profile.min)
            column["max"] = str(profile.max)
        else:
            samples = [str(value) for value in profile.sample_values]

            if profile.is_categorical and not any("@" in value for value in samples):
                column["values"] = samples
            else:
                column["shapes"] = list(dict.fromkeys(map(value_shape, samples)))[:MAX_SHAPES]

        columns.append(column)

    return json.dumps(
        {"row_count": schema.row_count, "columns": columns},
        ensure_ascii=False,
    )


def check_naming(payload: dict, column_count: int) -> str | None:
    """Raison de refuser la proposition, ou None si elle est recevable."""

    names = payload.get("names") or []

    if len(names) != column_count:
        return f"{len(names)} noms proposés pour {column_count} colonnes"

    invalid = [name for name in names if not NAME_PATTERN.match(name)]

    if invalid:
        return f"noms invalides : {', '.join(invalid)}"

    if len({name.lower() for name in names}) != len(names):
        return "noms en double"

    dataset = payload.get("dataset")

    if dataset is not None and not DATASET_PATTERN.match(dataset):
        return f"nom de dataset invalide : {dataset}"

    return None


def propose_column_names(
    client,
    schema: SchemaProfile,
    model: str = MODEL,
) -> tuple[ColumnNaming | None, str | None]:
    """(proposition vérifiée, None) ou (None, raison de l'échec)."""

    if client is None:
        return None, "aucun client LLM configuré"

    try:
        response = client.responses.create(
            model=model,
            instructions=NAMING_INSTRUCTIONS,
            input=naming_input(schema),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "column_naming",
                    "schema": NAMING_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
    except Exception as exc:
        if type(exc).__name__ == "AuthenticationError":
            return None, "clé API refusée (absente, invalide ou expirée)"

        return None, f"LLM indisponible : {type(exc).__name__}"

    reason = check_naming(payload, len(schema.columns))

    if reason:
        return None, f"proposition du LLM refusée : {reason}"

    return ColumnNaming(names=payload["names"], dataset=payload["dataset"]), None
