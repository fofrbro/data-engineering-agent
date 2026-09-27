"""
EXECUTE -> VERIFY -> AUDIT d'un AgentPlan validé.

- Aucune exécution sans contrat VALIDATED.
- La décision est recalculée par le Policy Engine au moment de
  l'exécution, à partir de validations réelles : la décision
  prévisionnelle du plan n'est jamais réutilisée.
- Seule une décision INGEST mène à Bronze, Silver et Gold.
- VERIFY contrôle les fichiers produits et la cohérence des
  totaux ; un contrôle en échec fait échouer le run.
- Chaque étape est horodatée et le run est audité, qu'il
  réussisse, soit bloqué par la politique ou échoue.
"""

import shutil
from uuid import uuid4
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.audit import (
    create_audit_record,
    create_run_id,
    finish_audit,
    record_output,
    record_step,
)
from src.audit_explain import explain_audit, format_run_explanation
from src.audit_store import DEFAULT_AUDIT_PATH, append_audit
from src.discovery.readers import read_dataframe
from src.execution.gold_executor import (
    METRIC_PATTERN,
    apply_exclusion,
    build_gold_tables,
)
from src.execution.silver_executor import (
    APPLIED,
    apply_silver_transformations,
)
from src.tools.contract_validation import validate_contract
from src.tools.data_validation import validate_csv
from src.tools.ingestion_decision import (
    RULE_PASSED_WITH_WARNINGS,
    determine_ingestion_decision,
)
from src.workflow.agent_workflow import (
    BLOCKED,
    EXECUTED,
    FAILED,
    AgentPlan,
    WorkflowError,
    validation_status,
)


# Tolérance des contrôles de totaux (arrondis décimaux).
TOTAL_TOLERANCE = 1e-6

STEP_STATUSES = {"SUCCESS", "SKIPPED", "QUARANTINED", "REJECTED", "FAILED"}


@dataclass
class ExecutionResult:
    run_id: str
    final_status: str
    decision: str | None
    outputs: dict[str, str] = field(default_factory=dict)
    verification: list[dict] = field(default_factory=list)
    explanation: str = ""
    # Décision et run de chaque fichier du plan.
    file_results: list[dict] = field(default_factory=list)


class _AuditedRun:
    """Exécute des étapes horodatées et les enregistre dans l'audit."""

    def __init__(self, audit: dict):
        self.audit = audit

    def step(self, name: str, action):
        started_at = datetime.now(timezone.utc)

        try:
            result = action()
        except Exception as exc:
            record_step(
                self.audit,
                name=name,
                status="FAILED",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error=str(exc),
            )
            raise

        status = result.get("status") if isinstance(result, dict) else None

        record_step(
            self.audit,
            name=name,
            status=status if status in STEP_STATUSES else "SUCCESS",
            result=result,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )

        return result


