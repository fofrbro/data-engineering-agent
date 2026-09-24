VALIDATED_CONTRACT = "VALIDATED"

# Codes des règles appliquées, conservés dans l'audit.
RULE_CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
RULE_CONTRACT_NOT_VALIDATED = "CONTRACT_NOT_VALIDATED"
RULE_QUALITY_ISSUES = "QUALITY_ISSUES"
RULE_ALL_CHECKS_PASSED = "ALL_CHECKS_PASSED"


def _untrusted_contract_reason(contract_status) -> str:
    if contract_status is None:
        return (
            "Aucun Data Contract validé n'a été appliqué : "
            "l'ingestion exige un contrat VALIDATED."
        )

    return (
        f"Le Data Contract a le statut {contract_status} : "
        "l'ingestion exige un contrat VALIDATED."
    )


def determine_ingestion_decision(
    contract_result: dict,
    quality_result: dict
) -> dict:
    """
    Détermine si un fichier doit être ingéré,
    mis en quarantaine ou rejeté.

    Règles, dans l'ordre :
    1. contrat violé                      -> REJECT
    2. contrat non VALIDATED (ou absent)  -> QUARANTINE
    3. problèmes de qualité               -> QUARANTINE
    4. sinon                              -> INGEST

    Un résultat de contrat sans contract_status est traité
    comme non validé : l'absence d'information ne permet
    jamais l'ingestion.
    """

    contract_valid = contract_result["valid"]
    quality_valid = quality_result["valid"]

    contract_errors = contract_result["errors_count"]
    quality_issues = quality_result["issues_count"]
    contract_status = contract_result.get("contract_status")

    def decide(decision: str, rule: str, reason: str) -> dict:
        return {
            "decision": decision,
            "policy_rule": rule,
            "reason": reason,
            "contract_status": contract_status,
            "contract_errors": contract_errors,
            "quality_issues": quality_issues
        }

    # ---------------------------------------------
    # REJECT
    # ---------------------------------------------

    if not contract_valid:
        return decide(
            "REJECT",
            RULE_CONTRACT_VIOLATION,
            "Le fichier ne respecte pas le Data Contract.",
        )

    # ---------------------------------------------
    # QUARANTINE
    # ---------------------------------------------

    if contract_status != VALIDATED_CONTRACT:
        return decide(
            "QUARANTINE",
            RULE_CONTRACT_NOT_VALIDATED,
            _untrusted_contract_reason(contract_status),
        )

    if not quality_valid:
        return decide(
            "QUARANTINE",
            RULE_QUALITY_ISSUES,
            (
                "Le fichier respecte le contrat mais "
                "présente des problèmes de qualité."
            ),
        )

    # ---------------------------------------------
    # INGEST
    # ---------------------------------------------

    return decide(
        "INGEST",
        RULE_ALL_CHECKS_PASSED,
        (
            "Le fichier respecte le Data Contract "
            "et les contrôles de qualité."
        ),
    )
