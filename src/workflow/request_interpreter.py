"""
Traduction d'une demande en langage naturel en action du workflow.

Le LLM propose une intention structurée (schéma JSON strict) ; le
code déterministe la vérifie puis l'exécute. Le LLM ne peut que :
- créer un plan pour un fichier (PLAN_FILE) ;
- expliquer un run existant (EXPLAIN_RUN).
Il n'a aucune action pour valider un contrat, approuver une
transformation ou exécuter un plan : ces décisions restent à
l'utilisateur, via les validations explicites du workflow.
"""

import json
from pathlib import Path

from src.audit_explain import explain_run, format_run_explanation


PLAN_FILE = "PLAN_FILE"
EXPLAIN_RUN = "EXPLAIN_RUN"
UNSUPPORTED = "UNSUPPORTED"

ACTIONS = [PLAN_FILE, EXPLAIN_RUN, UNSUPPORTED]

NULLABLE_STRING = {"type": ["string", "null"]}

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "file_path": NULLABLE_STRING,
        "contract_path": NULLABLE_STRING,
        "dataset": NULLABLE_STRING,
        "run_id": NULLABLE_STRING,
        "message": {"type": "string"},
    },
    "required": [
        "action", "file_path", "contract_path", "dataset", "run_id", "message",
    ],
    "additionalProperties": False,
}

INTERPRETER_INSTRUCTIONS = """
Tu traduis la demande d'un utilisateur en action d'un agent Data Engineering.

Actions possibles :
- PLAN_FILE : analyser et préparer un fichier (profil, contrat, qualité,
  pipeline Bronze/Silver/Gold, KPI, tableau de bord). Utilise-la aussi quand
  l'utilisateur demande d'ingérer, d'exécuter ou de préparer pour Fabric :
  l'exécution exige toujours des validations humaines ultérieures.
- EXPLAIN_RUN : expliquer un run d'audit identifié par son run_id.
- UNSUPPORTED : toute autre demande.

Règles :
1. N'invente jamais de chemin, de run_id ni de nom de dataset : mets null
   si l'information n'est pas dans la demande.
2. Tu ne peux ni valider, ni approuver, ni exécuter quoi que ce soit.
3. message : une phrase en français expliquant ce que l'agent va faire.
"""


class RequestInterpretationError(ValueError):
    """Intention invalide ou incomplète."""


def interpret_request(client, user_request: str) -> dict:
    """Demande au LLM une intention structurée, puis la vérifie."""

    response = client.responses.create(
        model="gpt-5.6",
        instructions=INTERPRETER_INSTRUCTIONS,
        input=user_request,
        text={
            "format": {
                "type": "json_schema",
                "name": "agent_intent",
                "schema": INTENT_SCHEMA,
                "strict": True,
            }
        },
    )

    if not response.output_text:
        raise RequestInterpretationError("Aucune intention retournée.")

    intent = json.loads(response.output_text)

    if intent.get("action") not in ACTIONS:
        raise RequestInterpretationError(
            f"Action non autorisée : {intent.get('action')}"
        )

    return intent


def handle_request(
    client,
    user_request: str,
    service,
    file_path: str | None = None,
    audit_path=None,
    dataset: str | None = None,
) -> dict:
    """
    Exécute l'intention après contrôles déterministes.

    file_path, s'il est fourni (fichier uploadé), remplace tout
    chemin proposé par le LLM ; dataset sert de nom par défaut.
    """

    intent = interpret_request(client, user_request)
    action = intent["action"]

    if action == PLAN_FILE:
        path = file_path or intent["file_path"]

        if not path or not Path(path).is_file():
            raise RequestInterpretationError(
                f"Fichier introuvable ou non précisé : {path}"
            )

        plan = service.create_plan(
            path,
            intent["contract_path"],
            intent["dataset"] or dataset,
        )

        return {"intent": intent, "plan": plan}

    if action == EXPLAIN_RUN:
        if not intent["run_id"]:
            raise RequestInterpretationError("run_id non précisé.")

        return {
            "intent": intent,
            "explanation": format_run_explanation(
                explain_run(intent["run_id"], audit_path)
            ),
        }

    return {"intent": intent}
