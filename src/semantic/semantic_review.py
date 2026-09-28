"""
Relecture sémantique par LLM.

Le LLM relit l'interprétation déterministe des colonnes et propose des
corrections de rôle. Il ne décide rien :
- chaque suggestion est vérifiée par le code (colonne existante, rôles
  connus et compatibles avec le type observé, changement réel) ; une
  suggestion invalide est écartée avec sa raison ;
- une suggestion ne s'applique qu'après acceptation par un relecteur
  nommé (voir src.workflow.agent_workflow) ;
- si le LLM est indisponible (clé absente ou expirée, réseau), la
  relecture est marquée UNAVAILABLE et le plan reste utilisable.

Données envoyées au LLM : nom, type, statistiques et rôles de chaque
colonne. Les valeurs d'exemple ne sont envoyées que pour les colonnes
catégorielles qui ne sont ni des identifiants ni des coordonnées
personnelles.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from src.discovery.schema_profiler import ColumnProfile, SchemaProfile
from src.semantic.semantic_profiler import (
    CONFIDENCE_CONFIRMED,
    ColumnSemantics,
    SemanticProfile,
    detect_relationships,
    infer_domain,
)
from src.semantic.vocabulary import (
    AMOUNT,
    ATTRIBUTE,
    CATEGORY,
    CONTACT,
    DATE,
    DATE_PART,
    DIMENSION,
    FLAG,
    GEOGRAPHY,
    IDENTIFIER,
    LEVEL,
    MEASURE,
    PRICE,
    QUANTITY,
    RATIO,
    STATUS,
    TAX,
    TEMPORAL,
    TIMESTAMP,
)


MODEL = "gpt-5.6"

# Statut de la relecture.
COMPLETED = "COMPLETED"
UNAVAILABLE = "UNAVAILABLE"

# Statut d'une suggestion.
PROPOSED = "PROPOSED"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"

MAX_SAMPLE_VALUES = 5

# Rôles métier admis pour chaque rôle sémantique.
COMPATIBLE_ROLES = {
    MEASURE: (AMOUNT, PRICE, QUANTITY, RATIO, TAX, LEVEL, None),
    DIMENSION: (STATUS, CATEGORY, GEOGRAPHY, DATE_PART, FLAG, None),
    TEMPORAL: (DATE, TIMESTAMP),
    IDENTIFIER: (None,),
    ATTRIBUTE: (CONTACT, None),
}
SEMANTIC_ROLES = list(COMPATIBLE_ROLES)
BUSINESS_ROLES = sorted(
    {role for roles in COMPATIBLE_ROLES.values() for role in roles if role}
)

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "semantic_role": {"type": "string", "enum": SEMANTIC_ROLES},
                    "business_role": {
                        "type": ["string", "null"],
                        "enum": [*BUSINESS_ROLES, None],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["column", "semantic_role", "business_role", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}

REVIEW_INSTRUCTIONS = f"""
Tu relis l'interprétation automatique des colonnes d'un dataset, produite
par des règles à partir des noms de colonnes et des données.

