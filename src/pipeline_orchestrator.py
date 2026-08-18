from src.pipeline_plan import PipelinePlan


def execute_pipeline(plan: PipelinePlan, tool_executor) -> dict:
    """
    Exécute un PipelinePlan de manière déterministe.

    Le LLM ne décide pas de l'ordre d'exécution ici.
    """

    plan.validate()

    results = {}

    # --------------------------------------------------
    # 1. Inspection
    # --------------------------------------------------

    if plan.inspect:
        results["inspect"] = tool_executor(
            "inspect_csv",
            {
                "file_path": plan.file_path,
            },
        )

    # --------------------------------------------------
    # 2. Profilage
    # --------------------------------------------------

    if plan.profile:
        results["profile"] = tool_executor(
            "profile_csv",
            {
                "file_path": plan.file_path,
            },
        )

    # --------------------------------------------------
    # 3. Qualité
    # --------------------------------------------------

    if plan.validate_quality:
        results["quality"] = tool_executor(
            "validate_csv",
            {
                "file_path": plan.file_path,
            },
        )

    # --------------------------------------------------
    # 4. Data Contract
    # --------------------------------------------------

    if plan.validate_contract:
        results["contract"] = tool_executor(
            "validate_contract",
            {
                "file_path": plan.file_path,
                "contract_path": plan.contract_path,
            },
        )

    # --------------------------------------------------
    # 5. Décision
    # --------------------------------------------------

    if not plan.decision:
        return results

    if "contract" not in results:
        raise ValueError(
            "La décision nécessite le résultat du Data Contract."
        )

    if "quality" not in results:
        raise ValueError(
            "La décision nécessite le résultat de qualité."
        )

    decision_result = tool_executor(
        "determine_ingestion_decision",
        {
            "contract_result": results["contract"],
            "quality_result": results["quality"],
        },
    )

    results["decision"] = decision_result

    decision = decision_result["decision"]

    # --------------------------------------------------
    # 6. REJECT
    # --------------------------------------------------

    if decision == "REJECT":

        results["action"] = tool_executor(
            "reject_csv",
            {
                "file_path": plan.file_path,
                "reason": "Le fichier ne respecte pas le Data Contract.",
            },
        )

        return results

    # --------------------------------------------------
    # 7. QUARANTINE
    # --------------------------------------------------

    if decision == "QUARANTINE":

        results["action"] = tool_executor(
            "quarantine_csv",
            {
                "file_path": plan.file_path,
                "reason": (
                    "Le fichier respecte le Data Contract "
                    "mais présente des problèmes de qualité."
                ),
            },
        )

        return results

    # --------------------------------------------------
    # 8. INGEST
    # --------------------------------------------------

    if decision != "INGEST":
        raise ValueError(
            f"Décision d'ingestion inconnue : {decision}"
        )

    dataset = results["contract"].get("dataset")

    if not dataset:
        raise ValueError(
            "Le Data Contract ne fournit pas de dataset."
        )

    if not plan.ingest:
        raise ValueError(
            "La décision INGEST exige ingest=True dans le plan."
        )

    results["ingest"] = tool_executor(
        "ingest_csv",
        {
            "file_path": plan.file_path,
            "dataset": dataset,
        },
    )

    # --------------------------------------------------
    # 9. Silver
    # --------------------------------------------------

    bronze_file = f"data/bronze/{dataset}.parquet"
    silver_file = f"data/silver/{dataset}.parquet"

    if plan.transform_to_silver:

        results["silver"] = tool_executor(
            "transform_to_silver",
            {
                "bronze_file_path": bronze_file,
                "silver_file_path": silver_file,
            },
        )

    # --------------------------------------------------
    # 10. Gold
    # --------------------------------------------------

    if plan.build_gold:

        gold_file = (
            f"data/gold/{dataset}_by_product.parquet"
        )

        results["gold"] = tool_executor(
            "build_sales_gold",
            {
                "silver_file_path": silver_file,
                "output_file_path": gold_file,
            },
        )

    return results
