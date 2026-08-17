import pandas as pd

from src.tools.gold_transformation import build_sales_gold


def test_build_sales_gold(tmp_path):
    silver_file = tmp_path / "sales.parquet"
    gold_file = tmp_path / "sales_by_product.parquet"

    df = pd.DataFrame({
        "customer_id": [1, 2, 3, 4],
        "product": ["Laptop", "Laptop", "Mouse", "Monitor"],
        "quantity": [2, 1, 5, 1],
        "price": [850, 850, 25, 300],
        "line_amount": [1700, 850, 125, 300],
    })

    df.to_parquet(silver_file, index=False)

    result = build_sales_gold(
        str(silver_file),
        str(gold_file),
    )

    assert result["status"] == "TRANSFORMED"
    assert result["rows"] == 3

    gold = pd.read_parquet(gold_file)

    laptop = gold[gold["product"] == "Laptop"].iloc[0]
    mouse = gold[gold["product"] == "Mouse"].iloc[0]

    assert laptop["total_quantity"] == 3
    assert laptop["total_sales"] == 2550
    assert laptop["number_of_lines"] == 2

    assert mouse["total_quantity"] == 5
    assert mouse["total_sales"] == 125
