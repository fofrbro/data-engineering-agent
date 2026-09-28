"""Mode démo publique : isolation des visiteurs, quotas, fichiers d'exemple."""

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.datastructures import UploadFile
from starlette.requests import Request

import api
from src.demo.quota import EXECUTION, LLM_CALL, PLAN, DailyQuota, LimitedLLMClient, QuotaExceeded
from src.demo.samples import SAMPLES
from src.demo.workspace import DemoFull, VisitorRegistry, new_visitor_id


def run(coroutine):
    return asyncio.run(coroutine)


def status_of(coroutine) -> tuple[int, str]:
    with pytest.raises(HTTPException) as error:
        run(coroutine)
    return error.value.status_code, error.value.detail


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def registry(tmp_path, clock):
    quota = DailyQuota({PLAN: 3, EXECUTION: 1, LLM_CALL: 2}, {LLM_CALL: 3})
    return VisitorRegistry(tmp_path / "demo", quota, ttl_seconds=60, max_visitors=2, clock=clock)


@pytest.fixture
def demo(registry, monkeypatch):
    monkeypatch.setattr(api, "DEMO_MODE", True)
    monkeypatch.setattr(api, "demo_registry", registry)
    return registry


# --- Quotas --------------------------------------------------------------


def test_quota_per_visitor_and_overall():
    days = iter(["2026-09-28"] * 6 + ["2026-09-29"] * 2)
    quota = DailyQuota({LLM_CALL: 2}, {LLM_CALL: 3}, today=lambda: next(days))

    quota.consume("a", LLM_CALL)
    quota.consume("a", LLM_CALL)
    with pytest.raises(QuotaExceeded, match="2 appels au LLM par jour"):
        quota.consume("a", LLM_CALL)
    quota.consume("b", LLM_CALL)
    with pytest.raises(QuotaExceeded, match="réessayez demain"):
        quota.consume("c", LLM_CALL)

    # Le lendemain, les compteurs repartent de zéro.
    quota.consume("a", LLM_CALL)
    assert quota.remaining("a") == {LLM_CALL: 1}


def test_llm_calls_consume_the_quota():
    calls = []
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: calls.append(kw) or "ok"))
    limited = LimitedLLMClient(client, DailyQuota({LLM_CALL: 1}), "a")

    assert limited.responses.create(model="m") == "ok"
    with pytest.raises(QuotaExceeded):
        limited.responses.create(model="m")
    assert len(calls) == 1


# --- Espaces des visiteurs -----------------------------------------------


def test_visitors_are_isolated(registry):
    first, second = registry.get(new_visitor_id()), registry.get(new_visitor_id())

    assert first.upload_dir != second.upload_dir
    assert first.service.contracts_dir != second.service.contracts_dir
    assert first.sessions is not second.sessions
    assert str(first.service.audit_path).startswith(str(registry.root))


def test_same_visitor_gets_the_same_workspace(registry):
    visitor = new_visitor_id()

    assert registry.get(visitor) is registry.get(visitor)


def test_inactive_workspaces_are_erased(registry, clock):
    visitor = new_visitor_id()
    folder = registry.get(visitor).upload_dir.parent
    (folder / "uploads" / "f.csv").write_text("a\n1\n")

    clock.now = 61
    registry.get(new_visitor_id())

    assert not folder.exists()
    assert registry.active == 1


def test_visitor_ids_that_could_escape_the_root_are_refused(registry):
    for bad in ("../../etc", "abc", "", None, "G" * 32):
        with pytest.raises(ValueError):
            registry.get(bad)


def test_simultaneous_visitors_are_capped(registry):
    for _ in range(2):
        registry.get(new_visitor_id()).sessions["lot"] = {}

    with pytest.raises(DemoFull):
        registry.get(new_visitor_id())


def test_empty_workspaces_make_room_for_new_visitors(registry, clock):
    # Deux requêtes sans cookie (robot) ne bloquent pas la démo.
    busy = registry.get(new_visitor_id())
    busy.sessions["lot"] = {}
    clock.now = 1
    idle = registry.get(new_visitor_id())
    clock.now = 2

    newcomer = registry.get(new_visitor_id())

    assert registry.active == 2
    assert not idle.upload_dir.exists()
    assert busy.upload_dir.exists() and newcomer.upload_dir.exists()


