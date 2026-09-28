import pandas as pd
import pytest

from src.discovery.header_detection import (
    DATE,
    NUMBER,
    file_has_header,
    has_header,
    value_kind,
)


def raw(rows):
    return pd.DataFrame(rows, dtype=str)


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "values, kind",
    [
        (["1", "2.5", "-3"], NUMBER),
        (["2019-07-01", "2020-01-31"], DATE),
        (["01/07/2019", "31/12/2019"], DATE),
        (["SO43701", "SO43704"], None),
        (["Mountain-100 Silver, 44"], None),
        (["", " "], None),
    ],
)
def test_value_kind(values, kind):
    assert value_kind(pd.Series(values)) == kind


def test_labels_above_numbers_and_dates_are_a_header():
    assert has_header(raw([["id", "day", "amount"], ["A1", "2019-07-01", "3.5"], ["A2", "2019-07-02", "4"]]))


def test_data_in_the_first_row_means_no_header():
    assert not has_header(raw([["A1", "2019-07-01", "3.5"], ["A2", "2019-07-02", "4"], ["A3", "2019-07-03", "1"]]))


def test_one_label_is_enough_to_keep_the_header():
    # « total » au-dessus de nombres : c'est un libellé, donc un en-tête.
    assert has_header(raw([["2019", "total"], ["10", "12"], ["11", "13"]]))


def test_text_only_file_keeps_the_usual_reading():
    assert has_header(raw([["Paris", "France"], ["Dakar", "Sénégal"]]))


def test_single_row_keeps_the_usual_reading():
    assert has_header(raw([["1", "2"]]))


def test_files(tmp_path):
    headerless = write(tmp_path, "2019.csv", 'SO1,1,2019-07-01,"Road, 44",3.5\nSO2,2,2019-07-02,"Road, 48",4\n')
    semicolon = write(tmp_path, "fr.csv", "code;date;montant\nA;2019-07-01;3,5\nB;2019-07-02;4\n")

    assert not file_has_header(headerless)
    assert file_has_header(semicolon)
    assert file_has_header("data/samples/sales.csv")


def test_non_delimited_files_are_left_alone(tmp_path):
    path = tmp_path / "orders.json"
    pd.DataFrame({"a": [1, 2]}).to_json(path, orient="records")

    assert file_has_header(path)
