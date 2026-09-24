import pandas as pd

from src.tabular_pipeline import (
    clean_dataframe,
    enrich_dataframe,
    profile_dataframe,
    read_tabular_file,
)


def test_profile_and_clean_dataframe():
    frame = pd.DataFrame({" name ": [" A ", " A "], "value": [1, 1]})

    profile = profile_dataframe(frame)
    cleaned, result = clean_dataframe(frame)

    assert profile["rows"] == 2
    assert list(cleaned.columns) == ["name", "value"]
    assert len(cleaned) == 1
    assert result["duplicates_removed"] == 1


def test_enrichment_operations_are_declarative():
    frame = pd.DataFrame({"quantity": [2], "price": [10], "date": ["2026-01-03"]})

    enriched, applied = enrich_dataframe(frame, [
        {"type": "arithmetic", "target": "total", "left": "quantity", "right": "price"},
        {"type": "date_part", "target": "year", "source": "date", "part": "year"},
    ])

    assert enriched.loc[0, "total"] == 20
    assert enriched.loc[0, "year"] == 2026
    assert [item["target"] for item in applied] == ["total", "year"]


def test_read_json_file(tmp_path):
    source = tmp_path / "events.json"
    source.write_text('[{"id": 1, "label": "ok"}]', encoding="utf-8")

    frame = read_tabular_file(source)

    assert frame.to_dict(orient="records") == [{"id": 1, "label": "ok"}]