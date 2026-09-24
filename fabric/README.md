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
