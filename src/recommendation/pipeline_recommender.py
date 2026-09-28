"""
Recommandation d'un pipeline Bronze / Silver / Gold.

La recommandation est une proposition (statut PROPOSED) : elle
n'exécute rien. Toute transformation qui supprime ou remplace des
valeurs source est marquée destructive et exige une validation.

Les règles sont déterministes et s'appuient sur le profil de
schéma, le profil sémantique et, s'il existe, le Data Contract.
"""

from dataclasses import asdict, dataclass, field

from src.contract.contract_lifecycle import VALIDATED, contract_status
from src.recommendation.business_rules import cancellation_exclusion
from src.discovery.schema_profiler import (
    DATETIME,
    INTEGER,
    STRING,
    SchemaProfile,
    name_tokens,
)
from src.semantic.semantic_profiler import (
    FOREIGN_KEY_CANDIDATE,
    PRIMARY_KEY_CANDIDATE,
    SALES_DOMAIN,
    SemanticProfile,
)
from src.semantic.vocabulary import (
    AMOUNT,
    CATEGORY,
    DATE_PART,
    DIMENSION,
    IDENTIFIER,
    MEASURE,
    PRICE,
    QUANTITY,
    TAX,
    STATUS,
    TEMPORAL,
)


PROPOSED = "PROPOSED"

# Au-delà, une dimension produit des agrégats peu lisibles.
MAX_GROUP_BY_DISTINCT = 50
MAX_AGGREGATE_DIMENSIONS = 3

DERIVED_AMOUNT = "line_amount"
UNKNOWN_LABEL = "UNKNOWN"


@dataclass
class Transformation:
    id: str
    type: str
    columns: list[str]
    description: str
    rationale: str
    destructive: bool = False
    parameters: dict = field(default_factory=dict)

    @property
    def requires_approval(self) -> bool:
        return self.destructive

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "requires_approval": self.requires_approval,
        }


@dataclass
class Metric:
    name: str
    expression: str
    source_columns: list[str]
    # Règle métier : lignes exclues avant agrégation, ex.
    # {"column": "status", "exclude": ["CANCELLED"]}.
    exclusion: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GoldTable:
    name: str
    table_type: str
    grain: list[str]
    columns: list[str]
    metrics: list[Metric]
    rationale: str

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


@dataclass
class PipelineRecommendation:
    dataset: str
    domain: str
    contract_status: str | None
    bronze: dict
    silver: dict
    gold: list[GoldTable]
    warnings: list[str]
    status: str = PROPOSED

    @property
    def transformations(self) -> list[Transformation]:
        return self.silver["transformations"]

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "status": self.status,
            "domain": self.domain,
            "contract_status": self.contract_status,
            "bronze": self.bronze,
            "silver": {
                **self.silver,
                "transformations": [
                    transformation.to_dict()
                    for transformation in self.transformations
                ],
            },
            "gold": [table.to_dict() for table in self.gold],
            "warnings": self.warnings,
            "requires_approval": any(
                transformation.requires_approval
                for transformation in self.transformations
            ),
        }


def silver_column_name(name: str) -> str:
    """Nom d'une colonne source dans Silver (snake_case)."""

    return "_".join(name_tokens(name)) or name


_snake_case = silver_column_name


class _Context:
    """Vues pratiques sur les profils, par nom de colonne final."""

    def __init__(
        self,
        schema: SchemaProfile,
        semantics: SemanticProfile,
        contract: dict | None,
    ):
        self.schema = schema
        self.semantics = semantics
        self.contract = contract or {}
        self.exclusion = cancellation_exclusion(schema, semantics)
        self.renames = {
            column.name: _snake_case(column.name)
            for column in schema.columns
        }
        self.profiles = {
            self.renames[column.name]: column
            for column in schema.columns
        }
        self.roles = {
            self.renames[column.column]: column
            for column in semantics.columns
        }

    def names(self, semantic_role: str, business_role=None) -> list[str]:
        return [
            name
            for name, role in self.roles.items()
            if role.semantic_role == semantic_role
            and (business_role is None or role.business_role == business_role)
        ]

    def contract_rules(self, name: str) -> dict:
        original = next(
            source
            for source, target in self.renames.items()
            if target == name
        )
        return self.contract.get("columns", {}).get(original, {})


# ----------------------------------------------------------------------
# Silver
# ----------------------------------------------------------------------


