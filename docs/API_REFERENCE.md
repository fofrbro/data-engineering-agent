# 🛠️ API Reference - Outils Disponibles

Guide de référence complet de tous les outils disponibles dans l'agent.

---

## 📋 Table des Matières

1. [Inspection & Profiling](#inspection--profiling)
2. [Validation](#validation)
3. [Ingestion](#ingestion)
4. [Transformation](#transformation)
5. [Publication](#publication)
6. [Analyse](#analyse)

---

## Inspection & Profiling

### `inspect_csv(file_path: str) → dict`

Inspecte la structure d'un fichier CSV.

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV

**Retour:**
```json
{
    "status": "SUCCESS",
    "file_path": "data/sales.csv",
    "rows": 1000,
    "columns": 5,
    "column_info": {
        "product": {"type": "object", "non_null": 1000},
        "quantity": {"type": "int64", "non_null": 995},
        "price": {"type": "float64", "non_null": 1000}
    },
    "duplicates": 0
}
```

**Exemple d'utilisation:**
```python
from src.tools.data_inspection import inspect_csv

result = inspect_csv("data/sales.csv")
print(result)
```

---

### `profile_csv(file_path: str) → dict`

Produit un profil statistique des colonnes numériques.

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV

**Retour:**
```json
{
    "status": "SUCCESS",
    "numeric_columns": {
        "quantity": {
            "min": 1,
            "max": 1000,
            "mean": 250.5,
            "median": 200.0,
            "std": 150.2
        },
        "price": {
            "min": 10.0,
            "max": 500.0,
            "mean": 150.0,
            "median": 125.0,
            "std": 75.3
        }
    }
}
```

---

## Validation

### `validate_csv(file_path: str) → dict`

Valide la qualité d'un fichier CSV.

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV

**Contrôles:**
- Valeurs nulles
- Doublons
- Quantités invalides
- Prix négatifs
- Produits vides

**Retour:**
```json
{
    "status": "VALID",
    "null_count": 5,
    "duplicates": 0,
    "issues": []
}
```

**Exemple d'utilisation:**
```python
from src.tools.data_validation import validate_csv

result = validate_csv("data/sales.csv")
if result["status"] == "VALID":
    print("✓ Fichier valide")
else:
    print(f"❌ Problèmes: {result['issues']}")
```

---

### `validate_contract(file_path: str, contract_path: str) → dict`

Valide un fichier CSV contre un contrat de données JSON.

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV
- `contract_path` (str): Chemin du contrat JSON

**Contrat JSON exemple:**
```json
{
    "dataset": "sales",
    "columns": {
        "product": {"type": "string", "required": true},
        "quantity": {"type": "int", "required": true, "min": 1},
        "price": {"type": "float", "required": true, "min": 0}
    }
}
```

**Retour:**
```json
{
    "status": "COMPLIANT",
    "missing_columns": [],
    "extra_columns": [],
    "type_mismatches": [],
    "constraint_violations": []
}
```

---

## Ingestion

### `ingest_csv(file_path: str, dataset: str) → dict`

Ingère un fichier CSV dans la zone Bronze (Parquet).

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV source
- `dataset` (str): Nom du dataset (ex: "sales")

**Retour:**
```json
{
    "status": "INGESTED",
    "source_file": "data/sales.csv",
    "destination_file": "data/bronze/sales.parquet",
    "rows": 1000,
    "columns": 5
}
```

**Exemple:**
```python
from src.tools.ingestion import ingest_csv

result = ingest_csv("data/sales.csv", "sales")
print(f"Ingéré: {result['rows']} lignes")
```

---

### `determine_ingestion_decision(contract_result: dict, quality_result: dict) → dict`

Détermine la décision d'ingestion basée sur les validations.

**Paramètres:**
- `contract_result` (dict): Résultat de `validate_contract()`
- `quality_result` (dict): Résultat de `validate_csv()`

**Retour (3 cas possibles):**
```json
{
    "decision": "INGEST",
    "reasoning": "Fichier valide et conforme au contrat"
}

{
    "decision": "QUARANTINE",
    "reasoning": "Données incomplètes (90% de complétude)"
}

{
    "decision": "REJECT",
    "reasoning": "Contrat non respecté: colonnes manquantes"
}
```

---

### `quarantine_csv(file_path: str, reason: str) → dict`

Place un fichier dans la zone de quarantaine.

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV
- `reason` (str): Raison de la quarantaine

**Exemple:**
```python
from src.tools.ingestion import quarantine_csv

quarantine_csv(
    "data/sales.csv",
    "Données manquantes: 50% des valeurs quantity"
)
```

---

### `reject_csv(file_path: str, reason: str) → dict`

Rejette un fichier (zone rejected).

**Paramètres:**
- `file_path` (str): Chemin du fichier CSV
- `reason` (str): Raison du rejet

---

## Transformation

### `transform_to_silver(bronze_file_path: str, silver_file_path: str) → dict`

Transforme les données de Bronze à Silver.

**Paramètres:**
- `bronze_file_path` (str): Chemin du Parquet Bronze
- `silver_file_path` (str): Chemin de sortie Silver

**Transformations appliquées:**
- Nettoyage des doublons
- Imputation des valeurs manquantes
- Calcul de colonnes dérivées (line_amount = quantity × price)
- Normalisation des types

**Retour:**
```json
{
    "status": "TRANSFORMED",
    "source_file": "data/bronze/sales.parquet",
    "output_file": "data/silver/sales.parquet",
    "rows": 995,
    "columns": 6
}
```

---

### `build_sales_gold(silver_file_path: str, output_file_path: str) → dict`

Construit les données Gold à partir de Silver.

**Paramètres:**
- `silver_file_path` (str): Chemin du Parquet Silver
- `output_file_path` (str): Chemin de sortie Gold

**Agrégations:**
- Regroupement par produit
- Quantité totale par produit
- Ventes totales (line_amount sum)
- Prix moyen par produit
- Nombre de transactions

**Retour:**
```json
{
    "status": "TRANSFORMED",
    "rows": 5,
    "columns": 5,
    "output_file": "data/gold/sales_by_product.parquet",
    "schema": {
        "product": "string",
        "total_quantity": "int",
        "total_sales": "float",
        "avg_unit_price": "float",
        "number_of_lines": "int"
    }
}
```

---

## Publication

### `publish_to_fabric(file_path: str, dataset_name: str, table_name: str = "data", mode: str = "incremental") → dict`

Publie les données dans Microsoft Fabric.

**Paramètres:**
- `file_path` (str): Chemin du Parquet à publier
- `dataset_name` (str): Nom du dataset Fabric
- `table_name` (str, opt): Nom de la table (défaut: "data")
- `mode` (str, opt): "incremental" ou "full_refresh" (défaut: "incremental")

**Retour:**
```json
{
    "status": "PUBLISHED",
    "dataset_name": "sales_analysis",
    "table_name": "sales",
    "rows": 5,
    "columns": 5,
    "mode": "incremental",
    "message": "Dataset sales_analysis.sales publié avec succès (5 lignes)"
}
```

**Exemple:**
```python
from src.tools.fabric_connector import publish_to_fabric

result = publish_to_fabric(
    file_path="data/gold/sales_by_product.parquet",
    dataset_name="sales_analysis",
    table_name="by_product",
    mode="full_refresh"
)
```

---

## Analyse

### `analyze_gold_data(file_path: str) → dict`

Analyse complète des données Gold comme un Data Analyst.

**Paramètres:**
- `file_path` (str): Chemin du Parquet Gold à analyser

**Retour (objet complexe):**
```json
{
    "status": "ANALYZED",
    "dataset_name": "gold_data",
    "basic_stats": {
        "total_rows": 1000,
        "total_columns": 5,
        "numeric_columns": 3,
        "memory_usage_mb": 0.5,
        "numeric_summary": {
            "quantity": {
                "min": 1,
                "max": 1000,
                "mean": 250.5,
                "std": 150.2,
                "q25": 100,
                "q75": 400
            }
        }
    },
    "data_quality": {
        "missing_values": {...},
        "duplicates": 0,
        "duplicate_rate_pct": 0,
        "completeness_pct": 100
    },
    "distributions": {
        "quantity": {
            "skewness": 0.25,
            "kurtosis": -0.5,
            "is_normal": true,
            "distribution_type": "normal"
        }
    },
    "correlations": {
        "correlations": [
            ["quantity", "price", 0.85],
            ["total_sales", "quantity", 0.92]
        ]
    },
    "anomalies": {
        "outliers": {
            "price": {
                "count": 3,
                "percentage": 0.3,
                "bounds": {"lower": 50, "upper": 500}
            }
        }
    },
    "segments": {
        "detected_segments": [
            {
                "column": "product",
                "unique_values": 10,
                "distribution": {"A": 100, "B": 150, ...}
            }
        ]
    },
    "insights": [
        "Dataset contient 1000 lignes et 5 colonnes",
        "✓ Données complètes (0% de valeurs manquantes)",
        "Corrélations fortes détectées (2 paires)"
    ],
    "recommendations": [
        "Dataset en bon état pour analyse",
        "Prêt pour transformation vers Gold"
    ]
}
```

**Exemple complet:**
```python
from src.tools.data_analyst import analyze_gold_data

result = analyze_gold_data("data/gold/sales_by_product.parquet")

print("=== ANALYSE DATA ===\\n")
print(f"Lignes: {result['basic_stats']['total_rows']}")
print(f"Complétude: {result['data_quality']['completeness_pct']:.1f}%")
print("\\nInsights:")
for insight in result['insights']:
    print(f"• {insight}")
print("\\nRecommandations:")
for rec in result['recommendations']:
    print(f"→ {rec}")
```

---

## 🔗 Flux Complet (Pipeline Recommandé)

```
1. inspect_csv()
   ↓
2. profile_csv()
   ↓
3. validate_csv() + validate_contract()
   ↓
4. determine_ingestion_decision()
   ├─ INGEST → 5
   ├─ QUARANTINE → quarantine_csv()
   └─ REJECT → reject_csv()
   ↓
5. ingest_csv() [si INGEST]
   ↓
6. transform_to_silver()
   ↓
7. build_sales_gold()
   ↓
8. publish_to_fabric()
   ↓
9. analyze_gold_data()
   ↓
10. Rapport final avec insights
```

---

## 📊 Structures de Données Clés

### Contrat de Données (Data Contract)
```json
{
    "dataset": "sales",
    "columns": {
        "product": {
            "type": "string",
            "required": true,
            "description": "Nom du produit"
        },
        "quantity": {
            "type": "int",
            "required": true,
            "min": 1,
            "description": "Quantité vendue"
        },
        "price": {
            "type": "float",
            "required": true,
            "min": 0,
            "description": "Prix unitaire"
        }
    }
}
```

### Décision d'Ingestion
- **INGEST**: Données valides, conforme au contrat → Ingestion autorisée
- **QUARANTINE**: Problèmes mineurs (données manquantes ≤ 10%) → Révision requise
- **REJECT**: Problèmes critiques (non-conformité contrat) → Rejet

---

## ⚙️ Intégration avec l'Agent LLM

Ces outils sont disponibles pour l'agent LLM via fonction_call.
L'agent choisit automatiquement quels outils appeler basé sur :
- La demande utilisateur
- Les résultats des outils précédents
- Les règles de décision (ex: INGEST → transform → publish → analyze)

**Voir:** `src/agent.py` pour la liste complète des outils disponibles.

---

## 🐛 Gestion d'Erreurs

Tous les outils retournent une structure cohérente:
```json
{
    "status": "ERROR",
    "message": "Description de l'erreur"
}
```

**Codes de statut courants:**
- `SUCCESS` ou nom spécifique (VALID, COMPLIANT, PUBLISHED, ANALYZED, etc.)
- `ERROR` pour les exceptions
- `SKIPPED` si l'opération n'est pas nécessaire (ex: fichier déjà ingéré)

---

**Dernière mise à jour:** 2024-08-23
