# 🚀 Data Engineering Agent - IA Agentique Complète

Un agent d'ingénierie des données alimenté par l'IA qui combine :
- ✅ Accepte les formats tabulaires CSV, TSV, JSON, JSONL, Excel, Parquet et TXT
- ✅ Nettoie les noms et chaînes, supprime les doublons et enrichit les colonnes

## Enrichissements déclaratifs

L'interface accepte une liste JSON d'opérations sûres, sans exécution de code :

```json
[
    {"type": "arithmetic", "target": "total", "left": "quantity", "right": "price", "operator": "multiply"},
    {"type": "date_part", "target": "sale_year", "source": "sale_date", "part": "year"},
    {"type": "concat", "target": "label", "columns": ["country", "city"], "separator": " - "}
]
```

Le pipeline produit un Parquet Silver nettoyé et un Parquet Gold analytique,
puis peut publier la table Gold dans un Lakehouse Fabric pour la consommation
Power BI.

## Architecture Globale

```
│  Source CSV     │
└────────┬────────┘
         │
┌─────────────────────────────────────────┐
│  BRONZE LAYER (Raw Data)               │
│  - inspect_csv                          │
│  - profile_csv                          │
│  - validate_csv + validate_contract     │
│  - determine_ingestion_decision         │
└────────┬────────────────────────────────┘
         │ (INGEST)
         ▼
┌─────────────────────────────────────────┐
│  SILVER LAYER (Cleaned & Curated)       │
│  - transform_to_silver                  │
│  - Business rules & aggregations        │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  GOLD LAYER (Analytics Ready)           │
│  - build_sales_gold                     │
│  - Aggregated metrics & KPIs            │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  MICROSOFT FABRIC                       │
│  - publish_to_fabric                    │
│  → Power BI Datasets                    │
│  → Semantic Models                      │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  DATA ANALYSIS (IA comme Data Analyst)  │
│  - analyze_gold_data                    │
│  → Statistiques complètes               │
│  → Détection d'anomalies                │
│  → Insights métier                      │
│  → Recommandations                      │
└─────────────────────────────────────────┘
```

---

## ✨ Capacités de l'Agent

### 1️⃣ **Data Engineer**
- ✅ Inspecte la structure des données (colonnes, types, nulls)
- ✅ Profile les données numériques (min, max, moyenne, médiane)
- ✅ Valide la qualité (doublons, valeurs manquantes, contraintes)
- ✅ Valide les contrats de données (schéma, types)
- ✅ Décide automatiquement : INGEST / QUARANTINE / REJECT

### 2️⃣ **Transformation Expert**
- ✅ Transforme Bronze → Silver (nettoyage, agrégations)
- ✅ Transforme Silver → Gold (KPIs, métriques métier)
- ✅ Gère les erreurs et traçabilité complète

### 3️⃣ **Fabric Publishing**
- ✅ Publie les données dans Microsoft Fabric
- ✅ Crée automatiquement les datasets Power BI
- ✅ Supporte mode incremental ou full_refresh
- ✅ Modèles sémantiques (à implémenter)

### 4️⃣ **Data Analyst** 🤖
- ✅ **Statistiques** : min, max, moyenne, médiane, écart-type
- ✅ **Qualité** : Complétude, doublons, valeurs manquantes
- ✅ **Distributions** : Skewness, kurtosis, normalité
- ✅ **Corrélations** : Détection de relations fortes
- ✅ **Anomalies** : Outliers par IQR, patterns suspects
- ✅ **Segmentation** : Détection de segments naturels
- ✅ **Insights** : Résumés intelligents des données
- ✅ **Recommandations** : Actions sugérées (nettoyage, normalisation, etc.)

---

## 🎯 Flux de Travail Complet

### Exemple : Ingestion et Analyse des Ventes

```bash
python -m src.agent

# Requête utilisateur :
"Ingère et analyse le fichier sales.csv avec le contrat data_contract.json"
```

**Étapes exécutées automatiquement :**

1. 🔍 **Inspection** → Structure du fichier
2. 📊 **Profiling** → Statistiques numériques
3. ✓ **Validation** → Qualité + Contrat
4. 🤔 **Décision** → INGEST / QUARANTINE / REJECT
5. 💾 **Ingestion** → CSV → Bronze (Parquet)
6. 🧹 **Silver** → Transformation, calculs
7. 🏆 **Gold** → Agrégations métier
8. ☁️ **Fabric** → Publication Power BI
9. 🔬 **Analyse** → Insights + Recommandations

**Résultat : Rapport complet avec analyses.**

---

