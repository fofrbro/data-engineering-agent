import json

from src.llm import client
from src.tools.contract_validation import validate_contract
from src.tools.data_validation import validate_csv
from src.tools.data_inspection import inspect_csv
from src.tools.ingestion import(ingest_csv, quarantine_csv,reject_csv,)
from src.tools.data_profiling import profile_csv
from src.tools.ingestion_decision import determine_ingestion_decision
from src.tools.gold_transformation import build_sales_gold
from src.tools.silver_transformation import transform_to_silver
from src.tools.fabric_connector import publish_to_fabric
from src.tools.data_analyst import analyze_gold_data
from src.pipeline_planner import generate_pipeline_plan
from src.pipeline_orchestrator import execute_pipeline


class FabricAuthenticationRequired(RuntimeError):
    """Signal envoyé à l’API quand la publication nécessite une connexion."""

    def __init__(self, details: dict):
        self.details = details
        super().__init__(details.get("message", "Authentification Fabric requise"))


tools = [
    {
        "type": "function",
        "name": "inspect_csv",
        "description": (
            "Inspecte la structure d'un fichier CSV : "
            "nombre de lignes, colonnes, types, valeurs nulles "
            "et doublons."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV."
                }
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "profile_csv",
        "description": (
            "Produit un profil statistique des colonnes numériques "
            "d'un fichier CSV : minimum, maximum, moyenne et médiane."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV."
                }
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "validate_csv",
        "description": (
            "Valide la qualité d'un fichier CSV en vérifiant "
            "les valeurs nulles, les doublons, les quantités invalides, "
            "les prix négatifs et les produits vides."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV."
                }
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "validate_contract",
        "description": (
            "Compare un fichier CSV avec un contrat de données JSON si fourni. "
            "Si aucun contrat n'est fourni, infère le schéma du fichier. "
            "Vérifie les colonnes manquantes ou supplémentaires, "
            "les types, les valeurs nulles et les contraintes minimales."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV."
                },
                "contract_path": {
                    "type": "string",
                    "description": "Chemin du contrat JSON."
                }
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "determine_ingestion_decision",
        "description": (
            "Détermine si un fichier doit être INGEST, "
            "QUARANTINE ou REJECT à partir des résultats "
            "du Data Contract et des contrôles de qualité."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "contract_result": {
                    "type": "object",
                    "description": "Résultat de la validation du Data Contract."
                },
                "quality_result": {
                    "type": "object",
                    "description": "Résultat de la validation de qualité."
                }
            },
            "required": [
                "contract_result",
                "quality_result"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "ingest_csv",
        "description": (
            "Ingère un fichier CSV validé dans la zone Bronze "
            "au format Parquet. Utilise cet outil uniquement "
            "si la décision d'ingestion est INGEST."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV à ingérer."
                },
                "dataset": {
                    "type": "string",
                    "description": "Nom du dataset."
                }
            },
            "required": [
                "file_path",
                "dataset"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "quarantine_csv",
        "description": (
            "Place un fichier CSV dans la zone de quarantaine. "
            "Utiliser uniquement lorsque la décision est QUARANTINE."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV."
                },
                "reason": {
                    "type": "string",
                    "description": "Raison de la mise en quarantaine."
                }
            },
            "required": [
                "file_path",
                "reason"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "reject_csv",
        "description": (
            "Place un fichier CSV dans la zone des fichiers rejetés. "
            "Utiliser uniquement lorsque la décision est REJECT."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier CSV."
                },
                "reason": {
                    "type": "string",
                    "description": "Raison du rejet."
                }
            },
            "required": [
                "file_path",
                "reason"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "transform_to_silver",
        "description": (
            "Transforme un fichier Parquet Bronze en fichier Parquet Silver. "
            "Ajoute les transformations nécessaires aux données de ventes, "
            "notamment le calcul de line_amount."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bronze_file_path": {
                    "type": "string",
                    "description": "Chemin du fichier Bronze."
                },
                "silver_file_path": {
                    "type": "string",
                    "description": "Chemin du fichier Silver."
                }
            },
            "required": [
                "bronze_file_path",
                "silver_file_path"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "build_sales_gold",
        "description": (
            "Construit la couche Gold des ventes à partir "
            "de la couche Silver. Agrège les ventes par produit "
            "et calcule les quantités, ventes totales, prix moyen "
            "et nombre de lignes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "silver_file_path": {
                    "type": "string",
                    "description": "Chemin du fichier Silver."
                },
                "output_file_path": {
                    "type": "string",
                    "description": "Chemin du fichier Gold."
                }
            },
            "required": [
                "silver_file_path",
                "output_file_path"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "publish_to_fabric",
        "description": (
            "Publie les données Gold vers Microsoft Fabric. "
            "Uploader un dataset Parquet dans Fabric pour l'analyser avec Power BI. "
            "Appelle cet outil après build_sales_gold avec succès."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier Parquet à publier."
                },
                "dataset_name": {
                    "type": "string",
                    "description": "Nom du dataset dans Fabric."
                },
                "table_name": {
                    "type": "string",
                    "description": "Nom de la table (défaut: 'data')."
                },
                "mode": {
                    "type": "string",
                    "description": "Mode de publication: 'incremental' ou 'full_refresh'."
                }
            },
            "required": [
                "file_path",
                "dataset_name"
            ],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "analyze_gold_data",
        "description": (
            "Analyse les données Gold comme un Data Analyst. "
            "Génère: statistiques, qualité, distributions, corrélations, "
            "anomalies, segments, insights et recommandations. "
            "Appelle cet outil après avoir publié dans Fabric pour proposer "
            "des analyses intelligentes à l'utilisateur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier Parquet Gold à analyser."
                }
            },
            "required": ["file_path"],
            "additionalProperties": False
        }
    },
]


