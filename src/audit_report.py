from src.audit_analysis import (
    calculate_pipeline_kpis,
    calculate_step_kpis,
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

    structured_steps = pipeline_steps[
        pipeline_steps["run_id"].isin(
            structured_runs["run_id"]
        )
    ]

    step_summary = (
        structured_steps
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
        "step_kpis": calculate_step_kpis(structured_steps),
    }
