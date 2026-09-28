"""
API REST pour l'Agent Data Engineering.

Expose l'agent via une API FastAPI avec endpoints pour :
- Upload de fichiers CSV
- Exécution du pipeline
- Récupération des résultats
- Authentification Fabric interactif
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os
import uuid
from datetime import datetime
from pathlib import Path
import asyncio
import threading
import secrets
import msal
from dotenv import load_dotenv

load_dotenv()

from src.discovery.format_detector import SUPPORTED_EXTENSIONS
from src.discovery.archive import ArchiveError, extract_data_files
from src.semantic.column_naming import parse_column_names
from src.contract.contract_lifecycle import (
    ContractStatusError,
    approve_contract_file,
    reject_contract_file,
)
from src.recommendation.dashboard_review import DashboardReviewError
from src.workflow.agent_workflow import WorkflowError
from src.workflow.workflow_service import WorkflowService
from src.contract.contract_generator import dataset_name_from_path
from src.llm import client as llm_client
from src.workflow.request_interpreter import (
    RequestInterpretationError,
    handle_request,
)
from src.tools.fabric_connector import configure_fabric_session

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
UPLOAD_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

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


class WorkflowPlanRequest(BaseModel):
    """Création d'un plan agent pour un fichier uploadé."""
    file_id: str
    contract_path: Optional[str] = None
    dataset_name: Optional[str] = None
    enrichments: List[Dict[str, Any]] = Field(default_factory=list)
    # Noms des colonnes des fichiers sans en-tête, séparés par des virgules.
    column_names: Optional[str] = None
    # Instructions en langage naturel, traduites par le LLM.
    instructions: Optional[str] = None


class WorkflowAskRequest(BaseModel):
    """Demande en langage naturel, éventuellement liée à un fichier uploadé."""
    message: str
    file_id: Optional[str] = None


class WorkflowReviewRequest(BaseModel):
    """Validation d'un élément du plan par un relecteur."""
    reviewer: str
    comment: Optional[str] = None


class DashboardReviewRequest(WorkflowReviewRequest):
    """Revue du tableau de bord : APPROVE, MODIFY ou REJECT."""
    action: str
    changes: Dict[str, Any] = Field(default_factory=dict)


class ColumnNamesRequest(WorkflowReviewRequest):
    """Validation des noms de colonnes, éventuellement modifiés."""
    names: Optional[List[str]] = None
    dataset: Optional[str] = None


class SemanticDecisionRequest(WorkflowReviewRequest):
    """Suggestions sémantiques acceptées ; les autres sont rejetées."""
    accepted: List[str] = Field(default_factory=list)