def execute_tool(name, arguments):

    if name == "inspect_csv":
        return inspect_csv(arguments["file_path"])

    if name == "profile_csv":
        return profile_csv(arguments["file_path"])

    if name == "validate_csv":
        return validate_csv(arguments["file_path"])
        
    if name == "validate_contract":
        return validate_contract(
            arguments["file_path"],
            arguments.get("contract_path")
        )

    if name == "determine_ingestion_decision":
        return determine_ingestion_decision(
            arguments["contract_result"],
            arguments["quality_result"]
        )

    if name == "ingest_csv":
        return ingest_csv(
            arguments["file_path"],
            arguments["dataset"]
        )

    if name == "quarantine_csv":
        return quarantine_csv(
            arguments["file_path"],
            arguments["reason"]
        )
    
    if name == "reject_csv":
        return reject_csv(
            arguments["file_path"],
            arguments["reason"]
        )
    if name == "transform_to_silver":
        return transform_to_silver(
            arguments["bronze_file_path"],
            arguments["silver_file_path"]
        )


    if name == "build_sales_gold":
        return build_sales_gold(
            arguments["silver_file_path"],
            arguments["output_file_path"]
        )

    if name == "publish_to_fabric":
        return publish_to_fabric(
            file_path=arguments["file_path"],
            dataset_name=arguments["dataset_name"],
            table_name=arguments.get("table_name", "data"),
            mode=arguments.get("mode", "incremental")
        )

    if name == "analyze_gold_data":
        return analyze_gold_data(
            file_path=arguments["file_path"]
        )

    raise ValueError(f"Outil inconnu : {name}")


