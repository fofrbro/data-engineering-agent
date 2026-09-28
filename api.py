"""
API REST et interface web de l'agent Data Engineering.

- Upload de fichiers (ou d'une archive ZIP) ;
- workflow PLAN -> VALIDATE -> EXECUTE -> VERIFY -> AUDIT ;
- revue des contrats, relecture sémantique, analyse des données.

Les tables Gold et l'audit sont préparés pour Fabric dans
data/fabric_export/ ; le dépôt dans le Lakehouse et les notebooks restent
des opérations manuelles (voir fabric/README.md).

Mode démo publique (DEMO_MODE=true, voir src/demo) : un espace isolé et
temporaire par visiteur, fichiers d'exemple seulement, quotas journaliers.
"""

from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os
import uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from src.demo.quota import EXECUTION, PLAN, DailyQuota, QuotaExceeded
from src.demo.samples import SAMPLES, SAMPLES_BY_KEY
from src.demo.workspace import (
    DemoFull,
    VisitorRegistry,
    Workspace,
    is_visitor_id,
    new_visitor_id,
)
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

# ============================================
# Configuration
# ============================================

app = FastAPI(
    title="Data Engineering Agent API",
    description="Agent Data Engineering : contrat, qualité, Bronze/Silver/Gold, Fabric, Power BI",
    version="1.0.0"
)

# Pas de CORS : l'interface est servie par cette même application ; une
# autre page web ouverte dans le navigateur ne peut pas lire l'API.

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


# Espace de travail local : les dossiers du projet.
UPLOAD_DIR = Path("uploads")
ARCHIVE_DIR = Path("data/archive")
UPLOAD_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_WORKSPACE = Workspace(
    upload_dir=UPLOAD_DIR,
    archive_dir=ARCHIVE_DIR,
    service=WorkflowService(llm_client=llm_client),
    llm_client=llm_client,
)

# Démo publique.
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
DEMO_COOKIE = "demo_visitor"
DEMO_TTL_SECONDS = _env_int("DEMO_TTL_MINUTES", 120) * 60
DEMO_SECURE_COOKIE = os.getenv("DEMO_SECURE_COOKIE", "true").lower() == "true"
DEMO_LIMITS = {
    PLAN: _env_int("DEMO_PLANS_PER_DAY", 30),
    EXECUTION: _env_int("DEMO_EXECUTIONS_PER_DAY", 10),
    "llm_call": _env_int("DEMO_LLM_CALLS_PER_DAY", 20),
}
DEMO_OVERALL_LIMITS = {"llm_call": _env_int("DEMO_LLM_CALLS_OVERALL_PER_DAY", 300)}

demo_registry = (
    VisitorRegistry(
        root=os.getenv("DEMO_ROOT", "demo_workspaces"),
        quota=DailyQuota(DEMO_LIMITS, DEMO_OVERALL_LIMITS),
        llm_client=llm_client,
        ttl_seconds=DEMO_TTL_SECONDS,
        max_visitors=_env_int("DEMO_MAX_VISITORS", 50),
    )
    if DEMO_MODE
    else None
)


def get_workspace(request: Request, response: Response) -> Workspace:
    """
    Espace de travail de la requête : le vôtre hors démo ; en démo, celui
    du visiteur, identifié par un cookie aléatoire (créé au besoin).
    """

    if demo_registry is None:
        return LOCAL_WORKSPACE

    visitor = request.cookies.get(DEMO_COOKIE)

    if not is_visitor_id(visitor):
        visitor = new_visitor_id()

    response.set_cookie(
        DEMO_COOKIE,
        visitor,
        max_age=DEMO_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=DEMO_SECURE_COOKIE,
    )

    try:
        return demo_registry.get(visitor)
    except DemoFull as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _consume(workspace: Workspace, action: str) -> None:
    try:
        workspace.consume(action)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))


