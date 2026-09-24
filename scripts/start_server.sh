#!/bin/bash

# 🚀 Script de démarrage du Data Engineering Agent

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Data Engineering Agent - Démarrage                            ║"
echo "║  Interface Web + API REST + IA Agentique                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Vérifie si virtualenv est activé
if [[ -z "${VIRTUAL_ENV}" ]]; then
    echo "⚠️  Activating virtual environment..."
    source .venv/bin/activate
fi

# Vérifie que les dépendances sont installées
echo "📦 Vérification des dépendances..."
"$ROOT_DIR/.venv/bin/python" -m pip install -r requirements.txt -q

# Affiche les informations de configuration
echo ""
echo "⚙️  Configuration:"
echo "   - OpenAI API: $("$ROOT_DIR/.venv/bin/python" -c 'import os; print("✓" if os.getenv("OPENAI_API_KEY") else "✗")')"
echo "   - Fabric Auth: $("$ROOT_DIR/.venv/bin/python" -c 'import os; print("✓" if os.getenv("FABRIC_WORKSPACE_ID") else "✗ (optionnel)")')"
echo ""

# Lance le serveur
echo "🚀 Démarrage du serveur..."
echo ""
echo "   📍 Interface Web  : http://localhost:8000"
echo "   📍 API Docs       : http://localhost:8000/docs"
echo "   📍 Health Check   : http://localhost:8000/health"
echo ""
echo "Appuyez sur Ctrl+C pour arrêter le serveur"
echo ""

"$ROOT_DIR/.venv/bin/python" -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
