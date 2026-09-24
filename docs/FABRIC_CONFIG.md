# Configuration Microsoft Fabric

L'agent utilise une connexion OAuth interactive. Tu te connectes avec ton compte
Microsoft habituel dans le navigateur. Avec une plateforme Web, un Client
Secret est nécessaire pour l'échange OAuth côté serveur.

## Variables d'environnement requises

```
# Fabric Configuration
FABRIC_WORKSPACE_ID=your-workspace-id
FABRIC_LAKEHOUSE_ID=your-lakehouse-id
FABRIC_TENANT_ID=organizations
FABRIC_CLIENT_ID=your-azure-client-id
FABRIC_CLIENT_SECRET=your-client-secret
FABRIC_REDIRECT_URI=http://localhost:8000/api/fabric/callback

# OpenAI API (déjà configuré)
OPENAI_API_KEY=your-openai-api-key
```

## Configuration initiale

### Choisir le Lakehouse cible
- Dans [Microsoft Fabric](https://app.fabric.microsoft.com/), ouvre le workspace
- Ouvre ou crée un élément **Lakehouse**
- Copie son ID depuis l'URL ou les détails de l'élément dans
	`FABRIC_LAKEHOUSE_ID`
- Dans **Gérer les connexions et passerelles** ou les paramètres de l'application
	Entra, accorde la permission déléguée `Lakehouse.ReadWrite.All`
- L'application doit aussi obtenir un jeton Storage pour OneLake. Le serveur
	le demande avec la portée `https://storage.azure.com/user_impersonation`.

### 1. Obtenir le Workspace ID
- Va dans Microsoft Fabric
- Ouvre ton workspace
- L'ID est dans l'URL : `https://app.fabric.microsoft.com/groups/{WORKSPACE_ID}`

### 2. Enregistrer l'application
- Va à https://portal.azure.com → Microsoft Entra ID → Inscriptions d'applications
- Crée une application et ajoute une plateforme **Web**
- Ajoute exactement cette URI de redirection :
	`http://localhost:8000/api/fabric/callback`
- Copie l'**ID d'application (client)** dans `FABRIC_CLIENT_ID`
- Pour une plateforme **Web**, crée un secret dans **Certificats et secrets** et
	copie sa valeur dans `FABRIC_CLIENT_SECRET`. Le secret n'est affiché qu'une
	seule fois.
- Une plateforme **Mobile et applications de bureau** peut utiliser le flux
	public sans secret, avec une URI de redirection adaptée.

### 3. Donner les permissions
- Ajoute les permissions déléguées Microsoft Fabric nécessaires
- Ajoute l'API **Azure Storage** puis la permission déléguée
	`user_impersonation`.
- Accorde le **consentement administrateur** aux permissions de l'application
	si le consentement utilisateur est désactivé dans ton organisation.
- Autorise l'utilisateur à accéder au workspace Fabric ciblé

## Utilisation

```python
Lance le serveur puis ouvre `http://localhost:8000`. Lorsque l'agent atteint
l'étape de publication, il ouvre `/fabric-auth`; clique sur **Continuer avec
Microsoft** et connecte-toi dans la page Microsoft.
```

Après le retour OAuth, l'agent reprend l'exécution interrompue.

Une reconnexion est nécessaire après la mise à jour du serveur afin de remplacer
les anciens jetons. L'API Fabric et OneLake n'acceptent pas le même jeton :
Fabric utilise le jeton `api.fabric.microsoft.com`, tandis que OneLake exige
un jeton dont l'audience est `https://storage.azure.com`.

### Vérifier une redirection vers Fabric

Si le navigateur termine sur une URL du type
`.../list?experience=fabric-developer`, l'URI de redirection Entra n'est pas
correcte. Elle doit être exactement `http://localhost:8000/api/fabric/callback`
et être déclarée dans **Authentification > Plateformes > Web**. Tu peux vérifier
la valeur utilisée localement avec `http://localhost:8000/api/fabric/config`.

## Mode prototype

Pour développer sans Fabric :
- Les données seront mockées localement
- La publication actuelle reste simulée localement
- C'est parfait pour tester le pipeline end-to-end
