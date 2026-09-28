# Data Engineering Agent

Agent de Data Engineering qui prend en charge un fichier de données de bout en
bout : il l'analyse, propose un Data Contract, un pipeline Bronze / Silver /
Gold, des KPI et un tableau de bord, puis, **après validation humaine**,
l'exécute, vérifie le résultat, trace tout dans un audit et prépare les tables
pour Microsoft Fabric et Power BI.

```
FICHIER (CSV, TSV, Excel, JSON, JSONL, Parquet, ou archive ZIP de ces fichiers)
  → DÉCOUVERTE        format, schéma, types, nulls, doublons, cardinalités
  → SÉMANTIQUE        identifiants, mesures, dimensions, dates, métier (confiance)
  → DATA CONTRACT     proposé (PROPOSED) → validé par un relecteur (VALIDATED)
  → POLICY ENGINE     INGEST / QUARANTINE / REJECT (règles déterministes)
  → BRONZE → SILVER → GOLD   transformations recommandées puis exécutées
  → VERIFY            fichiers, lignes, totaux Gold = totaux Silver
  → ANALYSE           KPI, tendances, tops, distributions, constats + commentaire LLM vérifié
  → AUDIT             run et étapes horodatés, explicables
  → FABRIC            tables Delta (Lakehouse) : audits et tables Gold
  → POWER BI          rapport d'observabilité + un rapport par dataset métier
```

## Principes

- **Le LLM propose, le code déterministe décide.** Le LLM relit
  l'interprétation des colonnes et traduit une demande en intention (créer un
  plan, expliquer un run) ; il n'a aucune action pour valider ou exécuter, et
  ses suggestions ne s'appliquent qu'après contrôle et acceptation.
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

Prérequis : Python 3.14. La clé OpenAI est **facultative** : à placer dans
un fichier `.env` (voir `.env.example`), elle active la relecture sémantique,
les noms de colonnes proposés, les instructions et la synthèse de l'analyse ;
sans elle, ces fonctions se déclarent indisponibles et tout le reste
fonctionne.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Lancer le serveur :

```bash
.venv/Scripts/python.exe -m uvicorn api:app --port 8000
```

Puis ouvrir http://localhost:8000 :

1. uploader un ou plusieurs fichiers, ou une archive `.zip` ; en option,
   donner des **instructions** à l'agent en langage naturel et/ou les **noms
   de colonnes** des fichiers sans en-tête ;
2. **« Préparer avec l'agent »** : un plan par dataset détecté, avec la
   décision prévisionnelle de chaque fichier, le contrat, le pipeline, les KPI
   et le tableau de bord ;
3. dans l'onglet **Agent** : saisir le nom du relecteur, **valider le
   contrat**, et si besoin les transformations destructives et le tableau de
   bord ;
   Avant de valider le contrat, **« Lancer la relecture »** (facultatif)
   demande au LLM de relire l'interprétation des colonnes (voir plus bas) ;
4. **« Exécuter le plan validé »** : contrôles VERIFY, explication du run,
   **analyse complète des données** affichée sur la page et dossier préparé
   pour Fabric.

Pour un nouveau fichier d'un dataset déjà validé, le contrat validé existant
(`data/contracts/<dataset>.json`) est réutilisé automatiquement ; le nom du
dataset vient du nom de fichier ou du champ « Nom du Dataset ».

### Plusieurs fichiers à la fois

- **Sans nom de dataset**, les fichiers qui ont exactement les mêmes colonnes
  (quel que soit leur ordre ou leur format) forment un même dataset ; un
  fichier au schéma différent a son propre plan.
- **Avec un nom de dataset**, tous les fichiers du lot sont traités comme ce
  dataset.
- Chaque fichier reçoit sa propre décision. Les fichiers INGEST sont combinés
  dans un seul run Bronze → Silver → Gold ; chaque fichier refusé est isolé
  (quarantaine ou rejet) dans son propre run audité, sans bloquer les autres.
  Les runs d'une même exécution partagent un `batch_id`.