def test_startup_only_erases_visitor_folders(tmp_path):
    root = tmp_path / "demo"
    (root / "a").mkdir(parents=True)
    kept = root / "contracts"
    kept.mkdir()
    old_visitor = root / new_visitor_id()
    old_visitor.mkdir()

    VisitorRegistry(root, DailyQuota({}))

    assert kept.exists() and (root / "a").exists()
    assert not old_visitor.exists()


# --- API en mode démo ----------------------------------------------------


def request_with_cookie(value=None):
    headers = [(b"cookie", f"{api.DEMO_COOKIE}={value}".encode())] if value else []
    return Request({"type": "http", "headers": headers})


def test_cookie_identifies_the_visitor(demo):
    response = Response()
    first = api.get_workspace(request_with_cookie(), response)
    cookie = response.headers["set-cookie"]
    visitor = cookie.split("=")[1].split(";")[0]

    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert api.get_workspace(request_with_cookie(visitor), Response()) is first
    # Un cookie falsifié ne donne jamais accès à un autre dossier.
    assert api.get_workspace(request_with_cookie("../x"), Response()) is not first


def test_uploads_and_direct_contract_review_are_refused_in_demo(demo):
    ws = demo.get(new_visitor_id())
    files = [UploadFile(file=io.BytesIO(b"a\n1\n"), filename="a.csv")]
    review = api.ContractReviewRequest(contract_path="data/contracts/sales.json", reviewer="x")

    assert status_of(api.upload_file(files, workspace=ws))[0] == 403
    assert status_of(api.approve_contract_endpoint(review))[0] == 403
    assert status_of(api.reject_contract_endpoint(review))[0] == 403


def test_config_lists_samples_and_remaining_quota(demo):
    ws = demo.get(new_visitor_id())

    config = run(api.get_config(workspace=ws))

    assert config["demo"] is True
    assert [s["key"] for s in config["samples"]] == [s.key for s in SAMPLES]
    assert config["remaining"] == {PLAN: 3, EXECUTION: 1, LLM_CALL: 2}
    assert config["llm_available"] is False


def test_every_sample_exists():
    assert all(sample.path.is_file() for sample in SAMPLES)


def test_sample_goes_from_loading_to_execution_within_quota(demo):
    ws = demo.get(new_visitor_id())

    loaded = run(api.load_sample("ventes", workspace=ws))
    plan = run(api.create_workflow_plan(api.WorkflowPlanRequest(file_id=loaded["file_id"]), workspace=ws))["plans"][0]
    run(api.approve_workflow_contract(plan["plan_id"], api.WorkflowReviewRequest(reviewer="visiteur"), workspace=ws))
    result = run(api.execute_workflow_plan(plan["plan_id"], workspace=ws))

    assert result["final_status"] == "SUCCESS"
    assert str(ws.upload_dir) in loaded["files"][0]["file_path"]
    # Le contrat validé reste dans l'espace du visiteur.
    assert (ws.service.contracts_dir / "ventes_2025_2026.json").is_file()
    assert not str(result["fabric_export"]).startswith("data/")
    json.dumps(result, default=str)

    # Quota d'exécution (1 par jour ici) épuisé.
    assert status_of(api.execute_workflow_plan(plan["plan_id"], workspace=ws)) == (
        429, "Limite de la démo atteinte : 1 exécutions par jour.",
    )


def test_plan_quota_answers_429(demo):
    ws = demo.get(new_visitor_id())
    loaded = run(api.load_sample("rejet", workspace=ws))
    request = api.WorkflowPlanRequest(file_id=loaded["file_id"])

    for _ in range(3):
        run(api.create_workflow_plan(request, workspace=ws))

    assert status_of(api.create_workflow_plan(request, workspace=ws))[0] == 429


def test_unknown_sample_is_a_404(demo):
    assert status_of(api.load_sample("secret", workspace=demo.get(new_visitor_id())))[0] == 404


def test_zip_sample_is_extracted_in_the_visitor_space(demo):
    ws = demo.get(new_visitor_id())

    loaded = run(api.load_sample("orders_zip", workspace=ws))

    assert [f["file_name"] for f in loaded["files"]] == ["2019.csv", "2020.csv", "2021.csv"]
    assert all(str(ws.upload_dir) in f["file_path"] for f in loaded["files"])