def _archive_name(filename: str, contents: bytes, uploaded_at: datetime) -> str:
    """Construit un nom d’archive lisible et stable dans le temps."""
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    words = [word for word in stem.split() if word]
    readable_name = "_".join(words[:8]) or "dataset"
    timestamp = uploaded_at.strftime("%Y%m%d_%H%M%S")
    suffix = Path(filename).suffix.lower() or ".bin"
    return f"{readable_name}_{timestamp}{suffix}"


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
            if suffix not in SUPPORTED_EXTENSIONS | {".zip"}:
                raise HTTPException(
                    status_code=415,
                    detail=f"Format non supporté: {suffix or 'inconnu'}. Formats: {', '.join(sorted(SUPPORTED_EXTENSIONS | {'.zip'}))}",
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
                archive_path = ARCHIVE_DIR / f"{archive_path.stem}_{file_id[:8]}{archive_path.suffix}"

            # Une archive ZIP est archivée telle quelle ; ses fichiers de
            # données rejoignent le lot comme s'ils avaient été uploadés.
            if suffix == ".zip":
                try:
                    members = extract_data_files(contents, SUPPORTED_EXTENSIONS)
                except ArchiveError as exc:
                    raise HTTPException(status_code=400, detail=f"{original_name} : {exc}")
            else:
                members = [(original_name, contents)]

            with open(archive_path, "wb") as archive_file:
                archive_file.write(contents)

            for member_name, member_contents in members:
                member_id = file_id if suffix != ".zip" else str(uuid.uuid4())
                file_path = UPLOAD_DIR / f"{member_id}_{member_name}"
                with open(file_path, "wb") as output_file:
                    output_file.write(member_contents)

                uploaded_files.append({
                    "file_id": member_id,
                    "file_name": member_name,
                    "file_path": str(file_path),
                    "archive_path": str(archive_path),
                    "source_archive": original_name if suffix == ".zip" else None,
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
# Workflow agent : PLAN -> VALIDATE -> EXECUTE
# ============================================

workflow_service = WorkflowService(llm_client=llm_client)


def _workflow_call(action):
    """Traduit les erreurs du workflow en réponses HTTP."""
    try:
        return action()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (WorkflowError, DashboardReviewError, ContractStatusError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/workflow/plan")
async def create_workflow_plan(request: WorkflowPlanRequest):
    """
    PLAN : analyse le ou les fichiers du lot et propose, pour chaque
    dataset détecté, contrat, pipeline, KPI et TBO.
    """
    if request.file_id not in sessions:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")

    files = sessions[request.file_id]["files"]

    # Les fichiers stockés sont préfixés par leur identifiant d'upload :
    # les datasets sont nommés d'après les noms d'origine.
    plans = _workflow_call(
        lambda: workflow_service.create_plans(
            [item["file_path"] for item in files],
            request.contract_path,
            request.dataset_name,
            request.enrichments,
            {item["file_path"]: item["file_name"] for item in files},
            parse_column_names(request.column_names) or None,
            request.instructions,
        )
    )

    return {"plans": plans}


@app.post("/api/workflow/ask")
async def ask_workflow(request: WorkflowAskRequest):
    """
    Le LLM traduit la demande en intention (planifier un fichier ou
    expliquer un run). Il ne peut ni valider ni exécuter.
    """
    file_path = None
    dataset = None

    if request.file_id:
        if request.file_id not in sessions:
            raise HTTPException(status_code=404, detail="Fichier non trouvé")
        files = sessions[request.file_id]["files"]
        if len(files) != 1:
            raise HTTPException(
                status_code=400,
                detail="Le workflow agent traite un fichier à la fois.",
            )
        file_path = files[0]["file_path"]
        dataset = dataset_name_from_path(files[0]["file_name"])

    try:
        return _workflow_call(
            lambda: handle_request(
                llm_client,
                request.message,
                workflow_service,
                file_path=file_path,
                dataset=dataset,
            )
        )
    except RequestInterpretationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/workflow/{plan_id}")
async def get_workflow_plan(plan_id: str):
    return _workflow_call(lambda: workflow_service.view(plan_id))


@app.post("/api/workflow/{plan_id}/approve-contract")
async def approve_workflow_contract(plan_id: str, review: WorkflowReviewRequest):
    return _workflow_call(
        lambda: workflow_service.approve_contract(plan_id, review.reviewer, review.comment)
    )


@app.post("/api/workflow/{plan_id}/column-names")
async def review_workflow_column_names(plan_id: str, review: ColumnNamesRequest):
    """Valide les noms de colonnes des fichiers sans en-tête, ou les remplace."""
    return _workflow_call(
        lambda: workflow_service.review_column_names(
            plan_id, review.reviewer, review.names, review.dataset, review.comment,
        )
    )


@app.post("/api/workflow/{plan_id}/semantic-review")
async def review_workflow_semantics(plan_id: str):
    """
    Le LLM relit l'interprétation des colonnes et propose des
    corrections, vérifiées par le code ; rien n'est appliqué.
    """
    return _workflow_call(lambda: workflow_service.review_semantics(plan_id))


@app.post("/api/workflow/{plan_id}/semantic-review/decide")
async def decide_workflow_semantics(plan_id: str, decision: SemanticDecisionRequest):
    return _workflow_call(
        lambda: workflow_service.decide_semantics(
            plan_id, decision.reviewer, decision.accepted, decision.comment,
        )
    )


@app.post("/api/workflow/{plan_id}/approve-transformations")
async def approve_workflow_transformations(plan_id: str, review: WorkflowReviewRequest):
    return _workflow_call(
        lambda: workflow_service.approve_transformations(
            plan_id, review.reviewer, review.comment,
        )
    )


@app.post("/api/workflow/{plan_id}/dashboard")
async def review_workflow_dashboard(plan_id: str, review: DashboardReviewRequest):
    return _workflow_call(
        lambda: workflow_service.review_dashboard(
            plan_id, review.action, review.reviewer, review.comment, review.changes,
        )
    )


@app.post("/api/workflow/{plan_id}/execute")
async def execute_workflow_plan(plan_id: str):
    """EXECUTE -> VERIFY -> AUDIT ; refusé tant que le contrat n'est pas validé."""
    return _workflow_call(lambda: workflow_service.execute(plan_id))


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
            "Upload de fichiers tabulaires",
            "Plan agent : contrat, qualité, pipeline, KPI, tableau de bord",
            "Validations explicites avant exécution",
            "Exécution Bronze/Silver/Gold vérifiée et auditée",
            "Analyse Data Analyst"
        ],
        "endpoints": {
            "upload": "POST /api/upload",
            "plan": "POST /api/workflow/plan",
            "ask": "POST /api/workflow/ask",
            "plan_view": "GET /api/workflow/{plan_id}",
            "approve_contract": "POST /api/workflow/{plan_id}/approve-contract",
            "approve_transformations": "POST /api/workflow/{plan_id}/approve-transformations",
            "dashboard": "POST /api/workflow/{plan_id}/dashboard",
            "execute": "POST /api/workflow/{plan_id}/execute"
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
