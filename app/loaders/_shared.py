"""Shared parsing helpers for the supplier-specific Excel loaders."""

from pathlib import Path
import re
from typing import Iterable, Optional, Sequence, Union

import pandas as pd


PathLike = Union[str, Path]

_MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}


def normalize_label(value: object) -> str:
    """Normalize human-authored Excel labels for reliable matching."""

    if pd.isna(value):
        return ""
    return " ".join(str(value).replace("\xa0", " ").strip().lower().split())


def read_excel_table(path: PathLike, required_labels: Iterable[str]) -> pd.DataFrame:
    """Find the header row near the top of a workbook and read its first sheet."""

    path = Path(path)
    preview = pd.read_excel(path, header=None, nrows=12, dtype=object)
    wanted = {normalize_label(label) for label in required_labels}

    for row_number, row in preview.iterrows():
        labels = {normalize_label(value) for value in row if not pd.isna(value)}
        if wanted.issubset(labels):
            return pd.read_excel(path, header=int(row_number))

    expected = ", ".join(sorted(required_labels))
    raise ValueError(f"Could not find Excel header with [{expected}] in {path}")


def find_column(frame: pd.DataFrame, candidates: Sequence[str]) -> object:
    """Return a column whose normalized label matches one of the candidates."""

    by_label = {normalize_label(column): column for column in frame.columns}
    for candidate in candidates:
        column = by_label.get(normalize_label(candidate))
        if column is not None:
            return column
    raise ValueError(f"None of the columns {list(candidates)} exist in the input")


def find_column_containing(frame: pd.DataFrame, fragment: str) -> object:
    """Return the first column containing a normalized text fragment."""

    fragment = normalize_label(fragment)
    for column in frame.columns:
        if fragment in normalize_label(column):
            return column
    raise ValueError(f"No column containing {fragment!r} exists in the input")


def find_optional_column(frame: pd.DataFrame, candidates: Sequence[str]) -> Optional[object]:
    """Return a matching column or None when the workbook does not contain it."""

    try:
        return find_column(frame, candidates)
    except ValueError:
        return None


def clean_string(series: pd.Series) -> pd.Series:
    """Strip identifiers/names while preserving missing values."""

    result = series.astype("string").str.strip()
    return result.mask(result.eq(""), pd.NA)


def parse_month_label(label: object) -> Optional[str]:
    """Convert Russian Excel month headers to the canonical YYYY-MM form."""

    if isinstance(label, (pd.Timestamp,)):
        return label.strftime("%Y-%m")

    normalized = normalize_label(label).replace(".", " ")
    match = re.search(r"([а-яё]+)\s+(20\d{2})", normalized)
    if not match:
        return None

    month_text, year = match.groups()
    month = next((number for stem, number in _MONTHS.items() if month_text.startswith(stem)), None)
    if month is None:
        return None
    return f"{year}-{month:02d}"


def monthly_to_long(
    frame: pd.DataFrame,
    supplier: str,
    code_candidates: Sequence[str],
    value_name: str,
    fill_missing: bool,
) -> pd.DataFrame:
    """Reshape a supplier's wide monthly sheet into the canonical long table."""

    code_column = find_column(frame, code_candidates)
    month_columns = {
        column: month
        for column in frame.columns
        if (month := parse_month_label(column)) is not None
    }
    if not month_columns:
        raise ValueError("No monthly columns were found in the input")

    subset = frame[[code_column, *month_columns]].copy()
    subset[code_column] = clean_string(subset[code_column])
    subset = subset.dropna(subset=[code_column])

    result = subset.melt(
        id_vars=code_column,
        value_vars=list(month_columns),
        var_name="source_month",
        value_name=value_name,
    )
    result["month"] = result["source_month"].map(month_columns).astype("string")
    result[value_name] = pd.to_numeric(result[value_name], errors="coerce")
    if fill_missing:
        result[value_name] = result[value_name].fillna(0.0)
    result[value_name] = result[value_name].astype(float)
    result = result.rename(columns={code_column: "sku_code"})
    result["sku_code"] = clean_string(result["sku_code"])
    result["supplier"] = pd.Series(supplier, index=result.index, dtype="string")

    columns = ["sku_code", "supplier", "month", value_name]
    result = result[columns]
    return (
        result.groupby(columns[:-1], as_index=False, sort=False)[value_name]
        .sum(min_count=1)
        .reset_index(drop=True)
    )


