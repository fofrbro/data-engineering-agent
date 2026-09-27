# Data Engineering Agent

Agent de Data Engineering qui prend en charge un fichier de données de bout en
bout : il l'analyse, propose un Data Contract, un pipeline Bronze / Silver /
Gold, des KPI et un tableau de bord, puis, **après validation humaine**,
l'exécute, vérifie le résultat, trace tout dans un audit et prépare les tables
pour Microsoft Fabric et Power BI.

```
FICHIER (CSV, TSV, Excel, JSON, JSONL, Parquet)
  → DÉCOUVERTE        format, schéma, types, nulls, doublons, cardinalités
  → SÉMANTIQUE        identifiants, mesures, dimensions, dates, métier (confiance)
  → DATA CONTRACT     proposé (PROPOSED) → validé par un relecteur (VALIDATED)
  → POLICY ENGINE     INGEST / QUARANTINE / REJECT (règles déterministes)
  → BRONZE → SILVER → GOLD   transformations recommandées puis exécutées
  → VERIFY            fichiers, lignes, totaux Gold = totaux Silver
  → AUDIT             run et étapes horodatés, explicables
  → FABRIC            tables Delta (Lakehouse) : audits et tables Gold
  → POWER BI          rapport d'observabilité + un rapport par dataset métier
```

## Principes

- **Le LLM propose, le code déterministe décide.** Le LLM traduit une demande
  en intention (créer un plan, expliquer un run) ; il n'a aucune action pour
  valider ou exécuter.
- **Rien n'est validé implicitement.** Le contrat, les transformations
  destructives et le tableau de bord sont validés explicitement par un
  relecteur nommé. Sans contrat validé, rien n'est exécuté.
- **La décision est recalculée à l'exécution**, à partir des vraies
  validations, jamais reprise du plan.
- **Décision et mode d'exécution sont distincts** : `decision = INGEST` et
  `execution_mode = ASSESS_ONLY` signifie « admissible, mais non ingéré par
  cette exécution ».
- **Tout est audité**, y compris les runs bloqués ou en échec.

## Démarrage rapide (Windows)

Prérequis : Python 3.14 et un fichier `.env` (voir `.env.example`) contenant
`OPENAI_API_KEY` (le serveur l'exige au démarrage, même si le parcours de
l'interface n'appelle pas le LLM).

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Lancer le serveur :

```bash
.venv/Scripts/python.exe -m uvicorn api:app --port 8000
```

Puis ouvrir http://localhost:8000 :

1. uploader un fichier ;
2. **« Préparer avec l'agent »** : plan, décision prévisionnelle, contrat,
   pipeline, KPI, tableau de bord ;
3. dans l'onglet **Agent** : saisir le nom du relecteur, **valider le
   contrat**, et si besoin les transformations destructives et le tableau de
   bord ;
4. **« Exécuter le plan validé »** : contrôles VERIFY, explication du run,
   rapport Data Analyst et dossier préparé pour Fabric.

Pour un nouveau fichier d'un dataset déjà validé, le contrat validé existant
(`data/contracts/<dataset>.json`) est réutilisé automatiquement ; le nom du
dataset vient du nom de fichier ou du champ « Nom du Dataset ».

### Fichiers d'exemple

`data/samples/` contient des données **fictives** pour tester les trois
décisions sur le dataset `ventes_2025_2026` :

| Fichier | Décision attendue | Raison |
|---|---|---|
| `ventes_2025_2026.csv` | INGEST | 1 500 commandes conformes |
| `ventes_quarantaine.csv` | QUARANTINE | colonne `commentaire` en partie vide |
| `ventes_rejet.csv` | REJECT | quantités négatives (contrat : ≥ 1) |

Pour les deux derniers, saisir `ventes_2025_2026` dans « Nom du Dataset » afin
de réutiliser le contrat validé.

## Règles de décision

| Situation | Décision | Règle |
|---|---|---|
| Le fichier viole le contrat | REJECT | `CONTRACT_VIOLATION` |
| Contrat non validé ou absent | QUARANTINE | `CONTRACT_NOT_VALIDATED` |
| Problème qualité bloquant | QUARANTINE | `QUALITY_ISSUES` |
| Avertissements qualité seulement | INGEST | `PASSED_WITH_WARNINGS` |
| Tout est conforme | INGEST | `ALL_CHECKS_PASSED` |

Qualité graduée : les doublons exacts et les nulls sur une colonne déclarée
nullable par le contrat sont des **avertissements** (corrigés en Silver si la
transformation est approuvée) ; les autres nulls et les valeurs métier
invalides sont **bloquants**.

Règle métier : dans un dataset de ventes, les commandes dont le statut est une
annulation (CANCELLED, ANNULÉE…) sont exclues des KPI, des mesures DAX et des
agrégats Gold ; la table de faits garde toutes les lignes.

