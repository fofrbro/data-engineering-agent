import pytest


@pytest.fixture(autouse=True)
def disable_real_audit_persistence(monkeypatch):
    """
    Empêche les tests automatisés d'écrire dans
    data/audit/pipeline_runs.jsonl.
    """

    monkeypatch.setattr(
        "src.pipeline_orchestrator.append_audit",
        lambda audit: None,
    )