def _write(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path.as_posix()


def _route(file_path: str, folder: Path, status: str, reason: str) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / Path(file_path).name
    shutil.copy2(file_path, destination)

    return {
        "status": status,
        "file": destination.as_posix(),
        "reason": reason,
    }


def _date_column(plan: AgentPlan) -> str | None:
    for step in plan.recommendation.transformations:
        if step.id == "derive_date_parts":
            return step.columns[0]

    return None


def _business_rules(plan: AgentPlan) -> dict:
    for step in plan.recommendation.transformations:
        if step.id == "validate_business_rules":
            return step.parameters["rules"]

    return {}


def verify_outputs(
    plan: AgentPlan,
    bronze: pd.DataFrame,
    silver_result,
    gold: dict[str, pd.DataFrame],
    outputs: dict[str, str],
) -> dict:
    """
    VERIFY : contrôles déterministes des résultats.
    """

    checks = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    silver = silver_result.data
    expected_rows = {
        "bronze": len(bronze),
        "silver": len(silver),
        **{name: len(table) for name, table in gold.items()},
    }

    for name, path in outputs.items():
        if name not in expected_rows:
            continue

        exists = Path(path).exists()
        rows = len(pd.read_parquet(path)) if exists else None
        check(
            f"file:{name}",
            exists and rows == expected_rows[name],
            f"{path} : {rows} ligne(s), attendu {expected_rows[name]}",
        )

    applied = [r for r in silver_result.reports if r.status == APPLIED]
    removed = sum(r.rows_before - r.rows_after - r.quarantined_rows for r in applied)
    quarantined = sum(r.quarantined_rows for r in applied)
    check(
        "row_reconciliation",
        len(bronze) - removed - quarantined == len(silver),
        f"bronze {len(bronze)} - supprimées {removed} - quarantaine "
        f"{quarantined} = silver {len(silver)}",
    )

    for column, rule in _business_rules(plan).items():
        if rule.get("nullable") is False and column in silver.columns:
            nulls = int(silver[column].isna().sum())
            check(
                f"not_null:{column}",
                nulls == 0,
                f"{nulls} valeur(s) nulle(s) dans Silver",
            )

    for table in plan.recommendation.gold:
        for metric in table.metrics:
            match = METRIC_PATTERN.match(metric.expression)

            if not match or match.group(1) != "SUM":
                continue

            column = match.group(2)
            gold_total = float(gold[table.name][metric.name].sum())
            kept = apply_exclusion(silver, metric.exclusion)
            silver_total = float(pd.to_numeric(kept[column]).sum())
            check(
                f"total:{table.name}.{metric.name}",
                abs(gold_total - silver_total) <= TOTAL_TOLERANCE,
                f"Gold {gold_total} / Silver {silver_total}",
            )

    return {
        "status": "SUCCESS" if all(c["passed"] for c in checks) else "FAILED",
        "checks": checks,
    }


def _new_audit(plan: AgentPlan, source_file: str, batch_id: str) -> dict:
    audit = create_audit_record(
        run_id=create_run_id(),
        source_file=source_file,
        contract_path=plan.contract_path,
    )
    audit["execution_mode"] = "INGEST"
    audit["plan_id"] = plan.plan_id
    audit["batch_id"] = batch_id
    return audit


def _fail(audit: dict, error: Exception, audit_path) -> None:
    finish_audit(
        audit,
        status="FAILED",
        decision=audit.get("decision"),
        execution_mode="INGEST",
        error=str(error),
    )
    append_audit(audit, audit_path)


def _assess(plan: AgentPlan, path: str, audit: dict) -> dict:
    """Évaluation d'un fichier, étapes enregistrées dans son audit."""

    run = _AuditedRun(audit)
    quality = run.step("validate_csv", lambda: validate_csv(path, plan.contract_path))
    contract = run.step(
        "validate_contract", lambda: validate_contract(path, plan.contract_path),
    )
    decision = run.step(
        "determine_ingestion_decision",
        lambda: determine_ingestion_decision(contract, quality),
    )

    audit["decision"] = decision["decision"]
    audit["policy_rule"] = decision["policy_rule"]
    audit["decision_reason"] = decision["reason"]

    return decision


def _isolate(path: str, decision: dict, audit: dict, root: Path, audit_path) -> ExecutionResult:
    """Fichier refusé : quarantaine ou rejet, dans son propre run."""

    quarantine = decision["decision"] == "QUARANTINE"
    _AuditedRun(audit).step(
        "quarantine_file" if quarantine else "reject_file",
        lambda: _route(
            path,
            root / ("quarantine" if quarantine else "rejected"),
            "QUARANTINED" if quarantine else "REJECTED",
            decision["reason"],
        ),
    )
    finish_audit(
        audit,
        status="QUARANTINED" if quarantine else "REJECTED",
        decision=decision["decision"],
        execution_mode="INGEST",
    )
    return _result(audit, {}, {}, audit_path)


def _combined_audit(plan: AgentPlan, accepted: list, batch_id: str) -> dict:
    """
    Run unique des fichiers INGEST. Pour un seul fichier, c'est son
    propre audit ; pour plusieurs, un run qui reprend leurs étapes
    d'évaluation, dans l'ordre.
    """

    if len(accepted) == 1:
        return accepted[0][2]

    audit = _new_audit(plan, ", ".join(path for path, _, _ in accepted), batch_id)
    audit["started_at"] = accepted[0][2]["started_at"]
    audit["steps"] = [step for _, _, file_audit in accepted for step in file_audit["steps"]]
    rules = {decision["policy_rule"] for _, decision, _ in accepted}
    audit["decision"] = "INGEST"
    audit["policy_rule"] = rules.pop() if len(rules) == 1 else RULE_PASSED_WITH_WARNINGS
    audit["decision_reason"] = (
        f"{len(accepted)} fichiers admis et combinés : "
        + " ; ".join(f"{path} : {decision['reason']}" for path, decision, _ in accepted)
    )
    return audit


def execute_plan(
    plan: AgentPlan,
    output_root: str | Path = "data",
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
) -> ExecutionResult:
    """
    EXECUTE -> VERIFY -> AUDIT.

    Chaque fichier du plan reçoit sa propre décision. Les fichiers
    refusés sont isolés, chacun dans son run ; les fichiers INGEST sont
    combinés dans un seul run Bronze -> Silver -> Gold. Tous les runs
    d'une exécution partagent un batch_id.

    Lève WorkflowError si le plan n'est pas prêt : rien n'est
    exécuté ni écrit.
    """

    status = validation_status(plan)

    if not status["ready_to_execute"]:
        raise WorkflowError(" ".join(status["blockers"]))

    root = Path(output_root)
    batch_id = str(uuid4())
    accepted = []
    file_results = []
    last_refused = None

    for path in plan.file_paths:
        audit = _new_audit(plan, path, batch_id)

        try:
            decision = _assess(plan, path, audit)

            if decision["decision"] != "INGEST":
                last_refused = _isolate(path, decision, audit, root, audit_path)
                file_results.append(
                    {
                        "file": path,
                        "decision": decision["decision"],
                        "policy_rule": decision["policy_rule"],
                        "run_id": audit["run_id"],
                        "final_status": audit["final_status"],
                    }
                )
                continue
        except Exception as exc:
            plan.status = FAILED
            _fail(audit, exc, audit_path)
            raise

        accepted.append((path, decision, audit))

    if not accepted:
        plan.status = BLOCKED

        if len(file_results) > 1:
            decisions = {result["decision"] for result in file_results}
            last_refused.decision = decisions.pop() if len(decisions) == 1 else "PARTIAL"
            last_refused.final_status = BLOCKED

        last_refused.file_results = file_results
        return last_refused

    audit = _combined_audit(plan, accepted, batch_id)
    run = _AuditedRun(audit)
    outputs: dict[str, str] = {}
    verification: dict = {}

    try:
        recommendation = plan.recommendation
        frames = {path: read_dataframe(path) for path, _, _ in accepted}
        bronze = pd.concat(frames.values(), ignore_index=True)

        def write_bronze():
            outputs["bronze"] = _write(
                bronze, root / "bronze" / f"{recommendation.bronze['table']}.parquet"
            )
            record_output(audit, path=outputs["bronze"], layer="bronze")
            return {
                "rows": len(bronze),
                "file": outputs["bronze"],
                "rows_by_file": {path: len(frame) for path, frame in frames.items()},
            }

        run.step("write_bronze", write_bronze)

        silver_result = None

        def write_silver():
            nonlocal silver_result
            silver_result = apply_silver_transformations(
                bronze,
                recommendation.transformations,
                destructive_approved=plan.destructive_approval is not None,
            )
            outputs["silver"] = _write(
                silver_result.data,
                root / "silver" / f"{recommendation.silver['table']}.parquet",
            )
            record_output(audit, path=outputs["silver"], layer="silver")

            if len(silver_result.quarantined):
                outputs["quarantined_rows"] = _write(
                    silver_result.quarantined,
                    root / "quarantine" / f"{plan.dataset}_rows.parquet",
                )
                record_output(audit, path=outputs["quarantined_rows"], layer="quarantine")

            return {
                "rows": len(silver_result.data),
                "quarantined_rows": len(silver_result.quarantined),
                "transformations": [r.to_dict() for r in silver_result.reports],
            }

        run.step("transform_silver", write_silver)

        gold = {}

        def write_gold():
            gold.update(
                build_gold_tables(
                    silver_result.data, recommendation.gold, _date_column(plan),
                )
            )
            for name, table in gold.items():
                outputs[name] = _write(table, root / "gold" / f"{name}.parquet")
                record_output(audit, path=outputs[name], layer="gold")
            return {"tables": {name: len(table) for name, table in gold.items()}}

        run.step("build_gold", write_gold)

        verification = run.step(
            "verify_outputs",
            lambda: verify_outputs(plan, bronze, silver_result, gold, outputs),
        )

        failed_checks = [c["check"] for c in verification["checks"] if not c["passed"]]
        plan.status = FAILED if failed_checks else EXECUTED
        finish_audit(
            audit,
            status="FAILED" if failed_checks else "SUCCESS",
            decision="INGEST",
            execution_mode="INGEST",
            error=(
                f"Vérification échouée : {', '.join(failed_checks)}"
                if failed_checks
                else None
            ),
        )
        result = _result(audit, outputs, verification, audit_path)

    except Exception as exc:
        plan.status = FAILED
        _fail(audit, exc, audit_path)
        raise

    for path, decision, _ in accepted:
        file_results.append(
            {
                "file": path,
                "decision": "INGEST",
                "policy_rule": decision["policy_rule"],
                "run_id": result.run_id,
                "final_status": result.final_status,
            }
        )

    result.file_results = sorted(
        file_results, key=lambda item: plan.file_paths.index(item["file"])
    )
    return result


def _result(

    audit: dict,
    outputs: dict,
    verification: dict,
    audit_path: str | Path,
) -> ExecutionResult:
    append_audit(audit, audit_path)

    return ExecutionResult(
        run_id=audit["run_id"],
        final_status=audit["final_status"],
        decision=audit["decision"],
        outputs=outputs,
        verification=verification.get("checks", []),
        explanation=format_run_explanation(explain_audit(audit)),
    )
