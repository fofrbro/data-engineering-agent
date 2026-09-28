import pandas as pd
import pytest

from src.execution.enrichment import enrich_dataframe


def test_enrichment_operations_are_declarative():
    frame = pd.DataFrame({"quantity": [2], "price": [10], "date": ["2026-01-03"]})

    enriched, applied = enrich_dataframe(frame, [
        {"type": "arithmetic", "target": "total", "left": "quantity", "right": "price"},
        {"type": "date_part", "target": "year", "source": "date", "part": "year"},
    ])

    assert enriched.loc[0, "total"] == 20
    assert enriched.loc[0, "year"] == 2026
    assert [item["target"] for item in applied] == ["total", "year"]


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "arithmetic", "target": "quantity", "left": "quantity", "right": "price"},
        {"type": "arithmetic", "target": "x", "left": "absent", "right": "price"},
        {"type": "code", "target": "x", "expression": "__import__('os')"},
    ],
)
def test_invalid_operations_are_refused(operation):
    with pytest.raises(ValueError):
        enrich_dataframe(pd.DataFrame({"quantity": [2], "price": [10]}), [operation])
