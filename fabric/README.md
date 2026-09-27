# Microsoft Fabric

Artefacts exécutés dans le workspace Fabric (Lakehouse, Spark).
Ils ne sont pas lancés par les tests locaux : seule la logique
équivalente, écrite en Python dans `src/`, est testée ici.

## Chaîne cible

```
Agent -> Parquet (data/audit/*_structured.parquet)
      -> Fabric Files (Files/audit/)
      -> Lakehouse Delta (pipeline_runs, pipeline_steps)
      -> vue pipeline_observability
      -> Semantic Model -> Power BI
```

## Contenu

- `notebooks/load_audit_tables.py` : notebook d'origine, chargement complet
  (overwrite) et création de la vue.
- `notebooks/incremental_load_audit_tables.py` : chargement incrémental
  (anti-join sur `run_id`, puis sur `run_id` + `step_order`). Logique
  testée localement via `src/fabric/incremental_load.py`
  (`tests/test_fabric_incremental_load.py`).
  Exécuté dans Fabric le 2026-09-24 : crée les tables Delta
  `pipeline_runs` et `pipeline_steps` et la vue `pipeline_observability`
  (type VIEW confirmé). Seconde exécution : aucun `run_id` en double dans
  `pipeline_runs` (idempotence confirmée dans Fabric).
- `sql/pipeline_observability.sql` : vue d'observabilité (volumes, décisions,
  succès, échecs, taux, durée moyenne). Le notebook incrémental en embarque
  une copie exacte. `tests/test_fabric_observability_view.py` exécute ce SQL
  dans SQLite et vérifie qu'il donne les mêmes KPI que
  `calculate_pipeline_kpis()`, y compris sur une table vide.
- `sql/pipeline_step_observability.sql` : vue par étape (exécutions, échecs,
  taux de succès, durée moyenne). Une étape réussie est une étape terminée
  sans erreur ; la durée moyenne reste NULL tant qu'aucune durée n'est
  connue. Même vérification SQLite contre `calculate_step_kpis()`.
  Exécutée dans Fabric le 2026-09-25 : 7 étapes, durées moyennes renseignées
  (colonnes d'horodatage ajoutées à `pipeline_steps` par `mergeSchema`).
- `notebooks/load_gold_tables.py` : chargement des tables Gold d'un dataset
  depuis `Files/gold/<dataset>/` (manifeste + Parquet). Chaque table est
  remplacée par sa dernière version vérifiée, le nombre de lignes est
  contrôlé, le chargement est tracé dans `gold_loads` et un run déjà chargé
  n'est pas rechargé. Les fichiers sont préparés par
  `src/fabric/gold_export.export_gold_for_fabric()` (exécution SUCCESS
  uniquement) dans `data/fabric_export/gold/<dataset>/`. Logique testée
  localement (`tests/test_fabric_gold_export.py`).
  Exécuté dans Fabric le 2026-09-24 pour le dataset `sales` : tables
  `fact_sales`, `dim_customer`, `dim_product`, `sales_by_product` et
  `sales_summary` créées, valeurs conformes (CA 3 110, quantité 12, 5 lignes).
  Table `gold_loads` confirmée le 2026-09-25 : 5 lignes, une par table, même
  `run_id`. Seconde exécution le 2026-09-25 : « Run … déjà chargé : aucune
  table modifiée » (idempotence confirmée dans Fabric).

## Dépannage

- **Fichier remplacé dans `Files/` mais ancien schéma lu** : une session Spark
  qui a déjà lu un fichier peut garder son ancien schéma en cache, tout en
  lisant les nouvelles lignes (constaté le 2026-09-27 : `duration_seconds`
  lu en `long` au lieu de `double`). Arrêter la session du notebook avant de
  relire des fichiers remplacés.
- **`DELTA_FAILED_TO_MERGE_FIELDS`** : la source et la table Delta typent une
  colonne différemment. Le notebook d'audit convertit désormais la source au
  type de la table ; vérifier aussi que les fichiers déposés sont les derniers
  exports.
- **Exporter les audits après les exécutions** : un export fait avant les runs
  est vide et n'ajoute rien.
