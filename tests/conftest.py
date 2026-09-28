from pathlib import Path

import pytest

from src.audit_store import DEFAULT_AUDIT_PATH


@pytest.fixture(autouse=True)
def forbid_writing_the_real_audit(monkeypatch):
    """
    Un test ne doit jamais écrire dans data/audit/pipeline_runs.jsonl :
    il échoue s'il le tente. Les audits vers un chemin temporaire restent
    écrits normalement.
    """

    import src.workflow.plan_executor as executor

    real = executor.append_audit
    forbidden = Path(DEFAULT_AUDIT_PATH).resolve()

    def guarded(audit, output_path=DEFAULT_AUDIT_PATH):
        if Path(output_path).resolve() == forbidden:
            raise AssertionError("Un test tente d'écrire dans le vrai journal d'audit.")
        return real(audit, output_path)

    monkeypatch.setattr(executor, "append_audit", guarded)
