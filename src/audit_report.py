from src.audit_analysis import (
    calculate_pipeline_kpis,
    filter_structured_runs,
    load_audit_tables,
)


def build_observability_report(input_path=None) -> dict:
    """
    Construit un rapport d'observabilité à partir
    des audits structurés.
    """

    pipeline_runs, pipeline_steps = load_audit_tables(
        input_path
    )

    structured_runs = filter_structured_runs(
        pipeline_runs
    )

    kpis = calculate_pipeline_kpis(
        structured_runs
    )

    step_summary = (
        pipeline_steps[
            pipeline_steps["run_id"].isin(
                structured_runs["run_id"]
            )
        ]
        .groupby(
            ["step_name", "status"]
        )
        .size()
        .reset_index(name="count")
    )

    return {
        "kpis": kpis,
        "runs": structured_runs,
        "steps": step_summary,
    }
