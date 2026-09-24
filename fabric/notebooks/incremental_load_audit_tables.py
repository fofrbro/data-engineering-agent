# Fabric notebook - chargement incrémental des tables d'audit.
#
# Remplace le chargement complet (overwrite) de load_audit_tables.py.
# Même logique que src/fabric/incremental_load.py, testée localement :
# - pipeline_runs  : anti-join sur run_id, les anciens runs ne sont
#   jamais réécrits ;
# - pipeline_steps : anti-join sur (run_id, step_order), uniquement
#   pour des runs présents dans la source ; un chargement interrompu
#   se rattrape au passage suivant ;
# - les étapes sont écrites avant les runs.
#
# Exécuté dans Fabric le 2026-09-24 : tables et vue créées ; une seconde
# exécution ne crée aucun run_id en double.
# Colonnes d'horodatage des étapes (mergeSchema) : pas encore exécuté
# dans Fabric.

# %%
from pyspark.sql import functions as F

spark.conf.set("spark.sql.session.timeZone", "UTC")

RUN_COLUMNS = [
    "run_id",
    "source_file",
    "contract_path",
    "decision",
    "execution_mode",
    "final_status",
    "started_at",
    "finished_at",
    "duration_seconds",
    "error",
]

STEP_COLUMNS = [
    "run_id",
    "step_order",
    "step_name",
    "status",
    "started_at",
    "finished_at",
    "duration_seconds",
    "error",
]

# Colonnes d'étape ajoutées avec l'horodatage des étapes : absentes des
# exports plus anciens, elles sont alors créées vides.
STEP_TIMING_TYPES = {
    "started_at": "timestamp",
    "finished_at": "timestamp",
    "duration_seconds": "double",
    "error": "string",
}

RUNS_SOURCE = "Files/audit/pipeline_runs_structured.parquet"
STEPS_SOURCE = "Files/audit/pipeline_steps_structured.parquet"

# %%
source_runs = (
    spark.read.parquet(RUNS_SOURCE)
    .select(*RUN_COLUMNS)
    .dropDuplicates(["run_id"])
)

raw_steps = spark.read.parquet(STEPS_SOURCE)

for column, column_type in STEP_TIMING_TYPES.items():
    if column not in raw_steps.columns:
        raw_steps = raw_steps.withColumn(column, F.lit(None).cast(column_type))

source_steps = (
    raw_steps
    .select(*STEP_COLUMNS)
    .join(source_runs.select("run_id"), "run_id", "left_semi")
    .dropDuplicates(["run_id", "step_order"])
)

# %%
if spark.catalog.tableExists("pipeline_steps"):
    new_steps = source_steps.join(
        spark.table("pipeline_steps").select("run_id", "step_order"),
        ["run_id", "step_order"],
        "left_anti",
    )
else:
    new_steps = source_steps

if spark.catalog.tableExists("pipeline_runs"):
    new_runs = source_runs.join(
        spark.table("pipeline_runs").select("run_id"),
        "run_id",
        "left_anti",
    )
else:
    new_runs = source_runs

# Les compteurs sont calculés avant l'écriture : après l'ajout,
# un DataFrame issu d'un anti-join serait réévalué à vide.
inserted_steps = new_steps.count()
inserted_runs = new_runs.count()

# %%
# mergeSchema : ajoute les colonnes d'horodatage à une table créée
# avant leur introduction ; les lignes existantes restent à NULL.
new_steps.select(*STEP_COLUMNS).write \
    .mode("append") \
    .format("delta") \
    .option("mergeSchema", "true") \
    .saveAsTable("pipeline_steps")

new_runs.select(*RUN_COLUMNS).write \
    .mode("append") \
    .format("delta") \
    .saveAsTable("pipeline_runs")

# %%
# Copie exacte de fabric/sql/pipeline_observability.sql
# (vérifiée par tests/test_fabric_observability_view.py).
spark.sql("""
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
""")

# %%
# Copie exacte de fabric/sql/pipeline_step_observability.sql
# (vérifiée par tests/test_fabric_observability_view.py).
spark.sql("""
CREATE OR REPLACE VIEW pipeline_step_observability AS
SELECT
    step_name,

    COUNT(*) AS executions,

    COALESCE(SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END), 0) AS failed_executions,

    COALESCE(1.0 * SUM(CASE WHEN status = 'FAILED' THEN 0 ELSE 1 END) / NULLIF(COUNT(*), 0), 0.0) AS success_rate,

    AVG(duration_seconds) AS average_duration_seconds

FROM pipeline_steps
GROUP BY step_name
""")

# %%
print(f"Runs ajoutés    : {inserted_runs}")
print(f"Étapes ajoutées : {inserted_steps}")
print(f"Total runs      : {spark.table('pipeline_runs').count()}")
print(f"Total étapes    : {spark.table('pipeline_steps').count()}")