- Les recommandations suivent le contrat : une colonne hors contrat n'est ni
  transformée ni utilisée dans Gold, les KPI ou le tableau de bord.

### Fichiers sans en-tête et archives ZIP

Un export découpé (par exemple une année par fichier, sans ligne d'en-tête,
dans un `.zip`) devient un seul dataset avec un seul contrat :

- une archive `.zip` est conservée dans `data/archive/` et ses fichiers de
  données rejoignent le lot (noms à plat, sans archive imbriquée, tailles
  limitées) ;
- un fichier délimité **sans en-tête** est détecté quand sa première ligne
  contient des nombres ou des dates là où les autres lignes en contiennent
  (un en-tête y porterait des libellés) ;
- ses colonnes sont nommées, par ordre de priorité : avec les **noms que
  vous donnez** (champ « Noms de colonnes » ou instructions) ; d'après le
  **seul contrat validé de même structure** (nombre et types de colonnes),
  qui est alors réutilisé ; par le **LLM** (pour les textes comme les noms
  ou e-mails, seule leur forme est envoyée, `Aaaaaaa Aaa`) ; sinon
  `column_1`, `column_2`… Les noms sont normalisés (`numéro de commande` ->
  `numero_de_commande`) ;
- l'étape **« Noms de colonnes »** du plan affiche les noms avec des exemples
  de valeurs : vous les validez ou les modifiez, **avant** de pouvoir valider
  le contrat (des noms repris d'un contrat validé sont déjà validés). Modifier
  les noms recalcule le plan ; si le contrat du plan est déjà validé, il faut
  aussi changer de nom de dataset ;
- une copie avec en-tête (`<fichier>_avec_entete.csv`) est écrite à côté du
  fichier, texte des cellules inchangé ; les fichiers de même structure ont
  les mêmes noms et forment un seul plan, chacun gardant sa décision.

Vérifié le 2026-09-28 avec l'export `data/samples/orders.zip` (2019, 2020, 2021 sans
en-tête) : un seul plan `sales` réutilisant le contrat validé, 32 718 lignes,
mêmes totaux que `data/samples/sales.csv` ; sans contrat, le LLM a proposé
`SalesOrderNumber`, `OrderDate`, `CustomerEmail`, `UnitPrice`, `TaxAmount`…

Limite : un fichier dont l'en-tête ne contient que des nombres (années en
colonnes, par exemple) serait pris pour un fichier sans en-tête ; le plan
l'indique (« Fichiers sans en-tête préparés »).

### Instructions à l'agent

Le champ « Instructions pour l'agent » accepte du texte libre, par exemple :
« les colonnes sont numéro de commande, ligne, date… ; appelle le dataset
ventes_ae ». Le LLM le traduit en actions vérifiées par le code — **nom du
dataset** et **noms de colonnes** — affichées dans le plan avec ce qui n'est
pas pris en charge (« trier par date »…) et ce qui a été écarté. Les champs
remplis explicitement l'emportent sur les instructions ; sans LLM, les
instructions sont signalées comme non appliquées.

### Fichiers d'exemple

`data/samples/` contient des données **fictives** pour tester les trois
décisions sur le dataset `ventes_2025_2026` :

| Fichier | Décision attendue | Raison |
|---|---|---|
| `ventes_2025_2026.csv` | INGEST | 1 500 commandes conformes |
| `ventes_quarantaine.csv` | QUARANTINE | colonne `commentaire` en partie vide |
| `ventes_rejet.csv` | REJECT | quantités négatives (contrat : ≥ 1) |

Pour les deux derniers, saisir `ventes_2025_2026` dans « Nom du Dataset » afin
de réutiliser le contrat validé. Les trois fichiers peuvent aussi être envoyés
ensemble avec ce nom : un seul plan, trois décisions.

`data/samples/sales.csv` est l'exemple de ventes **Adventure Works** de
Microsoft (clients fictifs), 32 718 lignes, pour tester un volume plus
important et un fichier sans colonne de montant : le chiffre d'affaires est
dérivé de `Quantity × UnitPrice` (20 928 022,43) et `TaxAmount` est reconnu
comme une taxe (1 674 241,85). Son contrat validé est
`data/contracts/sales.json`.

