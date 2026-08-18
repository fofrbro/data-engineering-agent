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

Règles fondamentales :

1. Identifie exactement le fichier source et le contrat JSON.
2. N'invente jamais de chemins.
3. Utilise exactement les chemins fournis par l'utilisateur.
4. Si une décision d'ingestion est demandée, alors :
   - validate_quality = true
   - validate_contract = true
   - decision = true
5. Si ingest = true :
   - validate_quality = true
   - validate_contract = true
   - decision = true
6. Si transform_to_silver = true :
   - ingest = true
   - decision = true
   - validate_quality = true
   - validate_contract = true
7. Si build_gold = true :
   - transform_to_silver = true
   - ingest = true
   - decision = true
   - validate_quality = true
   - validate_contract = true
8. quarantine et reject doivent rester false dans le plan initial.
   Ces décisions sont prises uniquement par le Policy Engine.
9. Le plan doit représenter les étapes nécessaires à l'exécution.
10. Une demande comme "transforme et ingère" doit permettre
    l'ingestion puis Silver, et Gold si le contexte du pipeline
    de ventes le prévoit.
11. Ne demande pas à l'utilisateur une information déjà présente
    dans sa demande.
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