def _silver_transformations(ctx: _Context) -> list[Transformation]:
    steps: list[Transformation] = []

    renames = {
        source: target
        for source, target in ctx.renames.items()
        if source != target
    }

    if renames:
        steps.append(
            Transformation(
                id="standardize_column_names",
                type="rename",
                columns=list(renames),
                description="Renommer les colonnes en snake_case.",
                rationale="Noms stables et sans accents pour SQL, Delta et Power BI.",
                parameters={"mapping": renames},
            )
        )

    strings = [
        name
        for name, profile in ctx.profiles.items()
        if profile.inferred_type == STRING
    ]

    if strings:
        steps.append(
            Transformation(
                id="trim_strings",
                type="clean",
                columns=strings,
                description="Supprimer les espaces en début et fin de texte.",
                rationale="Évite des doublons de catégories dus aux espaces.",
            )
        )

    casts = {}

    for name, profile in ctx.profiles.items():
        target = ctx.contract_rules(name).get("type")

        if profile.inferred_type == DATETIME and "datetime" not in profile.dtype:
            casts[name] = "datetime"
        elif (
            profile.inferred_type == INTEGER
            and "float" in profile.dtype
            and target != "decimal"
        ):
            casts[name] = "integer"
        elif target == "decimal" and "int" in profile.dtype:
            casts[name] = "decimal"

    if casts:
        steps.append(
            Transformation(
                id="cast_types",
                type="cast",
                columns=list(casts),
                description="Convertir les colonnes vers leur type logique.",
                rationale=(
                    "Le type stocké diffère du type attendu "
                    "(dates en texte, entiers lus en décimal, montants)."
                ),
                parameters={"types": casts},
            )
        )

    categories = [
        name
        for name in ctx.names(DIMENSION)
        if ctx.roles[name].business_role in (STATUS, CATEGORY)
        and ctx.profiles[name].inferred_type == STRING
    ]

    if categories:
        steps.append(
            Transformation(
                id="normalize_categories",
                type="normalize",
                columns=categories,
                description="Mettre les statuts et catégories en majuscules.",
                rationale="Regroupe 'paid' et 'PAID' dans les agrégats.",
            )
        )

    steps.extend(_null_handling(ctx))

    if ctx.schema.duplicate_rows > 0:
        steps.append(
            Transformation(
                id="deduplicate_rows",
                type="deduplicate",
                columns=list(ctx.profiles),
                description="Supprimer les lignes strictement identiques.",
                rationale=(
                    f"{ctx.schema.duplicate_rows} doublon(s) exact(s) observé(s)."
                ),
                destructive=True,
            )
        )

    business_rules = {
        name: {
            key: value
            for key, value in ctx.contract_rules(name).items()
            if key in ("nullable", "min", "max", "unique")
        }
        for name in ctx.profiles
        if ctx.contract_rules(name)
    }

    if business_rules:
        steps.append(
            Transformation(
                id="validate_business_rules",
                type="check",
                columns=list(business_rules),
                description=(
                    "Contrôler les règles du Data Contract ligne à ligne ; "
                    "les lignes en échec vont en quarantaine."
                ),
                rationale="Les règles du contrat restent garanties dans Silver.",
                parameters={"rules": business_rules},
            )
        )

    steps.extend(_derived_columns(ctx))

    return steps


def _null_handling(ctx: _Context) -> list[Transformation]:
    with_nulls = [
        name
        for name, profile in ctx.profiles.items()
        if 0 < profile.null_count < ctx.schema.row_count
    ]
    keys = [n for n in with_nulls if ctx.roles[n].semantic_role == IDENTIFIER]
    dimensions = [n for n in with_nulls if ctx.roles[n].semantic_role == DIMENSION]
    measures = [n for n in with_nulls if ctx.roles[n].semantic_role == MEASURE]

    steps = []

    if keys:
        steps.append(
            Transformation(
                id="drop_rows_with_null_keys",
                type="filter",
                columns=keys,
                description="Écarter les lignes sans identifiant.",
                rationale="Une ligne sans clé ne peut pas être rattachée.",
                destructive=True,
            )
        )

    if dimensions:
        steps.append(
            Transformation(
                id="fill_null_dimensions",
                type="impute",
                columns=dimensions,
                description=f"Remplacer les dimensions nulles par '{UNKNOWN_LABEL}'.",
                rationale="Les valeurs absentes restent visibles dans les rapports.",
                destructive=True,
                parameters={"value": UNKNOWN_LABEL},
            )
        )

    if measures:
        steps.append(
            Transformation(
                id="keep_null_measures",
                type="null_policy",
                columns=measures,
                description="Conserver les mesures nulles, sans imputation.",
                rationale="Imputer une mesure fausserait les totaux.",
            )
        )

    return steps