## 📦 Installation

### 1. Clone le projet
```bash
git clone <repo>
cd data-engineering-agent
```

### 2. Crée un environnement virtuel
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate  # Windows
```

### 3. Installe les dépendances
```bash
pip install -r requirements.txt
```

### 4. Configure l'environnement
```bash
cp .env.example .env
# Ajoute tes credentials OpenAI et Fabric
```

---

## 🔧 Configuration Fabric

Voir [docs/FABRIC_CONFIG.md](docs/FABRIC_CONFIG.md) pour :
- Enregistrer ton application Azure
- Obtenir les credentials
- Tester la connexion

---

## 💻 Utilisation

### Mode Standard (avec Agent LLM)
```python
from src.agent import run_agent

result = run_agent("Ingère sales.csv et analyse-le")
print(result)
```

### Mode Orchestré (Pipeline Déterministe)
```python
from src.agent import run_agent_orchestrated

result = run_agent_orchestrated("Ingère sales.csv")
print(result)
```

### Mode CLI Interactif
```bash
python -m src.agent
# Choisis mode : classic ou orchestrated
```

---

## 📊 Exemple d'Analyse Générée

Après ingestion et publication Fabric :

```
=== RAPPORT D'ANALYSE DATA ===

Dataset: sales_analysis

--- STATS DE BASE ---
- Lignes: 1000
- Colonnes: 5
- Colonnes numériques: 3
- Taille mémoire: 0.15 MB

--- QUALITÉ DES DONNÉES ---
- Complétude: 99.8%
- Doublons: 2 (0.2%)

--- INSIGHTS ---
• Dataset contient 1000 lignes et 5 colonnes
• ✓ Données complètes (0% de valeurs manquantes)
• Corrélations fortes détectées (2 paires)

--- RECOMMANDATIONS ---
→ Dataset en bon état pour analyse. Prêt pour transformation vers Gold.
```

---

## 🧪 Tests

```bash
# Tous les tests
pytest

# Tests spécifiques
pytest tests/test_fabric_connector.py -v
pytest tests/test_data_analyst.py -v

# Avec couverture
pytest --cov=src tests/
```

---

## 📁 Structure du Projet

```
data-engineering-agent/
├── src/
│   ├── agent.py                 # Agent orchestrateur principal
│   ├── llm.py                   # Client OpenAI
│   ├── pipeline_orchestrator.py # Exécuteur de pipeline
│   ├── pipeline_planner.py      # Générateur de plan
│   ├── audit*.py                # Audit et logging
│   └── tools/
│       ├── fabric_connector.py       # ✨ Nouveau : Intégration Fabric
│       ├── data_analyst.py           # ✨ Nouveau : Analyses intelligentes
│       ├── data_inspection.py        # Inspection de données
│       ├── data_profiling.py         # Profiling statistique
│       ├── data_validation.py        # Validation qualité
│       ├── contract_validation.py    # Validation contrat
│       ├── ingestion.py              # Ingestion Bronze
│       ├── silver_transformation.py  # Transformation Silver
│       └── gold_transformation.py    # Transformation Gold
├── tests/
│   ├── test_fabric_connector.py      # ✨ Nouveau : Tests Fabric
│   ├── test_data_analyst.py          # ✨ Nouveau : Tests Analytics
│   └── ... autres tests
├── data/
│   ├── bronze/  # Zone brute
│   ├── silver/  # Zone transformée
│   ├── gold/    # Zone analytique
│   └── audit/   # Logs d'audit
├── requirements.txt
├── pytest.ini
├── docs/                         # Guides et références
│   ├── API_REFERENCE.md
│   ├── FABRIC_CONFIG.md
│   └── QUICKSTART.md
├── scripts/                      # Lanceurs et exemples CLI
│   ├── examples.py
│   ├── start_server.sh
│   └── start_server.bat
├── public/                       # Interface web
│   └── index.html
└── api.py                        # API FastAPI
```

---

## 🎓 Prochaines Étapes

- [x] Bronze → Silver → Gold
- [x] Fabric Publishing
- [x] Data Analysis
- [ ] Semantic Models (Power BI)
- [ ] Dashboards automatiques
- [ ] Alertes et monitoring
- [ ] CI/CD avec GitHub Actions

---

## 🤝 Support

Pour les questions ou problèmes :
1. Vérifie la configuration Fabric dans `docs/FABRIC_CONFIG.md`
2. Consulte les logs d'audit dans `data/audit/`
3. Lance les tests : `pytest -v`

---

**Made with ❤️ for Data Analysts & Engineers**
