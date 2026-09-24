import os
import pandas as pd


def build_sales_gold(
    silver_file_path: str,
    output_file_path: str
) -> dict:
    """
    Construit la table Gold des ventes agrégées par produit
    à partir de la couche Silver.
    """

    df = pd.read_parquet(silver_file_path)

    required_columns = [
        "product",
        "quantity",
        "price",
        "line_amount",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        os.makedirs(
            os.path.dirname(output_file_path),
            exist_ok=True
        )
        df.to_parquet(output_file_path, index=False)

        return {
            "status": "TRANSFORMED",
            "mode": "generic",
            "source_file": silver_file_path,
            "output_file": output_file_path,
            "rows": len(df),
            "columns": df.columns.tolist(),
        }

    gold = (
        df.groupby("product", as_index=False)
        .agg(
            total_quantity=("quantity", "sum"),
            total_sales=("line_amount", "sum"),
            avg_unit_price=("price", "mean"),
            number_of_lines=("product", "count"),
        )
    )

    gold["avg_unit_price"] = gold["avg_unit_price"].round(2)

    os.makedirs(
        os.path.dirname(output_file_path),
        exist_ok=True
    )

    gold.to_parquet(
        output_file_path,
        index=False
    )

    return {
        "status": "TRANSFORMED",
        "source_file": silver_file_path,
        "output_file": output_file_path,
        "rows": len(gold),
        "columns": gold.columns.tolist(),
    }
