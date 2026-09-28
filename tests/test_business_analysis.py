import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.analysis.analysis_commentary import (
    anonymized_payload,
    cited_numbers,
    comment_analysis,
    unverified_numbers,
)
from src.analysis.business_analysis import (
    analyze_business_data,
    fr_number,
    fr_percent,
    render_analysis_text,
)
from src.discovery.schema_profiler import profile_schema
from src.recommendation.kpi_recommender import recommend_kpis
from src.semantic.semantic_profiler import profile_semantics
from tests.test_semantic_review import FakeClient


def sales_frame(start="2024-01-01", months=24):
    """Une commande par jour ; la dernière de chaque mois est annulée."""

    days = pd.date_range(start, periods=months * 31, freq="D")
    days = days[days < pd.Timestamp(start) + pd.DateOffset(months=months)]
    frame = pd.DataFrame(
        {
            "order_id": [f"SO{i}" for i in range(len(days))],
            "order_date": days,
            "customer_id": [f"C{i % 40}" for i in range(len(days))],
            "product": [f"P{i % 7}" for i in range(len(days))],
            "status": "PAID",
            "quantity": [1 + i % 3 for i in range(len(days))],
            "unit_price": [10.0 + (i % 5) for i in range(len(days))],
        }
    )
    frame.loc[frame["order_date"].dt.is_month_end, "status"] = "CANCELLED"
    return frame


def analyze(frame, dataset="ventes"):
    schema = profile_schema(frame)
    semantics = profile_semantics(schema)
    return analyze_business_data(frame, recommend_kpis(schema, semantics, dataset), semantics, dataset)


@pytest.fixture(scope="module")
def analysis():
    return analyze(sales_frame())


def kpi(analysis, name):
    return next(k["value"] for k in analysis["kpis"] if k["name"] == name)


def test_kpis_use_the_business_rule(analysis):
    frame = sales_frame()
    kept = frame[frame["status"] != "CANCELLED"]

    assert analysis["overview"]["excluded_rows"] == 24
    assert analysis["overview"]["exclusion"] == "status : CANCELLED"
    assert kpi(analysis, "Revenue") == pytest.approx((kept["quantity"] * kept["unit_price"]).sum())
    assert kpi(analysis, "Orders") == len(kept)


def test_monthly_trend_and_year_over_year(analysis):
    frame = sales_frame()
    kept = frame[frame["status"] != "CANCELLED"]
    by_month = (kept["quantity"] * kept["unit_price"]).groupby(kept["order_date"].dt.to_period("M")).sum()
    by_year = (kept["quantity"] * kept["unit_price"]).groupby(kept["order_date"].dt.year).sum()
    trend = analysis["trend"]

    assert len(trend["months"]) == 24
    assert trend["incomplete_months"] == []
    assert trend["best"]["month"] == str(by_month.idxmax())
    assert trend["best"]["value"] == pytest.approx(by_month.max())
    assert [y["months"] for y in trend["years"]] == [12, 12]
    assert trend["year_change"]["rate"] == pytest.approx(by_year[2025] / by_year[2024] - 1)


def test_partial_first_and_last_months_are_flagged():
    frame = sales_frame(start="2024-01-15", months=3)

    trend = analyze(frame)["trend"]

    assert trend["incomplete_months"] == ["2024-01", "2024-04"]
    assert trend["best"]["month"] not in trend["incomplete_months"]


def test_breakdowns_top_and_concentration(analysis):
    product = next(b for b in analysis["breakdowns"] if b["column"] == "product")

    assert product["distinct"] == 7
    assert len(product["top"]) == 5
    assert sum(t["share"] for t in product["top"]) == pytest.approx(product["top_share"])
    assert product["top"][0]["total"] >= product["top"][-1]["total"]
    assert 1 <= product["values_for_80_percent"] <= 7


def test_distributions_constants_and_outliers():
    frame = sales_frame(months=6)
    frame["quantity"] = 1
    frame.loc[0, "unit_price"] = 10_000.0

    distributions = {d["column"]: d for d in analyze(frame)["distributions"]}

    # Les distributions portent sur les lignes analysées (hors annulations).
    analysed = int((frame["status"] != "CANCELLED").sum())
    assert distributions["quantity"] == {"column": "quantity", "count": analysed, "constant": 1}
    assert distributions["unit_price"]["outliers"] == 1
    assert distributions["unit_price"]["largest"][0] == 10_000


def test_insights_are_written_in_french(analysis):
    text = " ".join(analysis["insights"])

    assert "par rapport à 2024 (années complètes)" in text
    assert " %" in text
    assert fr_number(1668735.18) == "1 668 735,18"
    assert fr_percent(0.678) == "67,8 %"


def test_analysis_is_json_serializable_and_rendered(analysis):
    json.dumps(analysis)
    text = render_analysis_text(analysis)

    assert text.startswith("ANALYSE DES DONNÉES - ventes")
    assert "Constats :" in text


