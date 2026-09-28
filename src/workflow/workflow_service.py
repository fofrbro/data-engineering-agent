"""
Service du workflow agent, indépendant de FastAPI.

Conserve les plans en mémoire et expose les actions PLAN,
VALIDATE et EXECUTE sous forme de dictionnaires sérialisables.
Chaque validation exige un relecteur explicite.
"""

import json
from pathlib import Path

import pandas as pd

from src.audit_parquet import export_structured_audit_to_parquet
from src.audit_store import DEFAULT_AUDIT_PATH
from src.contract.contract_generator import dataset_name_from_path
from src.fabric.gold_export import export_gold_for_fabric
from src.workflow.batch import group_files
from src.workflow.file_preparation import (
    FROM_CONTRACT,
    FROM_FILE,
    PreparationError,
    prepare_files,
)
from src.workflow.instructions import interpret_instructions
from src.analysis.analysis_commentary import comment_analysis
from src.analysis.business_analysis import analyze_business_data, render_analysis_text
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
    WorkflowError,
    decide_semantic_suggestions,
    plan_file,
    quality_warnings,
    render_plan_preview,
    review_plan_column_names,
    review_plan_semantics,
    validation_status,
)
from src.workflow.plan_executor import execute_plan


SAMPLE_ROWS = 3


def _column_naming(prepared: list[dict], files: list[str], preparations: dict) -> dict | None:
    """
    Étape « noms de colonnes » d'un plan dont des fichiers étaient sans
    en-tête : noms, origine, exemples de valeurs et statut. Des noms repris
    d'un contrat validé, ou imposés par l'en-tête d'un autre fichier du
    lot, sont déjà validés.
    """

    if not prepared:
        return None

    first = prepared[0]
    sample = pd.read_csv(first["path"], dtype=str, keep_default_na=False, nrows=SAMPLE_ROWS)
    has_file_header = any(preparations[path].header_source == FROM_FILE for path in files)
    validated = first["header_source"] == FROM_CONTRACT or has_file_header

    return {
        "names": list(sample.columns),
        "source": first["header_source"],
        "note": first["note"],
        "samples": sample.values.tolist(),
        "editable": not has_file_header,
        "status": "VALIDATED" if validated else "PROPOSED",
        "validated_by": (
            f"contrat {first['dataset']}" if first["header_source"] == FROM_CONTRACT
            else "en-tête d'un fichier du lot" if has_file_header
            else None
        ),
        "validated_at": None,
    }


