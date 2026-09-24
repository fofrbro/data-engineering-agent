# Fabric notebook - version d'origine, telle qu'exécutée dans le workspace.
# Chargement complet (overwrite) des tables d'audit et création de la vue
# pipeline_observability.

# %%
runs_df = spark.read.parquet(
    "Files/audit/pipeline_runs_structured.parquet"
)

steps_df = spark.read.parquet(
    "Files/audit/pipeline_steps_structured.parquet"
)

# %%
runs_df.write \
    .mode("overwrite") \
    .format("delta") \
    .saveAsTable("pipeline_runs")

steps_df.write \
    .mode("overwrite") \
    .format("delta") \
    .saveAsTable("pipeline_steps")

# %%
from pyspark.sql import functions as F

runs = spark.table("pipeline_runs")

kpis = runs.agg(
    F.count("*").alias("total_runs"),
    F.sum(
        F.when(
            F.col("execution_mode") == "ASSESS_ONLY",
            1
        ).otherwise(0)
    ).alias("assess_only_runs"),
    F.sum(
        F.when(
            F.col("execution_mode") == "INGEST",
            1
        ).otherwise(0)
    ).alias("ingest_runs"),
    F.sum(
        F.when(
            F.col("decision") == "QUARANTINE",
            1
        ).otherwise(0)
    ).alias("quarantine_runs"),
    F.sum(
        F.when(
            F.col("decision") == "REJECT",
            1
        ).otherwise(0)
    ).alias("reject_runs"),
    F.avg("duration_seconds").alias(
        "average_duration_seconds"
    ),
)

from pyspark.sql import functions as F

runs = spark.table("pipeline_runs")

pipeline_observability = runs.agg(
    F.count("*").alias("total_runs"),

    F.sum(
        F.when(
            F.col("execution_mode") == "ASSESS_ONLY",
            1
        ).otherwise(0)
    ).alias("assess_only_runs"),

    F.sum(
        F.when(
            F.col("execution_mode") == "INGEST",
            1
        ).otherwise(0)
    ).alias("ingest_runs"),

    F.sum(
        F.when(
            F.col("decision") == "QUARANTINE",
            1
        ).otherwise(0)
    ).alias("quarantine_runs"),

    F.sum(
        F.when(
            F.col("decision") == "REJECT",
            1
        ).otherwise(0)
    ).alias("reject_runs"),

    F.sum(
        F.when(
            F.col("final_status") == "SUCCESS",
            1
        ).otherwise(0)
    ).alias("successful_runs"),

    F.avg("duration_seconds").alias(
        "average_duration_seconds"
    )
)

spark.sql("""
CREATE OR REPLACE VIEW pipeline_observability AS
SELECT
    COUNT(*) AS total_runs,

    SUM(
        CASE
            WHEN execution_mode = 'ASSESS_ONLY'
            THEN 1 ELSE 0
        END
    ) AS assess_only_runs,

    SUM(
        CASE
            WHEN execution_mode = 'INGEST'
            THEN 1 ELSE 0
        END
    ) AS ingest_runs,

    SUM(
        CASE
            WHEN decision = 'QUARANTINE'
            THEN 1 ELSE 0
        END
    ) AS quarantine_runs,

    SUM(
        CASE
            WHEN decision = 'REJECT'
            THEN 1 ELSE 0
        END
    ) AS reject_runs,

    SUM(
        CASE
            WHEN final_status = 'SUCCESS'
            THEN 1 ELSE 0
        END
    ) AS successful_runs,

    AVG(duration_seconds) AS average_duration_seconds

FROM pipeline_runs
""")
