import pandas as pd
import pytest

from src.discovery.errors import EmptyFileError
from src.workflow.batch import group_files


SAMPLES = "data/samples"


def test_files_with_same_columns_form_one_dataset(tmp_path):
    first = tmp_path / "ventes_janvier.csv"
    second = tmp_path / "ventes_fevrier.xlsx"
    frame = pd.read_csv(f"{SAMPLES}/ventes_2025_2026.csv")
    frame.head(10).to_csv(first, index=False)
    # Même colonnes, ordre différent, autre format.
    frame.iloc[10:20, ::-1].to_excel(second, index=False)

    groups = group_files([str(first), str(second)])

    assert len(groups) == 1
    assert groups[0].files == [str(first), str(second)]
    assert groups[0].dataset is None


def test_different_schemas_form_separate_groups():
    groups = group_files(
        [
            f"{SAMPLES}/ventes_2025_2026.csv",
            "data/sales.csv",
            f"{SAMPLES}/ventes_rejet.csv",
            f"{SAMPLES}/ventes_quarantaine.csv",
        ]
    )

    assert [group.files for group in groups] == [
        [f"{SAMPLES}/ventes_2025_2026.csv", f"{SAMPLES}/ventes_rejet.csv"],
        ["data/sales.csv"],
        # Une colonne en plus : autre schéma.
        [f"{SAMPLES}/ventes_quarantaine.csv"],
    ]


def test_explicit_dataset_name_groups_every_file():
    files = [
        f"{SAMPLES}/ventes_2025_2026.csv",
        f"{SAMPLES}/ventes_quarantaine.csv",
        f"{SAMPLES}/ventes_rejet.csv",
    ]

    groups = group_files(files, dataset="ventes_2025_2026")

    assert len(groups) == 1
    assert groups[0].files == files
    assert groups[0].dataset == "ventes_2025_2026"


def test_empty_batch_and_unreadable_file_are_refused(tmp_path):
    empty = tmp_path / "vide.csv"
    empty.write_bytes(b"")

    with pytest.raises(ValueError):
        group_files([])

    with pytest.raises(EmptyFileError):
        group_files([str(empty)])
