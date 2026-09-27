# Guide de construction du rapport « Suivi des ventes - Ventes 2025 2026 »

Généré par `src/powerbi/report_spec.py` - ne pas modifier à la main.

Pour chaque visuel : cliquer sur l'icône du visuel dans le volet
« Visualisations », puis faire glisser les champs indiqués depuis le volet
« Données » dans les zones du volet « Générer un visuel ».

## 1. Créer le modèle sémantique

Un modèle sémantique dédié, séparé de celui de l'observabilité de l'agent :

1. Dans le Lakehouse, cliquer sur « Nouveau modèle sémantique ».
2. Le nommer « Suivi des ventes - Ventes 2025 2026 ».
3. Cocher uniquement : `fact_ventes_2025_2026`.
4. Dans ce modèle, créer les mesures de `ventes_2025_2026_measures.dax` dans la table `fact_ventes_2025_2026` (« Nouvelle mesure », puis coller la formule).
5. Régler le format de chaque mesure (section suivante).

## 2. Créer le rapport

Depuis ce modèle sémantique, cliquer sur « Créer un rapport ». Ce rapport est
distinct du rapport d'observabilité : un rapport ne se connecte qu'à un seul
modèle sémantique.

## Formats des mesures

Dans Fabric : ouvrir le modèle sémantique, « Ouvrir le modèle de données »,
cliquer sur la mesure dans le volet « Données », puis régler « Format » et
le nombre de décimales dans le volet « Propriétés » (section « Mise en
forme »). Dans Power BI Desktop : ruban « Outils de mesure ».

- Revenue : Devise, 2 décimales
- Orders : Nombre entier
- Quantity Sold : Nombre décimal, 2 décimales
- Average Order Value : Devise, 2 décimales
- Customers : Nombre entier
- Products : Nombre entier
- Average Unit Price : Devise, 2 décimales

## Page 1 - Suivi des ventes - Ventes 2025 2026

Renommer la page : « Suivi des ventes - Ventes 2025 2026 ».

### Visuels

- **Revenue** : Carte
  - Champs : mesure « Revenue »
- **Orders** : Carte
  - Champs : mesure « Orders »
- **Quantity Sold** : Carte
  - Champs : mesure « Quantity Sold »
- **Average Order Value** : Carte
  - Champs : mesure « Average Order Value »
- **Customers** : Carte
  - Champs : mesure « Customers »
- **Products** : Carte
  - Champs : mesure « Products »
- **Revenue by Month** : Graphique en courbes
  - Axe X : « fact_ventes_2025_2026 > order_date »
  - Axe Y : mesure « Revenue »
  - Dans l'axe, garder la hiérarchie de dates avec seulement Année et Mois, pour obtenir un point par mois.
- **Revenue by Month and category** : Histogramme empilé
  - Axe X : « fact_ventes_2025_2026 > order_date »
  - Axe Y : mesure « Revenue »
  - Légende : « fact_ventes_2025_2026 > category »
  - Dans l'axe, garder la hiérarchie de dates avec seulement Année et Mois, pour obtenir un point par mois.
- **Revenue by Product** : Graphique à barres groupées
  - Axe Y : « fact_ventes_2025_2026 > product »
  - Axe X : mesure « Revenue »
- **Revenue by Region** : Graphique à barres groupées
  - Axe Y : « fact_ventes_2025_2026 > region »
  - Axe X : mesure « Revenue »
- **Revenue by Category** : Graphique en anneau
  - Légende : « fact_ventes_2025_2026 > category »
  - Valeurs : mesure « Revenue »
- **Revenue by Status** : Graphique en anneau
  - Légende : « fact_ventes_2025_2026 > status »
  - Valeurs : mesure « Revenue »
- **Détail des lignes** : Table
  - Colonnes : « fact_ventes_2025_2026 > order_id », « fact_ventes_2025_2026 > customer_id », « fact_ventes_2025_2026 > order_date », « fact_ventes_2025_2026 > product », « fact_ventes_2025_2026 > category », « fact_ventes_2025_2026 > region », « fact_ventes_2025_2026 > status », « fact_ventes_2025_2026 > quantity », « fact_ventes_2025_2026 > unit_price »

### Segments (filtres de page)

- Segment sur « fact_ventes_2025_2026 > order_date », style : Entre (plage de dates)
- Segment sur « fact_ventes_2025_2026 > product », style : Liste déroulante
- Segment sur « fact_ventes_2025_2026 > category », style : Liste déroulante
- Segment sur « fact_ventes_2025_2026 > region », style : Liste déroulante
- Segment sur « fact_ventes_2025_2026 > status », style : Liste déroulante
