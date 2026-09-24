# Power BI

Artefacts à reproduire dans le modèle sémantique et le rapport Power BI.
Ils sont générés par `src/powerbi/` ; les tests vérifient leur sémantique
en Python, mais **ils n'ont pas été exécutés dans Power BI**.

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
