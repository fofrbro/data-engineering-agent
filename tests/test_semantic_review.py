import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.discovery.schema_profiler import profile_schema
from src.semantic.semantic_profiler import profile_semantics
from src.semantic.semantic_review import (
    COMPLETED,
    UNAVAILABLE,
    apply_semantic_overrides,
    column_context,
    review_input,
    review_semantics,
)


class FakeClient:
    """Client LLM de test : renvoie une réponse fixe ou lève une erreur."""

    def __init__(self, suggestions=None, error=None):
        self.calls = []
        self.responses = SimpleNamespace(create=self._create)
        self._suggestions = suggestions or []
        self._error = error

    def _create(self, **kwargs):
        self.calls.append(kwargs)

        if self._error:
            raise self._error

        return SimpleNamespace(output_text=json.dumps({"suggestions": self._suggestions}))


def suggestion(column, semantic_role, business_role, reason="raison"):
    return {
        "column": column,
        "semantic_role": semantic_role,
        "business_role": business_role,
        "reason": reason,
    }


def sales_frame(rows=12):
    return pd.DataFrame(
        {
            "order_id": [f"SO{i}" for i in range(rows)],
            "status": ["PAID", "SHIPPED"] * (rows // 2),
            "email": [f"client{i % 3}@exemple.com" for i in range(rows)],
            "quantity": [1, 2, 3] * (rows // 3),
            "unit_price": [10.0, 20.0] * (rows // 2),
            "net_value": [10.0, 40.0, 30.0] * (rows // 3),
        }
    )


@pytest.fixture
def profiles():
    schema = profile_schema(sales_frame())
    return schema, profile_semantics(schema)


def test_valid_suggestion_is_kept_and_invalid_ones_are_discarded(profiles):
    schema, semantics = profiles
    client = FakeClient(
        [
            suggestion("net_value", "MEASURE", "AMOUNT", "Valeur nette de la ligne."),
            suggestion("net_value", "MEASURE", "TAX"),
            suggestion("inconnue", "MEASURE", "AMOUNT"),
            suggestion("status", "MEASURE", "AMOUNT"),
            suggestion("quantity", "DIMENSION", "TAX"),
            suggestion("quantity", "MEASURE", "QUANTITY"),
        ]
    )

    review = review_semantics(client, schema, semantics, "ventes")

    assert review.status == COMPLETED
    assert [(s.id, s.column, s.business_role) for s in review.suggestions] == [
        ("s1", "net_value", "AMOUNT"),
    ]
    assert review.suggestions[0].current_semantic_role == "MEASURE"
    assert review.suggestions[0].current_business_role is None
    assert [d["discard_reason"] for d in review.discarded] == [
        "plusieurs suggestions pour la même colonne",
        "colonne inconnue",
        "une mesure doit être numérique",
        "rôle métier TAX incompatible avec DIMENSION",
        "identique à l'interprétation actuelle",
    ]


def test_request_uses_a_strict_schema(profiles):
    schema, semantics = profiles
    client = FakeClient()

    review = review_semantics(client, schema, semantics, "ventes")

    assert review.suggestions == []
    request = client.calls[0]
    assert request["text"]["format"]["strict"] is True
    assert json.loads(request["input"])["dataset"] == "ventes"


def test_personal_and_identifier_values_are_not_sent(profiles):
    schema, semantics = profiles

    sent = {c["name"]: c for c in json.loads(review_input(schema, semantics, "ventes"))["columns"]}

    assert sent["email"]["business_role"] == "CONTACT"
    assert "sample_values" not in sent["email"]
    assert "sample_values" not in sent["order_id"]
    assert sent["status"]["sample_values"] == ["PAID", "SHIPPED"]
    assert sent["quantity"]["min"] == 1


def test_numeric_bounds_are_json_serializable(profiles):
    schema, semantics = profiles
    profile = next(p for p in schema.columns if p.name == "unit_price")

    context = column_context(profile, semantics.column("unit_price"))

    json.dumps(context)
    assert (context["min"], context["max"]) == (10.0, 20.0)


def test_missing_client_makes_the_review_unavailable(profiles):
    review = review_semantics(None, *profiles, "ventes")

    assert review.status == UNAVAILABLE
    assert "OPENAI_API_KEY" in review.error


def test_rejected_key_is_reported_without_its_message(profiles):
    class AuthenticationError(Exception):
        pass

    client = FakeClient(error=AuthenticationError("Incorrect API key provided: sk-abc...xyz"))

    review = review_semantics(client, *profiles, "ventes")

    assert review.status == UNAVAILABLE
    assert review.error == "Clé API refusée (absente, invalide ou expirée)."


def test_other_llm_errors_make_the_review_unavailable(profiles):
    review = review_semantics(FakeClient(error=TimeoutError("délai dépassé")), *profiles, "ventes")

    assert review.status == UNAVAILABLE
    assert review.error == "LLM indisponible : TimeoutError: délai dépassé"


def test_overrides_replace_roles_and_recompute_the_domain():
    schema = profile_schema(sales_frame()[["order_id", "quantity", "net_value"]])
    semantics = profile_semantics(schema)

    updated = apply_semantic_overrides(
        semantics,
        schema,
        {
            "net_value": {
                "semantic_role": "MEASURE",
                "business_role": "AMOUNT",
                "reason": "valeur nette",
                "accepted_by": "cheikhou",
            }
        },
    )

    assert semantics.domain.name == "UNKNOWN"
    assert updated.column("net_value").business_role == "AMOUNT"
    assert updated.column("net_value").evidence == [
        "relecture sémantique acceptée par cheikhou : valeur nette"
    ]
    assert updated.domain.name == "SALES"
    assert apply_semantic_overrides(semantics, schema, {}) is semantics
