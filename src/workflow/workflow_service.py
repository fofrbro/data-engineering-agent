"""
Service du workflow agent, indépendant de FastAPI.

Conserve les plans en mémoire et expose les actions PLAN,
VALIDATE et EXECUTE sous forme de dictionnaires sérialisables.
Chaque validation exige un relecteur explicite.
"""

from pathlib import Path

from src.audit_store import DEFAULT_AUDIT_PATH
from src.fabric.gold_export import export_gold_for_fabric
from src.recommendation.dashboard_review import (
    APPROVE,
    MODIFY,
    REJECT,
    DashboardReviewError,
    modify_dashboard,
    reject_dashboard,
)
from src.workflow.agent_workflow import (
    DEFAULT_CONTRACTS_DIR,
    AgentPlan,
    approve_destructive_transformations,
    approve_plan_contract,
    approve_plan_dashboard,
    plan_file,
    render_plan_preview,
    validation_status,
)
from src.workflow.plan_executor import execute_plan


class WorkflowService:

    def __init__(
        self,
        contracts_dir: str | Path = DEFAULT_CONTRACTS_DIR,
        output_root: str | Path = "data",
        audit_path: str | Path = DEFAULT_AUDIT_PATH,
        fabric_export_root: str | Path = "data/fabric_export",
    ):
        self.contracts_dir = contracts_dir
        self.output_root = output_root
        self.audit_path = audit_path
        self.fabric_export_root = fabric_export_root
        self._plans: dict[str, AgentPlan] = {}

    def get(self, plan_id: str) -> AgentPlan:
        if plan_id not in self._plans:
            raise KeyError(f"Plan introuvable : {plan_id}")

        return self._plans[plan_id]

    def view(self, plan_id: str) -> dict:
        plan = self.get(plan_id)

        return {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "dataset": plan.dataset,
            "file": plan.file_path,
            "contract_path": plan.contract_path,
            "contract_status": plan.contract_status,
            "decision_preview": plan.decision_preview,
            "validation": validation_status(plan),
            "preview": render_plan_preview(plan),
            "recommendation": plan.recommendation.to_dict(),
            "kpis": plan.kpis.to_dict(),
            "dashboard": plan.dashboard.to_dict(),
            "history": plan.history,
        }

    def create_plan(
        self,
        file_path: str,
        contract_path: str | None = None,
        dataset: str | None = None,
        enrichments: list[dict] | None = None,
    ) -> dict:
        plan = plan_file(
            file_path,
            contract_path=contract_path or None,
            dataset=dataset or None,
            contracts_dir=self.contracts_dir,
            enrichments=enrichments,
        )
        self._plans[plan.plan_id] = plan

        return self.view(plan.plan_id)

    def approve_contract(self, plan_id: str, reviewer: str, comment=None) -> dict:
        approve_plan_contract(self.get(plan_id), reviewer, comment)
        return self.view(plan_id)

    def approve_transformations(self, plan_id: str, reviewer: str, comment=None) -> dict:
        approve_destructive_transformations(self.get(plan_id), reviewer, comment)
        return self.view(plan_id)

    def review_dashboard(
        self,
        plan_id: str,
        action: str,
        reviewer: str,
        comment: str | None = None,
        changes: dict | None = None,
    ) -> dict:
        plan = self.get(plan_id)

        if action == APPROVE:
            approve_plan_dashboard(plan, reviewer, comment)
        elif action == MODIFY:
            plan.dashboard = modify_dashboard(plan.dashboard, reviewer, changes or {}, comment)
        elif action == REJECT:
            plan.dashboard = reject_dashboard(plan.dashboard, reviewer, comment or "")
        else:
            raise DashboardReviewError(f"Action inconnue : {action}")

        return self.view(plan_id)

    def execute(self, plan_id: str) -> dict:
        plan = self.get(plan_id)
        result = execute_plan(
            plan,
            output_root=self.output_root,
            audit_path=self.audit_path,
        )

        # Seule une exécution vérifiée est préparée pour Fabric.
        fabric_export = (
            export_gold_for_fabric(plan, result, self.fabric_export_root).as_posix()
            if result.final_status == "SUCCESS"
            else None
        )

        return {
            "plan_id": plan_id,
            "run_id": result.run_id,
            "final_status": result.final_status,
            "decision": result.decision,
            "outputs": result.outputs,
            "verification": result.verification,
            "explanation": result.explanation,
            "fabric_export": fabric_export,
        }