def load_sales_transactions(path: PathLike, supplier: str) -> pd.DataFrame:
    """Load and normalize sales invoice rows for one supplier."""

    frame = read_excel_table(path, ("Дата", "Документ", "Код", "Количество"))
    date_column = find_column(frame, ("Дата",))
    document_column = find_column(frame, ("Документ",))
    code_column = find_column(frame, ("Код", "Код 1с", "Номенклатура.Код"))
    qty_column = find_column(frame, ("Количество",))

    sales_mask = frame[document_column].astype("string").str.contains(
        "Расходная накладная", case=False, na=False
    )
    result = frame.loc[sales_mask, [date_column, code_column, qty_column]].copy()
    result.columns = ["date", "sku_code", "qty"]
    result["date"] = pd.to_datetime(result["date"], dayfirst=True, errors="coerce")
    result["sku_code"] = clean_string(result["sku_code"])
    result["qty"] = pd.to_numeric(result["qty"], errors="coerce").abs()
    result = result.dropna(subset=["date", "sku_code", "qty"])
    result["qty"] = result["qty"].astype(float)
    result["supplier"] = pd.Series(supplier, index=result.index, dtype="string")
    return result[["date", "sku_code", "supplier", "qty"]].reset_index(drop=True)


def load_reference(path: PathLike, supplier: str) -> pd.DataFrame:
    """Extract names, supplier articles and units from a supported workbook."""

    frame = None
    for code_label in ("Код 1с", "Номенклатура.Код", "Код"):
        try:
            frame = read_excel_table(path, (code_label,))
            break
        except ValueError:
            continue
    if frame is None:
        raise ValueError(f"Could not find a SKU code column in {path}")
    code_column = find_column(frame, ("Код 1с", "Номенклатура.Код", "Код"))
    name_column = find_column(frame, ("Наименование", "Номенклатура", " Наименование"))
    article_column = find_optional_column(
        frame, ("Артикул поставщика", "Артикул ИЭК", "Артикул")
    )
    unit_column = find_optional_column(frame, ("Ед.", "Ед.изм", "Ед"))

    result = frame[[code_column, name_column]].copy()
    result.columns = ["sku_code", "name"]
    result["article"] = frame[article_column] if article_column is not None else ""
    result["unit"] = frame[unit_column] if unit_column is not None else ""
    result["sku_code"] = clean_string(result["sku_code"])
    result["name"] = clean_string(result["name"])
    result["article"] = clean_string(result["article"]).fillna("")
    result["unit"] = clean_string(result["unit"]).fillna("")
    result = result.dropna(subset=["sku_code", "name"])
    result["supplier"] = pd.Series(supplier, index=result.index, dtype="string")
    return result[["sku_code", "supplier", "name", "article", "unit"]].drop_duplicates(
        ["sku_code", "supplier"], keep="first"
    ).reset_index(drop=True)


def load_moq_table(path: PathLike, supplier: str, moq_candidates: Sequence[str]) -> pd.DataFrame:
    """Load a supplier MOQ sheet, treating missing or non-positive MOQ as one."""

    frame = read_excel_table(path, ("Номенклатура",) if supplier == "SE" else ("Код 1с",))
    code_column = find_column(frame, ("Код 1с", "Номенклатура.Код", "Код"))
    moq_column = find_column(frame, moq_candidates)

    result = frame[[code_column, moq_column]].copy()
    result.columns = ["sku_code", "moq"]
    result["sku_code"] = clean_string(result["sku_code"])
    result = result.dropna(subset=["sku_code"])
    moq = pd.to_numeric(result["moq"], errors="coerce")
    result["moq"] = moq.where(moq > 0, 1).fillna(1).round().astype("Int64")
    result["supplier"] = pd.Series(supplier, index=result.index, dtype="string")
    return result[["sku_code", "supplier", "moq"]].drop_duplicates(
        ["sku_code", "supplier"], keep="first"
    ).reset_index(drop=True)