### Relecture sémantique (LLM)

L'interprétation des colonnes (mesure, montant, taxe, dimension, date…) est
faite par des règles sur les noms et les données. Une règle peut se tromper :
`TotalDiscount` est pris pour le chiffre d'affaires à cause du mot « total ».
La relecture demande au LLM de signaler ces erreurs :

- chaque suggestion est **vérifiée par le code** (colonne existante, rôles
  connus et compatibles avec le type observé, changement réel) ; les autres
  sont écartées avec leur raison ;
- **rien n'est appliqué sans décision** d'un relecteur nommé : les cases
  cochées sont acceptées, les autres rejetées ;
- une fois acceptés, les rôles pilotent KPI, Gold et tableau de bord ; un
  contrat encore proposé est régénéré avec ces rôles, **un contrat validé
  n'est jamais modifié** ;
- seuls les noms, types, statistiques et rôles des colonnes sont envoyés au
  LLM ; les valeurs d'exemple uniquement pour les colonnes catégorielles qui
  ne sont ni des identifiants ni des coordonnées personnelles ;
- sans clé valide, la relecture est marquée indisponible et le workflow
  continue normalement.

Vérifié le 2026-09-28 avec le LLM réel : aucune suggestion sur
`ventes_2025_2026` (interprétation correcte) ; sur un extrait Adventure Works
avec une colonne `TotalDiscount`, le LLM a proposé de ne plus la traiter
comme un montant, et après acceptation le chiffre d'affaires est redevenu
`SUM(quantity * unit_price)`.

### Analyse des données

Après une exécution réussie, l'agent analyse les données Silver ingérées et
l'affiche sous le résultat (et dans `results/<dataset>_analysis.txt|json`) :

- **indicateurs** du plan, calculés avec les mêmes formules que Gold et
  Power BI, et la même règle métier (annulations exclues) ;
- **évolution mensuelle** de la mesure principale (histogramme), totaux par
  année, meilleur et moins bon mois, évolution du dernier mois et d'une
  année complète sur l'autre ; les mois incomplets sont signalés et écartés
  des comparaisons ;
- **top 5** par produit, client, catégorie, région ou statut, avec leur part
  et la concentration (combien de valeurs font 80 % du total) ;
- **distributions** des mesures (quartiles, valeurs hors 1,5 × l'écart
  interquartile ; au-delà de 10 %, décrites comme plusieurs gammes plutôt
  que comme des anomalies) ;
- **moyennes** des mesures de niveau (âge, température, note…) et des mesures
  sans rôle métier : globale, par mois et par dimension ; les extrêmes ne
  sont cités que sur des groupes d'au moins 5 lignes, et des moyennes à
  moins de 5 % d'écart sont dites « proches » ;
- **qualité** : décision de chaque fichier, contrôles VERIFY, avertissements ;
- **constats** rédigés par des règles, en français ;
- **synthèse du LLM**, marquée « texte généré » : il ne reçoit que les
  agrégats (clients remplacés par « Client 1 »…, jamais de lignes ni
  d'e-mails) ; chaque nombre qu'il cite est **vérifié** contre les chiffres
  calculés, et les nombres introuvables sont signalés. Sans clé, l'analyse
  reste complète sans synthèse.

Vérifié le 2026-09-28 sur `data/samples/sales.csv` avec le LLM réel :
chiffre d'affaires 20 928 022,43, totaux annuels identiques au fichier
source, 2021 en hausse de 67,8 % sur 2020, synthèse dont tous les nombres
ont été vérifiés.

### Données hors vente

Le métier est reconnu pour les ventes ; pour un autre fichier (RH, capteurs…),
le plan le signale (« Métier non reconnu ») et reste générique, sans jamais
inventer de chiffre d'affaires. Les mesures sont alors traitées selon leur
nature :

- une **mesure de niveau** (âge, température, humidité, pression, note,
  score, niveau, vitesse, ou colonne déjà moyenne) est **moyennée** partout :
  KPI, DAX, Gold, tableau de bord (en barres, jamais en anneau) et analyse ;
- une mesure sans rôle métier garde une somme (hypothèse signalée), et sa
  moyenne par groupe figure dans Gold et dans l'analyse (salaire moyen par
  département) ;
