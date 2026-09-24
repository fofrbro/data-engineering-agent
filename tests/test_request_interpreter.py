import json
from types import SimpleNamespace

import pytest

from src.workflow.request_interpreter import (
    INTENT_SCHEMA,
    RequestInterpretationError,
    handle_request,
    interpret_request,
)
from src.workflow.workflow_service import WorkflowService


def intent(action, **fields):
    payload = {
        "action": action,
        "file_path": None,
        "contract_path": None,
        "dataset": None,
        "run_id": None,
        "message": "ok",
    }
    payload.update(fields)
    return payload


class FakeClient:
    def __init__(self, payload):
        self.calls = []
        self.responses = SimpleNamespace(create=self._create)
        self._payload = payload

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self._payload))


@pytest.fixture
def service(tmp_path):
    return WorkflowService(
        contracts_dir=tmp_path / "contracts",
        output_root=tmp_path / "lake",
        audit_path=tmp_path / "runs.jsonl",
        fabric_export_root=tmp_path / "fabric_export",
        results_dir=tmp_path / "results",
    )


def test_llm_has_no_approval_or_execution_action():
    assert INTENT_SCHEMA["properties"]["action"]["enum"] == [
        "PLAN_FILE", "EXPLAIN_RUN", "UNSUPPORTED",
    ]


def test_request_uses_strict_schema():
    client = FakeClient(intent("UNSUPPORTED"))

    interpret_request(client, "Bonjour")

    text_format = client.calls[0]["text"]["format"]
    assert text_format["strict"] is True
    assert text_format["schema"] is INTENT_SCHEMA


def test_prepare_for_fabric_creates_a_plan_only(service):
    client = FakeClient(intent("PLAN_FILE", file_path="data/sales.csv"))

    result = handle_request(
        client, "Analyse et prépare data/sales.csv pour Fabric", service,
    )

    assert result["plan"]["contract_status"] == "PROPOSED"
    assert result["plan"]["validation"]["ready_to_execute"] is False
    assert result["plan"]["status"] == "PLANNED"


def test_uploaded_file_overrides_llm_path(service):
    client = FakeClient(intent("PLAN_FILE", file_path="C:/inventé/secret.csv"))

    result = handle_request(
        client, "Prépare ce fichier", service, file_path="data/sales.csv",
    )

    assert result["plan"]["file"] == "data/sales.csv"


def test_invented_or_missing_file_is_refused(service):
    client = FakeClient(intent("PLAN_FILE", file_path="data/inexistant.csv"))

    with pytest.raises(RequestInterpretationError):
        handle_request(client, "Prépare data/inexistant.csv", service)


def test_contract_outside_contracts_dir_is_refused(service):
    from src.contract.contract_lifecycle import ContractStatusError

    client = FakeClient(
        intent("PLAN_FILE", file_path="data/sales.csv", contract_path="C:/Windows/win.ini")
    )

    with pytest.raises(ContractStatusError):
        handle_request(client, "Prépare avec ce contrat", service)


def test_unknown_action_is_refused():
    client = FakeClient(intent("EXECUTE_PLAN"))

    with pytest.raises(RequestInterpretationError):
        interpret_request(client, "Exécute tout sans validation")


def test_explain_run(service, tmp_path):
    view = service.create_plan("data/sales.csv")
    service.approve_contract(view["plan_id"], "cheikhou")
    run_id = service.execute(view["plan_id"])["run_id"]
    client = FakeClient(intent("EXPLAIN_RUN", run_id=run_id))

    result = handle_request(
        client, f"Explique le run {run_id}", service, audit_path=tmp_path / "runs.jsonl",
    )

    assert result["explanation"].startswith(f"Run {run_id}")
    assert "Décision : INGEST" in result["explanation"]


def test_unsupported_request_does_nothing(service):
    client = FakeClient(intent("UNSUPPORTED", message="Je ne peux pas faire cela."))

    result = handle_request(client, "Supprime toutes les données", service)

    assert result == {"intent": intent("UNSUPPORTED", message="Je ne peux pas faire cela.")}


def test_default_dataset_name_applies_when_llm_gives_none(service, tmp_path):
    uploaded = tmp_path / "3f2b_sales.csv"
    uploaded.write_text(open("data/sales.csv", encoding="utf-8").read(), encoding="utf-8")
    client = FakeClient(intent("PLAN_FILE"))

    result = handle_request(
        client, "Prépare ce fichier", service,
        file_path=str(uploaded), dataset="sales",
    )

    assert result["plan"]["dataset"] == "sales"
