import json

from src.pipeline_plan import build_pipeline_plan


PIPELINE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
        },
        "contract_path": {
            "type": "string",
        },
        "inspect": {
            "type": "boolean",
        },
        "profile": {
            "type": "boolean",
        },
        "validate_quality": {
            "type": "boolean",
        },
        "validate_contract": {
            "type": "boolean",
        },
        "decision": {
            "type": "boolean",
        },
        "ingest": {
            "type": "boolean",
        },
        "transform_to_silver": {
            "type": "boolean",
        },
        "build_gold": {
            "type": "boolean",
        },
        "quarantine": {
            "type": "boolean",
        },
        "reject": {
            "type": "boolean",
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "file_path",
        "contract_path",
        "inspect",
        "profile",
        "validate_quality",
        "validate_contract",
        "decision",
        "ingest",
        "transform_to_silver",
        "build_gold",
        "quarantine",
        "reject",
        "steps",
    ],
    "additionalProperties": False,
}


PLANNER_INSTRUCTIONS = """
Tu es le planificateur d'un agent Data Engineering.

Ta tâche est de transformer la demande utilisateur en PipelinePlan.

Règles :

- Identifie le fichier source et le contrat JSON.
- Si l'utilisateur demande une analyse complète avant ingestion,
  active inspect, profile, validate_quality, validate_contract
  et decision.
- Si l'utilisateur demande l'ingestion d'un fichier valide,
  active ingest.
- Une ingestion autorisée peut être suivie de transform_to_silver
  puis build_gold.
- Ne définis jamais quarantine ou reject comme conséquence de ton
  propre jugement : ces décisions appartiennent au Policy Engine.
- quarantine et reject doivent donc rester false dans un plan
  normal d'analyse/ingestion.
- N'invente jamais de chemins.
- Utilise exactement les chemins fournis par l'utilisateur.
- Le plan doit être cohérent avec les dépendances du pipeline.
"""


def generate_pipeline_plan(client, user_request: str):
    """
    Demande au LLM de produire un PipelinePlan structuré,
    puis le valide côté Python.
    """

    response = client.responses.create(
        model="gpt-5.6",
        instructions=PLANNER_INSTRUCTIONS,
        input=user_request,
        text={
            "format": {
                "type": "json_schema",
                "name": "pipeline_plan",
                "description": (
                    "Plan structuré d'exécution d'un pipeline "
                    "Data Engineering."
                ),
                "schema": PIPELINE_PLAN_SCHEMA,
                "strict": True,
            }
        },
    )

    if not response.output_text:
        raise ValueError(
            "Le planificateur n'a retourné aucun plan."
        )

    data = json.loads(response.output_text)

    return build_pipeline_plan(data)
