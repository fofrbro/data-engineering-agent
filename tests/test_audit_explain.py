from datetime import datetime, timezone

import pytest

from src.audit_explain import (
    explain_audit,
    explain_run,
    format_run_explanation,
)
from src.audit import create_audit_record, finish_audit, record_output, record_step
from src.audit_store import append_audit
from src.tools.ingestion_decision import determine_ingestion_decision


def _step(audit, name, result=None, status="SUCCESS", error=None):
    now = datetime.now(timezone.utc)
    record_step(audit, name=name, status=status, result=result, started_at=now, finished_at=now, error=error)


def run_pipeline(contract_status, ingest=False, failing_tool=None):
    """
    Audit d'un run d'évaluation (ASSESS_ONLY) ou d'ingestion, construit
    avec les fonctions d'audit : les audits historiques en mode
    ASSESS_ONLY doivent toujours être expliqués.
    """

    audit = create_audit_record(
        run_id="run-test", source_file="data/sales.csv", contract_path="data/contracts/sales.json",
    )
    quality = {"valid": True, "issues_count": 0}
    contract = {"dataset": "sales", "valid": True, "errors_count": 0, "contract_status": contract_status}

    for name, result in (("validate_csv", quality), ("validate_contract", contract)):
        if name == failing_tool:
            _step(audit, name, status="FAILED", error="fichier illisible")
            return finish_audit(audit, status="FAILED", error="fichier illisible")

        _step(audit, name, result)

    decision = determine_ingestion_decision(contract, quality)
    _step(audit, "determine_ingestion_decision", decision)
    audit["policy_rule"] = decision["policy_rule"]
    audit["decision_reason"] = decision["reason"]
    mode = "INGEST" if ingest else "ASSESS_ONLY"

    if ingest and decision["decision"] == "INGEST":
        _step(audit, "ingest_csv")
        _step(audit, "transform_to_silver")
        record_output(audit, path="data/silver/sales.parquet", layer="silver")

    status = "SUCCESS" if decision["decision"] == "INGEST" else "QUARANTINED"
    return finish_audit(audit, status=status, decision=decision["decision"], execution_mode=mode)


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


def test_failed_run_points_to_failing_step():
    explanation = explain_audit(run_pipeline("VALIDATED", failing_tool="validate_contract"))
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
