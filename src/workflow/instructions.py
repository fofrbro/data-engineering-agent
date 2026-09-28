"""
Instructions données à l'agent au moment de l'upload.

Le LLM traduit le texte libre de l'utilisateur en actions précises, dans
un schéma strict ; le code vérifie chaque action avant de l'appliquer.
Actions possibles :
- dataset : nom du dataset ;
- column_names : noms des colonnes des fichiers sans en-tête.
Une action invalide est écartée avec sa raison ; tout le reste de la
demande est signalé comme non pris en charge. Le LLM n'a aucune action
pour valider ni exécuter. Les champs remplis explicitement dans le
formulaire l'emportent toujours sur les instructions.
"""

import json
from dataclasses import asdict, dataclass, field

from src.semantic.column_naming import (
    DATASET_PATTERN,
    invalid_names_reason,
    normalize_column_names,
    normalize_dataset_name,
)


MODEL = "gpt-5.6"

INSTRUCTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "dataset": {"type": ["string", "null"]},
        "column_names": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "unsupported": {"type": ["string", "null"]},
        "message": {"type": "string"},
    },
    "required": ["dataset", "column_names", "unsupported", "message"],
    "additionalProperties": False,
}

INSTRUCTIONS_PROMPT = """
Tu reçois les instructions d'un utilisateur qui confie des fichiers de
données à un agent Data Engineering. Traduis-les en actions :
- dataset : nom du jeu de données demandé, en snake_case minuscule sans
  accent (par exemple « ventes AE » -> ventes_ae), sinon null ;
- column_names : noms de colonnes donnés par l'utilisateur, dans l'ordre,
  sans espace ni accent (par exemple « numéro de commande » ->
  numero_commande), sinon null. N'invente aucun nom absent des instructions ;
- unsupported : ce que l'utilisateur demande d'autre (l'agent ne sait pas
  le faire à cette étape), en une phrase, sinon null ;
- message : une phrase en français résumant ce que l'agent va appliquer.
Tu ne peux ni valider, ni approuver, ni exécuter quoi que ce soit.
"""


@dataclass
class InterpretedInstructions:
    text: str
    status: str
    dataset: str | None = None
    column_names: list[str] | None = None
    message: str | None = None
    unsupported: str | None = None
    # Actions proposées par le LLM et refusées par les contrôles.
    discarded: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


COMPLETED = "COMPLETED"
UNAVAILABLE = "UNAVAILABLE"


def interpret_instructions(client, text: str, model: str = MODEL) -> InterpretedInstructions:
    if client is None:
        return InterpretedInstructions(
            text=text,
            status=UNAVAILABLE,
            error="aucun client LLM configuré : instructions non appliquées",
        )

    try:
        response = client.responses.create(
            model=model,
            instructions=INSTRUCTIONS_PROMPT,
            input=text,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "upload_instructions",
                    "schema": INSTRUCTIONS_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(response.output_text)
    except Exception as exc:
        error = (
            "clé API refusée (absente, invalide ou expirée)"
            if type(exc).__name__ == "AuthenticationError"
            else f"LLM indisponible : {type(exc).__name__}"
        )
        return InterpretedInstructions(
            text=text, status=UNAVAILABLE, error=f"{error} : instructions non appliquées",
        )

    result = InterpretedInstructions(
        text=text,
        status=COMPLETED,
        message=payload.get("message"),
        unsupported=payload.get("unsupported"),
    )
    # Normalisation déterministe : « e-mail » -> « e_mail », « ventes AE » ->
    # « ventes_ae ». Le relecteur valide ensuite les noms dans le plan.
    dataset = normalize_dataset_name(payload["dataset"]) if payload.get("dataset") else None
    names = normalize_column_names(payload["column_names"]) if payload.get("column_names") else None

    if dataset is not None:
        if DATASET_PATTERN.match(dataset):
            result.dataset = dataset
        else:
            result.discarded.append(f"nom de dataset invalide : {dataset}")

    if names:
        reason = invalid_names_reason(names)

        if reason:
            result.discarded.append(f"noms de colonnes : {reason}")
        else:
            result.column_names = names

    return result