def test_customer_labels_and_emails_never_reach_the_llm():
    analysis = {
        "breakdowns": [
            {"entity": "CUSTOMER", "top": [{"value": "Christy Zhu"}, {"value": "Julio Ruiz"}]},
            {"entity": None, "top": [{"value": "a@b.fr"}]},
            {"entity": "PRODUCT", "top": [{"value": "Road-150"}]},
        ],
        "commentary": {"summary": "ancien"},
    }

    payload = anonymized_payload(analysis)

    assert [[t["value"] for t in b["top"]] for b in payload["breakdowns"]] == [
        ["Client 1", "Client 2"], ["Client 1"], ["Road-150"],
    ]
    assert "commentary" not in payload
    assert analysis["breakdowns"][0]["top"][0]["value"] == "Christy Zhu"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("20,9 M", [("20,9 M", 20_900_000, 50_000)]),
        ("1 668 735,18", [("1 668 735,18", 1668735.18, 0.005)]),
        ("67,8 %", [("67,8 %", 67.8, 0.05)]),
        ("355,13 k", [("355,13 k", 355130, 5)]),
        ("en 2021, top 5, 12 mois", []),
    ],
)
def test_cited_numbers(text, expected):
    assert [(label, pytest.approx(value), pytest.approx(precision))
            for label, value, precision in cited_numbers(text)] == expected


def test_unverified_numbers_catch_invented_figures():
    analysis = {"kpis": [{"value": 20928022.43}], "trend": {"rate": 0.678}, "rows": 12387}

    text = "CA de 20,93 M (+67,8 %), 12 387 clients, et 999 999 commandes inventées."

    assert unverified_numbers(text, analysis) == ["999 999"]


def test_commentary_with_a_fake_llm(analysis):
    revenue = kpi(analysis, "Revenue")
    reply = {"summary": f"Le chiffre d'affaires atteint {fr_number(revenue)}.", "points": ["Il y a 123 456,78 clients."]}
    client = FakeClient()
    client.responses.create = lambda **kwargs: SimpleNamespace(output_text=json.dumps(reply))

    commentary = comment_analysis(client, analysis)

    assert commentary.status == "COMPLETED"
    assert commentary.unverified_numbers == ["123 456,78"]


def test_commentary_without_llm_is_unavailable(analysis):
    assert comment_analysis(None, analysis).status == "UNAVAILABLE"


def sensors_frame():
    """Deux villes aux températures nettement différentes, une troisième proche."""

    times = pd.date_range("2025-01-01", periods=360, freq="12h")
    city = ["Dakar", "Oslo", "Lyon"] * 120
    base = {"Dakar": 30.0, "Oslo": 5.0, "Lyon": 15.0}
    return pd.DataFrame(
        {
            "sensor_id": [f"S{i % 6}" for i in range(360)],
            "city": city,
            "measured_at": times,
            "temperature": [base[c] + (i % 4) for i, c in enumerate(city)],
            "humidity": [60.0 + (i % 5) for i in range(360)],
        }
    )


def test_level_measures_are_averaged_and_rows_are_counted():
    analysis = analyze(sensors_frame(), "capteurs")

    assert (analysis["measure"], analysis["measure_format"]) == ("Nombre de lignes", "integer")
    assert sum(m["value"] for m in analysis["trend"]["months"]) == 360
    kpis = {k["name"]: k["value"] for k in analysis["kpis"]}
    assert "Total temperature" not in kpis
    assert kpis["Average temperature"] == pytest.approx(sensors_frame()["temperature"].mean())

    temperature = next(a for a in analysis["averages"] if a["column"] == "temperature")
    by_city = {v["value"]: v["mean"] for v in temperature["by_dimension"][0]["values"]}
    assert by_city == pytest.approx({"Dakar": 31.5, "Lyon": 16.5, "Oslo": 6.5})
    assert [m["month"] for m in temperature["by_month"]][:2] == ["2025-01", "2025-02"]


def test_average_insights_rank_real_gaps_and_call_small_ones_close():
    insights = " ".join(analyze(sensors_frame(), "capteurs")["insights"])

    assert "Moyenne de temperature la plus élevée pour city = Dakar (31,50)" in insights
    assert "Moyennes de humidity proches d'un city à l'autre" in insights
    assert "Mois le plus chargé" in insights


def test_small_groups_are_not_cited_as_extremes():
    frame = sensors_frame().head(8)
    frame["measured_at"] = pd.date_range("2025-01-01", periods=8, freq="MS")

    insights = " ".join(analyze(frame, "capteurs")["insights"])

    # Un seul relevé par mois : aucune moyenne mensuelle citée comme extrême.
    assert "la plus élevée en" not in insights


def test_months_without_rows_count_as_zero_and_years_stay_consecutive():
    # Embauches de 2022 à 2024, aucune en mars 2023 : l'année 2023 reste
    # complète et 2024 se compare à 2023, pas à 2022.
    days = [d for d in pd.date_range("2022-01-01", "2024-12-31", freq="7D") if d.strftime("%Y-%m") != "2023-03"]
    frame = pd.DataFrame(
        {
            "employee_id": [f"E{i}" for i in range(len(days))],
            "hire_date": days,
            "age": [30 + i % 20 for i in range(len(days))],
        }
    )

    trend = analyze(frame, "rh")["trend"]
    months = {m["month"]: m["value"] for m in trend["months"]}

    assert len(trend["months"]) == 36
    assert months["2023-03"] == 0
    assert [(y["year"], y["complete"]) for y in trend["years"]] == [(2022, True), (2023, True), (2024, True)]
    assert (trend["year_change"]["year"], trend["year_change"]["previous"]) == (2024, 2023)
