# Guide de construction du rapport « Data Engineering Agent »

Généré par `src/powerbi/report_spec.py` - ne pas modifier à la main.

Pour chaque visuel : cliquer sur l'icône du visuel dans le volet
« Visualisations », puis faire glisser les champs indiqués depuis le volet
« Données » dans les zones du volet « Générer un visuel ».

## Formats des mesures

Sélectionner la mesure dans le volet « Données », puis choisir le format
dans le ruban « Outils de mesure ».

- Total Runs : Nombre entier
- Successful Runs : Nombre entier
- Failed Runs : Nombre entier
- Assess Only Runs : Nombre entier
- Ingest Runs : Nombre entier
- Quarantine Runs : Nombre entier
- Reject Runs : Nombre entier
- Success Rate : Pourcentage, 1 décimale
- Quarantine Rate : Pourcentage, 1 décimale
- Reject Rate : Pourcentage, 1 décimale
- Average Duration (s) : Nombre décimal, 2 décimales
- Step Executions : Nombre entier
- Failed Steps : Nombre entier
- Succeeded Steps : Nombre entier
- Step Success Rate : Pourcentage, 1 décimale
- Average Step Duration (s) : Nombre décimal, 2 décimales

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
  - Créer d'abord, dans la table pipeline_runs, une colonne calculée (« Nouvelle colonne ») : `started_at_date = DATE(YEAR(pipeline_runs[started_at]), MONTH(pipeline_runs[started_at]), DAY(pipeline_runs[started_at]))`. Si « Nouvelle colonne » est indisponible (modèle Direct Lake), voir powerbi/README.md.
  - Axe X : « pipeline_runs > started_at_date »
  - Axe Y : mesure « Total Runs »
  - Dans l'axe, choisir le champ lui-même et non sa hiérarchie de dates, pour obtenir un point par jour.

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
