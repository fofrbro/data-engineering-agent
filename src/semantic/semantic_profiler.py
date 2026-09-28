"""
Interprétation sémantique des colonnes à partir du profil de schéma.

Chaque interprétation est une inférence, jamais une certitude :
elle porte un score de confiance (toujours < 1) et la liste des
indices qui la justifient. Les règles sont déterministes.
"""

import re
from dataclasses import asdict, dataclass, field

from src.discovery.schema_profiler import (
    BOOLEAN,
    DECIMAL,
    EMPTY,
    IDENTIFIER_MIN_ROWS,
    IDENTIFIER_TOKENS,
    ColumnProfile,
    SchemaProfile,
    name_tokens,
)
from src.semantic.vocabulary import (
    AMOUNT,
    ATTRIBUTE,
    CUSTOMER,
    DATE,
    ORDER,
    PRICE,
    PRODUCT,
    QUANTITY,
    TRANSACTION,
    DIMENSION,
    DIMENSION_KEYWORDS,
    ENTITY_KEYWORDS,
    FLAG,
    CATEGORY,
    CONTACT,
    CONTACT_KEYWORDS,
    GEOGRAPHY,
    IDENTIFIER,
    MEASURE,
    MEASURE_KEYWORDS,
    RATIO,
    TEMPORAL,
    TEMPORAL_KEYWORDS,
    TIMESTAMP,
    match_keyword,
)


# Niveaux de confiance : un indice de nom confirmé par les données
# est plus fiable qu'un indice isolé.
CONFIDENCE_CONFIRMED = 0.95
CONFIDENCE_KEYWORD = 0.9
CONFIDENCE_NAME_ONLY = 0.85
CONFIDENCE_DATA_ONLY = 0.8
CONFIDENCE_CODED_DIMENSION = 0.75
CONFIDENCE_DEFAULT = 0.6
CONFIDENCE_WEAK = 0.55
CONFIDENCE_UNKNOWN = 0.5
CONFIDENCE_EMPTY = 0.3

TIME_PATTERN = re.compile(r"[T ](\d{1,2}):(\d{2})(?::(\d{2}))?")

PRIMARY_KEY_CANDIDATE = "PRIMARY_KEY_CANDIDATE"
FOREIGN_KEY_CANDIDATE = "FOREIGN_KEY_CANDIDATE"

SALES_DOMAIN = "SALES"
UNKNOWN_DOMAIN = "UNKNOWN"
SALES_ENTITIES = {CUSTOMER, PRODUCT, ORDER, TRANSACTION}


@dataclass
class ColumnSemantics:
    column: str
    semantic_role: str
    business_role: str | None
    entity: str | None
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Relationship:
    """
    Clé potentielle : PRIMARY_KEY_CANDIDATE identifie une ligne,
    FOREIGN_KEY_CANDIDATE référence une entité externe.
    """

    column: str
    relationship_type: str
    referenced_entity: str | None
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DomainInference:
    name: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SemanticProfile:
    columns: list[ColumnSemantics]
    relationships: list[Relationship] = field(default_factory=list)
    domain: DomainInference | None = None

    def column(self, name: str) -> ColumnSemantics:
        for semantics in self.columns:
            if semantics.column == name:
                return semantics

        raise KeyError(name)

    def _names(self, semantic_role: str) -> list[str]:
        return [
            semantics.column
            for semantics in self.columns
            if semantics.semantic_role == semantic_role
        ]

    @property
    def identifiers(self) -> list[str]:
        return self._names(IDENTIFIER)

    @property
    def measures(self) -> list[str]:
        return self._names(MEASURE)

    @property
    def dimensions(self) -> list[str]:
        return self._names(DIMENSION)

    @property
    def temporal_columns(self) -> list[str]:
        return self._names(TEMPORAL)

    @property
    def entities(self) -> list[str]:
        return sorted(
            {
                semantics.entity
                for semantics in self.columns
                if semantics.entity
            }
        )

    def to_dict(self) -> dict:
        return {
            "domain": self.domain.to_dict() if self.domain else None,
            "entities": self.entities,
            "identifiers": self.identifiers,
            "measures": self.measures,
            "dimensions": self.dimensions,
            "temporal_columns": self.temporal_columns,
            "columns": [
                semantics.to_dict()
                for semantics in self.columns
            ],
            "relationships": [
                relationship.to_dict()
                for relationship in self.relationships
            ],
        }


def _has_time_component(profile: ColumnProfile) -> bool:
    """Vrai si une valeur observée porte une heure non nulle."""

    values = [profile.min, profile.max, *profile.sample_values]

    for value in values:
        match = TIME_PATTERN.search(str(value))

        if match and any(int(part or 0) for part in match.groups()):
            return True

    return False


