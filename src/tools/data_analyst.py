"""
Module Data Analyst - Analyse intelligente des données.

Propose :
- Analyse statistique complète (distributions, corrélations, anomalies)
- Insights métier automatiques (tendances, patterns, segments)
- Recommandations d'actions basées sur les données
- Synthèse en langage naturel pour l'utilisateur
"""

import os
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from scipy import stats
from collections import Counter


class DataAnalyst:
    """Analyseur de données avec capacités intelligentes."""

    def __init__(self):
        """Initialise l'analyseur."""
        self.analysis_cache = {}

    @staticmethod
    def _sanitize_json_value(value):
        """Convertit les valeurs NumPy/NaN/inf en types JSON sûrs."""
        if isinstance(value, dict):
            return {str(k): DataAnalyst._sanitize_json_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [DataAnalyst._sanitize_json_value(v) for v in value]
        if isinstance(value, tuple):
            return [DataAnalyst._sanitize_json_value(v) for v in value]
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, (float, np.floating)):
            if not np.isfinite(value):
                return None
            return float(value)
        if isinstance(value, (int, np.integer)):
            return int(value)
        if value is None:
            return None
        return value

    def analyze_dataset(
        self,
        file_path: str,
        dataset_name: str = "unknown",
    ) -> Dict[str, Any]:
        """
        Effectue une analyse complète d'un dataset.

        Args:
            file_path: Chemin du fichier Parquet
            dataset_name: Nom du dataset pour les rapports

        Returns:
            Dict avec analyse complète
        """
        if not os.path.exists(file_path):
            return {
                "status": "ERROR",
                "message": f"Fichier non trouvé : {file_path}",
            }

        try:
            df = pd.read_parquet(file_path)

            analysis = {
                "status": "ANALYZED",
                "dataset_name": dataset_name,
                "file_path": file_path,
                "basic_stats": self._basic_statistics(df),
                "data_quality": self._analyze_quality(df),
                "distributions": self._analyze_distributions(df),
                "correlations": self._analyze_correlations(df),
                "anomalies": self._detect_anomalies(df),
                "segments": self._detect_segments(df),
                "insights": self._generate_insights(df),
                "recommendations": self._generate_recommendations(df),
            }

            analysis = self._sanitize_json_value(analysis)
            self.analysis_cache[dataset_name] = analysis
            return analysis

        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Erreur lors de l'analyse : {str(e)}",
            }

    def _basic_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calcule les statistiques de base."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        stats_dict = {
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "memory_usage_mb": df.memory_usage(deep=True).sum() / 1024**2,
            "numeric_columns": len(numeric_cols),
            "categorical_columns": len(
                df.select_dtypes(exclude=[np.number]).columns
            ),
            "numeric_summary": {},
        }

        for col in numeric_cols:
            stats_dict["numeric_summary"][col] = {
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "mean": float(df[col].mean()),
                "median": float(df[col].median()),
                "std": float(df[col].std()),
                "q25": float(df[col].quantile(0.25)),
                "q75": float(df[col].quantile(0.75)),
            }

        return stats_dict

    def _analyze_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyse la qualité des données."""
        quality = {
            "missing_values": {},
            "duplicates": len(df[df.duplicated()]),
            "duplicate_rate_pct": (
                len(df[df.duplicated()]) / len(df) * 100
                if len(df) > 0
                else 0
            ),
            "completeness_pct": (
                (1 - df.isnull().sum().sum() / (len(df) * len(df.columns)))
                * 100
            ),
        }

        for col in df.columns:
            missing = df[col].isnull().sum()
            quality["missing_values"][col] = {
                "count": int(missing),
                "pct": float(missing / len(df) * 100) if len(df) > 0 else 0,
            }

        return quality

    def _analyze_distributions(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyse les distributions des colonnes."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        distributions = {}

        for col in numeric_cols:
            data = df[col].dropna()
            if len(data) > 0:
                # Skewness et kurtosis
                skewness = float(stats.skew(data))
                kurtosis = float(stats.kurtosis(data))

                distributions[col] = {
                    "skewness": skewness,
                    "kurtosis": kurtosis,
                    "is_normal": abs(skewness) < 0.5,  # Heuristique simple
                    "distribution_type": self._classify_distribution(
                        skewness
                    ),
                }

        return distributions

    def _analyze_correlations(
        self,
        df: pd.DataFrame,
    ) -> Dict[str, List[Tuple[str, float]]]:
        """Analyse les corrélations entre variables numériques."""
        numeric_df = df.select_dtypes(include=[np.number])

        if len(numeric_df.columns) < 2:
            return {"correlations": []}

        corr_matrix = numeric_df.corr()

        # Extrait les corrélations significatives
        strong_correlations = []
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                corr_value = corr_matrix.iloc[i, j]
                if abs(corr_value) > 0.5:  # Corrélation forte
                    strong_correlations.append(
                        (
                            corr_matrix.columns[i],
                            corr_matrix.columns[j],
                            float(corr_value),
                        )
                    )

        strong_correlations.sort(
            key=lambda x: abs(x[2]),
            reverse=True
        )

        return {"correlations": strong_correlations}

    def _detect_anomalies(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Détecte les anomalies dans les données."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        anomalies = {
            "outliers": {},
            "suspicious_patterns": [],
        }

        for col in numeric_cols:
            data = df[col].dropna()
            if len(data) > 0:
                Q1 = data.quantile(0.25)
                Q3 = data.quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR

                outliers = df[
                    (df[col] < lower_bound) | (df[col] > upper_bound)
                ]

                if len(outliers) > 0:
                    anomalies["outliers"][col] = {
                        "count": len(outliers),
                        "percentage": float(
                            len(outliers) / len(df) * 100
                        ),
                        "bounds": {
                            "lower": float(lower_bound),
                            "upper": float(upper_bound),
                        },
                    }

        return anomalies

    def _detect_segments(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Détecte les segments naturels dans les données."""
        segments = {"detected_segments": []}
        categorical_cols = df.select_dtypes(
            exclude=[np.number]
        ).columns

        for col in categorical_cols:
            value_counts = df[col].value_counts()
            if len(value_counts) > 1 and len(value_counts) <= 10:
                segments["detected_segments"].append(
                    {
                        "column": col,
                        "unique_values": len(value_counts),
                        "distribution": value_counts.to_dict(),
                    }
                )

        return segments

    def _generate_insights(self, df: pd.DataFrame) -> List[str]:
        """Génère des insights métier à partir des données."""
        insights = []

        # Insight sur la taille
        insights.append(
            f"Dataset contient {len(df)} lignes et "
            f"{len(df.columns)} colonnes"
        )

        # Insight sur la qualité
        missing_pct = (
            df.isnull().sum().sum() / (len(df) * len(df.columns)) * 100
        )
        if missing_pct > 10:
            insights.append(
                f"⚠️  Qualité: {missing_pct:.1f}% de données manquantes"
            )
        elif missing_pct == 0:
            insights.append("✓ Données complètes (0% de valeurs manquantes)")

        # Insight sur les doublons
        duplicates = len(df[df.duplicated()])
        if duplicates > 0:
            insights.append(
                f"⚠️  {duplicates} lignes dupliquées détectées "
                f"({duplicates/len(df)*100:.1f}%)"
            )

        # Insights sur les corrélations
        numeric_df = df.select_dtypes(include=[np.number])
        if len(numeric_df.columns) > 1:
            corr_matrix = numeric_df.corr()
            strong_corrs = [
                corr_matrix.iloc[i, j]
                for i in range(len(corr_matrix.columns))
                for j in range(i + 1, len(corr_matrix.columns))
                if abs(corr_matrix.iloc[i, j]) > 0.7
            ]
            if strong_corrs:
                insights.append(
                    f"Corrélations fortes détectées "
                    f"({len(strong_corrs)} paires)"
                )

        return insights

    def _generate_recommendations(
        self,
        df: pd.DataFrame,
    ) -> List[str]:
        """Génère des recommandations d'action."""
        recommendations = []

        # Recommandation sur les valeurs manquantes
        missing_pct = (
            df.isnull().sum().sum() / (len(df) * len(df.columns)) * 100
        )
        if missing_pct > 5:
            recommendations.append(
                "Nettoyer/imputer les valeurs manquantes "
                "avant utilisation analytique"
            )

        # Recommandation sur les doublons
        if len(df[df.duplicated()]) > 0:
            recommendations.append(
                "Dédupliquer les lignes identiques"
            )

        # Recommandation sur la normalisation
        numeric_df = df.select_dtypes(include=[np.number])
        for col in numeric_df.columns:
            std = numeric_df[col].std()
            if std > 1000:
                recommendations.append(
                    f"Normaliser {col} pour les analyses ML"
                )
                break

        # Recommandation générale
        if len(recommendations) == 0:
            recommendations.append(
                "Dataset en bon état pour analyse. "
                "Prêt pour transformation vers Gold."
            )

        return recommendations

    def _classify_distribution(self, skewness: float) -> str:
        """Classifie le type de distribution."""
        if abs(skewness) < 0.5:
            return "normal"
        elif skewness > 0:
            return "right_skewed"
        else:
            return "left_skewed"

    def generate_analysis_report(
        self,
        analysis: Dict[str, Any],
    ) -> str:
        """
        Génère un rapport texte à partir de l'analyse.

        Args:
            analysis: Résultat d'analyze_dataset

        Returns:
            Rapport en texte structuré
        """
        if analysis.get("status") == "ERROR":
            return f"❌ {analysis['message']}"

        report = f"""
=== RAPPORT D'ANALYSE DATA ===

Dataset: {analysis['dataset_name']}

--- STATS DE BASE ---
- Lignes: {analysis['basic_stats']['total_rows']}
- Colonnes: {analysis['basic_stats']['total_columns']}
- Colonnes numériques: {analysis['basic_stats']['numeric_columns']}
- Colonnes catégories: {analysis['basic_stats']['categorical_columns']}
- Taille mémoire: {analysis['basic_stats']['memory_usage_mb']:.2f} MB

--- QUALITÉ DES DONNÉES ---
- Complétude: {analysis['data_quality']['completeness_pct']:.1f}%
- Doublons: {analysis['data_quality']['duplicates']} 
  ({analysis['data_quality']['duplicate_rate_pct']:.2f}%)

--- INSIGHTS ---
{chr(10).join("• " + insight for insight in analysis['insights'])}

--- RECOMMANDATIONS ---
{chr(10).join("→ " + rec for rec in analysis['recommendations'])}
"""
        return report


def analyze_gold_data(
    file_path: str,
    dataset_name: str = "gold_data",
) -> Dict[str, Any]:
    """
    Analyse les données Gold (fonction pratique).

    Args:
        file_path: Chemin du fichier Parquet
        dataset_name: Nom du dataset affiché dans le rapport

    Returns:
        Dict avec l'analyse complète
    """
    analyst = DataAnalyst()
    return analyst.analyze_dataset(
        file_path=file_path,
        dataset_name=dataset_name,
    )
