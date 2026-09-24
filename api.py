"""
API REST pour l'Agent Data Engineering.

Expose l'agent via une API FastAPI avec endpoints pour :
- Upload de fichiers CSV
- Exécution du pipeline
- Récupération des résultats
- Authentification Fabric interactif
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
import asyncio
import threading
import secrets
import msal
from dotenv import load_dotenv

load_dotenv()

from src.agent import FabricAuthenticationRequired, run_agent
from src.tabular_pipeline import (
    SUPPORTED_EXTENSIONS,
    process_uploads,
)
from src.tools.data_analyst import DataAnalyst, analyze_gold_data
from src.contract.contract_lifecycle import (
    ContractStatusError,
    approve_contract_file,
    reject_contract_file,
)
from src.upload_governance import assess_uploads
from src.tools.fabric_connector import (
    configure_fabric_session,
    publish_to_fabric as publish_dataset_to_fabric,
)

# ============================================
# Configuration
# ============================================

app = FastAPI(
    title="Data Engineering Agent API",
    description="IA Agentique pour Data Engineering + Fabric + Analytics",
    version="1.0.0"
)

# CORS pour l'interface web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dossiers de travail
UPLOAD_DIR = Path("uploads")
ARCHIVE_DIR = Path("data/archive")
RESULTS_DIR = Path("results")
UPLOAD_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# Stockage des sessions et authentification
FABRIC_ENABLED = os.getenv("FABRIC_ENABLED", "false").lower() == "true"

sessions: Dict[str, Dict[str, Any]] = {}
fabric_auth_state = {
    "authenticated": False,
    "onelake_authenticated": False,
    "workspace_id": None,
    "user_id": None,
    "access_token": None,
    "storage_access_token": None,
}
oauth_states: Dict[str, Dict[str, Any]] = {}
FABRIC_SCOPES = [
    "https://api.fabric.microsoft.com/Workspace.ReadWrite.All",
    "https://api.fabric.microsoft.com/Lakehouse.ReadWrite.All",
]
ONELAKE_SCOPE = "https://storage.azure.com/user_impersonation"
FABRIC_REDIRECT_URI = os.getenv(
    "FABRIC_REDIRECT_URI",
    "http://localhost:8000/api/fabric/callback",
)


def _fabric_msal_application():
    """Construit le client MSAL adapté au type d'application Entra."""
    client_id = os.getenv("FABRIC_CLIENT_ID")
    tenant_id = os.getenv("FABRIC_TENANT_ID", "organizations")
    client_secret = os.getenv("FABRIC_CLIENT_SECRET")
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    if client_secret:
        return msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority,
        )
    return msal.PublicClientApplication(
        client_id=client_id,
        authority=authority,
    )

# ============================================
# Modèles Pydantic
# ============================================


class ContractReviewRequest(BaseModel):
    """Revue d'un contrat proposé."""
    contract_path: str
    reviewer: str
    comment: Optional[str] = None


class PipelineRequest(BaseModel):
    """Demande d'exécution du pipeline."""
    file_id: str
    contract_path: Optional[str] = ""
    dataset_name: Optional[str] = None
    publish_to_fabric: bool = False
    drop_duplicates: bool = True
    enrichments: List[Dict[str, Any]] = Field(default_factory=list)


def _archive_name(filename: str, contents: bytes, uploaded_at: datetime) -> str:
    """Construit un nom d’archive lisible et stable dans le temps."""
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    words = [word for word in stem.split() if word]
    readable_name = "_".join(words[:8]) or "dataset"
    timestamp = uploaded_at.strftime("%Y%m%d_%H%M%S")
    suffix = Path(filename).suffix.lower() or ".bin"
    return f"{readable_name}_{timestamp}{suffix}"


def _analysis_file_stem(dataset_name: str) -> str:
    """Construit un nom de fichier sûr pour les rapports d'analyse."""
    stem = Path(dataset_name).stem
    safe_stem = "".join(
        character if character.isalnum() or character in ("-", "_") else "_"
        for character in stem
    ).strip("_")
    return safe_stem or "dataset"


