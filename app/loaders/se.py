"""Load and normalize Systeme Electric workbooks."""

import pandas as pd

from ._shared import (
    PathLike,
    clean_string,
    find_column,
    find_column_containing,
    load_moq_table,
    load_reference,
    load_sales_transactions,
    monthly_to_long,
    read_excel_table,
)


SUPPLIER = "SE"


def load_sales_tx(path: PathLike) -> pd.DataFrame:
    return load_sales_transactions(path, SUPPLIER)


def load_sales_monthly(path: PathLike) -> pd.DataFrame:
    frame = read_excel_table(path, ("Номенклатура", "Номенклатура.Код", "Артикул"))
    return monthly_to_long(
        frame, SUPPLIER, ("Номенклатура.Код", "Код 1с"), "qty", fill_missing=True
    )


def load_stock_monthly(path: PathLike) -> pd.DataFrame:
    frame = read_excel_table(path, ("Номенклатура", "Номенклатура.Код", "Ед.изм"))
    return monthly_to_long(
        frame,
        SUPPLIER,
        ("Номенклатура.Код", "Код 1с"),
        "opening_stock",
        fill_missing=False,
    )


def load_in_transit(path: PathLike) -> pd.DataFrame:
    frame = read_excel_table(path, ("Код 1с", "Артикул поставщика", "Наименование"))
    code_column = find_column(frame, ("Код 1с",))
    qty_column = find_column_containing(frame, "СЭ в пути")

    result = pd.DataFrame(
        {
            "sku_code": clean_string(frame[code_column]),
            "supplier": pd.Series(SUPPLIER, index=frame.index, dtype="string"),
            "qty": pd.to_numeric(frame[qty_column], errors="coerce").fillna(0.0).astype(float),
        }
    ).dropna(subset=["sku_code"])
    return result.groupby(["sku_code", "supplier"], as_index=False, sort=False)["qty"].sum()


def load_moq(path: PathLike) -> pd.DataFrame:
    return load_moq_table(path, SUPPLIER, ("Кратность",))


def load_sku_ref(path: PathLike) -> pd.DataFrame:
    return load_reference(path, SUPPLIER)
