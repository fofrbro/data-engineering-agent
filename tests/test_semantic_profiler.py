import json

import pandas as pd

from src.discovery.dataset_discovery import discover_dataset
from src.discovery.schema_profiler import profile_schema
from src.semantic.semantic_profiler import profile_semantics
from src.semantic.vocabulary import match_keyword, MEASURE_KEYWORDS


def semantics_of(frame):
    return profile_semantics(profile_schema(frame))


def orders_frame(rows=12):
    return pd.DataFrame(
        {
            "order_id": range(1, rows + 1),
            "customer_id": [1, 2, 3] * (rows // 3),
            "product": ["Laptop", "Mouse"] * (rows // 2),
            "status": ["PAID", "SHIPPED"] * (rows // 2),
            "country": ["FR", "SN"] * (rows // 2),
            "order_date": [f"2026-01-{day:02d}" for day in range(1, rows + 1)],
            "quantity": [1, 2, 3] * (rows // 3),
            "unit_price": [10.5, 20.0] * (rows // 2),
            "discount_rate": [0.1, 0.2] * (rows // 2),
            "total_amount": [100.5 * i for i in range(1, rows + 1)],
        }
    )


def test_keyword_priority_and_accents():
    assert match_keyword("discount_rate", MEASURE_KEYWORDS)[0] == "RATIO"
    assert match_keyword("UnitPrice", MEASURE_KEYWORDS)[0] == "PRICE"
    assert match_keyword("Quantité", MEASURE_KEYWORDS)[0] == "QUANTITY"
    assert match_keyword("chiffre_affaires", MEASURE_KEYWORDS)[0] == "AMOUNT"
    assert match_keyword("capacity", MEASURE_KEYWORDS) is None


def test_roles_of_a_sales_dataset():
    profile = semantics_of(orders_frame())

    expected = {
        "order_id": ("IDENTIFIER", None, "ORDER"),
        "customer_id": ("IDENTIFIER", None, "CUSTOMER"),
        "product": ("DIMENSION", None, "PRODUCT"),
        "status": ("DIMENSION", "STATUS", None),
        "country": ("DIMENSION", "GEOGRAPHY", None),
        "order_date": ("TEMPORAL", "DATE", "ORDER"),
        "quantity": ("MEASURE", "QUANTITY", None),
        "unit_price": ("MEASURE", "PRICE", None),
        "discount_rate": ("MEASURE", "RATIO", None),
        "total_amount": ("MEASURE", "AMOUNT", None),
    }

    for column, (semantic, business, entity) in expected.items():
        semantics = profile.column(column)
        assert (
            semantics.semantic_role,
            semantics.business_role,
            semantics.entity,
        ) == (semantic, business, entity), column


def test_confidence_is_bounded_and_justified():
    profile = semantics_of(orders_frame())

    for semantics in profile.columns:
        assert 0 < semantics.confidence < 1
        assert semantics.evidence

    # Nom + unicité > nom seul.
    assert (
        profile.column("order_id").confidence
        > profile.column("customer_id").confidence
    )


def test_timestamp_detected_from_time_component():
    frame = pd.DataFrame(
        {
            "created": ["2026-01-01 10:30:00", "2026-01-02 11:00:00"],
            "created_at": ["2026-01-01", "2026-01-02"],
            "birth_day": ["2026-01-01", "2026-01-02"],
        }
    )

    profile = semantics_of(frame)

    assert profile.column("created").business_role == "TIMESTAMP"
    assert profile.column("created_at").business_role == "TIMESTAMP"
    assert profile.column("birth_day").business_role == "DATE"
    assert profile.column("created").confidence < profile.column("birth_day").confidence


def test_dimension_keyword_overrides_weak_identifier_suffix():
    frame = pd.DataFrame(
        {
            "status_code": [1, 2, 1, 2],
            "zip_code": ["75001", "75002", "75001", "75003"],
            "product_code": ["A", "B", "A", "C"],
        }
    )

    profile = semantics_of(frame)

    assert profile.column("status_code").semantic_role == "DIMENSION"
    assert profile.column("status_code").business_role == "STATUS"
    assert profile.column("zip_code").business_role == "GEOGRAPHY"
    assert profile.column("product_code").semantic_role == "IDENTIFIER"
    assert profile.column("product_code").entity == "PRODUCT"


def test_numeric_without_hint_is_low_confidence_measure():
    frame = pd.DataFrame(
        {
            "score": [0.1, 0.5, 0.9],
            "capacity": [10, 20, 35],
            "year": [2024, 2025, 2026],
        }
    )

    profile = semantics_of(frame)

    assert profile.column("score").business_role == "RATIO"
    assert profile.column("score").confidence == 0.55
    assert profile.column("capacity").semantic_role == "MEASURE"
    assert profile.column("capacity").business_role is None
    assert profile.column("capacity").confidence == 0.6
    assert profile.column("year").semantic_role == "DIMENSION"
    assert profile.column("year").business_role == "DATE_PART"


def test_boolean_empty_and_free_text_columns():
    frame = pd.DataFrame(
        {
            "is_active": [True, False] * 30,
            "notes": [None] * 60,
            "comment": [f"texte libre {i}" for i in range(60)],
            "segment": ["A", "B", "C"] * 20,
        }
    )

    profile = semantics_of(frame)

    assert profile.column("is_active").business_role == "FLAG"
    assert profile.column("notes").semantic_role == "ATTRIBUTE"
    assert profile.column("notes").confidence == 0.3
    assert profile.column("comment").semantic_role == "ATTRIBUTE"
    assert profile.column("segment").business_role == "CATEGORY"


def test_existing_sales_file_end_to_end():
    schema = discover_dataset("data/sales.csv").schema

    profile = profile_semantics(schema)
    payload = profile.to_dict()
    json.dumps(payload)

    assert payload["identifiers"] == ["customer_id"]
    assert payload["measures"] == ["quantity", "price"]
    assert payload["dimensions"] == ["product"]
    assert profile.column("price").business_role == "PRICE"


def relationship(profile, column):
    return next(r for r in profile.relationships if r.column == column)


def test_primary_and_foreign_key_candidates():
    frame = orders_frame()
    frame["store_id"] = [7, 8] * 6

    profile = semantics_of(frame)

    order_key = relationship(profile, "order_id")
    customer_key = relationship(profile, "customer_id")
    store_key = relationship(profile, "store_id")

    assert order_key.relationship_type == "PRIMARY_KEY_CANDIDATE"
    assert order_key.referenced_entity == "ORDER"
    assert customer_key.relationship_type == "FOREIGN_KEY_CANDIDATE"
    assert customer_key.referenced_entity == "CUSTOMER"
    assert store_key.referenced_entity == "STORE"
    assert store_key.confidence < customer_key.confidence
    assert {r.column for r in profile.relationships} == {
        "order_id", "customer_id", "store_id",
    }


def test_small_unique_sample_is_not_a_primary_key():
    profile = profile_semantics(discover_dataset("data/sales.csv").schema)

    customer_key = relationship(profile, "customer_id")

    assert customer_key.relationship_type == "FOREIGN_KEY_CANDIDATE"
    assert "petit échantillon" in customer_key.evidence[-1]


def test_sales_domain_detected():
    profile = semantics_of(orders_frame())

    assert profile.domain.name == "SALES"
    assert 0.5 < profile.domain.confidence < 1
    assert "mesure PRICE" in profile.domain.evidence
    assert profile.entities == ["CUSTOMER", "ORDER", "PRODUCT"]


def test_unknown_domain_without_monetary_measure():
    frame = pd.DataFrame(
        {
            "sensor": ["A", "B"] * 6,
            "temperature": [20.5, 21.0] * 6,
            "quantity": [1, 2] * 6,
        }
    )

    domain = semantics_of(frame).domain

    assert domain.name == "UNKNOWN"
    assert domain.confidence == 0.0


def test_tax_is_not_the_sales_amount():
    assert match_keyword("TaxAmount", MEASURE_KEYWORDS)[0] == "TAX"
    assert match_keyword("montant_tva", MEASURE_KEYWORDS)[0] == "TAX"
    # Un taux de taxe reste un ratio.
    assert match_keyword("tax_rate", MEASURE_KEYWORDS)[0] == "RATIO"


def test_contact_columns_are_personal_attributes():
    frame = pd.DataFrame(
        {
            "EmailAddress": [f"client{i % 4}@exemple.com" for i in range(12)],
            "customer_phone": [f"06000000{i % 4}" for i in range(12)],
            "shipping_address": ["1 rue A", "2 rue B"] * 6,
        }
    )

    semantics = semantics_of(frame)

    for name in ("EmailAddress", "customer_phone"):
        column = semantics.column(name)
        assert (column.semantic_role, column.business_role) == ("ATTRIBUTE", "CONTACT")
    # Une adresse postale reste géographique.
    assert semantics.column("shipping_address").business_role == "GEOGRAPHY"
