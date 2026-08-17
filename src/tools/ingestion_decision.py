def determine_ingestion_decision(
    contract_result: dict,
    quality_result: dict
) -> dict:
    """
    Détermine si un fichier doit être ingéré,
    mis en quarantaine ou rejeté.
    """

    contract_valid = contract_result["valid"]
    quality_valid = quality_result["valid"]

    contract_errors = contract_result["errors_count"]
    quality_issues = quality_result["issues_count"]

    # ---------------------------------------------
    # REJECT
    # ---------------------------------------------

    if not contract_valid:
        return {
            "decision": "REJECT",
            "reason": "Le fichier ne respecte pas le Data Contract.",
            "contract_errors": contract_errors,
            "quality_issues": quality_issues
        }

    # ---------------------------------------------
    # QUARANTINE
    # ---------------------------------------------

    if not quality_valid:
        return {
            "decision": "QUARANTINE",
            "reason": (
                "Le fichier respecte le contrat mais "
                "présente des problèmes de qualité."
            ),
            "contract_errors": contract_errors,
            "quality_issues": quality_issues
        }

    # ---------------------------------------------
    # INGEST
    # ---------------------------------------------

    return {
        "decision": "INGEST",
        "reason": (
            "Le fichier respecte le Data Contract "
            "et les contrôles de qualité."
        ),
        "contract_errors": contract_errors,
        "quality_issues": quality_issues
    }
