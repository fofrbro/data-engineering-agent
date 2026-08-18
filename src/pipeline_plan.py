from dataclasses import dataclass, field


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

    steps: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """
        Vérifie la cohérence du plan.
        """

        # Une seule action terminale parmi
        # INGEST, QUARANTINE et REJECT.
        terminal_actions = sum(
            [
                self.ingest,
                self.quarantine,
                self.reject,
            ]
        )

        if terminal_actions > 1:
            raise ValueError(
                "Un plan ne peut contenir qu'une seule "
                "action terminale : INGEST, QUARANTINE ou REJECT."
            )

        if self.decision and not self.validate_contract:
            raise ValueError(
                "La décision nécessite la validation du Data Contract."
            )

        if self.decision and not self.validate_quality:
            raise ValueError(
                "La décision nécessite la validation de la qualité."
            )

        if self.ingest and not self.decision:
            raise ValueError(
                "INGEST nécessite l'étape de décision."
            )

        # Silver nécessite l'ingestion.
        if self.transform_to_silver and not self.ingest:
            raise ValueError(
                "Silver nécessite l'étape INGEST."
            )

        # Gold nécessite Silver.
        if self.build_gold and not self.transform_to_silver:
            raise ValueError(
                "Gold nécessite l'étape Silver."
            )

        # REJECT interdit les transformations.
        if self.reject and (
            self.transform_to_silver
            or self.build_gold
        ):
            raise ValueError(
                "REJECT interdit les transformations Silver et Gold."
            )

        # QUARANTINE interdit les transformations.
        if self.quarantine and (
            self.transform_to_silver
            or self.build_gold
        ):
            raise ValueError(
                "QUARANTINE interdit les transformations Silver et Gold."
            )

    def add_step(self, step: str) -> None:
        """
        Ajoute une étape au plan si elle n'est pas déjà présente.
        """

        if step not in self.steps:
            self.steps.append(step)


def build_pipeline_plan(data: dict) -> PipelinePlan:
    """
    Construit et valide un PipelinePlan à partir d'un dictionnaire.

    Les champs inconnus sont ignorés.
    """

    required_fields = [
        "file_path",
        "contract_path",
    ]

    missing_fields = [
        field
        for field in required_fields
        if not data.get(field)
    ]

    if missing_fields:
        raise ValueError(
            f"Champs obligatoires manquants : {missing_fields}"
        )

    plan = PipelinePlan(
        file_path=data["file_path"],
        contract_path=data["contract_path"],
        inspect=bool(data.get("inspect", False)),
        profile=bool(data.get("profile", False)),
        validate_quality=bool(
            data.get("validate_quality", False)
        ),
        validate_contract=bool(
            data.get("validate_contract", False)
        ),
        decision=bool(data.get("decision", False)),
        ingest=bool(data.get("ingest", False)),
        transform_to_silver=bool(
            data.get("transform_to_silver", False)
        ),
        build_gold=bool(
            data.get("build_gold", False)
        ),
        quarantine=bool(
            data.get("quarantine", False)
        ),
        reject=bool(
            data.get("reject", False)
        ),
        steps=list(data.get("steps", [])),
    )

    plan.validate()

    return plan