def _derived_columns(ctx: _Context) -> list[Transformation]:
    steps = []
    quantities = ctx.names(MEASURE, QUANTITY)
    prices = ctx.names(MEASURE, PRICE)

    if quantities and prices and not ctx.names(MEASURE, AMOUNT):
        steps.append(
            Transformation(
                id="derive_line_amount",
                type="derive",
                columns=[quantities[0], prices[0]],
                description=(
                    f"Calculer {DERIVED_AMOUNT} = "
                    f"{quantities[0]} * {prices[0]}."
                ),
                rationale="Aucun montant n'est fourni : il est dérivé.",
                parameters={
                    "target": DERIVED_AMOUNT,
                    "expression": f"{quantities[0]} * {prices[0]}",
                },
            )
        )

    temporal = ctx.names(TEMPORAL)

    if temporal:
        steps.append(
            Transformation(
                id="derive_date_parts",
                type="derive",
                columns=[temporal[0]],
                description=f"Extraire l'année et le mois de {temporal[0]}.",
                rationale="Permet les analyses mensuelles et annuelles.",
                parameters={"targets": ["year", "month"]},
            )
        )

    return steps


# ----------------------------------------------------------------------
# Gold
# ----------------------------------------------------------------------


def _amount_column(
    ctx: _Context,
    transformations: list[Transformation],
) -> str | None:
    amounts = ctx.names(MEASURE, AMOUNT)

    if amounts:
        return amounts[0]

    if any(step.id == "derive_line_amount" for step in transformations):
        return DERIVED_AMOUNT

    return None


def _metrics(
    ctx: _Context,
    transformations: list[Transformation],
    count_column: str,
) -> list[Metric]:
    metrics = []
    amount = _amount_column(ctx, transformations)

    if amount:
        name = "total_sales" if amount == DERIVED_AMOUNT else f"total_{amount}"
        metrics.append(Metric(name, f"SUM({amount})", [amount]))

    for tax in ctx.names(MEASURE, TAX):
        metrics.append(Metric(f"total_{tax}", f"SUM({tax})", [tax]))

    for quantity in ctx.names(MEASURE, QUANTITY):
        name = "total_quantity" if quantity == "quantity" else f"total_{quantity}"
        metrics.append(Metric(name, f"SUM({quantity})", [quantity]))

    for price in ctx.names(MEASURE, PRICE):
        name = "avg_unit_price" if price == "price" else f"avg_{price}"
        metrics.append(Metric(name, f"AVG({price})", [price]))

    metrics.append(
        Metric("number_of_lines", f"COUNT({count_column})", [count_column])
    )

    # Même règle que pour les KPI : les agrégats Gold et les mesures
    # Power BI restent cohérents.
    for metric in metrics:
        metric.exclusion = ctx.exclusion

    return metrics


def _group_by_dimensions(ctx: _Context) -> list[str]:
    candidates = [
        name
        for name in ctx.names(DIMENSION)
        if ctx.roles[name].business_role != DATE_PART
        and ctx.profiles[name].distinct_count <= MAX_GROUP_BY_DISTINCT
    ]

    # Les dimensions liées à une entité métier passent en premier.
    candidates.sort(key=lambda name: ctx.roles[name].entity is None)

    return candidates[:MAX_AGGREGATE_DIMENSIONS]


def _gold_tables(
    ctx: _Context,
    dataset: str,
    transformations: list[Transformation],
) -> list[GoldTable]:
    tables = []
    keys = [
        relationship.column
        for relationship in ctx.semantics.relationships
        if relationship.relationship_type == PRIMARY_KEY_CANDIDATE
    ]
    measures = ctx.names(MEASURE)
    amount = _amount_column(ctx, transformations)

    if amount == DERIVED_AMOUNT:
        measures = measures + [DERIVED_AMOUNT]

    count_column = next(iter(ctx.profiles))

    if measures:
        tables.append(
            GoldTable(
                name=f"fact_{dataset}",
                table_type="fact",
                grain=[_snake_case(key) for key in keys] or ["source_row"],
                columns=[
                    *ctx.names(IDENTIFIER),
                    *ctx.names(TEMPORAL),
                    *ctx.names(DIMENSION),
                    *measures,
                ],
                metrics=[],
                rationale="Table de faits au grain de la ligne source.",
            )
        )

    tables.extend(_dimension_tables(ctx, dataset))

    for dimension in _group_by_dimensions(ctx):
        tables.append(
            GoldTable(
                name=f"{dataset}_by_{dimension}",
                table_type="aggregate",
                grain=[dimension],
                columns=[dimension],
                metrics=_metrics(ctx, transformations, dimension),
                rationale=f"Analyse des mesures par {dimension}.",
            )
        )

    temporal = ctx.names(TEMPORAL)

    if temporal:
        tables.append(
            GoldTable(
                name=f"{dataset}_by_month",
                table_type="aggregate",
                grain=["year", "month"],
                columns=["year", "month"],
                metrics=_metrics(ctx, transformations, temporal[0]),
                rationale=f"Évolution mensuelle selon {temporal[0]}.",
            )
        )

    tables.append(
        GoldTable(
            name=f"{dataset}_summary",
            table_type="aggregate",
            grain=[],
            columns=[],
            metrics=_metrics(ctx, transformations, count_column),
            rationale="Indicateurs globaux du dataset.",
        )
    )

    return tables


