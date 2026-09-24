import pytest

from src.agent_guard import ToolCallGuard


def test_decision_blocked_until_both_validations_ran():
    guard = ToolCallGuard()
    guard.record("validate_contract", {"valid": True})

    _, blocked = guard.prepare("determine_ingestion_decision", {})

    assert blocked["status"] == "BLOCKED"
    assert "validate_csv" in blocked["message"]


def test_decision_arguments_are_replaced_by_real_results():
    guard = ToolCallGuard()
    contract = {"valid": True, "contract_status": "PROPOSED"}
    quality = {"valid": True, "issues_count": 0}
    guard.record("validate_contract", contract)
    guard.record("validate_csv", quality)

    arguments, blocked = guard.prepare(
        "determine_ingestion_decision",
        {"contract_result": {"contract_status": "VALIDATED"}, "quality_result": {}},
    )

    assert blocked is None
    assert arguments == {"contract_result": contract, "quality_result": quality}


@pytest.mark.parametrize(
    "tool",
    ["ingest_csv", "transform_to_silver", "build_sales_gold", "publish_to_fabric"],
)
@pytest.mark.parametrize("decision", [None, "QUARANTINE", "REJECT"])
def test_write_tools_require_computed_ingest(tool, decision):
    guard = ToolCallGuard()

    if decision:
        guard.record("determine_ingestion_decision", {"decision": decision})

    _, blocked = guard.prepare(tool, {})

    assert blocked["status"] == "BLOCKED"


def test_write_tools_allowed_after_ingest_decision():
    guard = ToolCallGuard()
    guard.record("determine_ingestion_decision", {"decision": "INGEST"})

    arguments, blocked = guard.prepare("ingest_csv", {"file_path": "a.csv"})

    assert blocked is None
    assert arguments == {"file_path": "a.csv"}


def test_read_only_and_routing_tools_are_not_blocked():
    guard = ToolCallGuard()

    for tool in ("inspect_csv", "profile_csv", "quarantine_csv", "reject_csv"):
        assert guard.prepare(tool, {})[1] is None
