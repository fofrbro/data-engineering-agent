CREATE OR REPLACE VIEW pipeline_observability AS
SELECT
    COUNT(*) AS total_runs,

    COALESCE(SUM(CASE WHEN execution_mode = 'ASSESS_ONLY' THEN 1 ELSE 0 END), 0) AS assess_only_runs,
    COALESCE(SUM(CASE WHEN execution_mode = 'INGEST' THEN 1 ELSE 0 END), 0) AS ingest_runs,

    COALESCE(SUM(CASE WHEN decision = 'QUARANTINE' THEN 1 ELSE 0 END), 0) AS quarantine_runs,
    COALESCE(SUM(CASE WHEN decision = 'REJECT' THEN 1 ELSE 0 END), 0) AS reject_runs,

    COALESCE(SUM(CASE WHEN final_status = 'SUCCESS' THEN 1 ELSE 0 END), 0) AS successful_runs,
    COALESCE(SUM(CASE WHEN final_status = 'FAILED' THEN 1 ELSE 0 END), 0) AS failed_runs,

    COALESCE(1.0 * SUM(CASE WHEN final_status = 'SUCCESS' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 0.0) AS success_rate,
    COALESCE(1.0 * SUM(CASE WHEN decision = 'QUARANTINE' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 0.0) AS quarantine_rate,
    COALESCE(1.0 * SUM(CASE WHEN decision = 'REJECT' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 0.0) AS reject_rate,

    COALESCE(AVG(duration_seconds), 0.0) AS average_duration_seconds

FROM pipeline_runs
