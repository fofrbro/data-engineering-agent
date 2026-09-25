# Power BI

Artefacts à reproduire dans le modèle sémantique et le rapport Power BI.
Ils sont générés par `src/powerbi/` ; les tests vérifient leur sémantique
en Python. Dans Power BI, la relation et les mesures ont été créées le
2026-09-25 ; **les valeurs affichées et les pages du rapport ne sont pas
encore confirmées**.

## Modèle sémantique

Tables (Lakehouse Fabric) : `pipeline_runs`, `pipeline_steps`.

Relation : `pipeline_steps[run_id]` (plusieurs) → `pipeline_runs[run_id]`
(un), filtrage simple de `pipeline_runs` vers `pipeline_steps`. Les filtres
posés sur les runs (fichier, décision, mode, statut, date) s'appliquent ainsi
aux étapes.

Les mesures sont construites sur les tables et non sur les vues
`pipeline_observability` / `pipeline_step_observability` : une vue agrégée
ne réagit pas aux filtres du rapport.

## Mesures

`observability_measures.dax` : une définition par mesure, avec sa table,
son dossier d'affichage et son format. À créer dans le modèle (Nouvelle
mesure, ou Tabular Editor). Le fichier est régénéré par :

```bash
.venv/Scripts/python.exe -c "from pathlib import Path; from src.powerbi.measures import render_measures_script; Path('powerbi/observability_measures.dax').write_text(render_measures_script(), encoding='utf-8', newline='\n')"
```

`tests/test_powerbi_measures.py` calcule chaque mesure avec pandas selon la
sémantique DAX et la compare aux KPI Python (`calculate_pipeline_kpis`,
`calculate_step_kpis`). Seule différence connue : sur une table vide,
`AVERAGE` renvoie BLANK en DAX et 0.0 en Python.

## Rapport

**Pour construire les pages, suivre `observability_report_guide.md`** :
visuel par visuel, avec les noms de l'interface Power BI en français et les
champs à glisser dans chaque zone.

`observability_report.json` décrit les pages 1 et 2 : pour chaque visuel,
son type Power BI, ses champs et ses mesures, plus les segments (fichier,
décision, mode, statut, date). C'est une référence de construction, pas un
fichier importable dans Power BI. Il est régénéré par
`src.powerbi.report_spec.build_report_spec()` et un test le garde à jour.

- **AGENT OBSERVABILITY** : cartes Total Runs, Successful Runs, Assess Only,
  Ingest, Quarantine, Reject, Success Rate, Average Duration ; Decisions
  (anneau), Execution Mode (colonnes), Runs over time (courbe par jour).
- **PIPELINE STEPS** : exécutions par étape, statut par étape (barres
  empilées), matrice étape × statut, durée moyenne par étape, taux de succès.
- **DATASET** : produite par `build_report_spec(plan, kpis, table)` à partir
  d'un `DashboardPlan` **APPROVED** uniquement, avec les mesures DAX des KPI
  (`src/powerbi/kpi_dax.py`). Un plan non approuvé est refusé.
