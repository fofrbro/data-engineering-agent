@echo off
REM 🚀 Script de démarrage du Data Engineering Agent (Windows)

set "ROOT_DIR=%~dp0.."
pushd "%ROOT_DIR%"

echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║  Data Engineering Agent - Démarrage                            ║
echo ║  Interface Web + API REST + IA Agentique                       ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM Vérifie si virtualenv est activé
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Environnement Windows absent ou incompatible. Creation de .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer l'environnement virtuel.
        popd
        pause
        exit /b 1
    )
)

if not defined VIRTUAL_ENV (
    echo [INFO] Activation de l'environnement virtuel...
    call .venv\Scripts\activate.bat
)

REM Vérifie que les dépendances sont installées
echo 📦 Vérification des dépendances...
python -m pip install -r requirements.txt -q

REM Affiche les informations de configuration
echo.
echo ⚙️  Configuration:
python -c "import os; print('   - OpenAI API: ✓' if os.getenv('OPENAI_API_KEY') else '   - OpenAI API: ✗')"
python -c "import os; print('   - Fabric Auth: ✓' if os.getenv('FABRIC_WORKSPACE_ID') else '   - Fabric Auth: ✗ (optionnel)')"
echo.

REM Lance le serveur
echo 🚀 Démarrage du serveur...
echo.
echo    📍 Interface Web  : http://localhost:8000
echo    📍 API Docs       : http://localhost:8000/docs
echo    📍 Health Check   : http://localhost:8000/health
echo.
echo Appuyez sur Ctrl+C pour arrêter le serveur
echo.

python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload

popd
pause