def _infer_temporal(
    profile: ColumnProfile,
    entity: str | None,
) -> ColumnSemantics:
    evidence = ["valeurs reconnues comme des dates"]
    keyword = match_keyword(profile.name, TEMPORAL_KEYWORDS)
    has_time = _has_time_component(profile)

    if has_time:
        evidence.append("composante horaire observée")

    if keyword:
        evidence.append(f"nom contenant '{keyword[1]}'")

    is_timestamp = has_time or (keyword and keyword[0] == TIMESTAMP)

    return ColumnSemantics(
        column=profile.name,
        semantic_role=TEMPORAL,
        business_role=TIMESTAMP if is_timestamp else DATE,
        entity=entity,
        confidence=(
            CONFIDENCE_CONFIRMED
            if keyword
            else CONFIDENCE_DATA_ONLY
        ),
        evidence=evidence,
    )


def _infer_identifier(
    profile: ColumnProfile,
    entity: str | None,
) -> ColumnSemantics:
    reasons = profile.identifier_reasons
    evidence = []

    if "name" in reasons:
        evidence.append("nom évoquant un identifiant")

    if "unique_values" in reasons:
        evidence.append("valeurs uniques et non nulles")

    if entity:
        evidence.append(f"entité {entity} reconnue dans le nom")

    if len(reasons) == 2:
        confidence = CONFIDENCE_CONFIRMED
    elif "name" in reasons:
        confidence = CONFIDENCE_NAME_ONLY
    else:
        confidence = CONFIDENCE_DEFAULT

    return ColumnSemantics(
        column=profile.name,
        semantic_role=IDENTIFIER,
        business_role=None,
        entity=entity,
        confidence=confidence,
        evidence=evidence,
    )


def _infer_numeric(
    profile: ColumnProfile,
    entity: str | None,
    dimension: tuple[str, str] | None,
) -> ColumnSemantics:
    measure = match_keyword(profile.name, MEASURE_KEYWORDS)

    if dimension and not measure:
        return ColumnSemantics(
            column=profile.name,
            semantic_role=DIMENSION,
            business_role=dimension[0],
            entity=entity,
            confidence=CONFIDENCE_CODED_DIMENSION,
            evidence=[
                f"nom contenant '{dimension[1]}'",
                "valeurs numériques utilisées comme codes",
            ],
        )

    if measure:
        return ColumnSemantics(
            column=profile.name,
            semantic_role=MEASURE,
            business_role=measure[0],
            entity=entity,
            confidence=CONFIDENCE_KEYWORD,
            evidence=[
                "colonne numérique",
                f"nom contenant '{measure[1]}'",
            ],
        )

    if (
        profile.inferred_type == DECIMAL
        and profile.min is not None
        and 0 <= profile.min
        and profile.max <= 1
    ):
        return ColumnSemantics(
            column=profile.name,
            semantic_role=MEASURE,
            business_role=RATIO,
            entity=entity,
            confidence=CONFIDENCE_WEAK,
            evidence=["valeurs décimales comprises entre 0 et 1"],
        )

    return ColumnSemantics(
        column=profile.name,
        semantic_role=MEASURE,
        business_role=None,
        entity=entity,
        confidence=CONFIDENCE_DEFAULT,
        evidence=["colonne numérique sans indice métier"],
    )


def _infer_text(
    profile: ColumnProfile,
    entity: str | None,
    dimension: tuple[str, str] | None,
) -> ColumnSemantics:
    if profile.inferred_type == BOOLEAN:
        return ColumnSemantics(
            column=profile.name,
            semantic_role=DIMENSION,
            business_role=FLAG,
            entity=entity,
            confidence=CONFIDENCE_DATA_ONLY,
            evidence=["valeurs booléennes"],
        )

    if dimension:
        evidence = [f"nom contenant '{dimension[1]}'"]

        if profile.is_categorical:
            evidence.append("cardinalité faible")

        return ColumnSemantics(
            column=profile.name,
            semantic_role=DIMENSION,
            business_role=dimension[0],
            entity=entity,
            confidence=(
                CONFIDENCE_KEYWORD
                if profile.is_categorical
                else CONFIDENCE_DATA_ONLY
            ),
            evidence=evidence,
        )

    if profile.is_categorical:
        evidence = ["cardinalité faible"]

        if entity:
            evidence.append(f"entité {entity} reconnue dans le nom")

        return ColumnSemantics(
            column=profile.name,
            semantic_role=DIMENSION,
            business_role=None if entity else CATEGORY,
            entity=entity,
            confidence=(
                CONFIDENCE_NAME_ONLY
                if entity
                else CONFIDENCE_DEFAULT
            ),
            evidence=evidence,
        )

    return ColumnSemantics(
        column=profile.name,
        semantic_role=ATTRIBUTE,
        business_role=None,
        entity=entity,
        confidence=CONFIDENCE_UNKNOWN,
        evidence=["texte à forte cardinalité"],
    )


