import json
from types import SimpleNamespace

import src.agent as agent


def make_function_call(name, arguments, call_id):
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=json.dumps(arguments),
        call_id=call_id,
    )


def make_final_message(text):
    content = SimpleNamespace(
        type="output_text",
        text=text,
    )

    return SimpleNamespace(
        type="message",
        content=[content],
    )


def make_response(response_id, output):
    return SimpleNamespace(
        id=response_id,
        output=output,
        output_text="",
    )


def run_scenario(monkeypatch, responses, tool_results, user_request):
    """
    Exécute un scénario d'agent avec OpenAI et les outils simulés.
    """

    responses = list(responses)
    create_calls = []
    executed_tools = []

    def fake_create(*args, **kwargs):
        create_calls.append(kwargs)
        return responses.pop(0)

    def fake_execute_tool(name, arguments):
        executed_tools.append((name, arguments))

        key = name

        if key not in tool_results:
            raise AssertionError(
                f"Résultat simulé manquant pour l'outil {name}"
            )

        result = tool_results[key]

        if callable(result):
            return result(arguments)

        return result

    monkeypatch.setattr(
        agent.client.responses,
        "create",
        fake_create,
    )

    monkeypatch.setattr(
        agent,
        "execute_tool",
        fake_execute_tool,
    )

    result = agent.run_agent(user_request)

    return result, executed_tools, create_calls


def test_agent_ingest_pipeline(monkeypatch):
    responses = [
        make_response(
            "resp_1",
            [
                make_function_call(
                    "determine_ingestion_decision",
                    {
                        "contract_result": {
                            "valid": True,
                            "errors_count": 0,
                        },
                        "quality_result": {
                            "valid": True,
                            "issues_count": 0,
                        },
                    },
                    "call_1",
                )
            ],
        ),
        make_response(
            "resp_2",
            [
                make_function_call(
                    "ingest_csv",
                    {
                        "file_path": "data/sales.csv",
                        "dataset": "sales",
                    },
                    "call_2",
                )
            ],
        ),
        make_response(
            "resp_3",
            [
                make_function_call(
                    "transform_to_silver",
                    {
                        "bronze_file_path": "data/bronze/sales.parquet",
                        "silver_file_path": "data/silver/sales.parquet",
                    },
                    "call_3",
                )
            ],
        ),
        make_response(
            "resp_4",
            [
                make_function_call(
                    "build_sales_gold",
                    {
                        "silver_file_path": "data/silver/sales.parquet",
                        "output_file_path": "data/gold/sales_by_product.parquet",
                    },
                    "call_4",
                )
            ],
        ),
        make_response(
            "resp_5",
            [
                make_final_message("Pipeline terminé.")
            ],
        ),
    ]

    tool_results = {
        "determine_ingestion_decision": {
            "decision": "INGEST"
        },
        "ingest_csv": {
            "status": "INGESTED"
        },
        "transform_to_silver": {
            "status": "TRANSFORMED"
        },
        "build_sales_gold": {
            "status": "TRANSFORMED"
        },
    }

    result, executed_tools, _ = run_scenario(
        monkeypatch,
        responses,
        tool_results,
        "Analyse et ingère sales.csv.",
    )

    assert result == "Pipeline terminé."

    assert [name for name, _ in executed_tools] == [
        "determine_ingestion_decision",
        "ingest_csv",
        "transform_to_silver",
        "build_sales_gold",
    ]


def test_agent_quarantine_pipeline(monkeypatch):
    responses = [
        make_response(
            "resp_1",
            [
                make_function_call(
                    "determine_ingestion_decision",
                    {
                        "contract_result": {
                            "valid": True,
                            "errors_count": 0,
                        },
                        "quality_result": {
                            "valid": False,
                            "issues_count": 1,
                        },
                    },
                    "call_1",
                )
            ],
        ),
        make_response(
            "resp_2",
            [
                make_function_call(
                    "quarantine_csv",
                    {
                        "file_path": "data/test_quarantine.csv",
                        "reason": "Problème de qualité.",
                    },
                    "call_2",
                )
            ],
        ),
        make_response(
            "resp_3",
            [
                make_final_message("Fichier mis en quarantaine.")
            ],
        ),
    ]

    tool_results = {
        "determine_ingestion_decision": {
            "decision": "QUARANTINE"
        },
        "quarantine_csv": {
            "status": "QUARANTINED"
        },
    }

    result, executed_tools, _ = run_scenario(
        monkeypatch,
        responses,
        tool_results,
        "Analyse le fichier avant ingestion.",
    )

    assert result == "Fichier mis en quarantaine."

    assert [name for name, _ in executed_tools] == [
        "determine_ingestion_decision",
        "quarantine_csv",
    ]


