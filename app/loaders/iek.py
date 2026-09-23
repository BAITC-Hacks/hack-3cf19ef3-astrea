"""Load and normalize IEK workbooks."""

import pandas as pd

from ._shared import (
    PathLike,
    clean_string,
    find_column,
    load_moq_table,
    load_reference,
    load_sales_transactions,
    monthly_to_long,
    read_excel_table,
)


SUPPLIER = "IEK"


def load_sales_tx(path: PathLike) -> pd.DataFrame:
    return load_sales_transactions(path, SUPPLIER)


def load_sales_monthly(path: PathLike) -> pd.DataFrame:
    frame = read_excel_table(path, ("Номенклатура", "Номенклатура.Код"))
    return monthly_to_long(
        frame, SUPPLIER, ("Номенклатура.Код", "Код 1с"), "qty", fill_missing=True
    )


def load_stock_monthly(path: PathLike) -> pd.DataFrame:
    frame = read_excel_table(path, ("Номенклатура", "Номенклатура.Код", "Ед."))
    return monthly_to_long(
        frame,
        SUPPLIER,
        ("Номенклатура.Код", "Код 1с"),
        "opening_stock",
        fill_missing=True,
    )


def load_in_transit(path: PathLike) -> pd.DataFrame:
    frame = read_excel_table(path, ("Код 1с", "Артикул ИЭК"))
    code_column = find_column(frame, ("Код 1с",))
    metadata = {
        code_column,
        find_column(frame, ("Артикул ИЭК",)),
        find_column(frame, ("Наименование", " Наименование")),
    }
    quantity_columns = [column for column in frame.columns if column not in metadata]
    quantities = frame[quantity_columns].apply(pd.to_numeric, errors="coerce")

    result = pd.DataFrame(
        {
            "sku_code": clean_string(frame[code_column]),
            "supplier": pd.Series(SUPPLIER, index=frame.index, dtype="string"),
            "qty": quantities.sum(axis=1, min_count=1).fillna(0.0).astype(float),
        }
    ).dropna(subset=["sku_code"])
    return result.groupby(["sku_code", "supplier"], as_index=False, sort=False)["qty"].sum()


def load_moq(path: PathLike) -> pd.DataFrame:
    return load_moq_table(path, SUPPLIER, ("Мин. разр. к отгр.",))


def load_sku_ref(path: PathLike) -> pd.DataFrame:
    return load_reference(path, SUPPLIER)
