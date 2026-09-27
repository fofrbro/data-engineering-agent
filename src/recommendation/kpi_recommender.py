"""
Découverte automatique des KPI d'un dataset.

Les KPI sont proposés (statut PROPOSED) à partir du profil
sémantique. Leur confiance ne dépasse jamais celle des colonnes
utilisées : un KPI n'est pas plus fiable que son interprétation.

Les colonnes sont désignées par leur nom Silver (snake_case), car
les tableaux de bord sont construits sur Silver et Gold.
"""

from dataclasses import asdict, dataclass, field

from src.discovery.schema_profiler import SchemaProfile
from src.recommendation.business_rules import cancellation_exclusion, with_exclusion
from src.recommendation.pipeline_recommender import (
    MAX_GROUP_BY_DISTINCT,
    silver_column_name,
)
from src.semantic.semantic_profiler import (
    SALES_DOMAIN,
    ColumnSemantics,
    SemanticProfile,
)
from src.semantic.vocabulary import (
    AMOUNT,
    CATEGORY,
    CUSTOMER,
    DATE_PART,
    DIMENSION,
    GEOGRAPHY,
    IDENTIFIER,
    MEASURE,
    ORDER,
    PRICE,
    PRODUCT,
    QUANTITY,
    RATIO,
    STATUS,
    TEMPORAL,
    TRANSACTION,
)


PROPOSED = "PROPOSED"

SCALAR = "scalar"
BREAKDOWN = "breakdown"
TREND = "trend"

CURRENCY = "currency"
NUMBER = "number"
PERCENT = "percent"

# Facteurs appliqués à la confiance des colonnes sources.
DERIVED_FACTOR = 0.95
BREAKDOWN_FACTOR = 0.95
GENERIC_FACTOR = 0.8
COUNT_CONFIDENCE = 0.95

MAX_BREAKDOWNS = 4

# Ordre de préférence des axes d'analyse.
BREAKDOWN_PRIORITY = {
    PRODUCT: 0,
    CUSTOMER: 1,
    GEOGRAPHY: 2,
    CATEGORY: 3,
    STATUS: 4,
}


@dataclass
class KPI:
    name: str
    description: str
    formula: str
    source_columns: list[str]
    aggregation: str
    confidence: float
    rationale: str
    kpi_type: str = SCALAR
    dimension: str | None = None
    format: str = NUMBER
    exclusion: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KpiRecommendation:
    dataset: str
    domain: str
    kpis: list[KPI] = field(default_factory=list)
    status: str = PROPOSED

    def kpi(self, name: str) -> KPI:
        for kpi in self.kpis:
            if kpi.name == name:
                return kpi

        raise KeyError(name)

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "status": self.status,
            "domain": self.domain,
            "kpis": [kpi.to_dict() for kpi in self.kpis],
        }


@dataclass
class _Measure:
    """Mesure principale : colonne directe ou formule dérivée."""

    label: str
    expression: str
    source_columns: list[str]
    confidence: float
    rationale: str
    format: str


class _Columns:

    def __init__(self, semantics: SemanticProfile, schema: SchemaProfile):
        self.semantics = semantics
        self.distinct = {
            silver_column_name(column.name): column.distinct_count
            for column in schema.columns
        }

    def find(self, semantic_role, business_role=None, entity=None) -> list[ColumnSemantics]:
        return [
            column
            for column in self.semantics.columns
            if column.semantic_role == semantic_role
            and (business_role is None or column.business_role == business_role)
            and (entity is None or column.entity == entity)
        ]

    def first(self, *args, **kwargs) -> ColumnSemantics | None:
        found = self.find(*args, **kwargs)
        return found[0] if found else None


def _name(column: ColumnSemantics) -> str:
    return silver_column_name(column.column)


def _confidence(*values: float) -> float:
    return round(min(values), 2)


def _main_measure(cols: _Columns, is_sales: bool) -> _Measure | None:
    amount = cols.first(MEASURE, AMOUNT)
    quantity = cols.first(MEASURE, QUANTITY)
    price = cols.first(MEASURE, PRICE)
    label = "Revenue" if is_sales else None

    if amount:
        return _Measure(
            label=label or f"Total {_name(amount)}",
            expression=f"SUM({_name(amount)})",
            source_columns=[_name(amount)],
            confidence=amount.confidence,
            rationale=f"Somme de la colonne montant {_name(amount)}.",
            format=CURRENCY,
        )

    if quantity and price:
        return _Measure(
            label=label or f"Total {_name(quantity)} x {_name(price)}",
            expression=f"SUM({_name(quantity)} * {_name(price)})",
            source_columns=[_name(quantity), _name(price)],
            confidence=_confidence(
                quantity.confidence * DERIVED_FACTOR,
                price.confidence * DERIVED_FACTOR,
            ),
            rationale=(
                "Aucun montant fourni : dérivé de la quantité "
                "et du prix unitaire."
            ),
            format=CURRENCY,
        )

    return None


