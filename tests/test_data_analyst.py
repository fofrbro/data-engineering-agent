"""Tests pour le module Data Analyst."""

import pytest
import pandas as pd
import numpy as np
from src.tools.data_analyst import DataAnalyst, analyze_gold_data


@pytest.fixture
def analyst():
    """Crée une instance d'analyseur."""
    return DataAnalyst()


@pytest.fixture
def sample_dataframe():
    """Crée un DataFrame d'exemple."""
    return pd.DataFrame({
        "product": ["A", "B", "C", "A", "B"],
        "quantity": [10, 20, 15, 5, 25],
        "price": [100.0, 200.0, 150.0, 100.0, 200.0],
        "date": pd.date_range("2024-01-01", periods=5)
    })


@pytest.fixture
def sample_parquet_file(tmp_path, sample_dataframe):
    """Crée un fichier Parquet d'exemple."""
    file_path = tmp_path / "test_data.parquet"
    sample_dataframe.to_parquet(file_path)
    return str(file_path)


def test_analyst_init(analyst):
    """Test l'initialisation de l'analyseur."""
    assert analyst.analysis_cache == {}


def test_analyze_dataset_file_not_found(analyst):
    """Test l'analyse avec fichier non trouvé."""
    result = analyst.analyze_dataset(
        file_path="/path/nonexistent/file.parquet",
        dataset_name="test"
    )
    assert result["status"] == "ERROR"
    assert "non trouvé" in result["message"]


def test_analyze_dataset_success(analyst, sample_parquet_file):
    """Test l'analyse réussie d'un dataset."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test_dataset"
    )

    assert result["status"] == "ANALYZED"
    assert result["dataset_name"] == "test_dataset"
    assert "basic_stats" in result
    assert "data_quality" in result
    assert "distributions" in result
    assert "correlations" in result
    assert "anomalies" in result
    assert "segments" in result
    assert "insights" in result
    assert "recommendations" in result


def test_basic_statistics(analyst, sample_parquet_file):
    """Test le calcul des statistiques de base."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test"
    )

    stats = result["basic_stats"]
    assert stats["total_rows"] == 5
    assert stats["total_columns"] == 4
    assert stats["numeric_columns"] == 2  # quantity et price
    assert stats["categorical_columns"] == 2  # product et date
    assert "quantity" in stats["numeric_summary"]


def test_data_quality_analysis(analyst, sample_parquet_file):
    """Test l'analyse de la qualité des données."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test"
    )

    quality = result["data_quality"]
    assert "missing_values" in quality
    assert "duplicates" in quality
    assert "duplicate_rate_pct" in quality
    assert "completeness_pct" in quality
    assert quality["completeness_pct"] == 100.0  # Pas de valeurs manquantes


def test_data_quality_with_missing_values(analyst, tmp_path):
    """Test l'analyse de qualité avec valeurs manquantes."""
    df = pd.DataFrame({
        "col1": [1, 2, None, 4],
        "col2": [None, "B", "C", "D"]
    })
    file_path = tmp_path / "missing.parquet"
    df.to_parquet(file_path)

    result = analyst.analyze_dataset(
        file_path=str(file_path),
        dataset_name="test"
    )

    quality = result["data_quality"]
    assert quality["missing_values"]["col1"]["count"] == 1
    assert quality["missing_values"]["col2"]["count"] == 1
    assert quality["completeness_pct"] < 100.0


def test_distributions_analysis(analyst, sample_parquet_file):
    """Test l'analyse des distributions."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test"
    )

    distributions = result["distributions"]
    assert "quantity" in distributions
    assert "skewness" in distributions["quantity"]
    assert "kurtosis" in distributions["quantity"]
    assert "is_normal" in distributions["quantity"]
    assert "distribution_type" in distributions["quantity"]


def test_segments_detection(analyst, sample_parquet_file):
    """Test la détection de segments."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test"
    )

    segments = result["segments"]
    assert "detected_segments" in segments
    # Doit détecter le segment "product"
    assert any(seg["column"] == "product" for seg in segments["detected_segments"])


def test_insights_generation(analyst, sample_parquet_file):
    """Test la génération d'insights."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test"
    )

    insights = result["insights"]
    assert isinstance(insights, list)
    assert len(insights) > 0
    assert any("5 lignes" in insight for insight in insights)


def test_recommendations_generation(analyst, sample_parquet_file):
    """Test la génération de recommandations."""
    result = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="test"
    )

    recommendations = result["recommendations"]
    assert isinstance(recommendations, list)
    assert len(recommendations) > 0


def test_generate_analysis_report_success(analyst, sample_parquet_file):
    """Test la génération d'un rapport d'analyse."""
    analysis = analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="Test Dataset"
    )

    report = analyst.generate_analysis_report(analysis)
    assert isinstance(report, str)
    assert "RAPPORT D'ANALYSE DATA" in report
    assert "Test Dataset" in report
    assert "STATS DE BASE" in report
    assert "QUALITÉ DES DONNÉES" in report
    assert "INSIGHTS" in report
    assert "RECOMMANDATIONS" in report


def test_generate_analysis_report_error(analyst):
    """Test la génération de rapport avec erreur."""
    error_result = {"status": "ERROR", "message": "Test error"}
    report = analyst.generate_analysis_report(error_result)
    assert "❌" in report
    assert "Test error" in report


def test_analyze_gold_data_function(sample_parquet_file):
    """Test la fonction pratique analyze_gold_data."""
    result = analyze_gold_data(file_path=sample_parquet_file)

    assert result["status"] == "ANALYZED"
    assert result["dataset_name"] == "gold_data"
    assert "basic_stats" in result


def test_classification_distribution():
    """Test la classification des distributions."""
    analyst = DataAnalyst()

    # Distribution normale
    assert analyst._classify_distribution(0.2) == "normal"
    assert analyst._classify_distribution(-0.3) == "normal"

    # Distribution asymétrique à droite
    assert analyst._classify_distribution(0.7) == "right_skewed"

    # Distribution asymétrique à gauche
    assert analyst._classify_distribution(-0.7) == "left_skewed"


def test_analysis_caching(analyst, sample_parquet_file):
    """Test la mise en cache des analyses."""
    analyst.analyze_dataset(
        file_path=sample_parquet_file,
        dataset_name="cached_dataset"
    )

    assert "cached_dataset" in analyst.analysis_cache
    assert analyst.analysis_cache["cached_dataset"]["status"] == "ANALYZED"
