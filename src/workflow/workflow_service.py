"""
Service du workflow agent, indépendant de FastAPI.

Conserve les plans en mémoire et expose les actions PLAN,
VALIDATE et EXECUTE sous forme de dictionnaires sérialisables.
Chaque validation exige un relecteur explicite.
"""

import json
from pathlib import Path

from src.audit_store import DEFAULT_AUDIT_PATH
from src.contract.contract_generator import dataset_name_from_path
from src.fabric.gold_export import export_gold_for_fabric
from src.workflow.batch import group_files
from src.tools.data_analyst import DataAnalyst, analyze_gold_data
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
        results_dir: str | Path = "results",
    ):
        self.contracts_dir = contracts_dir
        self.output_root = output_root
        self.audit_path = audit_path
        self.fabric_export_root = fabric_export_root
        self.results_dir = Path(results_dir)
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
            "files": plan.file_paths,
            "file_previews": plan.file_previews,
            "contract_path": plan.contract_path,
            "contract_status": plan.contract_status,
            "contract_origin": plan.contract_origin,
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
        file_path: str | list[str],
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

    def create_plans(
        self,
        file_paths: list[str],
        contract_path: str | None = None,
        dataset: str | None = None,
        enrichments: list[dict] | None = None,
        display_names: dict[str, str] | None = None,
    ) -> list[dict]:
        """
        Un plan par dataset du lot (voir group_files). Un groupe sans
        nom fourni prend le nom d'origine de son premier fichier
        (display_names), suffixé en cas de doublon.
        """

        display_names = display_names or {}
        views = []
        used = set()

        for group in group_files(file_paths, dataset):
            name = group.dataset or dataset_name_from_path(
                display_names.get(group.files[0], group.files[0])
            )
            unique, index = name, 2

            while unique in used:
                unique, index = f"{name}_{index}", index + 1

            used.add(unique)
            views.append(
                self.create_plan(group.files, contract_path, unique, enrichments)
            )

        return views

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

    def _analyze(self, plan: AgentPlan, silver_path: str) -> dict:
        """
        Rapport Data Analyst sur Silver. Un échec d'analyse ne change
        pas le résultat du run, déjà vérifié et audité : il est signalé.
        """

        try:
            analysis = analyze_gold_data(silver_path, dataset_name=plan.dataset)
            report = DataAnalyst().generate_analysis_report(analysis)
        except Exception as exc:
            return {"analysis_report": None, "analysis_files": None, "analysis_error": str(exc)}

        self.results_dir.mkdir(parents=True, exist_ok=True)
        text_path = self.results_dir / f"{plan.dataset}_analysis.txt"
        json_path = self.results_dir / f"{plan.dataset}_analysis.json"
        text_path.write_text(report, encoding="utf-8")
        json_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        return {
            "analysis_report": report,
            "analysis_files": {"text": text_path.as_posix(), "json": json_path.as_posix()},
            "analysis_error": None,
        }

    def execute(self, plan_id: str) -> dict:
        plan = self.get(plan_id)
        result = execute_plan(
            plan,
            output_root=self.output_root,
            audit_path=self.audit_path,
        )

        # Seule une exécution vérifiée est préparée pour Fabric et analysée.
        succeeded = result.final_status == "SUCCESS"
        fabric_export = (
            export_gold_for_fabric(plan, result, self.fabric_export_root).as_posix()
            if succeeded
            else None
        )
        analysis = (
            self._analyze(plan, result.outputs["silver"])
            if succeeded
            else {"analysis_report": None, "analysis_files": None, "analysis_error": None}
        )

        return {
            "plan_id": plan_id,
            "run_id": result.run_id,
            "final_status": result.final_status,
            "decision": result.decision,
            "outputs": result.outputs,
            "verification": result.verification,
            "explanation": result.explanation,
            "file_results": result.file_results,
            "fabric_export": fabric_export,
            **analysis,
        }
