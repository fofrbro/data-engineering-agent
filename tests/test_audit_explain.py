import pytest

from src.audit_explain import (
    explain_audit,
    explain_run,
    format_run_explanation,
)
from src.audit_store import append_audit
from src.pipeline_orchestrator import execute_pipeline
from src.pipeline_plan import PipelinePlan
from src.tools.ingestion_decision import determine_ingestion_decision


def run_pipeline(contract_status, ingest=False, failing_tool=None):
    def tool(name, arguments):
        if name == failing_tool:
            raise ValueError("fichier illisible")
        if name == "validate_contract":
            return {"dataset": "sales", "valid": True, "errors_count": 0,
                    "contract_status": contract_status}
        if name == "validate_csv":
            return {"valid": True, "issues_count": 0}
        if name == "determine_ingestion_decision":
            return determine_ingestion_decision(**arguments)
        return {"status": "OK"}

    plan = PipelinePlan(
        file_path="data/sales.csv",
        contract_path="data/contracts/sales.json",
        validate_quality=True,
        validate_contract=True,
        decision=True,
        ingest=ingest,
        transform_to_silver=ingest,
    )

    return execute_pipeline(plan, tool)["audit"]


def test_ingest_decision_in_assess_only_mode_is_explained():
    explanation = explain_audit(run_pipeline("VALIDATED"))

    assert explanation["decision"] == "INGEST"
    assert explanation["execution_mode"] == "ASSESS_ONLY"
    assert explanation["meaning"] == (
        "Le fichier est admissible à l'ingestion, mais cette "
        "exécution ne l'a pas ingéré."
    )
    assert explanation["outputs"] == []


def test_ingest_run_lists_outputs_and_steps():
    explanation = explain_audit(run_pipeline("VALIDATED", ingest=True))
    text = format_run_explanation(explanation)

    assert explanation["meaning"].endswith("réellement été demandée.")
    assert explanation["outputs"] == [
        {"path": "data/silver/sales.parquet", "layer": "silver"},
    ]
    assert "Sorties : silver : data/silver/sales.parquet" in text
    assert "  5. transform_to_silver - SUCCESS (" in text


def test_quarantine_explains_why():
    explanation = explain_audit(run_pipeline("PROPOSED"))
    text = format_run_explanation(explanation)

    assert explanation["decision"] == "QUARANTINE"
    assert explanation["policy_rule"] == "CONTRACT_NOT_VALIDATED"
    assert "Pourquoi : Le Data Contract a le statut PROPOSED" in text
    assert "Signification : Le fichier n'a pas été ingéré" in text


def test_failed_run_points_to_failing_step(monkeypatch):
    import src.pipeline_orchestrator as orchestrator

    persisted = []
    monkeypatch.setattr(orchestrator, "append_audit", persisted.append)

    with pytest.raises(ValueError):
        run_pipeline("VALIDATED", failing_tool="validate_contract")

    explanation = explain_audit(persisted[0])
    text = format_run_explanation(explanation)

    assert explanation["final_status"] == "FAILED"
    assert explanation["failed_step"] == "validate_contract"
    assert "erreur : fichier illisible" in text
    assert text.splitlines()[-1] == "Étape en échec : validate_contract"


def test_legacy_audit_is_explained_without_inventing(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_audit(
        {
            "run_id": "old-run",
            "source_file": "data/sales.csv",
            "decision": "INGEST",
            "final_status": "SUCCESS",
            "steps": [{"name": "validate_csv", "status": "SUCCESS"}],
        },
        path,
    )

    text = format_run_explanation(explain_run("old-run", path))

    assert "Mode d'exécution : non enregistré (audit antérieur)" in text
    assert "Pourquoi : non enregistré (audit antérieur)" in text
    assert "Durée : inconnue" in text
    assert "  1. validate_csv - SUCCESS (inconnue)" in text


def test_unknown_run_id(tmp_path):
    with pytest.raises(KeyError):
        explain_run("missing", tmp_path / "runs.jsonl")