class WorkflowService:

    def __init__(
        self,
        contracts_dir: str | Path = DEFAULT_CONTRACTS_DIR,
        output_root: str | Path = "data",
        audit_path: str | Path = DEFAULT_AUDIT_PATH,
        fabric_export_root: str | Path = "data/fabric_export",
        results_dir: str | Path = "results",
        llm_client=None,
    ):
        self.contracts_dir = contracts_dir
        self.output_root = output_root
        self.audit_path = audit_path
        self.fabric_export_root = fabric_export_root
        self.results_dir = Path(results_dir)
        # Sans client, la relecture sémantique est indisponible ; le
        # reste du workflow n'en dépend pas.
        self.llm_client = llm_client
        self._plans: dict[str, AgentPlan] = {}

    @property
    def plan_count(self) -> int:
        return len(self._plans)

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
            "file_preparations": plan.file_preparations,
            "column_naming": plan.column_naming,
            "instructions": plan.instructions,
            "contract_path": plan.contract_path,
            "contract_status": plan.contract_status,
            "contract_origin": plan.contract_origin,
            "decision_preview": plan.decision_preview,
            "validation": validation_status(plan),
            "preview": render_plan_preview(plan),
            "recommendation": plan.recommendation.to_dict(),
            "kpis": plan.kpis.to_dict(),
            "dashboard": plan.dashboard.to_dict(),
            "semantic_review": (
                plan.semantic_review.to_dict() if plan.semantic_review else None
            ),
            "semantic_overrides": plan.semantic_overrides,
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
        column_names: list[str] | None = None,
        instructions: str | None = None,
    ) -> list[dict]:
        """
        Un plan par dataset du lot (voir group_files). Les fichiers sans
        en-tête sont d'abord préparés (voir file_preparation) : ceux de
        même structure reçoivent les mêmes noms et forment un seul plan.

        Nom d'un groupe : celui fourni, sinon celui issu de la préparation
        (contrat reconnu ou LLM), sinon le nom d'origine de son premier
        fichier (display_names), suffixé en cas de doublon.

        instructions (texte libre) est traduit par le LLM en nom de
        dataset et noms de colonnes vérifiés ; dataset et column_names
        fournis explicitement l'emportent.
        """

        display_names = display_names or {}
        interpreted = (
            interpret_instructions(self.llm_client, instructions.strip())
            if instructions and instructions.strip()
            else None
        )

        if interpreted:
            dataset = dataset or interpreted.dataset
            column_names = column_names or interpreted.column_names

        try:
            prepared_files = prepare_files(
                file_paths, self.contracts_dir, self.llm_client, column_names,
            )
        except PreparationError as exc:
            raise WorkflowError(str(exc)) from exc

        preparations = {prepared.path: prepared for prepared in prepared_files}
        views = []
        used = set()

        for group in group_files(list(preparations), dataset):
            originals = [preparations[path].original for path in group.files]
            suggested = {preparations[path].dataset for path in group.files}
            name = (
                group.dataset
                or (suggested.pop() if len(suggested) == 1 and None not in suggested else None)
                or dataset_name_from_path(display_names.get(originals[0], originals[0]))
            )
            unique, index = name, 2

            while unique in used:
                unique, index = f"{name}_{index}", index + 1

            used.add(unique)
            view = self.create_plan(group.files, contract_path, unique, enrichments)
            plan = self._plans[view["plan_id"]]
            plan.file_preparations = [
                preparations[path].to_dict()
                for path in group.files
                if preparations[path].header_source != FROM_FILE
            ]
            plan.column_naming = _column_naming(plan.file_preparations, group.files, preparations)
            plan.instructions = interpreted.to_dict() if interpreted else None
            views.append(self.view(view["plan_id"]))

        return views

    def review_column_names(
        self,
        plan_id: str,
        reviewer: str,
        names: list[str] | None = None,
        dataset: str | None = None,
        comment=None,
    ) -> dict:
        plan = review_plan_column_names(self.get(plan_id), reviewer, names, dataset, comment)
        self._plans[plan_id] = plan
        return self.view(plan_id)

    def approve_contract(self, plan_id: str, reviewer: str, comment=None) -> dict:
        approve_plan_contract(self.get(plan_id), reviewer, comment)
        return self.view(plan_id)

    def review_semantics(self, plan_id: str) -> dict:
        review_plan_semantics(self.get(plan_id), self.llm_client)
        return self.view(plan_id)

    def decide_semantics(
        self,
        plan_id: str,
        reviewer: str,
        accepted_ids: list[str],
        comment=None,
    ) -> dict:
        decide_semantic_suggestions(self.get(plan_id), reviewer, accepted_ids, comment)
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

    def _analyze(self, plan: AgentPlan, result) -> dict:
        """
        Analyse métier complète des données Silver ingérées (voir
        src.analysis), puis commentaire du LLM, dont les nombres sont
        vérifiés. Un échec d'analyse ne change pas le résultat du run,
        déjà vérifié et audité : il est signalé.
        """

        quality = {
            "files": [
                {
                    "file": item["file"],
                    "decision": item["decision"],
                    "final_status": item["final_status"],
                }
                for item in result.file_results
            ],
            "checks": [
                {"check": check["check"], "passed": check["passed"]}
                for check in result.verification or []
            ],
            "warnings": [warning["message"] for warning in quality_warnings(plan)],
        }

        try:
            analysis = analyze_business_data(
                pd.read_parquet(result.outputs["silver"]),
                plan.kpis,
                plan.semantics,
                plan.dataset,
                quality,
            )
        except Exception as exc:
            return {
                "analysis": None,
                "analysis_report": None,
                "analysis_files": None,
                "analysis_error": str(exc),
            }

        analysis["commentary"] = comment_analysis(self.llm_client, analysis).to_dict()
        report = render_analysis_text(analysis)

        self.results_dir.mkdir(parents=True, exist_ok=True)
        text_path = self.results_dir / f"{plan.dataset}_analysis.txt"
        json_path = self.results_dir / f"{plan.dataset}_analysis.json"
        text_path.write_text(report, encoding="utf-8")
        json_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        return {
            "analysis": analysis,
            "analysis_report": report,
            "analysis_files": {"text": text_path.as_posix(), "json": json_path.as_posix()},
            "analysis_error": None,
        }

    def _export_audit(self) -> dict:
        """
        Exporte l'audit structuré pour Fabric (Files/audit/). Un échec
        d'export ne change pas le résultat du run, déjà audité : il est
        signalé.
        """

        folder = Path(self.fabric_export_root) / "audit"

        try:
            runs_path, steps_path = export_structured_audit_to_parquet(
                self.audit_path,
                folder / "pipeline_runs_structured.parquet",
                folder / "pipeline_steps_structured.parquet",
            )
        except Exception as exc:
            return {"audit_export": None, "audit_export_error": str(exc)}

        return {
            "audit_export": {"runs": runs_path.as_posix(), "steps": steps_path.as_posix()},
            "audit_export_error": None,
        }

    def execute(self, plan_id: str) -> dict:
        plan = self.get(plan_id)
        result = execute_plan(
            plan,
            output_root=self.output_root,
            audit_path=self.audit_path,
        )

        # Seule une exécution vérifiée est préparée pour Fabric et analysée.
        # Un échec d'export ne change pas le résultat du run, déjà vérifié
        # et audité : il est signalé.
        succeeded = result.final_status == "SUCCESS"
        fabric_export, fabric_export_error = None, None

        if succeeded:
            try:
                fabric_export = export_gold_for_fabric(plan, result, self.fabric_export_root).as_posix()
            except OSError as exc:
                fabric_export_error = f"Export Fabric impossible : {exc}"
        analysis = (
            self._analyze(plan, result)
            if succeeded
            else {
                "analysis": None,
                "analysis_report": None,
                "analysis_files": None,
                "analysis_error": None,
            }
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
            "fabric_export_error": fabric_export_error,
            # Tout run est audité, y compris refusé ou en échec : l'audit
            # est donc exporté après chaque exécution.
            **self._export_audit(),
            **analysis,
        }