## API

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/upload` | uploader un ou plusieurs fichiers |
| POST | `/api/workflow/plan` | créer le plan d'un fichier uploadé |
| POST | `/api/workflow/ask` | demande en langage naturel (LLM → plan ou explication) |
| GET | `/api/workflow/{plan_id}` | consulter un plan |
| POST | `/api/workflow/{plan_id}/approve-contract` | valider le contrat |
| POST | `/api/workflow/{plan_id}/approve-transformations` | approuver les transformations destructives |
| POST | `/api/workflow/{plan_id}/dashboard` | revue du tableau de bord : APPROVE, MODIFY, REJECT |
| POST | `/api/workflow/{plan_id}/execute` | exécuter, vérifier, auditer |
| POST | `/api/contracts/approve`, `/api/contracts/reject` | revue d'un fichier de contrat |

Les plans sont conservés en mémoire : ils sont perdus au redémarrage du
serveur (les contrats validés et les audits, eux, sont sur disque).

## Utilisation en Python

```python
from src.workflow.agent_workflow import plan_file, approve_plan_contract, render_plan_preview
from src.workflow.plan_executor import execute_plan

plan = plan_file("data/samples/ventes_2025_2026.csv")
print(render_plan_preview(plan))

# Un contrat validé existant est réutilisé ; sinon il faut valider le contrat proposé.
if plan.contract_status != "VALIDATED":
    approve_plan_contract(plan, "relecteur")

result = execute_plan(plan)
print(result.explanation)
```

Expliquer un run à partir de l'audit :

```python
from src.audit_explain import explain_run, format_run_explanation

print(format_run_explanation(explain_run("<run_id>")))
```

## Microsoft Fabric

Voir [fabric/README.md](fabric/README.md) : notebooks de chargement incrémental
des audits (`pipeline_runs`, `pipeline_steps`), vues d'observabilité, chargement
des tables Gold par dataset (`load_gold_tables`), dépannage.

Exporter les audits structurés avant de les déposer dans `Files/audit/` :

```bash
.venv/Scripts/python.exe -c "from src.audit_parquet import export_structured_audit_to_parquet; print(export_structured_audit_to_parquet())"
```

Les tables Gold d'une exécution réussie sont préparées dans
`data/fabric_export/gold/<dataset>/`, à déposer dans `Files/gold/<dataset>/`.

Validé dans Fabric : chargements incrémentaux et idempotents, rattrapage après
interruption, vues, tables Gold `ventes_2025_2026` conformes au fichier source.

## Power BI

Voir [powerbi/README.md](powerbi/README.md) :

- **Observabilité de l'agent** (2 pages) : mesures dans
  `observability_measures.dax`, guide pas à pas dans
  `observability_report_guide.md` ;
- **Un rapport par dataset métier**, sur son propre modèle sémantique, généré
  à partir d'un tableau de bord **approuvé** : `ventes_2025_2026_measures.dax`
  et `ventes_2025_2026_report_guide.md`.

Les deux rapports ont été construits et leurs valeurs vérifiées contre les
données sources.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

La logique Fabric et Power BI est testée localement (Lakehouse simulé en
Parquet, SQL des vues exécuté dans SQLite, mesures DAX évaluées avec pandas) ;
ces tests ne remplacent pas une exécution dans Fabric ou Power BI, consignée
dans les README correspondants.

## Structure

```
api.py                      API FastAPI et interface web (public/index.html)
src/
  discovery/                détection de fichier et de format, lecteurs, profil de schéma
  semantic/                 profil sémantique, vocabulaire métier
  contract/                 génération et cycle de vie des Data Contracts
  tools/                    validations qualité et contrat, Policy Engine, outils historiques
  recommendation/           pipeline, KPI, tableau de bord, revue, règles métier
  execution/                exécution Silver et Gold
  workflow/                 PLAN → VALIDATE → EXECUTE → VERIFY → AUDIT, service, LLM
  fabric/                   chargement incrémental, export Gold (logique testable)
  powerbi/                  mesures DAX, traduction des KPI, guides de rapport
  audit*.py                 audit, tables, KPI d'observabilité, export Parquet, explication
  agent.py                  agent LLM historique (mode outils libre encadré par agent_guard)
fabric/                     notebooks PySpark et SQL des vues pour Fabric
powerbi/                    mesures, guides et tableaux de bord approuvés
data/contracts/             contrats validés (versionnés) ; proposed/ est ignoré
data/samples/               fichiers d'exemple fictifs
tests/                      tests unitaires et de bout en bout
```

## Limites connues

- `docs/` (API_REFERENCE, QUICKSTART, FABRIC_CONFIG) décrit l'ancien parcours
  et n'a pas été mis à jour.
- Le workflow traite un fichier à la fois.
- La détection des annulations s'appuie sur les valeurs d'exemple du profil
  (5 valeurs distinctes au plus par colonne).
- Les routes de connexion Fabric (`/api/fabric/*`) et les modes historiques de
  `src/agent.py` ne sont plus utilisés par l'interface.
