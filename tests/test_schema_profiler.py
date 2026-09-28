import json

import pandas as pd

from src.discovery.schema_profiler import profile_schema


def column(profile, name):
    return next(c for c in profile.columns if c.name == name)


def orders_frame(rows=12):
    return pd.DataFrame(
        {
            "order_id": range(1, rows + 1),
            "customer_id": [1, 2, 3] * (rows // 3),
            "status": ["PAID", "SHIPPED"] * (rows // 2),
            "order_date": [f"2026-01-{day:02d}" for day in range(1, rows + 1)],
            "amount": [10.5 * i for i in range(1, rows + 1)],
        }
    )


def test_profile_counts_and_types():
    profile = profile_schema(orders_frame())

    assert profile.row_count == 12
    assert profile.column_count == 5
    assert profile.duplicate_rows == 0
    assert column(profile, "order_id").inferred_type == "integer"
    assert column(profile, "amount").inferred_type == "decimal"
    assert column(profile, "status").inferred_type == "string"
    assert column(profile, "order_date").inferred_type == "datetime"


def test_column_categories():
    profile = profile_schema(orders_frame())

    assert profile.numeric_columns == ["order_id", "customer_id", "amount"]
    assert profile.categorical_columns == ["status"]
    assert profile.temporal_columns == ["order_date"]


def test_identifier_candidates_by_name_and_uniqueness():
    frame = orders_frame()
    frame["reference"] = [f"R{i}" for i in range(12)]

    profile = profile_schema(frame)

    assert column(profile, "order_id").identifier_reasons == [
        "name", "unique_values",
    ]
    assert column(profile, "customer_id").identifier_reasons == ["name"]
    assert column(profile, "reference").identifier_reasons == ["unique_values"]
    assert column(profile, "amount").is_identifier_candidate is False
    assert "reference" not in profile.categorical_columns


def test_uniqueness_alone_is_not_enough_on_small_samples():
    frame = pd.DataFrame({"product": ["Laptop", "Mouse", "Keyboard"]})

    product = column(profile_schema(frame), "product")

    assert product.is_unique is True
    assert product.is_identifier_candidate is False
    assert product.is_categorical is True


def test_nulls_cardinality_and_integers_with_nulls():
    frame = pd.DataFrame(
        {
            "quantity": [1, None, 3, 3],
            "comment": [None, None, None, None],
        }
    )

    profile = profile_schema(frame)
    quantity = column(profile, "quantity")
    comment = column(profile, "comment")

    assert quantity.inferred_type == "integer"
    assert quantity.null_count == 1
    assert quantity.null_ratio == 0.25
    assert quantity.distinct_count == 2
    assert quantity.cardinality_ratio == 2 / 3
    assert (quantity.min, quantity.max) == (1, 3)
    assert comment.inferred_type == "empty"
    assert comment.null_ratio == 1.0


def test_duplicate_rows():
    frame = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})

    assert profile_schema(frame).duplicate_rows == 1


def test_temporal_min_max_and_non_date_strings():
    frame = pd.DataFrame(
        {
            "created_at": ["2026-03-01T10:00:00Z", "2026-01-15T08:30:00Z"],
            "year_label": ["2024", "2025"],
        }
    )

    profile = profile_schema(frame)
    created_at = column(profile, "created_at")

    assert created_at.is_temporal is True
    assert created_at.min.startswith("2026-01-15")
    assert created_at.max.startswith("2026-03-01")
    assert column(profile, "year_label").is_temporal is False


def test_boolean_is_categorical_not_numeric():
    frame = pd.DataFrame({"active": [True, False, True]})

    active = column(profile_schema(frame), "active")

    assert active.inferred_type == "boolean"
    assert active.is_categorical is True
    assert active.is_numeric is False


def test_empty_dataframe_with_columns():
    frame = pd.DataFrame(columns=["id", "name"])

    profile = profile_schema(frame)

    assert profile.row_count == 0
    assert profile.column_count == 2
    assert column(profile, "name").inferred_type == "empty"
    assert column(profile, "id").is_unique is False


def test_unhashable_values_from_json():
    frame = pd.DataFrame({"tags": [["a"], ["a"], ["b"]], "id": [1, 1, 2]})

    profile = profile_schema(frame)

    assert column(profile, "tags").distinct_count == 2
    assert profile.duplicate_rows == 1


def test_profile_is_json_serializable():
    payload = profile_schema(orders_frame()).to_dict()

    json.dumps(payload)

    assert payload["identifier_candidates"] == ["order_id", "customer_id"]


def test_french_identifier_names_start_with_the_hint():
    frame = pd.DataFrame(
        {
            "numero_de_commande": ["SO1", "SO1", "SO2"] * 4,
            "code_client": ["C1", "C2", "C1"] * 4,
            "numero": [1, 2, 3] * 4,
            "quantite": [1, 2, 3] * 4,
        }
    )

    profile = profile_schema(frame)

    # Valeurs répétées (plusieurs lignes par commande) : seul le nom compte.
    assert column(profile, "numero_de_commande").identifier_reasons == ["name"]
    assert column(profile, "code_client").identifier_reasons == ["name"]
    assert column(profile, "numero").is_identifier_candidate is False
    assert column(profile, "quantite").is_identifier_candidate is False
