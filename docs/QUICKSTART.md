# 🚀 Guide de Démarrage - Interface Web

Comment lancer l'agent avec l'interface web interactive et la magie de l'IA agentique !

---

## 📋 Prérequis

- Python 3.8+
- Dépendances installées : `pip install -r requirements.txt`
- Clé OpenAI API configurée dans `.env`

---

## 🎯 Démarrage Rapide (3 étapes)

### 1️⃣ Configure ta clé OpenAI

```bash
# Édite le fichier .env
nano .env
```

Ajoute ta clé OpenAI (si elle n'y est pas) :
```
OPENAI_API_KEY=sk-your-key-here
```

### 2️⃣ Lance le serveur

#### Sur Linux/Mac :
```bash
chmod +x scripts/start_server.sh
./scripts/start_server.sh
```

#### Sur Windows :
```bash
start_server.bat
```

Tu peux aussi double-cliquer sur `start_server.bat` depuis le dossier du projet.

#### Sortie attendue :
```
🚀 Démarrage du serveur...

   📍 Interface Web  : http://localhost:8000
   📍 API Docs       : http://localhost:8000/docs
   📍 Health Check   : http://localhost:8000/health

Appuyez sur Ctrl+C pour arrêter le serveur
```

### 3️⃣ Ouvre l'interface web

Accède à : **http://localhost:8000** 🎉

---

## 🎨 Interface Web - Guide d'Utilisation

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                   Data Engineering Agent                    │
│          IA Agentique pour Ingestion & Analyse              │
└─────────────────────────────────────────────────────────────┘
┌──────────────────┬──────────────────────────────────────────┐
│                  │    📤 Upload & Pipeline                  │
│                  │    • Drag & Drop CSV                     │
│  • Workspace ID  │    • Chemin Contrat JSON                 │
│  • Tenant ID     │    • Dataset Name                        │
│  • Client ID     │    • Publish to Fabric (checkbox)        │
│  • Secret        │                                          │
│                  │    [🚀 Lancer Pipeline]                  │
└──────────────────┴──────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│           📊 Résultats & Monitoring                         │
│                                                             │
│  [Fichiers] [Exécutions] [Documentation]                   │
│                                                             │
│  • Statut en temps réel                                     │
│  • Résultats d'analyse                                      │
│  • Insights de l'IA                                         │
└─────────────────────────────────────────────────────────────┘
```

### Étape 1 : Upload et analyse locale

1. Upload un ou plusieurs fichiers CSV.
2. L’analyse locale et les transformations commencent sans authentification Fabric.
3. Si la publication Fabric est demandée, une page Microsoft s’ouvre automatiquement.

### Étape 2 : Upload du fichier CSV

1. Drag & Drop un ou plusieurs fichiers CSV dans la zone de dépôt
   - Ou clique pour le sélectionner
   - Format: `.csv` uniquement
   - Taille max: 100 MB

Les fichiers sélectionnés sont traités comme un même lot. L’agent compare leurs
schémas, recherche les colonnes communes, les clés de jointure et les relations
possibles, puis distingue les relations confirmées des hypothèses.

Chaque fichier est également archivé immédiatement dans `data/archive/` avec un
nom lisible dérivé du nom du fichier et la date de l’upload.

✓ Fichier uploadé → Tu verras une notification

### Étape 3 : Configurer le Pipeline

1. **Chemin du Contrat JSON** : Entrée ton chemin
   ```
    data/contracts/data_contract.json
   ```

2. **Dataset Name** : Nom du dataset (défaut: "sales")

3. **Publier dans Fabric** : Coche la case si tu es authentifié

### Étape 4 : Lancer le Pipeline

Clique sur le bouton **🚀 Lancer le Pipeline**

L'agent va automatiquement :
- ✅ Inspecter le CSV
- ✅ Valider la qualité
- ✅ Valider le contrat
- ✅ Ingérer en Bronze
- ✅ Transformer en Silver
- ✅ Transformer en Gold
- ✅ Publier dans Fabric (si configuré)
- ✅ Analyser les données
- ✅ Générer des insights

### Étape 5 : Voir les Résultats

**Onglet "Exécutions"** affiche :
- ✓ Rapport complet de l'agent
- ✓ Résultats étape par étape
- ✓ Erreurs (le cas échéant)
- ✓ Insights et recommandations

---

## 🔐 Authentification Fabric Détaillée

### Configuration OAuth initiale

#### Workspace ID
1. Va à Microsoft Fabric : https://app.fabric.microsoft.com
2. Sélectionne ton workspace
3. L'URL ressemblera à : `https://app.fabric.microsoft.com/groups/{WORKSPACE_ID}`
4. Copie l'ID

#### Tenant ID et Client ID
1. Va à Azure Portal : https://portal.azure.com
2. Cherche "Azure Active Directory"
3. Clique sur "Essentials"
4. Copie le **Tenant ID** (UUID à côté de "Tenant ID")

Le Client Secret n’est pas nécessaire. Configure uniquement `FABRIC_CLIENT_ID`
et éventuellement `FABRIC_TENANT_ID`, puis ajoute l’URI de redirection indiquée
dans `docs/FABRIC_CONFIG.md`.

### Tester la Connexion

L'interface teste automatiquement la connexion quand tu cliques "Authentifier".

Tu verras :
- ✓ **Vert** = Connecté
- ✗ **Rouge** = Erreur (vérifiez les credentials)

---

## 🎯 Workflow Complet - Exemple

### Scénario : Ingérer et analyser des ventes

**Fichier :** `data/sales.csv`
**Contrat :** `data/contracts/data_contract.json`

**Étapes dans l'interface :**

1. Drag & Drop → `data/sales.csv`
2. Contrat → `data/contracts/data_contract.json`
3. Dataset → `sales`
4. Fabric → ☑ Coché (si authentifié)
5. **Lancer Pipeline** ▶️

**Résultat après 2-5 min :**

```
═══════════════════════════════════════════════════════════

RAPPORT D'EXÉCUTION

✓ Ingestion: 1000 lignes, 5 colonnes
✓ Bronze: data/bronze/sales.parquet
✓ Silver: data/silver/sales.parquet (transformation réussie)
✓ Gold: data/gold/sales_by_product.parquet (5 produits agrégés)
✓ Fabric: Dataset "sales_analysis" publié
✓ Analyse: 
  • Complétude: 99.8%
  • Corrélations fortes: 2 paires
  • Anomalies détectées: 3 outliers
  • Recommandations: Nettoyer les valeurs manquantes

═══════════════════════════════════════════════════════════
```

---

## 📊 Tabs de l'Interface

### Tab "Fichiers"
Affiche tous les fichiers uploadés avec leur statut :
- 📤 Uploading
- ⏳ Processing
- ✅ Completed
- ❌ Error

### Tab "Exécutions"
Affiche le détail de la dernière exécution :
- Rapport complet de l'agent
- Erreurs (le cas échéant)
- Insights analytiques

### Tab "Documentation"
Contient :
- Guide rapide du pipeline
- Description des étapes
- Liens vers la documentation

---

## 🐛 Résolution de Problèmes

### Erreur : "Fabric auth required"

**Cause :** Checkbox "Publier dans Fabric" coché mais pas authentifié

**Solution :**
1. Vérifie que `FABRIC_CLIENT_ID` est configuré.
2. Vérifie que l’URI `http://localhost:8000/api/fabric/callback` est déclarée.
3. Retourne à l’application et reconnecte-toi avec Microsoft.

### Erreur : "Fichier non trouvé"

**Cause :** Le chemin du contrat n'existe pas

**Solution :**
1. Vérifie le chemin : `data/contracts/data_contract.json`
2. Crée le fichier contrat s'il n'existe pas
3. Utilise un chemin absolu si nécessaire

### Erreur : "CSV invalide"

**Cause :** Fichier CSV mal formaté ou données manquantes

**Solution :**
1. Vérifie le fichier CSV dans Excel/Calc
2. Applique le contrat JSON (colonnes, types)
3. Ré-upload le fichier

### Serveur ne démarre pas

**Cause :** Port 8000 déjà utilisé

**Solution :**
```bash
# Utilise un autre port
python -m uvicorn api:app --port 8001
```

---

## ⚙️ Configuration Avancée

### Variable d'Environnement

Tu peux configurer dans `.env` :

```
# API
API_PORT=8000
API_HOST=0.0.0.0

# Fabric (optionnel)
FABRIC_WORKSPACE_ID=your-id
FABRIC_TENANT_ID=your-tenant
FABRIC_CLIENT_ID=your-client
FABRIC_REDIRECT_URI=http://localhost:8000/api/fabric/callback

# Agent
DEBUG=false
LOG_LEVEL=INFO
```

### Mode sans Reload

```bash
# Pour production (pas de reload auto)
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## 📡 API REST (Mode Avancé)

Si tu préfères utiliser l'API directement (curl, Postman, etc.) :

### Endpoints Disponibles

**Info API :**
```bash
GET http://localhost:8000/health
GET http://localhost:8000/api/info
```

**Upload :**
```bash
POST http://localhost:8000/api/upload
Content-Type: multipart/form-data
Body: file={csv_file}
```

**Démarrer la connexion Microsoft Fabric :**
```bash
GET http://localhost:8000/api/fabric/login?file_id=uuid&workspace_id=workspace-id
```

**Exécuter Pipeline :**
```bash
POST http://localhost:8000/api/pipeline/execute
Content-Type: application/json
Body: {
  "file_id": "uuid-from-upload",
    "contract_path": "data/contracts/data_contract.json",
  "dataset_name": "sales",
  "publish_to_fabric": true
}
```

**Voir Résultats :**
```bash
GET http://localhost:8000/api/pipeline/results?file_id=uuid
```

**Documentation OpenAPI :**
```
GET http://localhost:8000/docs      # Swagger UI
GET http://localhost:8000/redoc     # ReDoc
```

---

## 🎯 Conseils d'Utilisation

1. **D'abord configurer Fabric** avant de lancer les pipelines
   - Cela te donne accès à Power BI directement

2. **Utiliser des chemins relatifs** pour les fichiers
   - `data/contracts/sales_contract.json` ✓
   - `/home/user/...` peut ne pas marcher

3. **Garder les fichiers CSV organisés**
   - Crée un dossier `data/uploads/` pour tes fichiers
   - Utilise des noms clairs : `sales_2024_08.csv`

4. **Tester d'abord sans Fabric**
   - Décocher "Publier dans Fabric"
   - Vérifier que le pipeline fonctionne
   - Puis ajouter Fabric

5. **Consulter les Insights**
   - Lis bien le rapport d'analyse
   - Les recommandations sont précieuses
   - Améliore tes données selon les suggestions

---

## 🚀 Cas d'Usage

### Production Data Pipelines
```
CSV Source
    ↓
[Interface Web - Upload]
    ↓
[Authentifier Fabric]
    ↓
[Lancer Pipeline]
    ↓
[Bronze → Silver → Gold]
    ↓
[Power BI Dataset]
    ↓
[Analytics & Insights]
```

### Test & Développement
```
CSV de test
    ↓
[Upload]
    ↓
[Décocher Fabric]
    ↓
[Lancer Pipeline - Mode local]
    ↓
[Analyser résultats]
    ↓
[Itérer sur schéma/données]
```

---

## 📚 Documentation Associée

- **README.md** - Vue d'ensemble du projet
- **docs/FABRIC_CONFIG.md** - Guide Fabric détaillé
- **docs/API_REFERENCE.md** - Référence complète des outils
- **scripts/examples.py** - Exemples CLI

---

## ✅ Checklist de Démarrage

- [ ] Python 3.8+ installé
- [ ] `pip install -r requirements.txt`
- [ ] Clé OpenAI dans `.env`
- [ ] (Optionnel) Credentials Fabric dans `.env`
- [ ] Lancer `./scripts/start_server.sh` ou `python -m uvicorn api:app`
- [ ] Ouvrir http://localhost:8000
- [ ] Upload un fichier CSV
- [ ] Lancer le pipeline
- [ ] Analyser les résultats 🎉

---

**Besoin d'aide ?** Consulte la documentation ou les logs du serveur pour plus d'infos !

**Happy Analyzing! 🚀📊**
