"""
API REST et interface web de l'agent Data Engineering.

- Upload de fichiers (ou d'une archive ZIP) ;
- workflow PLAN -> VALIDATE -> EXECUTE -> VERIFY -> AUDIT ;
- revue des contrats, relecture sémantique, analyse des données.

Les tables Gold et l'audit sont préparés pour Fabric dans
data/fabric_export/ ; le dépôt dans le Lakehouse et les notebooks restent
des opérations manuelles (voir fabric/README.md).
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import os
import uuid
from datetime import datetime
from pathlib import Path
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

# Dossiers de travail
UPLOAD_DIR = Path("uploads")
ARCHIVE_DIR = Path("data/archive")
UPLOAD_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# Lots uploadés, en mémoire.
sessions: Dict[str, Dict[str, Any]] = {}

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
