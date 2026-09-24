"""
Garde-fou déterministe des appels d'outils décidés par le LLM.

Le LLM propose les appels, ce module décide s'ils sont exécutés :

- la décision d'ingestion est toujours calculée à partir des
  résultats réels de validate_contract et validate_csv obtenus
  pendant le run, jamais à partir d'arguments fournis par le LLM ;
- les outils qui écrivent Bronze, Silver, Gold ou publient vers
  Fabric exigent une décision INGEST réellement calculée.
"""


DECISION_TOOL = "determine_ingestion_decision"
CONTRACT_TOOL = "validate_contract"
QUALITY_TOOL = "validate_csv"

INGEST_ONLY_TOOLS = {
    "ingest_csv",
    "transform_to_silver",
    "build_sales_gold",
    "publish_to_fabric",
}


class ToolCallGuard:

    def __init__(self):
        self.results: dict[str, dict] = {}
        self.decision: str | None = None

    def prepare(
        self,
        name: str,
        arguments: dict,
    ) -> tuple[dict, dict | None]:
        """
        Retourne (arguments à utiliser, résultat de blocage).
        Si le résultat de blocage n'est pas None, l'outil
        ne doit pas être exécuté.
        """

        if name == DECISION_TOOL:
            missing = [
                tool
                for tool in (CONTRACT_TOOL, QUALITY_TOOL)
                if tool not in self.results
            ]

            if missing:
                return arguments, blocked(
                    name,
                    "La décision exige d'abord l'exécution de : "
                    + ", ".join(missing)
                    + ".",
                )

            return {
                "contract_result": self.results[CONTRACT_TOOL],
                "quality_result": self.results[QUALITY_TOOL],
            }, None

        if name in INGEST_ONLY_TOOLS and self.decision != "INGEST":
            return arguments, blocked(
                name,
                "Outil réservé aux fichiers dont la décision "
                f"calculée est INGEST (décision actuelle : "
                f"{self.decision or 'aucune'}).",
            )

        return arguments, None

    def record(self, name: str, result) -> None:
        """Mémorise les résultats réels utiles aux contrôles."""

        if not isinstance(result, dict):
            return

        if name in (CONTRACT_TOOL, QUALITY_TOOL):
            self.results[name] = result

        if name == DECISION_TOOL:
            self.decision = result.get("decision")


def blocked(name: str, message: str) -> dict:
    return {
        "status": "BLOCKED",
        "tool": name,
        "message": message,
    }
