# Déployer la démo publique sur un VPS

Objectif : `https://demo.fofanalyse.com` sert l'agent en **mode démo**
(fichiers d'exemple seulement, un espace isolé et temporaire par visiteur,
quotas journaliers), derrière **Caddy**, qui gère seul le certificat HTTPS.

> Ces fichiers (`Dockerfile`, `docker-compose.yml`, `Caddyfile`) n'ont pas
> encore été exécutés : Docker n'était pas disponible sur le poste de
> développement. Le mode démo lui-même est testé (tests automatisés et essai
> en navigateur). Premier déploiement : suivre les vérifications de
> l'étape 6.

## 1. Le serveur

Un petit VPS Linux suffit : 2 vCPU, 2 à 4 Go de RAM, Ubuntu 24.04 (par
exemple Hetzner CX22 ou OVH VPS, environ 4 à 6 € par mois). Choisir une
connexion par **clé SSH** plutôt que par mot de passe.

## 2. Le nom de domaine

Chez le registraire de `fofanalyse.com`, créer un enregistrement DNS :

| Type | Nom | Valeur |
|---|---|---|
| A | `demo` | adresse IPv4 du VPS |

La propagation prend de quelques minutes à quelques heures. Vérifier avec
`nslookup demo.fofanalyse.com`.

## 3. Préparer le serveur

Se connecter (`ssh root@<IP>`), puis :

```bash
apt update && apt upgrade -y
```

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
```

Installer Docker (méthode officielle) :

```bash
curl -fsSL https://get.docker.com | sh
```

## 4. Installer l'agent

```bash
git clone https://github.com/fofrbro/data-engineering-agent.git
```

```bash
cd data-engineering-agent/deploy
```

Créer `deploy/.env` (ignoré par Git), lisible seulement par vous :

```bash
nano .env
```

```
OPENAI_API_KEY=la-cle-du-projet-openai-dedie-a-la-demo
```

```bash
chmod 600 .env
```

Sans clé, la démo fonctionne aussi : les fonctions LLM se déclarent
indisponibles.

## 5. La clé OpenAI de la démo

Dans la console OpenAI, créer un **projet dédié à la démo**, avec sa propre
clé et une **limite de dépense mensuelle** (par exemple 10 $). Même si les
quotas de l'application étaient contournés, la dépense resterait plafonnée.
Ne jamais réutiliser votre clé personnelle.

## 6. Lancer et vérifier

```bash
docker compose up -d --build
```

Vérifications :

```bash
docker compose ps
```

```bash
docker compose logs caddy --tail 50
```

```bash
curl -I https://demo.fofanalyse.com/health
```

Puis ouvrir `https://demo.fofanalyse.com`, charger un exemple, préparer le
plan, valider le contrat et exécuter.

## 7. Mettre à jour

```bash
git pull && docker compose up -d --build
```

## Réglages

Les limites se règlent dans `docker-compose.yml` :

| Variable | Défaut | Rôle |
|---|---|---|
| `DEMO_TTL_MINUTES` | 120 | inactivité avant effacement de l'espace d'un visiteur |
| `DEMO_MAX_VISITORS` | 50 | espaces simultanés (les espaces vides sont libérés en premier) |
| `DEMO_PLANS_PER_DAY` | 30 | préparations de plan par visiteur et par jour |
| `DEMO_EXECUTIONS_PER_DAY` | 10 | exécutions par visiteur et par jour |
| `DEMO_LLM_CALLS_PER_DAY` | 20 | appels au LLM par visiteur et par jour |
| `DEMO_LLM_CALLS_OVERALL_PER_DAY` | 300 | appels au LLM par jour, tous visiteurs confondus |

Les compteurs et les espaces sont en mémoire : ils repartent de zéro quand
le conteneur redémarre.