def _refuse_in_demo(feature: str) -> None:
    if DEMO_MODE:
        raise HTTPException(
            status_code=403,
            detail=f"{feature} n'est pas disponible dans la démo publique.",
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


def _store_file(
    workspace: Workspace,
    original_name: str,
    contents: bytes,
    uploaded_at: datetime,
) -> list[dict]:
    """
    Archive un fichier reçu et écrit ses fichiers de données dans l'espace :
    une archive ZIP est archivée telle quelle et ses fichiers de données
    rejoignent le lot comme s'ils avaient été uploadés.
    """

    suffix = Path(original_name).suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS | {".zip"}:
        raise HTTPException(
            status_code=415,
            detail=f"Format non supporté: {suffix or 'inconnu'}. Formats: {', '.join(sorted(SUPPORTED_EXTENSIONS | {'.zip'}))}",
        )

    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{original_name} dépasse 100 MB")

    file_id = str(uuid.uuid4())
    archive_path = workspace.archive_dir / _archive_name(original_name, contents, uploaded_at)

    if archive_path.exists():
        archive_path = workspace.archive_dir / f"{archive_path.stem}_{file_id[:8]}{archive_path.suffix}"

    if suffix == ".zip":
        try:
            members = extract_data_files(contents, SUPPORTED_EXTENSIONS)
        except ArchiveError as exc:
            raise HTTPException(status_code=400, detail=f"{original_name} : {exc}")
    else:
        members = [(original_name, contents)]

    archive_path.write_bytes(contents)
    stored = []

    for member_name, member_contents in members:
        member_id = file_id if suffix != ".zip" else str(uuid.uuid4())
        file_path = workspace.upload_dir / f"{member_id}_{member_name}"
        file_path.write_bytes(member_contents)
        stored.append({
            "file_id": member_id,
            "file_name": member_name,
            "file_path": str(file_path),
            "archive_path": str(archive_path),
            "source_archive": original_name if suffix == ".zip" else None,
        })

    return stored


def _register_batch(workspace: Workspace, uploaded_files: list[dict], uploaded_at: datetime) -> dict:
    """Une session représente le lot analysé ensemble."""

    batch_id = str(uuid.uuid4())
    workspace.sessions[batch_id] = {
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


# ============================================
# Endpoints Upload & Pipeline
# ============================================


@app.post("/api/upload")
async def upload_file(
    files: List[UploadFile] = File(...),
    workspace: Workspace = Depends(get_workspace),
):
    """Upload d'un ou plusieurs fichiers, ou d'une archive ZIP."""

    _refuse_in_demo("L'upload de fichiers")

    try:
        if not files:
            raise HTTPException(status_code=400, detail="Aucun fichier fourni")

        uploaded_at = datetime.now()
        uploaded_files = []

        for file in files:
            original_name = Path(file.filename or "dataset").name
            uploaded_files += _store_file(workspace, original_name, await file.read(), uploaded_at)

        return _register_batch(workspace, uploaded_files, uploaded_at)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'upload : {str(e)}"
        )


@app.get("/api/config")
async def get_config(workspace: Workspace = Depends(get_workspace)):
    """Mode de l'application et, en démo, fichiers d'exemple et quotas restants."""

    if not DEMO_MODE:
        return {"demo": False}

    return {
        "demo": True,
        "samples": [sample.to_dict() for sample in SAMPLES],
        "ttl_minutes": DEMO_TTL_SECONDS // 60,
        "remaining": workspace.quota.remaining(workspace.visitor_id),
        "llm_available": workspace.llm_client is not None,
    }


@app.post("/api/demo/samples/{key}")
async def load_sample(key: str, workspace: Workspace = Depends(get_workspace)):
    """Charge un fichier d'exemple dans l'espace, comme s'il avait été uploadé."""

    sample = SAMPLES_BY_KEY.get(key)

    if sample is None:
        raise HTTPException(status_code=404, detail=f"Exemple inconnu : {key}")

    uploaded_at = datetime.now()
    stored = _store_file(workspace, sample.file, sample.path.read_bytes(), uploaded_at)

    return _register_batch(workspace, stored, uploaded_at)


# ============================================
# Interface Web Statique
# ============================================


@app.get("/")
async def serve_index():
    """Serve l'interface web."""
    return FileResponse("public/index.html")


@app.get("/health")
async def health_check():
    """Health check de l'API."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# Workflow agent : PLAN -> VALIDATE -> EXECUTE
# ============================================


def _workflow_call(action):
    """Traduit les erreurs du workflow en réponses HTTP."""
    try:
        return action()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (WorkflowError, DashboardReviewError, ContractStatusError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/workflow/plan")
async def create_workflow_plan(
    request: WorkflowPlanRequest,
    workspace: Workspace = Depends(get_workspace),
):
    """
    PLAN : analyse le ou les fichiers du lot et propose, pour chaque
    dataset détecté, contrat, pipeline, KPI et TBO.
    """
    if request.file_id not in workspace.sessions:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")

    _consume(workspace, PLAN)
    files = workspace.sessions[request.file_id]["files"]

    # Les fichiers stockés sont préfixés par leur identifiant d'upload :
    # les datasets sont nommés d'après les noms d'origine.
    plans = _workflow_call(
        lambda: workspace.service.create_plans(
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
async def ask_workflow(
    request: WorkflowAskRequest,
    workspace: Workspace = Depends(get_workspace),
):
    """
    Le LLM traduit la demande en intention (planifier un fichier ou
    expliquer un run). Il ne peut ni valider ni exécuter.
    """
    if workspace.llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY non configurée : la demande en langage naturel est indisponible.",
        )

    file_path = None
    dataset = None

    if request.file_id:
        if request.file_id not in workspace.sessions:
            raise HTTPException(status_code=404, detail="Fichier non trouvé")
        files = workspace.sessions[request.file_id]["files"]
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
                workspace.llm_client,
                request.message,
                workspace.service,
                file_path=file_path,
                dataset=dataset,
            )
        )
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except RequestInterpretationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/workflow/{plan_id}")
async def get_workflow_plan(plan_id: str, workspace: Workspace = Depends(get_workspace)):
    return _workflow_call(lambda: workspace.service.view(plan_id))


@app.post("/api/workflow/{plan_id}/approve-contract")
async def approve_workflow_contract(
    plan_id: str,
    review: WorkflowReviewRequest,
    workspace: Workspace = Depends(get_workspace),
):
    return _workflow_call(
        lambda: workspace.service.approve_contract(plan_id, review.reviewer, review.comment)
    )


@app.post("/api/workflow/{plan_id}/column-names")
async def review_workflow_column_names(
    plan_id: str,
    review: ColumnNamesRequest,
    workspace: Workspace = Depends(get_workspace),
):
    """Valide les noms de colonnes des fichiers sans en-tête, ou les remplace."""
    return _workflow_call(
        lambda: workspace.service.review_column_names(
            plan_id, review.reviewer, review.names, review.dataset, review.comment,
        )
    )


@app.post("/api/workflow/{plan_id}/semantic-review")
async def review_workflow_semantics(plan_id: str, workspace: Workspace = Depends(get_workspace)):
    """
    Le LLM relit l'interprétation des colonnes et propose des
    corrections, vérifiées par le code ; rien n'est appliqué.
    """
    return _workflow_call(lambda: workspace.service.review_semantics(plan_id))


@app.post("/api/workflow/{plan_id}/semantic-review/decide")
async def decide_workflow_semantics(
    plan_id: str,
    decision: SemanticDecisionRequest,
    workspace: Workspace = Depends(get_workspace),
):
    return _workflow_call(
        lambda: workspace.service.decide_semantics(
            plan_id, decision.reviewer, decision.accepted, decision.comment,
        )
    )


@app.post("/api/workflow/{plan_id}/approve-transformations")
async def approve_workflow_transformations(
    plan_id: str,
    review: WorkflowReviewRequest,
    workspace: Workspace = Depends(get_workspace),
):
    return _workflow_call(
        lambda: workspace.service.approve_transformations(
            plan_id, review.reviewer, review.comment,
        )
    )


@app.post("/api/workflow/{plan_id}/dashboard")
async def review_workflow_dashboard(
    plan_id: str,
    review: DashboardReviewRequest,
    workspace: Workspace = Depends(get_workspace),
):
    return _workflow_call(
        lambda: workspace.service.review_dashboard(
            plan_id, review.action, review.reviewer, review.comment, review.changes,
        )
    )


@app.post("/api/workflow/{plan_id}/execute")
async def execute_workflow_plan(plan_id: str, workspace: Workspace = Depends(get_workspace)):
    """EXECUTE -> VERIFY -> AUDIT ; refusé tant que le contrat n'est pas validé."""
    _workflow_call(lambda: workspace.service.get(plan_id))
    _consume(workspace, EXECUTION)
    return _workflow_call(lambda: workspace.service.execute(plan_id))


# ============================================
# Revue des Data Contracts
# ============================================


@app.post("/api/contracts/approve")
async def approve_contract_endpoint(review: ContractReviewRequest):
    """Valide un contrat proposé ; il devient utilisable pour l'ingestion."""
    _refuse_in_demo("La revue directe de contrats")

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
    _refuse_in_demo("La revue directe de contrats")

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
async def list_uploaded_files(workspace: Workspace = Depends(get_workspace)):
    """Liste les fichiers uploadés."""
    files = []
    for file_id, session in workspace.sessions.items():
        files.append({
            "file_id": file_id,
            "file_name": session["file_name"],
            "files": session.get("files", []),
            "status": session["status"],
            "created_at": session["created_at"]
        })
    return {"files": files}


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str, workspace: Workspace = Depends(get_workspace)):
    """Supprime un fichier et sa session."""
    if file_id not in workspace.sessions:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")

    session = workspace.sessions[file_id]
    for item in session.get("files", []):
        for key in ("file_path", "archive_path"):
            file_path = Path(item[key])
            if file_path.exists():
                file_path.unlink()

    del workspace.sessions[file_id]

    return {"message": "✓ Fichier supprimé"}


@app.get("/api/info")
async def get_api_info():
    """Retourne les infos de l'API."""
    return {
        "name": "Data Engineering Agent API",
        "version": "1.0.0",
        "features": [
            "Upload de fichiers tabulaires ou d'une archive ZIP",
            "Fichiers sans en-tête : noms de colonnes proposés puis validés",
            "Plan agent : contrat, qualité, pipeline, KPI, tableau de bord",
            "Validations explicites avant exécution",
            "Exécution Bronze/Silver/Gold vérifiée et auditée",
            "Relecture sémantique par LLM, suggestions vérifiées",
            "Analyse des données avec synthèse LLM vérifiée",
            "Export pour Fabric (tables Gold et audit)"
        ],
        "endpoints": {
            "upload": "POST /api/upload",
            "plan": "POST /api/workflow/plan",
            "ask": "POST /api/workflow/ask",
            "plan_view": "GET /api/workflow/{plan_id}",
            "column_names": "POST /api/workflow/{plan_id}/column-names",
            "semantic_review": "POST /api/workflow/{plan_id}/semantic-review",
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
        host="127.0.0.1",
        port=8000,
        reload=True
    )