def _save_analysis_reports(
    dataset_name: str,
    analysis: Dict[str, Any],
    analysis_report: str,
) -> Dict[str, str]:
    """Enregistre les versions lisible et structurée du rapport d'analyse."""
    file_stem = _analysis_file_stem(dataset_name)
    text_path = RESULTS_DIR / f"{file_stem}_analysis.txt"
    json_path = RESULTS_DIR / f"{file_stem}_analysis.json"

    text_path.write_text(analysis_report, encoding="utf-8")
    json_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "text": str(text_path),
        "json": str(json_path),
    }


# ============================================
# Endpoints d'Authentification Fabric
# ============================================


@app.get("/api/fabric/auth-status")
async def get_fabric_auth_status():
    """Vérifie l'état d'authentification Fabric."""
    return {
        "authenticated": fabric_auth_state["authenticated"],
        "onelake_authenticated": bool(fabric_auth_state.get("storage_access_token")),
        "workspace_id": fabric_auth_state.get("workspace_id"),
        "message": (
            "Authentifié à Fabric et OneLake ✓"
            if fabric_auth_state["authenticated"] and fabric_auth_state.get("storage_access_token")
            else "Authentifié à Fabric, reconnexion nécessaire pour OneLake"
            if fabric_auth_state["authenticated"]
            else "Non authentifié - Veuillez vous connecter à Fabric"
        )
    }


@app.get("/api/fabric/config")
async def get_fabric_config():
    """Expose uniquement les paramètres non sensibles du callback OAuth."""
    return {
        "redirect_uri": FABRIC_REDIRECT_URI,
        "tenant_configured": bool(os.getenv("FABRIC_TENANT_ID")),
        "client_configured": bool(os.getenv("FABRIC_CLIENT_ID")),
        "workspace_configured": bool(os.getenv("FABRIC_WORKSPACE_ID")),
        "lakehouse_configured": bool(os.getenv("FABRIC_LAKEHOUSE_ID")),
    }


@app.get("/api/fabric/login")
async def fabric_login(file_id: Optional[str] = None, workspace_id: Optional[str] = None):
    """Démarre la connexion Microsoft OAuth pour Fabric."""
    client_id = os.getenv("FABRIC_CLIENT_ID")
    tenant_id = os.getenv("FABRIC_TENANT_ID", "organizations")
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="FABRIC_CLIENT_ID doit être configuré pour la connexion Microsoft.",
        )

    state = secrets.token_urlsafe(32)
    oauth_states[state] = {
        "file_id": file_id,
        "workspace_id": workspace_id,
        "phase": "fabric",
        "created_at": datetime.now().isoformat(),
    }
    application = _fabric_msal_application()
    auth_code_flow = application.initiate_auth_code_flow(
        scopes=FABRIC_SCOPES,
        state=state,
        redirect_uri=FABRIC_REDIRECT_URI,
        prompt="select_account",
    )
    oauth_states[state]["auth_code_flow"] = auth_code_flow
    return JSONResponse({"authorization_url": auth_code_flow["auth_uri"]})


