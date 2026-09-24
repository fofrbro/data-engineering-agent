CREATE OR REPLACE VIEW pipeline_step_observability AS
SELECT
    step_name,

    COUNT(*) AS executions,

    COALESCE(SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END), 0) AS failed_executions,

    COALESCE(1.0 * SUM(CASE WHEN status = 'FAILED' THEN 0 ELSE 1 END) / NULLIF(COUNT(*), 0), 0.0) AS success_rate,

    AVG(duration_seconds) AS average_duration_seconds

FROM pipeline_steps
GROUP BY step_name