def _scalar_kpis(
    cols: _Columns,
    main: _Measure | None,
    is_sales: bool,
) -> list[KPI]:
    kpis = []
    order_id = (
        cols.first(IDENTIFIER, entity=ORDER)
        or cols.first(IDENTIFIER, entity=TRANSACTION)
    )

    if main:
        kpis.append(
            KPI(
                name=main.label,
                description="Chiffre d'affaires total." if is_sales else "Total de la mesure principale.",
                formula=main.expression,
                source_columns=main.source_columns,
                aggregation="SUM",
                confidence=main.confidence,
                rationale=main.rationale,
                format=main.format,
            )
        )

    if order_id:
        kpis.append(
            KPI(
                name="Orders",
                description="Nombre de commandes distinctes.",
                formula=f"COUNT(DISTINCT {_name(order_id)})",
                source_columns=[_name(order_id)],
                aggregation="COUNT_DISTINCT",
                confidence=_confidence(order_id.confidence),
                rationale=f"{_name(order_id)} identifie une commande.",
            )
        )
    else:
        kpis.append(
            KPI(
                name="Number of Lines",
                description="Nombre de lignes du dataset.",
                formula="COUNT(*)",
                source_columns=[],
                aggregation="COUNT",
                confidence=COUNT_CONFIDENCE,
                rationale=(
                    "Aucun identifiant de commande : le comptage "
                    "porte sur les lignes, pas sur les commandes."
                ),
            )
        )

    quantity = cols.first(MEASURE, QUANTITY)

    if quantity:
        kpis.append(
            KPI(
                name="Quantity Sold" if is_sales else f"Total {_name(quantity)}",
                description="Quantité totale.",
                formula=f"SUM({_name(quantity)})",
                source_columns=[_name(quantity)],
                aggregation="SUM",
                confidence=_confidence(quantity.confidence),
                rationale=f"{_name(quantity)} est une quantité.",
            )
        )

    if main and is_sales:
        if order_id:
            kpis.append(
                KPI(
                    name="Average Order Value",
                    description="Chiffre d'affaires moyen par commande.",
                    formula=f"{main.expression} / COUNT(DISTINCT {_name(order_id)})",
                    source_columns=[*main.source_columns, _name(order_id)],
                    aggregation="RATIO",
                    confidence=_confidence(main.confidence, order_id.confidence),
                    rationale="Panier moyen : CA rapporté aux commandes.",
                    format=CURRENCY,
                )
            )
        else:
            kpis.append(
                KPI(
                    name="Average Revenue per Line",
                    description="Chiffre d'affaires moyen par ligne.",
                    formula=f"{main.expression} / COUNT(*)",
                    source_columns=main.source_columns,
                    aggregation="RATIO",
                    confidence=_confidence(main.confidence * DERIVED_FACTOR),
                    rationale=(
                        "Sans identifiant de commande, le panier moyen "
                        "ne peut pas être calculé ; moyenne par ligne."
                    ),
                    format=CURRENCY,
                )
            )

    for entity, label in ((CUSTOMER, "Customers"), (PRODUCT, "Products")):
        column = cols.first(IDENTIFIER, entity=entity) or cols.first(DIMENSION, entity=entity)

        if column:
            kpis.append(
                KPI(
                    name=label,
                    description=f"Nombre de {label.lower()} distincts.",
                    formula=f"COUNT(DISTINCT {_name(column)})",
                    source_columns=[_name(column)],
                    aggregation="COUNT_DISTINCT",
                    confidence=_confidence(column.confidence),
                    rationale=f"{_name(column)} désigne l'entité {entity}.",
                )
            )

    price = cols.first(MEASURE, PRICE)

    if price:
        kpis.append(
            KPI(
                name="Average Unit Price",
                description="Prix unitaire moyen.",
                formula=f"AVG({_name(price)})",
                source_columns=[_name(price)],
                aggregation="AVG",
                confidence=_confidence(price.confidence),
                rationale=f"{_name(price)} est un prix unitaire.",
                format=CURRENCY,
            )
        )

    for ratio in cols.find(MEASURE, RATIO):
        kpis.append(
            KPI(
                name=f"Average {_name(ratio)}",
                description=f"Moyenne du ratio {_name(ratio)}.",
                formula=f"AVG({_name(ratio)})",
                source_columns=[_name(ratio)],
                aggregation="AVG",
                confidence=_confidence(ratio.confidence),
                rationale="Un ratio se moyenne, il ne se somme pas.",
                format=PERCENT,
            )
        )

    for measure in cols.find(MEASURE, None):
        if measure.business_role is not None:
            continue

        kpis.append(
            KPI(
                name=f"Total {_name(measure)}",
                description=f"Somme de {_name(measure)}.",
                formula=f"SUM({_name(measure)})",
                source_columns=[_name(measure)],
                aggregation="SUM",
                confidence=_confidence(measure.confidence * GENERIC_FACTOR),
                rationale=(
                    "Mesure sans rôle métier reconnu : "
                    "la somme est une hypothèse à confirmer."
                ),
            )
        )

    return kpis