def run_agent(user_request: str):

    response = client.responses.create(
        model="gpt-5.6",
        instructions=(
            "Tu es un Data Engineer et Data Analyst senior. "
            "Tu dois : ingérer les données, les valider, les transformer, "
            "les publier dans Microsoft Fabric, et proposer des analyses. "

            "Tu disposes d'outils déterministes pour : inspecter, profiler, "
            "valider, transformer, publier (Fabric) et analyser les données. "

            "Utilise les résultats réels des outils comme source de vérité. "
            "N'invente jamais de données. "

            "Ne répète pas un outil avec exactement les mêmes arguments "
            "si son résultat est déjà disponible. "

            "Lorsque toutes les informations nécessaires sont disponibles, "
            "arrête l'utilisation des outils et produis immédiatement "
            "la réponse finale en français. "

            "=== INGESTION ET VALIDATION === "
            "Pour une décision d'ingestion, utilise validate_contract et validate_csv. "
            "Le contrat est facultatif : sans contrat, accepte le schéma inféré. "
            "La décision INGEST, QUARANTINE ou REJECT doit provenir "
            "de determine_ingestion_decision. "
            "Après une décision INGEST, appelle ingest_csv. "
            "Si la décision est QUARANTINE ou REJECT, n'appelle jamais ingest_csv. "
            "Ne modifie jamais la décision produite par determine_ingestion_decision. "

            "=== TRANSFORMATION === "
            "Après INGEST, transforme Bronze → Silver → Gold. "
            "Utilise des chemins dérivés du nom du dataset. "
            "Le parcours sales peut calculer line_amount et agréger par produit ; "
            "pour tout autre schéma, conserve les colonnes et produis une table Gold générique. "
            "Si ingest_csv retourne SKIPPED (fichier déjà ingéré), "
            "continue quand même si les fichiers existent. "
            "Ne construis jamais Silver/Gold si décision = QUARANTINE/REJECT. "

            "=== PUBLICATION FABRIC === "
            "Après build_sales_gold avec succès, publie obligatoirement "
            "les données dans Microsoft Fabric. "
            "Utilise publish_to_fabric avec : "
            "le fichier Gold produit pour le dataset courant, "
            "avec un nom de dataset Fabric dérivé du dataset courant. "
            "C'est obligatoire pour exposer les données à Power BI. "

            "=== ANALYSE DATA === "
            "Après la publication Fabric, analyse obligatoirement "
            "les données Gold. "
            "Utilise analyze_gold_data avec le chemin Gold. "
            "Cet outil génère : statistiques, qualité, distributions, "
            "corrélations, anomalies, segments, insights et recommandations. "
            "Présente-les en langage naturel clair pour l'utilisateur. "

            "=== RÈGLES CRITIQUES === "
            "1. Ne saute aucune étape du pipeline. "
            "2. Analyse = obligatoire après Fabric. "
            "3. Utilise exactement les chemins fournis. "
            "4. Aucune donnée inventée. "
            "5. Réponds toujours en français. "
        ),
        input=user_request,
        tools=tools,
    )

    MAX_ITERATIONS = 15
    executed_calls = set()

    for iteration in range(MAX_ITERATIONS):

        function_calls = [
            item
            for item in response.output
            if item.type == "function_call"
        ]

        # Aucun outil supplémentaire : réponse finale
        if not function_calls:

            for item in response.output:

                if item.type == "message":

                    for content in item.content:

                        if content.type == "output_text":
                            return content.text

            return response.output_text

        tool_outputs = []

        for item in function_calls:

            arguments = json.loads(item.arguments)

            call_signature = (
                item.name,
                json.dumps(arguments, sort_keys=True)
            )

            if call_signature in executed_calls:
                raise RuntimeError(
                    f"L'agent tente de répéter inutilement "
                    f"l'outil {item.name} avec les mêmes arguments."
                )

            executed_calls.add(call_signature)

            print(f"\nOutil appelé : {item.name}")
            print(f"Arguments : {arguments}")

            result = execute_tool(
                item.name,
                arguments
            )

            if item.name == "publish_to_fabric" and isinstance(result, dict):
                if result.get("status") == "AUTH_REQUIRED":
                    raise FabricAuthenticationRequired(result)

            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(
                        result,
                        ensure_ascii=False
                    ),
                }
            )

        response = client.responses.create(
            model="gpt-5.6",
            instructions=(
                "Les outils viennent d'être exécutés. "
                "Utilise leurs résultats comme source de vérité. "
                "N'invente aucune donnée. "

                "Ne rappelle jamais un outil déjà exécuté avec "
                "exactement les mêmes arguments. "

                "=== APRÈS INGESTION === "
                "Si determine_ingestion_decision retourne INGEST, "
                "le pipeline doit continuer après ingest_csv. "
                "Même si ingest_csv retourne SKIPPED (fichier déjà ingéré), "
                "considère l'étape Bronze comme disponible et continue. "

                "=== TRANSFORMATION OBLIGATOIRE === "
                "Après ingest_csv, appelle obligatoirement transform_to_silver avec les chemins "
                "Bronze et Silver dérivés du dataset courant. "

                "Après transform_to_silver, appelle obligatoirement build_sales_gold avec les chemins "
                "Silver et Gold dérivés du dataset courant. "

                "=== PUBLICATION FABRIC OBLIGATOIRE === "
                "Après build_sales_gold avec succès, appelle obligatoirement "
                "publish_to_fabric avec le fichier Gold et le nom du dataset courant. "

                "=== ANALYSE OBLIGATOIRE === "
                "Après publish_to_fabric avec succès, appelle obligatoirement "
                "analyze_gold_data avec le fichier Gold du dataset courant. "
                "Puis synthétise les insights de cette analyse dans ta réponse finale. "

                "=== CAS QUARANTINE/REJECT === "
                "Si la décision est QUARANTINE ou REJECT, "
                "n'appelle pas les transformations Silver/Gold, "
                "ni publish_to_fabric, ni analyze_gold_data. "

                "=== RÉPONSE FINALE === "
                "Lorsque l'analyse est complète, produis la réponse finale "
                "en français, incluant les insights analytiques. "
            ),
            previous_response_id=response.id,
            input=[
                {
                    "role": "user",
                    "content": user_request,
                },
                *tool_outputs,
            ],
            tools=tools,
        )

    raise RuntimeError(
        f"L'agent a atteint la limite de {MAX_ITERATIONS} "
        "itérations sans produire de réponse finale."
    )