Rôles sémantiques et rôles métier admis :
- MEASURE : valeur numérique agrégeable ; rôle métier AMOUNT (montant des
  ventes ou d'une transaction), PRICE (prix unitaire), QUANTITY, RATIO,
  TAX (taxe : ce n'est pas un montant de ventes), LEVEL (mesure de niveau
  qui se moyenne et ne s'additionne pas : âge, température, note, score)
  ou null (mesure additive sans rôle précis).
- DIMENSION : axe d'analyse ; STATUS, CATEGORY, GEOGRAPHY, DATE_PART,
  FLAG ou null.
- TEMPORAL : DATE ou TIMESTAMP.
- IDENTIFIER : clé ; rôle métier null.
- ATTRIBUTE : donnée descriptive non analysée ; CONTACT (e-mail,
  téléphone : donnée personnelle) ou null.

Règles :
1. Ne propose une correction que si l'interprétation actuelle est
   manifestement fausse et qu'elle fausserait les indicateurs (par exemple
   une taxe prise pour le chiffre d'affaires, un e-mail pris pour une
   adresse géographique, une température ou un âge qui serait additionné).
   En cas de doute, ne propose rien.
2. Utilise uniquement les noms de colonnes fournis.
3. reason : une phrase en français, compréhensible par un analyste métier.
4. Une liste vide est une réponse normale.
Rôles métier connus : {", ".join(BUSINESS_ROLES)}.
"""


@dataclass
class SemanticSuggestion:
    id: str
    column: str
    current_semantic_role: str
    current_business_role: str | None
    semantic_role: str
    business_role: str | None
    reason: str
    status: str = PROPOSED

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SemanticReview:
    status: str
    reviewed_at: str
    model: str | None = None
    suggestions: list[SemanticSuggestion] = field(default_factory=list)
    # Suggestions du LLM écartées par les contrôles, avec la raison.
    discarded: list[dict] = field(default_factory=list)
    error: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None

    @property
    def pending(self) -> list[SemanticSuggestion]:
        return [s for s in self.suggestions if s.status == PROPOSED]

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value):
    """Valeur sérialisable en JSON (nombres gardés, reste en texte)."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def column_context(profile: ColumnProfile, semantics: ColumnSemantics) -> dict:
    """Ce que le LLM voit d'une colonne."""

    context = {
        "name": profile.name,
        "type": profile.inferred_type,
        "null_ratio": round(profile.null_ratio, 3),
        "distinct_count": profile.distinct_count,
        "unique": profile.is_unique,
        "semantic_role": semantics.semantic_role,
        "business_role": semantics.business_role,
        "entity": semantics.entity,
        "confidence": semantics.confidence,
        "evidence": semantics.evidence,
    }

    if profile.is_numeric:
        context["min"] = _plain(profile.min)
        context["max"] = _plain(profile.max)

    shareable = (
        profile.is_categorical
        and semantics.semantic_role != IDENTIFIER
        and semantics.business_role != CONTACT
    )

    if shareable:
        context["sample_values"] = [
            _plain(value) for value in profile.sample_values[:MAX_SAMPLE_VALUES]
        ]

    return context


def review_input(schema: SchemaProfile, semantics: SemanticProfile, dataset: str) -> str:
    roles = {column.column: column for column in semantics.columns}

    return json.dumps(
        {
            "dataset": dataset,
            "row_count": schema.row_count,
            "columns": [
                column_context(profile, roles[profile.name])
                for profile in schema.columns
                if profile.name in roles
            ],
        },
        ensure_ascii=False,
    )


def check_suggestion(
    raw: dict,
    schema: SchemaProfile,
    semantics: SemanticProfile,
    seen: set[str],
) -> str | None:
    """Raison d'écarter une suggestion du LLM, ou None si elle est recevable."""

    profiles = {profile.name: profile for profile in schema.columns}
    column = raw.get("column")
    semantic_role = raw.get("semantic_role")
    business_role = raw.get("business_role")

    if column not in profiles:
        return "colonne inconnue"

    if column in seen:
        return "plusieurs suggestions pour la même colonne"

    if business_role not in COMPATIBLE_ROLES.get(semantic_role, ()):
        return f"rôle métier {business_role} incompatible avec {semantic_role}"

    profile = profiles[column]

    if semantic_role == MEASURE and not profile.is_numeric:
        return "une mesure doit être numérique"

    if semantic_role == TEMPORAL and not profile.is_temporal:
        return "une colonne temporelle doit contenir des dates"

    current = semantics.column(column)

    if (current.semantic_role, current.business_role) == (semantic_role, business_role):
        return "identique à l'interprétation actuelle"

    return None


def _unavailable(error: str) -> SemanticReview:
    return SemanticReview(status=UNAVAILABLE, reviewed_at=_now(), error=error)


def review_semantics(
    client,
    schema: SchemaProfile,
    semantics: SemanticProfile,
    dataset: str,
    model: str = MODEL,
) -> SemanticReview:
    """Demande au LLM ses corrections, puis ne garde que les recevables."""

    if client is None:
        return _unavailable("Aucun client LLM configuré (OPENAI_API_KEY absente).")

    try:
        response = client.responses.create(
            model=model,
            instructions=REVIEW_INSTRUCTIONS,
            input=review_input(schema, semantics, dataset),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "semantic_review",
                    "schema": REVIEW_SCHEMA,
                    "strict": True,
                }
            },
        )
        raw_suggestions = json.loads(response.output_text)["suggestions"]
    except Exception as exc:
        if type(exc).__name__ == "AuthenticationError":
            # Le message d'origine peut contenir une partie de la clé.
            return _unavailable("Clé API refusée (absente, invalide ou expirée).")

        return _unavailable(f"LLM indisponible : {type(exc).__name__}: {exc}"[:300])

    suggestions, discarded, seen = [], [], set()

    for raw in raw_suggestions:
        reason = check_suggestion(raw, schema, semantics, seen)

        if reason:
            discarded.append({**raw, "discard_reason": reason})
            continue

        seen.add(raw["column"])
        current = semantics.column(raw["column"])
        suggestions.append(
            SemanticSuggestion(
                id=f"s{len(suggestions) + 1}",
                column=raw["column"],
                current_semantic_role=current.semantic_role,
                current_business_role=current.business_role,
                semantic_role=raw["semantic_role"],
                business_role=raw["business_role"],
                reason=raw["reason"],
            )
        )

    return SemanticReview(
        status=COMPLETED,
        reviewed_at=_now(),
        model=model,
        suggestions=suggestions,
        discarded=discarded,
    )


def apply_semantic_overrides(
    semantics: SemanticProfile,
    schema: SchemaProfile,
    overrides: dict[str, dict],
) -> SemanticProfile:
    """
    Applique les rôles acceptés par un relecteur. Relations et domaine
    sont recalculés, puisqu'ils dépendent des rôles.
    """

    if not overrides:
        return semantics

    columns = []

    for column in semantics.columns:
        override = overrides.get(column.column)

        if override is None:
            columns.append(column)
            continue

        columns.append(
            ColumnSemantics(
                column=column.column,
                semantic_role=override["semantic_role"],
                business_role=override["business_role"],
                entity=column.entity,
                confidence=CONFIDENCE_CONFIRMED,
                evidence=[
                    f"relecture sémantique acceptée par {override['accepted_by']} : "
                    f"{override['reason']}"
                ],
            )
        )

    return SemanticProfile(
        columns=columns,
        relationships=detect_relationships(schema, columns),
        domain=infer_domain(columns),
    )
