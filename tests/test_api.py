"""
Routes de l'API, appelées directement (sans client HTTP) avec un espace
de travail temporaire : uploads, archives, contrats, lac et audit sont
isolés, et le LLM est désactivé.
"""

import asyncio
import io
import json

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

import api
from src.demo.workspace import Workspace
from src.workflow.workflow_service import WorkflowService


def make_workspace(root):
    (root / "uploads").mkdir(parents=True)
    (root / "archive").mkdir()
    return Workspace(
        upload_dir=root / "uploads",
        archive_dir=root / "archive",
        service=WorkflowService(
            contracts_dir=root / "contracts",
            output_root=root / "lake",
            audit_path=root / "runs.jsonl",
            fabric_export_root=root / "fabric_export",
            results_dir=root / "results",
        ),
        llm_client=None,
    )


@pytest.fixture
def ws(tmp_path):
    return make_workspace(tmp_path)


def run(coroutine):
    return asyncio.run(coroutine)


def upload(ws, *paths):
    files = [
        UploadFile(file=io.BytesIO(open(path, "rb").read()), filename=path.split("/")[-1])
        for path in paths
    ]
    return run(api.upload_file(files, workspace=ws))


def status_of(coroutine) -> tuple[int, str]:
    with pytest.raises(HTTPException) as error:
        run(coroutine)
    return error.value.status_code, error.value.detail


def test_health():
    assert run(api.health_check())["status"] == "healthy"


def test_unsupported_format_is_refused(ws):
    files = [UploadFile(file=io.BytesIO(b"x"), filename="notes.pdf")]

    code, detail = status_of(api.upload_file(files, workspace=ws))

    assert code == 415
    assert ".zip" in detail


def test_unreadable_zip_is_refused_and_not_archived(ws):
    files = [UploadFile(file=io.BytesIO(b"not a zip"), filename="orders.zip")]

    assert status_of(api.upload_file(files, workspace=ws)) == (400, "orders.zip : Archive ZIP illisible.")
    assert list(ws.archive_dir.iterdir()) == []


def test_upload_then_plan_names_the_dataset_after_the_original_file(ws):
    uploaded = upload(ws, "data/samples/ventes_2025_2026.csv")

    plans = run(api.create_workflow_plan(
        api.WorkflowPlanRequest(file_id=uploaded["file_id"]), workspace=ws,
    ))["plans"]

    assert [plan["dataset"] for plan in plans] == ["ventes_2025_2026"]
    assert plans[0]["contract_status"] == "PROPOSED"


def test_zip_export_goes_from_upload_to_execution(ws):
    uploaded = upload(ws, "data/samples/orders.zip")

    assert [item["file_name"] for item in uploaded["files"]] == ["2019.csv", "2020.csv", "2021.csv"]
    assert {item["source_archive"] for item in uploaded["files"]} == {"orders.zip"}

    plans = run(api.create_workflow_plan(api.WorkflowPlanRequest(
        file_id=uploaded["file_id"],
        dataset_name="commandes",
        column_names="numero_commande, ligne, date, client, e_mail, article, quantite, prix_unitaire, taxe",
    ), workspace=ws))["plans"]
    plan_id = plans[0]["plan_id"]
    review = api.WorkflowReviewRequest(reviewer="cheikhou")

    # Les noms fournis doivent être validés avant le contrat.
    assert plans[0]["column_naming"]["source"] == "USER"
    assert status_of(api.approve_workflow_contract(plan_id, review, workspace=ws))[0] == 400

    run(api.review_workflow_column_names(plan_id, api.ColumnNamesRequest(reviewer="cheikhou"), workspace=ws))
    run(api.approve_workflow_contract(plan_id, review, workspace=ws))
    result = run(api.execute_workflow_plan(plan_id, workspace=ws))

    assert result["final_status"] == "SUCCESS"
    assert sum(item["decision"] == "INGEST" for item in result["file_results"]) == 3
    revenue = next(k["value"] for k in result["analysis"]["kpis"] if k["name"] == "Revenue")
    assert revenue == pytest.approx(20928022.4307)
    json.dumps(result, default=str)


def test_unknown_plan_is_a_404(ws):
    assert status_of(api.get_workflow_plan("absent", workspace=ws))[0] == 404
    assert status_of(api.execute_workflow_plan("absent", workspace=ws))[0] == 404


def test_natural_language_request_without_llm_is_a_503(ws):
    code, detail = status_of(api.ask_workflow(api.WorkflowAskRequest(message="prépare ce fichier"), workspace=ws))

    assert code == 503
    assert "OPENAI_API_KEY" in detail


def test_deleting_an_upload_removes_its_files(ws):
    uploaded = upload(ws, "data/samples/ventes_rejet.csv")

    run(api.delete_file(uploaded["file_id"], workspace=ws))

    assert list(ws.upload_dir.iterdir()) == []
    assert status_of(api.delete_file(uploaded["file_id"], workspace=ws))[0] == 404
