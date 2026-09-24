import pandas as pd
import pytest

from src.workflow.agent_workflow import (
    WorkflowError,
    approve_plan_contract,
    plan_file,
)
from src.workflow.plan_executor import execute_plan


def enriched_plan(tmp_path, enrichments):
    plan = plan_file(
        "data/sales.csv",
        contracts_dir=tmp_path / "contracts",
        enrichments=enrichments,
    )
    approve_plan_contract(plan, "cheikhou")
    return plan


def test_enrichments_become_silver_steps_and_are_executed(tmp_path):
    plan = enriched_plan(
        tmp_path,
        [
            {"type": "arithmetic", "target": "gross", "left": "line_amount", "right": "quantity", "operator": "add"},
            {"type": "concat", "target": "label", "columns": ["product", "customer_id"], "separator": "-"},
            {"type": "constant", "target": "source", "value": "upload"},
        ],
    )

    steps = [s for s in plan.recommendation.transformations if s.type == "enrich"]
    result = execute_plan(plan, output_root=tmp_path / "lake", audit_path=tmp_path / "runs.jsonl")
    silver = pd.read_parquet(result.outputs["silver"])

    assert [s.id for s in steps] == ["enrich_gross", "enrich_label", "enrich_source"]
    assert all(not s.requires_approval for s in steps)
    assert result.final_status == "SUCCESS"
    assert silver["gross"].tolist() == [1702.0, 130.0, 138.0, 301.0, 851.0]
    assert silver["label"].iloc[0] == "Laptop-1"
    assert set(silver["source"]) == {"upload"}


def test_enrichments_survive_contract_approval(tmp_path):
    plan = enriched_plan(tmp_path, [{"type": "constant", "target": "source", "value": "x"}])

    assert "enrich_source" in [s.id for s in plan.recommendation.transformations]


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "python", "target": "x", "code": "__import__('os')"},
        {"type": "arithmetic", "target": "x", "left": "missing", "right": "price"},
        {"type": "arithmetic", "target": "x", "left": "quantity", "right": "price", "operator": "power"},
        {"type": "arithmetic", "target": "price", "left": "quantity", "right": "price"},
        {"type": "date_part", "target": "x", "source": "product", "part": "century"},
        {"type": "concat", "target": "x", "columns": []},
    ],
)
def test_invalid_enrichments_are_refused_at_plan_time(tmp_path, operation):
    with pytest.raises(WorkflowError):
        plan_file(
            "data/sales.csv",
            contracts_dir=tmp_path / "contracts",
            enrichments=[operation],
        )