@app.get("/api/fabric/callback")
async def fabric_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Reçoit le retour Microsoft et active l’accès Fabric."""
    callback_state = oauth_states.pop(state, None) if state else None
    if error:
        raise HTTPException(status_code=401, detail=f"Connexion Microsoft refusée : {error}")
    if not callback_state or not code:
        raise HTTPException(status_code=400, detail="Réponse OAuth invalide ou expirée.")

    application = _fabric_msal_application()
    token_result = application.acquire_token_by_auth_code_flow(
        callback_state["auth_code_flow"],
        dict(request.query_params),
        scopes=FABRIC_SCOPES if callback_state.get("phase") == "fabric" else [ONELAKE_SCOPE],
    )
    if "access_token" not in token_result:
        raise HTTPException(
            status_code=401,
            detail=token_result.get("error_description", "Jeton Microsoft non obtenu."),
        )

    if callback_state.get("phase") == "fabric":
        accounts = application.get_accounts()
        storage_result = None
        if accounts:
            storage_result = application.acquire_token_silent(
                [ONELAKE_SCOPE],
                account=accounts[0],
            )
        storage_access_token = storage_result.get("access_token") if storage_result else None

        if not storage_access_token:
            storage_state = secrets.token_urlsafe(32)
            oauth_states[storage_state] = {
                "file_id": callback_state.get("file_id"),
                "workspace_id": callback_state.get("workspace_id"),
                "phase": "storage",
                "fabric_access_token": token_result["access_token"],
                "created_at": datetime.now().isoformat(),
            }
            storage_flow = application.initiate_auth_code_flow(
                scopes=[ONELAKE_SCOPE],
                state=storage_state,
                redirect_uri=FABRIC_REDIRECT_URI,
                prompt="select_account",
            )
            oauth_states[storage_state]["auth_code_flow"] = storage_flow
            return RedirectResponse(url=storage_flow["auth_uri"])

        fabric_access_token = token_result["access_token"]
    else:
        fabric_access_token = callback_state.get("fabric_access_token")
        storage_access_token = token_result["access_token"]
        if not fabric_access_token:
            raise HTTPException(status_code=401, detail="Jeton Fabric manquant, reconnectez-vous.")

    fabric_auth_state.update({
        "authenticated": True,
        "workspace_id": callback_state.get("workspace_id"),
        "user_id": token_result.get("id_token_claims", {}).get("oid"),
        "access_token": fabric_access_token,
        "storage_access_token": storage_access_token,
    })
    configure_fabric_session(
        fabric_access_token,
        callback_state.get("workspace_id"),
        storage_access_token,
    )
    if callback_state.get("workspace_id"):
        os.environ["FABRIC_WORKSPACE_ID"] = callback_state["workspace_id"]

    resume_file_id = callback_state.get("file_id")
    return_url = "/"
    if resume_file_id:
        return_url += f"?resume={resume_file_id}"
    return RedirectResponse(url=return_url)


# ============================================
# Endpoints Upload & Pipeline
# ============================================


@app.post("/api/upload")
async def upload_file(files: List[UploadFile] = File(...)):
    """
    Upload un fichier CSV.
    
    Retourne le chemin du fichier pour l'utiliser dans le pipeline.
    """
    try:
        if not files:
            raise HTTPException(status_code=400, detail="Aucun fichier fourni")

        batch_id = str(uuid.uuid4())
        uploaded_at = datetime.now()
        uploaded_files = []

        for file in files:
            original_name = Path(file.filename or "dataset").name
            suffix = Path(original_name).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=415,
                    detail=f"Format non supporté: {suffix or 'inconnu'}. Formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                )
            file_id = str(uuid.uuid4())
            contents = await file.read()
            if len(contents) > 100 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"{original_name} dépasse 100 MB")
            archive_path = ARCHIVE_DIR / _archive_name(
                original_name,
                contents,
                uploaded_at,
            )
            if archive_path.exists():
                archive_path = ARCHIVE_DIR / f"{archive_path.stem}_{file_id[:8]}.csv"

            file_path = UPLOAD_DIR / f"{file_id}_{original_name}"
            with open(file_path, "wb") as output_file:
                output_file.write(contents)
            with open(archive_path, "wb") as archive_file:
                archive_file.write(contents)

            uploaded_files.append({
                "file_id": file_id,
                "file_name": original_name,
                "file_path": str(file_path),
                "archive_path": str(archive_path),
            })

        # Une session représente le lot analysé ensemble.
        sessions[batch_id] = {
            "file_name": ", ".join(item["file_name"] for item in uploaded_files),
            "file_path": uploaded_files[0]["file_path"],
            "files": uploaded_files,
            "status": "uploaded",
            "created_at": uploaded_at.isoformat(),
            "results": None
        }

        return {
            "file_id": batch_id,
            "files": uploaded_files,
            "message": f"✓ {len(uploaded_files)} fichier(s) uploadé(s) et archivé(s)"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'upload : {str(e)}"
        )


@app.post("/api/pipeline/execute")
async def execute_pipeline(
    pipeline_request: PipelineRequest,
    background_tasks: BackgroundTasks
):
    """
    Exécute le pipeline complet pour un fichier.
    
    Étapes :
    1. Validation de l'authentification Fabric (si publish_to_fabric=True)
    2. Ingestion → Transformation → Publication → Analyse
    3. Retour des résultats avec insights
    """
    try:
        file_id = pipeline_request.file_id
        contract_path = pipeline_request.contract_path
        dataset_name = pipeline_request.dataset_name
        publish_to_fabric = pipeline_request.publish_to_fabric

        # Vérifie que le fichier existe
        if file_id not in sessions:
            raise HTTPException(status_code=404, detail="Fichier non trouvé")

        # Le contrat est facultatif : le schéma peut être inféré.
        if contract_path and not os.path.exists(contract_path):
            raise HTTPException(status_code=404, detail="Contrat non trouvé")

        session = sessions[file_id]
        session["status"] = "executing"

        # Prépare la demande pour l'agent
        dataset_name = dataset_name or Path(session["file_name"]).stem
        file_paths = [item["file_path"] for item in session["files"]]
        file_names = [item["file_name"] for item in session["files"]]
        # Exécute le pipeline en arrière-plan
        background_tasks.add_task(
            run_pipeline_async,
            file_id,
            file_paths,
            dataset_name,
            publish_to_fabric,
            pipeline_request.enrichments,
            pipeline_request.drop_duplicates,
            contract_path or None,
        )

        return {
            "file_id": file_id,
            "status": "executing",
            "message": "✓ Pipeline lancé en arrière-plan",
            "check_status": f"/api/pipeline/status?file_id={file_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        if "session" in locals():
            session["status"] = "error"
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pipeline/status")
async def get_pipeline_status(file_id: str):
    """Récupère le statut d'exécution du pipeline."""
    if file_id not in sessions:
        raise HTTPException(status_code=404, detail="Session non trouvée")

    session = sessions[file_id]
    return {
        "file_id": file_id,
        "file_name": session["file_name"],
        "status": session["status"],
        "created_at": session["created_at"],
        "results": session.get("results")
    }