- l'évolution mensuelle et les tops portent sur le **nombre de lignes**.

La relecture sémantique du LLM peut proposer le rôle « niveau » pour une
colonne que les règles n'ont pas reconnue.

`data/samples/rh_employes.csv` (600 employés fictifs : service, poste,
ville, statut, date d'embauche, âge, salaire, note d'évaluation, formation,
absences) permet de le tester. Les règles y prennent `departement` pour une
donnée géographique (départements français) : c'est un cas pour la
relecture sémantique du LLM.

Vérifié le 2026-09-28 sur deux fichiers générés (300 employés, 2 000 relevés
de capteurs) : âge et salaire moyens par département, température et
humidité moyennes par ville et par mois, aucune somme d'âge ni de
température.

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
| POST | `/api/upload` | uploader un ou plusieurs fichiers, ou une archive `.zip` |
| POST | `/api/workflow/plan` | créer les plans d'un lot uploadé (`{"plans": [...]}`, un par dataset) ; options `column_names`, `instructions` |
| POST | `/api/workflow/{plan_id}/column-names` | valider les noms de colonnes, ou les modifier (`names`, `dataset`) |
| POST | `/api/workflow/ask` | demande en langage naturel (LLM → plan ou explication), un fichier à la fois |
| GET | `/api/workflow/{plan_id}` | consulter un plan |
| POST | `/api/workflow/{plan_id}/semantic-review` | relecture sémantique par le LLM (suggestions seulement) |
| POST | `/api/workflow/{plan_id}/semantic-review/decide` | accepter des suggestions (`accepted`), les autres sont rejetées |
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

Après chaque exécution, l'agent prépare automatiquement :

- l'audit structuré de tous les runs (y compris refusés ou en échec) dans
  `data/fabric_export/audit/`, à déposer dans `Files/audit/` ;
- les tables Gold d'une exécution réussie dans
  `data/fabric_export/gold/<dataset>/`, à déposer dans `Files/gold/<dataset>/`.

L'export de l'audit peut aussi être relancé à la main :

```bash
.venv/Scripts/python.exe -c "from src.audit_parquet import export_structured_audit_to_parquet as e; print(e(None, 'data/fabric_export/audit/pipeline_runs_structured.parquet', 'data/fabric_export/audit/pipeline_steps_structured.parquet'))"
```

Validé dans Fabric : chargements incrémentaux et idempotents, rattrapage après
interruption, vues, tables Gold `ventes_2025_2026` et `sales` (Adventure Works)
conformes au fichier source.

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
  tools/                    validations qualité et contrat, Policy Engine
  recommendation/           pipeline, KPI, tableau de bord, revue, règles métier
  execution/                exécution Silver et Gold
  workflow/                 PLAN → VALIDATE → EXECUTE → VERIFY → AUDIT, service, LLM
  fabric/                   chargement incrémental, export Gold (logique testable)
  powerbi/                  mesures DAX, traduction des KPI, guides de rapport
  audit*.py                 audit, tables, KPI d'observabilité, export Parquet, explication
fabric/                     notebooks PySpark et SQL des vues pour Fabric
powerbi/                    mesures, guides et tableaux de bord approuvés
data/contracts/             contrats validés (versionnés) ; proposed/ est ignoré
data/samples/               fichiers d'exemple fictifs
tests/                      tests unitaires et de bout en bout
```

## Limites connues

- La demande en langage naturel (`/api/workflow/ask`) traite un fichier à la
  fois ; l'interface et `/api/workflow/plan` acceptent un lot.
- La détection des annulations s'appuie sur les valeurs d'exemple du profil
  (5 valeurs distinctes au plus par colonne).
