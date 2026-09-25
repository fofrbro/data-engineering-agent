# Fabric notebook - chargement des tables Gold d'un dataset.
#
# Entrée : Files/gold/<DATASET>/ (manifest.json + un Parquet par table),
# produit localement par src/fabric/gold_export.py après une exécution
# vérifiée (SUCCESS).
# Même logique que src/fabric/gold_export.load_gold_from_manifest, testée
# localement :
# - chaque table Gold est remplacée par sa dernière version vérifiée ;
# - le nombre de lignes est contrôlé contre le manifeste ;
# - chaque chargement est tracé dans la table gold_loads ;
# - un run_id déjà chargé pour ce dataset n'est pas rechargé.
#
# Exécuté dans Fabric le 2026-09-24 (dataset sales) : 5 tables Gold créées,
# valeurs conformes ; gold_loads confirmée le 2026-09-25 (5 lignes, même
# run_id). Non encore confirmé : le saut d'un run déjà chargé.

# %%
DATASET = "sales"  # paramètre du notebook

# %%
import json
from datetime import datetime, timezone

from pyspark.sql import Row

spark.conf.set("spark.sql.session.timeZone", "UTC")

FOLDER = f"Files/gold/{DATASET}"

# Le Lakehouse par défaut est monté localement dans les notebooks Fabric.
with open(f"/lakehouse/default/{FOLDER}/manifest.json", encoding="utf-8") as file:
    manifest = json.load(file)

run_id = manifest["run_id"]

# %%
already_loaded = spark.catalog.tableExists("gold_loads") and (
    spark.table("gold_loads")
    .filter(f"run_id = '{run_id}' AND dataset = '{DATASET}'")
    .count()
    > 0
)

# %%
if already_loaded:
    print(f"Run {run_id} déjà chargé : aucune table modifiée.")
else:
    loaded_at = datetime.now(timezone.utc)
    log = []

    for table in manifest["tables"]:
        data = spark.read.parquet(f"{FOLDER}/{table['file']}")
        rows = data.count()

        if rows != table["rows"]:
            raise ValueError(
                f"{table['table_name']} : {rows} ligne(s), manifeste {table['rows']}."
            )

        data.write \
            .mode("overwrite") \
            .format("delta") \
            .option("overwriteSchema", "true") \
            .saveAsTable(table["table_name"])

        log.append(
            Row(
                run_id=run_id,
                dataset=DATASET,
                table_name=table["table_name"],
                rows=rows,
                loaded_at=loaded_at,
            )
        )

    spark.createDataFrame(log).write \
        .mode("append") \
        .format("delta") \
        .saveAsTable("gold_loads")

    print(f"Run {run_id} : {len(log)} table(s) Gold chargée(s).")
