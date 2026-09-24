from datetime import datetime, timezone

from src.audit import (
    create_audit_record,
    create_run_id,
    finish_audit,
    record_output,
    record_step,
)
from src.pipeline_plan import PipelinePlan
from src.audit_store import append_audit


def execute_pipeline(plan: PipelinePlan, tool_executor) -> dict:
    """
    Exécute un PipelinePlan de manière déterministe
    et produit un journal d'audit.
    """

    plan.validate()

    run_id = create_run_id()

    audit = create_audit_record(
        run_id=run_id,
        source_file=plan.file_path,
        contract_path=plan.contract_path,
    )

    execution_mode = (
        "INGEST"
        if plan.ingest
        else "ASSESS_ONLY"
    )

    audit["execution_mode"] = execution_mode

    def persist_audit() -> None:
        """
        Persiste l'audit sans jamais faire échouer le pipeline métier.
        """
        try:
            append_audit(audit)
        except Exception:
            # L'audit est important, mais ne doit pas bloquer
            # l'exécution du pipeline.
            pass

    results = {}

    def execute_step(name: str, arguments: dict):
        started_at = datetime.now(timezone.utc)

        try:
            result = tool_executor(name, arguments)
        except Exception as exc:
            # L'étape en échec reste visible dans l'audit.
            record_step(
                audit,
                name=name,
                status="FAILED",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error=str(exc),
            )
            raise

        finished_at = datetime.now(timezone.utc)

        status = "SUCCESS"

        if isinstance(result, dict):
            tool_status = result.get("status")

            if tool_status == "SKIPPED":
                status = "SKIPPED"
            elif tool_status in {
                "QUARANTINED",
                "REJECTED",
            }:
                status = tool_status

        record_step(
            audit,
            name=name,
            status=status,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
        )

        return result

    try:
        # ------------------------------
        # Inspection
        # ------------------------------

        if plan.inspect:
            results["inspect"] = execute_step(
                "inspect_csv",
                {
                    "file_path": plan.file_path,
                },
            )

        # ------------------------------
        # Profilage
        # ------------------------------

        if plan.profile:
            results["profile"] = execute_step(
                "profile_csv",
                {
                    "file_path": plan.file_path,
                },
            )

        # ------------------------------
        # Qualité
        # ------------------------------

        if plan.validate_quality:
            results["quality"] = execute_step(
                "validate_csv",
                {
                    "file_path": plan.file_path,
                },
            )

        # ------------------------------
        # Data Contract
        # ------------------------------

        if plan.validate_contract:
            results["contract"] = execute_step(
                "validate_contract",
                {
                    "file_path": plan.file_path,
                    "contract_path": plan.contract_path,
                },
            )

        # ------------------------------
        # Décision
        # ------------------------------

        if not plan.decision:
            audit = finish_audit(
                audit,
                status="SUCCESS",
            )

            results["audit"] = audit
            persist_audit()

            return results

        if "contract" not in results:
            raise ValueError(
                "La décision nécessite le résultat du Data Contract."
            )

        if "quality" not in results:
            raise ValueError(
                "La décision nécessite le résultat de qualité."
            )

        decision_result = execute_step(
            "determine_ingestion_decision",
            {
                "contract_result": results["contract"],
                "quality_result": results["quality"],
            },
        )

        results["decision"] = decision_result

        decision = decision_result["decision"]

        audit["decision"] = decision
        audit["policy_rule"] = decision_result.get("policy_rule")
        audit["decision_reason"] = decision_result.get("reason")

        # ------------------------------
        # REJECT
        # ------------------------------

        if decision == "REJECT":

            results["action"] = execute_step(
                "reject_csv",
                {
                    "file_path": plan.file_path,
                    "reason": decision_result.get(
                        "reason",
                        "Le fichier ne respecte pas "
                        "le Data Contract.",
                    ),
                },
            )

            audit = finish_audit(
                audit,
                status="REJECTED",
                decision=decision,
                execution_mode=execution_mode,
            )

            results["audit"] = audit
            persist_audit()

            return results

        # ------------------------------
        # QUARANTINE
        # ------------------------------

        if decision == "QUARANTINE":

            results["action"] = execute_step(
                "quarantine_csv",
                {
                    "file_path": plan.file_path,
                    "reason": decision_result.get(
                        "reason",
                        "Le fichier respecte le Data Contract "
                        "mais présente des problèmes de qualité.",
                    ),
                },
            )

            audit = finish_audit(
                audit,
                status="QUARANTINED",
                decision=decision,
                execution_mode=execution_mode,
            )

            results["audit"] = audit
            persist_audit()

            return results

        # ------------------------------
        # INGEST
        # ------------------------------

        if decision != "INGEST":
            raise ValueError(
                f"Décision d'ingestion inconnue : {decision}"
            )

        dataset = results["contract"].get("dataset")

        if not dataset:
            raise ValueError(
                "Le Data Contract ne fournit pas de dataset."
            )

        # Mode "decision only" :
        # le fichier est éligible à l'ingestion,
        # mais l'utilisateur n'a pas demandé son ingestion.
        if not plan.ingest:
            audit = finish_audit(
                audit,
                status="SUCCESS",
                decision=decision,
                execution_mode=execution_mode,
            )

            results["audit"] = audit
            persist_audit()

            return results

        # Ingestion réellement demandée.
        results["ingest"] = execute_step(
            "ingest_csv",
            {
                "file_path": plan.file_path,
                "dataset": dataset,
            },
        )

        # ------------------------------
        # Silver
        # ------------------------------

        bronze_file = f"data/bronze/{dataset}.parquet"
        silver_file = f"data/silver/{dataset}.parquet"

        if plan.transform_to_silver:

            results["silver"] = execute_step(
                "transform_to_silver",
                {
                    "bronze_file_path": bronze_file,
                    "silver_file_path": silver_file,
                },
            )

            record_output(
                audit,
                path=silver_file,
                layer="silver",
            )


        # ------------------------------
        # Gold
        # ------------------------------

        if plan.build_gold:

            gold_file = (
                f"data/gold/{dataset}_by_product.parquet"
            )

            results["gold"] = execute_step(
                "build_sales_gold",
                {
                    "silver_file_path": silver_file,
                    "output_file_path": gold_file,
                },
            )

            record_output(
                audit,
                path=gold_file,
                layer="gold",
            )

        audit = finish_audit(
            audit,
            status="SUCCESS",
            decision=decision,
            execution_mode=execution_mode,
        )

        results["audit"] = audit
        persist_audit()

        return results

    except Exception as exc:
        audit = finish_audit(
            audit,
            status="FAILED",
            decision=audit.get("decision"),
            execution_mode=execution_mode,
            error=str(exc),
        )

        results["audit"] = audit
        persist_audit()    
        
        raise