def infer_column_semantics(profile: ColumnProfile) -> ColumnSemantics:
    """
    Interprète une colonne.

    Ordre des règles : vide, temporel, identifiant, numérique, texte.
    Un mot-clé de dimension l'emporte sur un identifiant suggéré
    seulement par un suffixe faible (ex. "zip_code", "status_code").
    """

    entity_match = match_keyword(profile.name, ENTITY_KEYWORDS)
    entity = entity_match[0] if entity_match else None

    if profile.inferred_type == EMPTY:
        return ColumnSemantics(
            column=profile.name,
            semantic_role=ATTRIBUTE,
            business_role=None,
            entity=entity,
            confidence=CONFIDENCE_EMPTY,
            evidence=["colonne sans valeur"],
        )

    if profile.is_temporal:
        return _infer_temporal(profile, entity)

    contact = match_keyword(profile.name, CONTACT_KEYWORDS)

    if contact:
        # Donnée personnelle : conservée, mais jamais agrégée ni
        # utilisée comme axe d'analyse.
        return ColumnSemantics(
            column=profile.name,
            semantic_role=ATTRIBUTE,
            business_role=CONTACT,
            entity=entity,
            confidence=CONFIDENCE_KEYWORD,
            evidence=[f"nom contenant '{contact[1]}'"],
        )

    dimension = match_keyword(profile.name, DIMENSION_KEYWORDS)
    strong_identifier_name = any(
        token in IDENTIFIER_TOKENS
        for token in name_tokens(profile.name)
    )

    dimension_wins = bool(dimension) and (
        dimension[0] == GEOGRAPHY
        or not (strong_identifier_name or profile.is_unique)
    )

    # Des valeurs uniques contenant des espaces évoquent du texte
    # libre plutôt qu'une clé.
    looks_like_free_text = profile.identifier_reasons == [
        "unique_values"
    ] and any(
        " " in str(value).strip()
        for value in profile.sample_values
    )

    if (
        profile.is_identifier_candidate
        and not dimension_wins
        and not looks_like_free_text
    ):
        return _infer_identifier(profile, entity)

    if profile.is_numeric:
        return _infer_numeric(profile, entity, dimension)

    return _infer_text(profile, entity, dimension)


def _entity_from_name(name: str) -> str | None:
    """
    Déduit l'entité référencée par un identifiant d'après son nom :
    "store_id" -> "STORE".
    """

    tokens = [
        token
        for token in name_tokens(name)
        if token not in IDENTIFIER_TOKENS
    ]

    return "_".join(tokens).upper() or None


def detect_relationships(
    schema: SchemaProfile,
    columns: list[ColumnSemantics],
) -> list[Relationship]:
    """
    Détecte les clés primaires et étrangères candidates
    parmi les colonnes identifiants.
    """

    profiles = {column.name: column for column in schema.columns}
    relationships = []

    for semantics in columns:
        if semantics.semantic_role != IDENTIFIER:
            continue

        profile = profiles[semantics.column]
        entity = semantics.entity or _entity_from_name(profile.name)

        if (
            profile.is_unique
            and schema.row_count >= IDENTIFIER_MIN_ROWS
        ):
            relationships.append(
                Relationship(
                    column=profile.name,
                    relationship_type=PRIMARY_KEY_CANDIDATE,
                    referenced_entity=entity,
                    confidence=semantics.confidence,
                    evidence=["valeurs uniques et non nulles"],
                )
            )
            continue

        if "name" not in profile.identifier_reasons:
            continue

        evidence = ["nom évoquant un identifiant"]

        if not profile.is_unique:
            evidence.append("valeurs répétées entre les lignes")
        else:
            evidence.append(
                "unicité non significative sur un petit échantillon"
            )

        relationships.append(
            Relationship(
                column=profile.name,
                relationship_type=FOREIGN_KEY_CANDIDATE,
                referenced_entity=entity,
                confidence=(
                    CONFIDENCE_DATA_ONLY
                    if semantics.entity
                    else CONFIDENCE_DEFAULT
                ),
                evidence=evidence,
            )
        )

    return relationships


def infer_domain(columns: list[ColumnSemantics]) -> DomainInference:
    """
    Déduit le métier du dataset.

    Seul le domaine SALES est reconnu pour l'instant : il exige une
    mesure monétaire (montant ou prix) et au moins un autre indice
    (quantité ou entité commerciale).
    """

    business_roles = {
        semantics.business_role
        for semantics in columns
        if semantics.semantic_role == MEASURE
    }
    entities = {
        semantics.entity
        for semantics in columns
        if semantics.entity
    }

    monetary = business_roles & {AMOUNT, PRICE}
    signals = [
        f"mesure {role}"
        for role in sorted(monetary | (business_roles & {QUANTITY}))
    ] + [
        f"entité {entity}"
        for entity in sorted(entities & SALES_ENTITIES)
    ]

    if not monetary or len(signals) < 2:
        return DomainInference(
            name=UNKNOWN_DOMAIN,
            confidence=0.0,
            evidence=["aucun ensemble d'indices métier suffisant"],
        )

    return DomainInference(
        name=SALES_DOMAIN,
        confidence=min(
            CONFIDENCE_CONFIRMED,
            0.5 + 0.1 * len(signals),
        ),
        evidence=signals,
    )


def profile_semantics(schema: SchemaProfile) -> SemanticProfile:
    """
    Produit le profil sémantique d'un dataset.
    """

    columns = [
        infer_column_semantics(column)
        for column in schema.columns
    ]

    return SemanticProfile(
        columns=columns,
        relationships=detect_relationships(schema, columns),
        domain=infer_domain(columns),
    )