def _breakdown_dimensions(cols: _Columns) -> list[ColumnSemantics]:
    candidates = [
        column
        for column in cols.find(DIMENSION)
        if column.business_role != DATE_PART
        and cols.distinct.get(_name(column), 0) <= MAX_GROUP_BY_DISTINCT
    ]

    def priority(column: ColumnSemantics) -> int:
        return BREAKDOWN_PRIORITY.get(
            column.entity,
            BREAKDOWN_PRIORITY.get(column.business_role, len(BREAKDOWN_PRIORITY)),
        )

    return sorted(candidates, key=priority)[:MAX_BREAKDOWNS]


def _breakdown_kpis(cols: _Columns, main: _Measure | None) -> list[KPI]:
    if main:
        label, expression = main.label, main.expression
        sources, confidence, fmt = main.source_columns, main.confidence, main.format
    else:
        label, expression = "Number of Lines", "COUNT(*)"
        sources, confidence, fmt = [], COUNT_CONFIDENCE, NUMBER

    kpis = []
    temporal = cols.first(TEMPORAL)

    if temporal:
        kpis.append(
            KPI(
                name=f"{label} by Month",
                description=f"Évolution mensuelle : {label}.",
                formula=f"{expression} GROUP BY MONTH({_name(temporal)})",
                source_columns=[*sources, _name(temporal)],
                aggregation="SUM" if main else "COUNT",
                confidence=_confidence(confidence * BREAKDOWN_FACTOR, temporal.confidence),
                rationale=f"{_name(temporal)} permet de suivre l'évolution dans le temps.",
                kpi_type=TREND,
                dimension=_name(temporal),
                format=fmt,
            )
        )

    for dimension in _breakdown_dimensions(cols):
        name = _name(dimension)
        title = "Region" if dimension.business_role == GEOGRAPHY else name.replace("_", " ").title()

        kpis.append(
            KPI(
                name=f"{label} by {title}",
                description=f"Répartition de {label} par {name}.",
                formula=f"{expression} GROUP BY {name}",
                source_columns=[*sources, name],
                aggregation="SUM" if main else "COUNT",
                confidence=_confidence(confidence * BREAKDOWN_FACTOR, dimension.confidence),
                rationale=f"{name} est une dimension d'analyse à faible cardinalité.",
                kpi_type=BREAKDOWN,
                dimension=name,
                format=fmt,
            )
        )

    return kpis


def recommend_kpis(
    schema: SchemaProfile,
    semantics: SemanticProfile,
    dataset: str = "dataset",
) -> KpiRecommendation:
    """
    Propose les KPI pertinents d'un dataset.
    """

    domain = semantics.domain.name if semantics.domain else "UNKNOWN"
    is_sales = domain == SALES_DOMAIN
    cols = _Columns(semantics, schema)
    main = _main_measure(cols, is_sales)
    kpis = [
        *_scalar_kpis(cols, main, is_sales),
        *_breakdown_kpis(cols, main),
    ]

    # Règle métier : les commandes annulées ne comptent dans aucun KPI.
    exclusion = cancellation_exclusion(schema, semantics)

    if exclusion:
        for kpi in kpis:
            kpi.formula = with_exclusion(kpi.formula, exclusion)
            kpi.exclusion = exclusion
            kpi.rationale += (
                f" Lignes exclues : {exclusion['column']} = "
                f"{', '.join(exclusion['exclude'])}."
            )

    return KpiRecommendation(dataset=dataset, domain=domain, kpis=kpis)


def recommend_kpis_for_file(path: str, dataset: str | None = None) -> KpiRecommendation:
    """Découvre un fichier puis propose ses KPI."""

    from src.contract.contract_generator import dataset_name_from_path
    from src.discovery.dataset_discovery import discover_dataset
    from src.semantic.semantic_profiler import profile_semantics

    schema = discover_dataset(path).schema

    return recommend_kpis(
        schema,
        profile_semantics(schema),
        dataset or dataset_name_from_path(path),
    )