def test_agent_reject_pipeline(monkeypatch):
    responses = [
        make_response(
            "resp_1",
            [
                make_function_call(
                    "determine_ingestion_decision",
                    {
                        "contract_result": {
                            "valid": False,
                            "errors_count": 1,
                        },
                        "quality_result": {
                            "valid": False,
                            "issues_count": 1,
                        },
                    },
                    "call_1",
                )
            ],
        ),
        make_response(
            "resp_2",
            [
                make_function_call(
                    "reject_csv",
                    {
                        "file_path": "data/test_contract.csv",
                        "reason": "Data Contract non respecté.",
                    },
                    "call_2",
                )
            ],
        ),
        make_response(
            "resp_3",
            [
                make_final_message("Fichier rejeté.")
            ],
        ),
    ]

    tool_results = {
        "determine_ingestion_decision": {
            "decision": "REJECT"
        },
        "reject_csv": {
            "status": "REJECTED"
        },
    }

    result, executed_tools, _ = run_scenario(
        monkeypatch,
        responses,
        tool_results,
        "Analyse le fichier avant ingestion.",
    )

    assert result == "Fichier rejeté."

    assert [name for name, _ in executed_tools] == [
        "determine_ingestion_decision",
        "reject_csv",
    ]


def test_run_agent_planned(monkeypatch):

    planned_data = {
        "file_path": "data/sales.csv",
        "contract_path": "data/contracts/sales_contract.json",
        "inspect": True,
        "profile": True,
        "validate_quality": True,
        "validate_contract": True,
        "decision": True,
        "ingest": True,
        "transform_to_silver": True,
        "build_gold": True,
        "quarantine": False,
        "reject": False,
        "steps": [
            "inspect",
            "profile",
            "validate_quality",
            "validate_contract",
            "decision",
            "ingest",
            "transform_to_silver",
            "build_gold",
        ],
    }

    class FakePlan:
        file_path = planned_data["file_path"]
        contract_path = planned_data["contract_path"]
        inspect = planned_data["inspect"]
        profile = planned_data["profile"]
        validate_quality = planned_data["validate_quality"]
        validate_contract = planned_data["validate_contract"]
        decision = planned_data["decision"]
        ingest = planned_data["ingest"]
        transform_to_silver = planned_data["transform_to_silver"]
        build_gold = planned_data["build_gold"]
        quarantine = planned_data["quarantine"]
        reject = planned_data["reject"]

    monkeypatch.setattr(
        agent,
        "generate_pipeline_plan",
        lambda client, request: FakePlan(),
    )

    plan = agent.run_agent_planned(
        "Analyse et ingère data/sales.csv."
    )

    assert plan.file_path == "data/sales.csv"
    assert plan.contract_path == (
        "data/contracts/sales_contract.json"
    )

    assert plan.ingest is True
    assert plan.transform_to_silver is True
    assert plan.build_gold is True

    assert plan.quarantine is False
    assert plan.reject is False



def test_run_agent_orchestrated(monkeypatch):

    planned_data = {
        "file_path": "data/sales.csv",
        "contract_path": "data/contracts/sales_contract.json",
        "inspect": True,
        "profile": True,
        "validate_quality": True,
        "validate_contract": True,
        "decision": True,
        "ingest": True,
        "transform_to_silver": True,
        "build_gold": True,
        "quarantine": False,
        "reject": False,
        "steps": [],
    }

    from src.pipeline_plan import build_pipeline_plan

    fake_plan = build_pipeline_plan(planned_data)

    monkeypatch.setattr(
        agent,
        "generate_pipeline_plan",
        lambda client, request: fake_plan,
    )

    calls = []

    def fake_execute_tool(name, arguments):
        calls.append(name)

        if name == "validate_contract":
            return {
                "dataset": "sales",
                "valid": True,
                "errors_count": 0,
            }

        if name == "validate_csv":
            return {
                "valid": True,
                "issues_count": 0,
            }

        if name == "determine_ingestion_decision":
            return {
                "decision": "INGEST",
            }

        return {
            "status": "OK",
        }

    monkeypatch.setattr(
        agent,
        "execute_tool",
        fake_execute_tool,
    )

    result = agent.run_agent_orchestrated(
        "Analyse et ingère data/sales.csv."
    )

    assert result["decision"]["decision"] == "INGEST"

    assert calls == [
        "inspect_csv",
        "profile_csv",
        "validate_csv",
        "validate_contract",
        "determine_ingestion_decision",
        "ingest_csv",
        "transform_to_silver",
        "build_sales_gold",
    ]