DATE_DIMENSION_SUFFIX = "_dim_date"


def _dimension_tables(ctx: _Context, dataset: str) -> list[GoldTable]:
    """
    Dimensions du dataset, préfixées par son nom : deux datasets
    chargés dans le même Lakehouse ne s'écrasent pas.
    """

    tables = []
    seen = set()

    for relationship in ctx.semantics.relationships:
        if relationship.relationship_type != FOREIGN_KEY_CANDIDATE:
            continue

        entity = relationship.referenced_entity

        if not entity or entity in seen:
            continue

        seen.add(entity)
        key = _snake_case(relationship.column)
        attributes = [
            name
            for name in ctx.names(DIMENSION)
            if ctx.roles[name].entity == entity
        ]
        tables.append(
            GoldTable(
                name=f"{dataset}_dim_{entity.lower()}",
                table_type="dimension",
                grain=[key],
                columns=[key, *attributes],
                metrics=[],
                rationale=f"Dimension {entity} référencée par {key}.",
            )
        )

    for name in ctx.names(DIMENSION):
        entity = ctx.roles[name].entity

        if entity and entity not in seen:
            seen.add(entity)
            tables.append(
                GoldTable(
                    name=f"{dataset}_dim_{entity.lower()}",
                    table_type="dimension",
                    grain=[name],
                    columns=[name],
                    metrics=[],
                    rationale=f"Dimension {entity} identifiée par son libellé {name}.",
                )
            )

    temporal = ctx.names(TEMPORAL)

    if temporal:
        tables.append(
            GoldTable(
                name=f"{dataset}{DATE_DIMENSION_SUFFIX}",
                table_type="dimension",
                grain=["date"],
                columns=["date", "year", "quarter", "month", "day"],
                metrics=[],
                rationale=f"Calendrier couvrant {temporal[0]}.",
            )
        )

    return tables


# ----------------------------------------------------------------------
# Point d'entrée
# ----------------------------------------------------------------------


def _warnings(ctx: _Context, status: str | None) -> list[str]:
    warnings = []

    if status != VALIDATED:
        warnings.append(
            "Le Data Contract n'est pas VALIDATED : le pipeline ne "
            "pourra être exécuté qu'après sa validation."
        )

    if not ctx.semantics.domain or ctx.semantics.domain.name != SALES_DOMAIN:
        warnings.append(
            "Métier non reconnu : les tables Gold proposées restent génériques."
        )

    if not ctx.names(MEASURE):
        warnings.append("Aucune mesure détectée : les agrégats se limitent aux comptages.")

    if not ctx.names(TEMPORAL):
        warnings.append("Aucune colonne temporelle : pas d'analyse d'évolution.")

    return warnings


def recommend_pipeline(
    schema: SchemaProfile,
    semantics: SemanticProfile,
    contract: dict | None = None,
    dataset: str | None = None,
) -> PipelineRecommendation:
    """
    Propose les couches Bronze, Silver et Gold d'un dataset.
    """

    dataset = dataset or (contract or {}).get("dataset") or "dataset"
    ctx = _Context(schema, semantics, contract)
    status = contract_status(contract) if contract else None
    transformations = _silver_transformations(ctx)

    return PipelineRecommendation(
        dataset=dataset,
        domain=semantics.domain.name if semantics.domain else "UNKNOWN",
        contract_status=status,
        bronze={
            "table": f"{dataset}_raw",
            "description": "Copie brute du fichier source, horodatée, sans transformation.",
            "columns": [column.name for column in schema.columns],
        },
        silver={
            "table": f"{dataset}_clean",
            "transformations": transformations,
        },
        gold=_gold_tables(ctx, dataset, transformations),
        warnings=_warnings(ctx, status),
    )


def recommend_pipeline_for_file(
    path: str,
    contract: dict | None = None,
    dataset: str | None = None,
) -> PipelineRecommendation:
    """Découvre un fichier puis propose son pipeline."""

    from src.contract.contract_generator import dataset_name_from_path
    from src.discovery.dataset_discovery import discover_dataset
    from src.semantic.semantic_profiler import profile_semantics

    schema = discover_dataset(path).schema

    return recommend_pipeline(
        schema,
        profile_semantics(schema),
        contract,
        dataset or (contract or {}).get("dataset") or dataset_name_from_path(path),
    )