@app.get("/api/pipeline/results")
async def get_pipeline_results(file_id: str):
    """Récupère les résultats complets du pipeline."""
    if file_id not in sessions:
        raise HTTPException(status_code=404, detail="Session non trouvée")

    session = sessions[file_id]

    if session["status"] != "completed":
        return {
            "status": session["status"],
            "message": f"Pipeline en cours ({session['status']})..."
        }

    return {
        "file_id": file_id,
        "file_name": session["file_name"],
        "status": "completed",
        "results": session.get("results")
    }


# ============================================
# Interface Web Statique
# ============================================


@app.get("/")
async def serve_index():
    """Serve l'interface web."""
    return FileResponse("public/index.html")


@app.get("/fabric-auth")
async def serve_fabric_auth():
    """Serve la page de connexion Fabric à la demande."""
    return FileResponse("public/fabric-auth.html")


@app.get("/health")
async def health_check():
    """Health check de l'API."""
    return {
        "status": "healthy",
        "fabric_enabled": FABRIC_ENABLED,
        "fabric_authenticated": fabric_auth_state["authenticated"],
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# Exécution Asynchrone du Pipeline
# ============================================


def run_pipeline_async(
    file_id: str,
    file_paths: list[str],
    dataset_name: str,
    publish_to_fabric: bool,
    enrichments: list[dict[str, Any]],
    drop_duplicates: bool,
    contract_path: Optional[str] = None,
):
    """Exécute un pipeline tabulaire déterministe dans une tâche de fond."""
    session = sessions[file_id]

    try:
        session["status"] = "processing"

        # Le Policy Engine décide avant tout traitement :
        # seuls les lots entièrement INGEST sont transformés.
        governance = assess_uploads(
            file_paths,
            contract_path,
            dataset_name,
        )
        if not governance["allowed"]:
            session["results"] = {
                "status": "blocked",
                "governance": governance,
                "completed_at": datetime.now().isoformat(),
            }
            session["status"] = "blocked"
            return

        pipeline = process_uploads(
            file_paths=file_paths,
            dataset_name=dataset_name,
            enrichment_operations=enrichments,
            drop_duplicates=drop_duplicates,
        )
        gold_file = pipeline["gold_file"]
        analysis = analyze_gold_data(
            gold_file,
            dataset_name=dataset_name,
        )
        analysis_report = DataAnalyst().generate_analysis_report(analysis)
        analysis_files = _save_analysis_reports(
            dataset_name,
            analysis,
            analysis_report,
        )
        publication = None
        if FABRIC_ENABLED and publish_to_fabric:
            publication = publish_dataset_to_fabric(
                file_path=gold_file,
                dataset_name=dataset_name,
                table_name="data",
                mode="full_refresh",
            )
            if publication.get("status") == "AUTH_REQUIRED":
                raise FabricAuthenticationRequired(publication)
            if publication.get("status") != "PUBLISHED":
                raise RuntimeError(publication.get("message", "Publication Fabric échouée"))
        elif publish_to_fabric and not FABRIC_ENABLED:
            publication = {
                "status": "DISABLED",
                "message": "La publication Fabric est désactivée pour le moment.",
            }
        session["results"] = {
            "status": "success",
            "governance": governance,
            "pipeline": pipeline,
            "analysis": analysis,
            "analysis_report": analysis_report,
            "analysis_files": analysis_files,
            "publication": publication,
            "fabric_published": bool(publication and publication.get("status") == "PUBLISHED"),
            "completed_at": datetime.now().isoformat()
        }

        session["status"] = "completed"

    except FabricAuthenticationRequired as exc:
        session["results"] = {
            "status": "auth_required",
            "fabric_auth_required": True,
            "message": str(exc),
            "details": exc.details,
            "pipeline": locals().get("pipeline"),
            "completed_at": datetime.now().isoformat()
        }
        session["status"] = "awaiting_fabric_auth"

    except Exception as e:
        session["results"] = {
            "status": "error",
            "error_message": str(e),
            "completed_at": datetime.now().isoformat()
        }
        session["status"] = "error"


# ============================================
# Revue des Data Contracts
# ============================================


@app.post("/api/contracts/approve")
async def approve_contract_endpoint(review: ContractReviewRequest):
    """Valide un contrat proposé ; il devient utilisable pour l'ingestion."""
    try:
        path = approve_contract_file(
            review.contract_path,
            review.reviewer,
            review.comment,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ContractStatusError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "VALIDATED", "contract_path": path.as_posix()}


@app.post("/api/contracts/reject")
async def reject_contract_endpoint(review: ContractReviewRequest):
    """Rejette un contrat proposé ; le commentaire sert de motif."""
    try:
        path = reject_contract_file(
            review.contract_path,
            review.reviewer,
            review.comment or "",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ContractStatusError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "REJECTED", "contract_path": path.as_posix()}


# ============================================
# Utilitaires
# ============================================


@app.get("/api/files")
async def list_uploaded_files():
    """Liste les fichiers uploadés."""
    files = []
    for file_id, session in sessions.items():
        files.append({
            "file_id": file_id,
            "file_name": session["file_name"],
            "files": session.get("files", []),
            "status": session["status"],
            "created_at": session["created_at"]
        })
    return {"files": files}


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str):
    """Supprime un fichier et sa session."""
    if file_id not in sessions:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")

    session = sessions[file_id]
    for item in session.get("files", []):
        for key in ("file_path", "archive_path"):
            file_path = Path(item[key])
            if file_path.exists():
                file_path.unlink()

    del sessions[file_id]

    return {"message": "✓ Fichier supprimé"}


@app.get("/api/info")
async def get_api_info():
    """Retourne les infos de l'API."""
    return {
        "name": "Data Engineering Agent API",
        "version": "1.0.0",
        "fabric_enabled": FABRIC_ENABLED,
        "features": [
            "Upload de fichiers CSV",
            "Ingestion Bronze/Silver/Gold",
            "Analyse IA intelligente",
            "Génération d'insights"
        ],
        "endpoints": {
            "upload": "POST /api/upload",
            "pipeline": "POST /api/pipeline/execute",
            "status": "GET /api/pipeline/status",
            "results": "GET /api/pipeline/results"
        }
    }


if __name__ == "__main__":
    import uvicorn

    print("""
╔════════════════════════════════════════════════════════════════╗
║  Data Engineering Agent - API Server                           ║
║  Démarrage du serveur...                                       ║
╚════════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
