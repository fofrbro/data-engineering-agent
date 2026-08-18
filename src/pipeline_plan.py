from dataclasses import dataclass, field
from typing import List


@dataclass
class PipelinePlan:
    """
    Plan d'exécution déterministe du pipeline Data Engineering.
    """

    file_path: str
    contract_path: str

    inspect: bool = False
    profile: bool = False
    validate_quality: bool = False
    validate_contract: bool = False

    decision: bool = False

    ingest: bool = False
    transform_to_silver: bool = False
    build_gold: bool = False

    quarantine: bool = False
    reject: bool = False

    steps: List[str] = field(default_factory=list)

    def validate(self) -> None:
        """
        Vérifie la cohérence du plan.
        """

        if self.ingest and (
            self.quarantine
            or self.reject
        ):
            raise ValueError(
                "Un plan ne peut pas contenir INGEST, "
                "QUARANTINE et REJECT simultanément."
            )

        if self.quarantine and self.reject:
            raise ValueError(
                "Un plan ne peut pas contenir "
                "QUARANTINE et REJECT simultanément."
            )

        if self.transform_to_silver and not self.ingest:
            raise ValueError(
                "Silver nécessite l'étape INGEST."
            )

        if self.build_gold and not self.transform_to_silver:
            raise ValueError(
                "Gold nécessite l'étape Silver."
            )

        if self.quarantine and self.ingest:
            raise ValueError(
                "QUARANTINE et INGEST sont incompatibles."
            )

        if self.reject and (
            self.transform_to_silver
            or self.build_gold
        ):
            raise ValueError(
                "REJECT interdit les transformations Silver et Gold."
            )

    def add_step(self, step: str) -> None:
        if step not in self.steps:
            self.steps.append(step)
