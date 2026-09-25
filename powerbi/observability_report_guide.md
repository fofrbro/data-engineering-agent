# Guide de construction du rapport « Data Engineering Agent »

Généré par `src/powerbi/report_spec.py` - ne pas modifier à la main.

Pour chaque visuel : cliquer sur l'icône du visuel dans le volet
« Visualisations », puis faire glisser les champs indiqués depuis le volet
« Données » dans les zones du volet « Générer un visuel ».

## Page 1 - AGENT OBSERVABILITY

Renommer la page : « AGENT OBSERVABILITY ».

### Visuels

- **Total Runs** : Carte
  - Champs : mesure « Total Runs »
- **Successful Runs** : Carte
  - Champs : mesure « Successful Runs »
- **Assess Only Runs** : Carte
  - Champs : mesure « Assess Only Runs »
- **Ingest Runs** : Carte
  - Champs : mesure « Ingest Runs »
- **Quarantine Runs** : Carte
  - Champs : mesure « Quarantine Runs »
- **Reject Runs** : Carte
  - Champs : mesure « Reject Runs »
- **Success Rate** : Carte
  - Champs : mesure « Success Rate »
- **Average Duration (s)** : Carte
  - Champs : mesure « Average Duration (s) »
- **Decisions** : Graphique en anneau
  - Légende : « pipeline_runs > decision »
  - Valeurs : mesure « Total Runs »
- **Execution Mode** : Histogramme groupé
  - Axe X : « pipeline_runs > execution_mode »
  - Axe Y : mesure « Total Runs »
- **Runs over time** : Graphique en courbes
  - Axe X : « pipeline_runs > started_at »
  - Axe Y : mesure « Total Runs »
  - Dans l'axe, remplacer la hiérarchie de dates par le champ lui-même (granularité : jour).

### Segments (filtres de page)

- Segment sur « pipeline_runs > source_file », style : Liste déroulante
- Segment sur « pipeline_runs > decision », style : Liste déroulante
- Segment sur « pipeline_runs > execution_mode », style : Liste déroulante
- Segment sur « pipeline_runs > final_status », style : Liste déroulante
- Segment sur « pipeline_runs > started_at », style : Entre (plage de dates)

## Page 2 - PIPELINE STEPS

Renommer la page : « PIPELINE STEPS ».

### Visuels

- **Executions by step** : Graphique à barres groupées
  - Axe Y : « pipeline_steps > step_name »
  - Axe X : mesure « Step Executions »
- **Step status** : Graphique à barres empilées
  - Axe Y : « pipeline_steps > step_name »
  - Légende : « pipeline_steps > status »
  - Axe X : mesure « Step Executions »
- **Step x status** : Matrice
  - Lignes : « pipeline_steps > step_name »
  - Colonnes : « pipeline_steps > status »
  - Valeurs : mesure « Step Executions »
- **Average duration by step** : Graphique à barres groupées
  - Axe Y : « pipeline_steps > step_name »
  - Axe X : mesure « Average Step Duration (s) »
- **Step Success Rate** : Carte
  - Champs : mesure « Step Success Rate »

### Segments (filtres de page)

- Segment sur « pipeline_runs > source_file », style : Liste déroulante
- Segment sur « pipeline_runs > decision », style : Liste déroulante
- Segment sur « pipeline_runs > execution_mode », style : Liste déroulante
- Segment sur « pipeline_runs > final_status », style : Liste déroulante
- Segment sur « pipeline_runs > started_at », style : Entre (plage de dates)
