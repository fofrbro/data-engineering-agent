@echo off
setlocal
set "ROOT_DIR=%~dp0"
set "PYTHON=%ROOT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [INFO] Environnement Windows absent. Creation de .venv...
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERREUR] Python n'est pas disponible dans le PATH.
        echo Installe Python 3.10+ puis relance ce fichier.
        exit /b 1
    )
    python -m venv "%ROOT_DIR%.venv"
    if errorlevel 1 exit /b 1
)

"%PYTHON%" -m pip install -r "%ROOT_DIR%requirements.txt"
if errorlevel 1 exit /b 1

"%PYTHON%" -m pytest %*
exit /b %errorlevel%