def run_agent_planned(user_request: str):

    plan = generate_pipeline_plan(
        client,
        user_request,
    )

    print("\nPlan d'exécution validé :")
    print(f"Fichier : {plan.file_path}")
    print(f"Contrat : {plan.contract_path}")

    print("\nÉtapes :")

    if plan.inspect:
        print("- inspect_csv")

    if plan.profile:
        print("- profile_csv")

    if plan.validate_quality:
        print("- validate_csv")

    if plan.validate_contract:
        print("- validate_contract")

    if plan.decision:
        print("- determine_ingestion_decision")

    if plan.ingest:
        print("- ingest_csv")

    if plan.transform_to_silver:
        print("- transform_to_silver")

    if plan.build_gold:
        print("- build_sales_gold")

    if plan.quarantine:
        print("- quarantine_csv")

    if plan.reject:
        print("- reject_csv")

    return plan


"""def run_agent_orchestrated(user_request: str):
    
    Génère un PipelinePlan avec le LLM puis l'exécute
    avec l'orchestrateur déterministe.
    

    plan = generate_pipeline_plan(
        client,
        user_request,
    )

    return execute_pipeline(
        plan,
        execute_tool,
    )"""


def run_agent_orchestrated(user_request: str):

    plan = generate_pipeline_plan(
        client,
        user_request,
    )

    print("\n=== PIPELINE PLAN ===")
    print(plan)

    return execute_pipeline(
        plan,
        execute_tool,
    )


if __name__ == "__main__":

    request = input("Que voulez-vous que je fasse ? ")

    mode = input(
        "Mode [classic/orchestrated] : "
    ).strip().lower()

    if mode == "orchestrated":
        result = run_agent_orchestrated(request)

        print("\nRésultat du pipeline orchestré :")
        print(result)

    else:
        result = run_agent(request)

        print("\nRéponse de l'agent :")
        print(result)
